package main

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const maxSonarrArchive = 64 << 20

func readAPIKey(data []byte) (string, error) {
	var config struct {
		XMLName xml.Name `xml:"Config"`
		Key     string   `xml:"ApiKey"`
	}
	if err := xml.Unmarshal(data, &config); err != nil {
		return "", err
	}
	if !requireKey(config.Key) {
		return "", backupError("Sonarr API key is unavailable.")
	}
	return config.Key, nil
}

func validateSonarr(ctx context.Context, path string) error {
	archive, err := zip.OpenReader(path)
	if err != nil {
		return err
	}
	defer archive.Close()
	if len(archive.File) != 3 {
		return backupError("Native archive has unexpected or missing recovery files.")
	}
	files := map[string]*zip.File{}
	var size uint64
	for _, entry := range archive.File {
		if files[entry.Name] != nil || entry.FileInfo().IsDir() || entry.UncompressedSize64 == 0 {
			return backupError("Native archive has unexpected or missing recovery files.")
		}
		files[entry.Name] = entry
		if entry.UncompressedSize64 > 256<<20 {
			return backupError("Native archive exceeds its size limit.")
		}
		size += entry.UncompressedSize64
	}
	if size > 256<<20 || files["config.xml"] == nil || files["sonarr.db"] == nil || files["INFO"] == nil {
		return backupError("Native archive has unexpected or missing recovery files.")
	}
	directory, err := os.MkdirTemp("", "sonarr-validation-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(directory)
	for name, entry := range files {
		input, err := entry.Open()
		if err != nil {
			return err
		}
		var target io.Writer = io.Discard
		var database *os.File
		var config bytes.Buffer
		if name == "sonarr.db" {
			database, err = os.OpenFile(filepath.Join(directory, name), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
			if err != nil {
				input.Close()
				return err
			}
			target = database
		} else if name == "config.xml" {
			target = &config
		}
		_, err = io.Copy(target, contextReader{ctx, input})
		input.Close()
		if database != nil {
			closeErr := database.Close()
			if err == nil {
				err = closeErr
			}
		}
		if err != nil {
			return err
		}
		if name == "config.xml" {
			if _, err := readAPIKey(config.Bytes()); err != nil {
				return err
			}
		}
	}
	return validateSQLite(ctx, filepath.Join(directory, "sonarr.db"), []string{"Series", "Episodes", "Config", "VersionInfo"})
}

type sonarrAPI struct {
	client    *http.Client
	base, key string
}
type nativeBackup struct {
	ID               int64 `json:"id"`
	Type, Name, Path string
}

func (s sonarrAPI) request(ctx context.Context, method, path string, payload, output any) error {
	var body []byte
	if payload != nil {
		var err error
		body, err = json.Marshal(payload)
		if err != nil {
			return err
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, s.base+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("X-Api-Key", s.key)
	req.Header.Set("Content-Type", "application/json")
	response, err := s.client.Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return backupError(fmt.Sprintf("Sonarr API request failed with HTTP %d.", response.StatusCode))
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, maxSonarrArchive+1))
	if err != nil {
		return err
	}
	if len(data) > maxSonarrArchive {
		return backupError("Native backup response exceeds the size limit.")
	}
	if output == nil {
		return nil
	}
	return json.Unmarshal(data, output)
}

func exportSonarr(ctx context.Context, configPath, target, base string) error {
	data, err := os.ReadFile(configPath)
	if err != nil {
		return err
	}
	key, err := readAPIKey(data)
	if err != nil {
		return err
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	api := sonarrAPI{&http.Client{Timeout: 30 * time.Second, Transport: transport,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}, base, key}
	var old []nativeBackup
	if err := api.request(ctx, "GET", "/api/v3/system/backup", nil, &old); err != nil {
		return err
	}
	previous := map[int64]bool{}
	for _, backup := range old {
		previous[backup.ID] = true
	}
	var command struct {
		ID int64 `json:"id"`
	}
	if err := api.request(ctx, "POST", "/api/v3/command", map[string]string{"name": "Backup"}, &command); err != nil {
		return err
	}
	if err := waitFor(ctx, 3*time.Minute, func(ctx context.Context) (bool, error) {
		var result struct {
			Status string `json:"status"`
		}
		if err := api.request(ctx, "GET", fmt.Sprintf("/api/v3/command/%d", command.ID), nil, &result); err != nil {
			return false, err
		}
		switch result.Status {
		case "completed":
			return true, nil
		case "failed", "aborted", "cancelled", "orphaned":
			return false, backupError("Native Sonarr backup command failed.")
		}
		return false, nil
	}); err != nil {
		return err
	}
	var backups []nativeBackup
	if err := api.request(ctx, "GET", "/api/v3/system/backup", nil, &backups); err != nil {
		return err
	}
	var fresh []nativeBackup
	for _, backup := range backups {
		if !previous[backup.ID] && backup.Type == "manual" {
			fresh = append(fresh, backup)
		}
	}
	if len(fresh) != 1 {
		return backupError("Expected exactly one new completed native backup.")
	}
	backup := fresh[0]
	if !strings.HasPrefix(backup.Name, "sonarr_backup_") || !strings.HasSuffix(backup.Name, ".zip") || strings.ContainsAny(backup.Name, "/\\") || backup.Path != "/backup/manual/"+backup.Name {
		return backupError("Native backup download path is unexpected.")
	}
	var host struct {
		BackupFolder string `json:"backupFolder"`
	}
	if err := api.request(ctx, "GET", "/api/v3/config/host", nil, &host); err != nil {
		return err
	}
	root := filepath.Dir(configPath)
	folder := host.BackupFolder
	if !filepath.IsAbs(folder) {
		folder = filepath.Join(root, folder)
	}
	native := filepath.Join(folder, "manual", backup.Name)
	resolved, err := filepath.EvalSymlinks(native)
	if err != nil {
		return err
	}
	resolvedRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		return err
	}
	relative, err := filepath.Rel(resolvedRoot, resolved)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(os.PathSeparator)) {
		return backupError("Native archive is outside the config volume.")
	}
	info, err := os.Lstat(native)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() <= 0 || info.Size() > maxSonarrArchive {
		return backupError("Completed native archive is unavailable on the config volume.")
	}
	if err := atomicExport(ctx, target, func(out *os.File) error {
		input, err := os.Open(native)
		if err != nil {
			return err
		}
		defer input.Close()
		n, err := io.Copy(out, contextReader{ctx, io.LimitReader(input, maxSonarrArchive+1)})
		if err != nil {
			return err
		}
		if n > maxSonarrArchive {
			return backupError("Native archive exceeds its size limit.")
		}
		return nil
	}, func(path string) error { return validateSonarr(ctx, path) }); err != nil {
		return err
	}
	// Delete only the native archive created by this invocation, after validation.
	if err := api.request(ctx, "DELETE", fmt.Sprintf("/api/v3/system/backup/%d", backup.ID), nil, nil); err != nil {
		return err
	}
	fmt.Println("Validated native Sonarr archive staged.")
	return nil
}

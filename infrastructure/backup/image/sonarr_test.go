package main

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func zipFixture(t *testing.T, files map[string][]byte) []byte {
	t.Helper()
	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	for name, data := range files {
		entry, err := writer.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := entry.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return buffer.Bytes()
}

func sonarrFixture(t *testing.T, root, scenario string) []byte {
	t.Helper()
	database := filepath.Join(root, "fixture.db")
	tables := []string{"Series", "Episodes", "Config", "VersionInfo"}
	if scenario == "missing tables" {
		tables = []string{"Series"}
	}
	sqliteFixture(t, database, tables)
	files := map[string][]byte{"config.xml": []byte("<Config><ApiKey>fixture-key</ApiKey></Config>"), "sonarr.db": readFixture(t, database), "INFO": []byte("fixture")}
	switch scenario {
	case "extra files":
		files["logs/sonarr.log"] = []byte("exclude")
	case "corrupt database":
		files["sonarr.db"] = []byte("broken")
	case "bad config":
		files["config.xml"] = []byte("<Config/>")
	}
	return zipFixture(t, files)
}

func TestSonarrExport(t *testing.T) {
	for _, scenario := range []string{"success", "extra files", "corrupt database", "missing tables", "bad config", "stale", "failed command", "bad path", "outside config"} {
		t.Run(scenario, func(t *testing.T) {
			root := t.TempDir()
			configRoot := filepath.Join(root, "config")
			config := filepath.Join(configRoot, "config.xml")
			target := filepath.Join(root, "exports/sonarr.zip")
			writeFixture(t, config, []byte("<Config><ApiKey>fixture-key</ApiKey></Config>"))
			writeFixture(t, target, []byte("previous"))
			archive := sonarrFixture(t, root, scenario)
			folder := "Backups"
			if scenario == "outside config" {
				folder = filepath.Join(root, "outside")
			}
			nativeFolder := folder
			if !filepath.IsAbs(nativeFolder) {
				nativeFolder = filepath.Join(configRoot, folder)
			}
			writeFixture(t, filepath.Join(nativeFolder, "manual/sonarr_backup_new.zip"), archive)
			inventory, deleted := 0, false
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("X-Api-Key") != "fixture-key" || strings.Contains(r.URL.String(), "fixture-key") {
					t.Error("Credential handling changed")
				}
				var response any
				switch r.URL.Path {
				case "/api/v3/system/backup":
					inventory++
					old := nativeBackup{ID: 1, Type: "manual", Name: "sonarr_backup_old.zip"}
					response = []nativeBackup{old}
					if inventory > 1 && scenario != "stale" {
						path := "/backup/manual/sonarr_backup_new.zip"
						if scenario == "bad path" {
							path = "//outside/archive.zip"
						}
						response = []nativeBackup{old, {ID: 2, Type: "manual", Name: "sonarr_backup_new.zip", Path: path}}
					}
				case "/api/v3/command":
					if r.Method != "POST" {
						t.Error("Backup command not submitted")
					}
					response = map[string]any{"id": 42}
				case "/api/v3/command/42":
					status := "completed"
					if scenario == "failed command" {
						status = "failed"
					}
					response = map[string]string{"status": status}
				case "/api/v3/config/host":
					response = map[string]string{"backupFolder": folder}
				case "/api/v3/system/backup/2":
					if r.Method != "DELETE" {
						t.Error("Unexpected method")
					}
					deleted = true
					w.WriteHeader(204)
					return
				default:
					t.Error("Unexpected endpoint")
					w.WriteHeader(404)
					return
				}
				json.NewEncoder(w).Encode(response)
			}))
			defer server.Close()
			err := exportSonarr(context.Background(), config, target, server.URL)
			if scenario == "success" {
				if err != nil {
					t.Fatal(err)
				}
				if !bytes.Equal(readFixture(t, target), archive) || !deleted {
					t.Fatal("Fresh native export was not validated and staged")
				}
				info, _ := os.Stat(target)
				if info.Mode().Perm() != 0600 {
					t.Fatal("Incorrect export permissions")
				}
			} else {
				if err == nil || string(readFixture(t, target)) != "previous" || deleted {
					t.Fatal("Invalid native export replaced previous archive or deleted recovery data")
				}
			}
			entries, _ := os.ReadDir(filepath.Dir(target))
			if len(entries) != 1 {
				t.Fatal("Temporary export left behind")
			}
		})
	}
}

func TestSonarrNeverForwardsAPIKeyOnRedirect(t *testing.T) {
	root := t.TempDir()
	config := filepath.Join(root, "config.xml")
	writeFixture(t, config, []byte("<Config><ApiKey>fixture-key</ApiKey></Config>"))
	forwarded := false
	destination := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { forwarded = true }))
	defer destination.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, destination.URL, 302) }))
	defer server.Close()
	if err := exportSonarr(context.Background(), config, filepath.Join(root, "archive.zip"), server.URL); err == nil || forwarded {
		t.Fatal("Credential-bearing redirect was followed")
	}
}

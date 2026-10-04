package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type forgejoLayout struct{ local, nas, stage, cache string }

func requireNFS(path, mountInfo string) error {
	data, err := os.ReadFile(mountInfo)
	if err != nil {
		return err
	}
	for _, line := range strings.Split(string(data), "\n") {
		parts := strings.SplitN(line, " - ", 2)
		if len(parts) != 2 {
			continue
		}
		fields, filesystem := strings.Fields(parts[0]), strings.Fields(parts[1])
		if len(fields) >= 5 && len(filesystem) > 0 && fields[4] == path && (filesystem[0] == "nfs" || filesystem[0] == "nfs4") {
			return nil
		}
	}
	return backupError("Expected a mounted NAS volume; refusing an ordinary directory.")
}

func directory(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() {
		return backupError("Invalid source or staging directory.")
	}
	return nil
}

func (l forgejoLayout) prepare(mountInfo string) error {
	for _, path := range []string{l.nas, l.stage} {
		if err := requireNFS(path, mountInfo); err != nil {
			return err
		}
	}
	for _, path := range []string{l.local, l.nas, l.stage} {
		if err := directory(path); err != nil {
			return err
		}
	}
	for _, name := range []string{"gitea/forgejo.db", "gitea/conf/app.ini"} {
		info, err := os.Lstat(filepath.Join(l.local, name))
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return backupError("Forgejo database or configuration is missing.")
		}
	}
	marker := filepath.Join(l.stage, ".forgejo-staging")
	info, err := os.Lstat(marker)
	if err == nil {
		if !info.Mode().IsRegular() {
			return backupError("Unrecognized staging ownership marker.")
		}
		value, err := os.ReadFile(marker)
		if err != nil {
			return err
		}
		if string(value) != "forgejo-staging-v1\n" {
			return backupError("Unrecognized staging ownership marker.")
		}
	} else if os.IsNotExist(err) {
		entries, err := os.ReadDir(l.stage)
		if err != nil {
			return err
		}
		if len(entries) > 0 {
			return backupError("Staging volume contains unrecognized data.")
		}
		if err := os.WriteFile(marker, []byte("forgejo-staging-v1\n"), 0600); err != nil {
			return err
		}
	} else {
		return err
	}
	for _, path := range []string{filepath.Join(l.stage, "current"), filepath.Join(l.stage, "current/local"), filepath.Join(l.stage, "current/nas"), l.cache} {
		if _, err := os.Lstat(path); os.IsNotExist(err) {
			if err := os.Mkdir(path, 0700); err != nil {
				return err
			}
		}
		if err := directory(path); err != nil {
			return err
		}
	}
	return nil
}

func synchronize(ctx context.Context, source, target string, live bool) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := os.MkdirAll(target, 0700); err != nil {
		return err
	}
	if err := directory(target); err != nil {
		return err
	}
	entries, err := os.ReadDir(source)
	if err != nil {
		return err
	}
	present := make(map[string]bool, len(entries))
	for _, entry := range entries {
		present[entry.Name()] = true
	}
	old, err := os.ReadDir(target)
	if err != nil {
		return err
	}
	for _, entry := range old {
		if !present[entry.Name()] {
			if err := os.RemoveAll(filepath.Join(target, entry.Name())); err != nil {
				return err
			}
		}
	}
	for _, entry := range entries {
		if err := ctx.Err(); err != nil {
			return err
		}
		from, to := filepath.Join(source, entry.Name()), filepath.Join(target, entry.Name())
		info, err := os.Lstat(from)
		if err != nil {
			return err
		}
		existing, err := os.Lstat(to)
		if err != nil && !os.IsNotExist(err) {
			return err
		}
		switch {
		case info.Mode()&os.ModeSymlink != 0:
			link, err := os.Readlink(from)
			if err != nil {
				return err
			}
			if existing != nil && existing.Mode()&os.ModeSymlink != 0 {
				old, err := os.Readlink(to)
				if err == nil && old == link {
					continue
				}
			}
			if err := os.RemoveAll(to); err != nil {
				return err
			}
			if err := os.Symlink(link, to); err != nil {
				return err
			}
		case info.IsDir():
			if existing != nil && !existing.IsDir() {
				if err := os.RemoveAll(to); err != nil {
					return err
				}
			}
			if err := synchronize(ctx, from, to, live); err != nil {
				return err
			}
			if err := os.Chmod(to, info.Mode()); err != nil {
				return err
			}
			if err := os.Chtimes(to, info.ModTime(), info.ModTime()); err != nil {
				return err
			}
		case info.Mode().IsRegular():
			if existing != nil && !existing.Mode().IsRegular() {
				if err := os.RemoveAll(to); err != nil {
					return err
				}
				existing = nil
			}
			unchanged := existing != nil && info.Size() == existing.Size()
			if unchanged && live {
				unchanged = info.ModTime().Equal(existing.ModTime())
			} else if unchanged {
				first, err := digest(ctx, from)
				if err != nil {
					return err
				}
				second, err := digest(ctx, to)
				if err != nil {
					return err
				}
				unchanged = first == second
			}
			if !unchanged {
				if err := copyFile(ctx, from, to, info); err != nil {
					return err
				}
			}
		default:
			return backupError("Unsupported entry in a source store.")
		}
	}
	return nil
}

func (l forgejoLayout) copy(ctx context.Context, live bool) error {
	for _, store := range []struct{ source, name string }{{l.local, "local"}, {l.nas, "nas"}} {
		if err := synchronize(ctx, store.source, filepath.Join(l.stage, "current", store.name), live); err != nil && !(live && os.IsNotExist(err)) {
			return fmt.Errorf("synchronize %s store: %w", store.name, err)
		}
	}
	return nil
}

func (l forgejoLayout) validate(ctx context.Context) error {
	directory, err := os.MkdirTemp(l.cache, "sqlite-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(directory)
	source := filepath.Join(l.stage, "current/local/gitea/forgejo.db")
	for _, suffix := range []string{"", "-wal", "-shm"} {
		info, err := os.Stat(source + suffix)
		if suffix != "" && os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return err
		}
		if err := copyFile(ctx, source+suffix, filepath.Join(directory, "forgejo.db"+suffix), info); err != nil {
			return err
		}
	}
	return validateSQLite(ctx, filepath.Join(directory, "forgejo.db"), nil)
}

func resumeForgejo(ctx context.Context, api forgejoAPI, marker string) error {
	current, err := api.Deployment(ctx)
	if err != nil {
		return err
	}
	if current.Metadata.Annotations[pauseAnnotation] != marker {
		return backupError("Backup pause ownership changed; manual inspection is required.")
	}
	if err := api.Patch(ctx, current, 1, nil); err != nil {
		return err
	}
	err = waitFor(ctx, 5*time.Minute, func(ctx context.Context) (bool, error) {
		d, err := api.Deployment(ctx)
		return d.Status.AvailableReplicas == 1, err
	})
	if err == nil {
		fmt.Println("Forgejo resumed and is available.")
	}
	return err
}

func recoverForgejo(ctx context.Context, api forgejoAPI, now time.Time) error {
	d, err := api.Deployment(ctx)
	if err != nil {
		return err
	}
	marker := d.Metadata.Annotations[pauseAnnotation]
	if marker == "" {
		return nil
	}
	var value struct {
		ID      string  `json:"id"`
		Started float64 `json:"started"`
	}
	if json.Unmarshal([]byte(marker), &value) != nil || value.ID == "" || value.Started <= 0 {
		return backupError("Unrecognized backup pause marker.")
	}
	if float64(now.UnixNano())/1e9-value.Started > 1500 {
		return resumeForgejo(ctx, api, marker)
	}
	return nil
}

func stageForgejo(ctx context.Context, api forgejoAPI, copy, validate func(context.Context) error) (result error) {
	current, err := api.Deployment(ctx)
	if err != nil {
		return err
	}
	if current.Spec.Replicas != 1 || current.Metadata.Annotations[pauseAnnotation] != "" {
		return backupError("Forgejo is stopped or already paused; refusing another backup.")
	}
	value, _ := json.Marshal(map[string]any{"id": randomID(), "started": float64(time.Now().UnixNano()) / 1e9})
	marker := string(value)
	if err := api.Patch(ctx, current, 0, &marker); err != nil {
		return err
	}
	defer func() {
		// Resuming uses a fresh context even if SIGTERM canceled staging.
		cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
		defer cancel()
		result = errors.Join(result, resumeForgejo(cleanup, api, marker))
	}()
	if err := waitFor(ctx, 3*time.Minute, func(ctx context.Context) (bool, error) { n, err := api.Pods(ctx, current); return n == 0, err }); err != nil {
		return err
	}
	fmt.Println("Forgejo stopped; synchronizing both stores.")
	if err := copy(ctx); err != nil {
		return fmt.Errorf("synchronize stopped Forgejo stores: %w", err)
	}
	after, err := api.Deployment(ctx)
	if err != nil {
		return err
	}
	pods, err := api.Pods(ctx, current)
	if err != nil {
		return err
	}
	if after.Spec.Replicas != 0 || pods != 0 || after.Metadata.Annotations[pauseAnnotation] != marker {
		return backupError("Forgejo restarted during staging; refusing an inconsistent backup.")
	}
	if err := validate(ctx); err != nil {
		return fmt.Errorf("validate staged Forgejo database: %w", err)
	}
	return nil
}

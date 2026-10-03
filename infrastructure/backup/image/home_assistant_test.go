package main

import (
	"archive/tar"
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func tarFixture(t *testing.T, path string, modified time.Time) {
	t.Helper()
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	w := tar.NewWriter(f)
	if err := w.WriteHeader(&tar.Header{Name: "backup.json", Mode: 0600, Size: 2}); err != nil {
		t.Fatal(err)
	}
	w.Write([]byte("{}"))
	w.Close()
	f.Close()
	os.Chtimes(path, modified, modified)
}

func TestHomeAssistantStagesOnlyLatest(t *testing.T) {
	root := t.TempDir()
	now := time.Now()
	old, latest := filepath.Join(root, "old.tar"), filepath.Join(root, "native with spaces.tar")
	tarFixture(t, old, now.Add(-2*time.Hour))
	tarFixture(t, latest, now.Add(-10*time.Minute))
	writeFixture(t, filepath.Join(root, "live.db"), []byte("never export"))
	target := filepath.Join(root, "exports/backups/home-assistant.tar")
	if err := stageHomeAssistant(context.Background(), root, target, now); err != nil {
		t.Fatal(err)
	}
	if string(readFixture(t, target)) != string(readFixture(t, latest)) {
		t.Fatal("Wrong archive staged")
	}
	info, _ := os.Stat(target)
	if info.Mode().Perm() != 0600 {
		t.Fatal("Private export permissions missing")
	}
}

func TestHomeAssistantRejectsInvalidSources(t *testing.T) {
	for _, scenario := range []string{"recent", "stale", "too many", "symlink", "invalid tar", "empty"} {
		t.Run(scenario, func(t *testing.T) {
			root := t.TempDir()
			now := time.Now()
			path := filepath.Join(root, "backup.tar")
			tarFixture(t, path, now.Add(-10*time.Minute))
			switch scenario {
			case "recent":
				os.Chtimes(path, now, now)
			case "stale":
				os.Chtimes(path, now.Add(-31*time.Hour), now.Add(-31*time.Hour))
			case "too many":
				for _, name := range []string{"2.tar", "3.tar", "4.tar"} {
					tarFixture(t, filepath.Join(root, name), now.Add(-10*time.Minute))
				}
			case "symlink":
				os.Rename(path, path+".bin")
				os.Symlink(path+".bin", path)
			case "invalid tar":
				writeFixture(t, path, []byte("not a tar"))
				os.Chtimes(path, now.Add(-10*time.Minute), now.Add(-10*time.Minute))
			case "empty":
				writeFixture(t, path, nil)
			}
			target := filepath.Join(root, "exports/archive.tar")
			writeFixture(t, target, []byte("previous"))
			if err := stageHomeAssistant(context.Background(), root, target, now); err == nil {
				t.Fatal("Invalid source accepted")
			}
			if string(readFixture(t, target)) != "previous" {
				t.Fatal("Previous export replaced")
			}
		})
	}
}

func TestAtomicExportPreservesPreviousOnFailure(t *testing.T) {
	root := t.TempDir()
	target := filepath.Join(root, "archive.tar")
	writeFixture(t, target, []byte("previous"))
	err := atomicExport(context.Background(), target, func(f *os.File) error { f.Write([]byte("partial")); return errors.New("fixture") }, nil)
	if err == nil || string(readFixture(t, target)) != "previous" {
		t.Fatal("Failed export replaced previous archive")
	}
	entries, _ := os.ReadDir(root)
	if len(entries) != 1 {
		t.Fatal("Temporary export left behind")
	}
	link := filepath.Join(root, "link")
	os.Symlink(target, link)
	if err := atomicExport(context.Background(), link, func(*os.File) error { return nil }, nil); err == nil {
		t.Fatal("Symlink export accepted")
	}
}

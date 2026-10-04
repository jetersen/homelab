package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func writeFixture(t *testing.T, path string, data []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}
func readFixture(t *testing.T, path string) []byte {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func sqliteFixture(t *testing.T, path string, tables []string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	for _, name := range tables {
		if _, err := db.Exec("CREATE TABLE " + name + " (Id INTEGER)"); err != nil {
			t.Fatal(err)
		}
	}
}

func TestSynchronize(t *testing.T) {
	root := t.TempDir()
	source, target := filepath.Join(root, "source"), filepath.Join(root, "target")
	writeFixture(t, filepath.Join(source, "repository/data"), []byte("new"))
	writeFixture(t, filepath.Join(target, "repository/data"), []byte("old"))
	writeFixture(t, filepath.Join(target, "obsolete"), []byte("remove"))
	writeFixture(t, filepath.Join(root, "outside"), []byte("preserve"))
	if err := os.Symlink(filepath.Join(root, "outside"), filepath.Join(target, "link")); err != nil {
		t.Fatal(err)
	}
	writeFixture(t, filepath.Join(source, "link"), []byte("regular"))
	if err := os.Symlink("../outside", filepath.Join(source, "source-link")); err != nil {
		t.Fatal(err)
	}
	if err := synchronize(context.Background(), source, target, false); err != nil {
		t.Fatal(err)
	}
	if string(readFixture(t, filepath.Join(target, "repository/data"))) != "new" || string(readFixture(t, filepath.Join(root, "outside"))) != "preserve" {
		t.Fatal("Incorrect synchronization")
	}
	if _, err := os.Lstat(filepath.Join(target, "obsolete")); !os.IsNotExist(err) {
		t.Fatal("Obsolete staging entry remains")
	}
	if info, err := os.Lstat(filepath.Join(target, "link")); err != nil || !info.Mode().IsRegular() {
		t.Fatal("Destination symlink was not replaced")
	}
	if link, err := os.Readlink(filepath.Join(target, "source-link")); err != nil || link != "../outside" {
		t.Fatal("Source symlink was followed")
	}
}

func TestSynchronizeReadOnlyFile(t *testing.T) {
	for _, live := range []bool{true, false} {
		t.Run(fmt.Sprintf("live=%t", live), func(t *testing.T) {
			root := t.TempDir()
			source, target := filepath.Join(root, "source"), filepath.Join(root, "target")
			from, to := filepath.Join(source, "pack"), filepath.Join(target, "pack")
			writeFixture(t, from, []byte("new"))
			old := "old"
			if live {
				// Git can refresh a pack's timestamp without changing its contents.
				old = "new"
			}
			writeFixture(t, to, []byte(old))
			mtime := time.Unix(1700000000, 123456789)
			for path, stamp := range map[string]time.Time{from: mtime, to: mtime.Add(-time.Hour)} {
				if err := os.Chmod(path, 0444); err != nil {
					t.Fatal(err)
				}
				if err := os.Chtimes(path, stamp, stamp); err != nil {
					t.Fatal(err)
				}
			}
			if err := synchronize(context.Background(), source, target, live); err != nil {
				t.Fatal(err)
			}
			info, err := os.Stat(to)
			if err != nil {
				t.Fatal(err)
			}
			if string(readFixture(t, to)) != "new" || info.Mode().Perm() != 0444 || !info.ModTime().Equal(mtime) {
				t.Fatal("Staged content or metadata differs from source")
			}
		})
	}
}

func TestCopyFileCancellationPreservesDestination(t *testing.T) {
	root := t.TempDir()
	source, target := filepath.Join(root, "source"), filepath.Join(root, "target")
	writeFixture(t, source, []byte("new"))
	writeFixture(t, target, []byte("previous backup"))
	info, err := os.Stat(source)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := copyFile(ctx, source, target, info); !errors.Is(err, context.Canceled) {
		t.Fatalf("Expected cancellation, got %v", err)
	}
	if string(readFixture(t, target)) != "previous backup" {
		t.Fatal("Interrupted copy damaged the previous staged file")
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 2 {
		t.Fatalf("Temporary copy was not removed: %v", err)
	}
}

type fakeForgejo struct {
	replicas   int
	marker     string
	changes    []int
	patches    int
	patchError bool
}

func (f *fakeForgejo) Deployment(ctx context.Context) (deployment, error) {
	if err := ctx.Err(); err != nil {
		return deployment{}, err
	}
	var d deployment
	d.Spec.Replicas = f.replicas
	d.Status.AvailableReplicas = f.replicas
	d.Metadata.ResourceVersion = "7"
	d.Metadata.Annotations = map[string]string{pauseAnnotation: f.marker}
	return d, nil
}
func (f *fakeForgejo) Patch(ctx context.Context, d deployment, replicas int, marker *string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if f.patchError {
		return errors.New("fixture")
	}
	f.replicas = replicas
	f.marker = ""
	if marker != nil {
		f.marker = *marker
	}
	f.changes = append(f.changes, replicas)
	f.patches++
	return nil
}
func (f *fakeForgejo) Pods(ctx context.Context, d deployment) (int, error) {
	return f.replicas, ctx.Err()
}

func TestForgejoStageAndResume(t *testing.T) {
	for _, scenario := range []string{"success", "copy failure", "validation failure", "restart", "cancellation", "ownership changed"} {
		t.Run(scenario, func(t *testing.T) {
			api := &fakeForgejo{replicas: 1}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			validated := false
			copy := func(context.Context) error {
				if api.replicas != 0 {
					t.Fatal("Copy ran against live application")
				}
				switch scenario {
				case "copy failure":
					return errors.New("fixture")
				case "restart":
					api.replicas = 1
				case "cancellation":
					cancel()
					return ctx.Err()
				case "ownership changed":
					api.marker = "another-owner"
				}
				return nil
			}
			validate := func(context.Context) error {
				if api.replicas != 0 {
					t.Fatal("Validation ran after resume")
				}
				validated = true
				if scenario == "validation failure" {
					return errors.New("fixture")
				}
				return nil
			}
			err := stageForgejo(ctx, api, copy, validate)
			if (err == nil) != (scenario == "success") {
				t.Fatalf("Unexpected result: %v", err)
			}
			if scenario == "ownership changed" {
				if api.marker != "another-owner" || api.replicas != 0 {
					t.Fatal("Another owner's pause was cleared")
				}
				return
			}
			if api.replicas != 1 || api.marker != "" || !reflect.DeepEqual(api.changes, []int{0, 1}) {
				t.Fatal("Application was not resumed")
			}
			if scenario == "success" && !validated {
				t.Fatal("Validation skipped")
			}
		})
	}
}

func TestForgejoDoesNotPauseStoppedApplication(t *testing.T) {
	for _, api := range []*fakeForgejo{{replicas: 0}, {replicas: 1, marker: "owned"}, {replicas: 1, patchError: true}} {
		if err := stageForgejo(context.Background(), api, func(context.Context) error { t.Fatal("Unexpected copy"); return nil }, nil); err == nil {
			t.Fatal("Expected refusal")
		}
		if api.patches != 0 {
			t.Fatal("Unexpected change")
		}
	}
}

func TestForgejoRecovery(t *testing.T) {
	api := &fakeForgejo{replicas: 0, marker: `{"id":"fixture","started":100}`}
	if err := recoverForgejo(context.Background(), api, time.Unix(200, 0)); err != nil || api.replicas != 0 {
		t.Fatal("Unexpired pause recovered")
	}
	if err := recoverForgejo(context.Background(), api, time.Unix(1700, 0)); err != nil || api.replicas != 1 {
		t.Fatal("Expired pause not recovered")
	}
	api.marker = `{"started":1}`
	if err := recoverForgejo(context.Background(), api, time.Now()); err == nil {
		t.Fatal("Malformed marker accepted")
	}
}

func TestForgejoLayout(t *testing.T) {
	root := t.TempDir()
	layout := forgejoLayout{filepath.Join(root, "local"), filepath.Join(root, "nas"), filepath.Join(root, "stage"), filepath.Join(root, "cache")}
	for _, path := range []string{layout.local, layout.nas, layout.stage} {
		if err := os.Mkdir(path, 0700); err != nil {
			t.Fatal(err)
		}
	}
	writeFixture(t, filepath.Join(layout.local, "gitea/conf/app.ini"), nil)
	writeFixture(t, filepath.Join(layout.local, "gitea/forgejo.db"), nil)
	mountInfo := filepath.Join(root, "mountinfo")
	writeFixture(t, mountInfo, []byte("1 0 0:1 / "+layout.nas+" rw - nfs4 host:/nas rw\n2 0 0:2 / "+layout.stage+" rw - nfs4 host:/stage rw\n"))
	writeFixture(t, filepath.Join(layout.stage, "unrelated"), nil)
	if err := layout.prepare(mountInfo); err == nil {
		t.Fatal("Unrecognized staging data accepted")
	}
	os.Remove(filepath.Join(layout.stage, "unrelated"))
	if err := layout.prepare(mountInfo); err != nil {
		t.Fatal(err)
	}
	os.Remove(filepath.Join(layout.stage, "current/nas"))
	os.Symlink(layout.nas, filepath.Join(layout.stage, "current/nas"))
	if err := layout.prepare(mountInfo); err == nil {
		t.Fatal("Symlink staging destination accepted")
	}
	if err := requireNFS(root, mountInfo); err == nil {
		t.Fatal("Ordinary directory accepted as NAS")
	}
}

func TestForgejoSQLiteValidation(t *testing.T) {
	root := t.TempDir()
	layout := forgejoLayout{stage: filepath.Join(root, "stage"), cache: filepath.Join(root, "cache")}
	os.Mkdir(layout.cache, 0700)
	path := filepath.Join(layout.stage, "current/local/gitea/forgejo.db")
	sqliteFixture(t, path, []string{"fixture"})
	if err := layout.validate(context.Background()); err != nil {
		t.Fatal(err)
	}
	writeFixture(t, path, []byte("not a SQLite database"))
	if err := layout.validate(context.Background()); err == nil {
		t.Fatal("Corrupt SQLite accepted")
	}
}

func TestKubernetesRequests(t *testing.T) {
	var observed bool
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer fixture" {
			t.Error("Missing authorization")
		}
		if r.Method == "PATCH" {
			var patch map[string]any
			if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
				t.Error(err)
			}
			metadata := patch["metadata"].(map[string]any)
			if metadata["resourceVersion"] != "7" || metadata["annotations"].(map[string]any)[pauseAnnotation] != nil {
				t.Error("Incorrect guarded patch")
			}
			observed = true
		}
		if r.URL.Path == "/api/v1/namespaces/forgejo/pods" {
			if r.URL.Query().Get("labelSelector") != "app=forgejo" {
				t.Error("Missing pod selector")
			}
			w.Write([]byte(`{"items":[]}`))
			return
		}
		w.Write([]byte(`{"metadata":{"resourceVersion":"7"},"spec":{"replicas":1,"selector":{"matchLabels":{"app":"forgejo"}}}}`))
	}))
	defer server.Close()
	api := &kubernetes{client: server.Client(), base: server.URL, namespace: "forgejo", token: "fixture"}
	d, err := api.Deployment(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if err := api.Patch(context.Background(), d, 1, nil); err != nil || !observed {
		t.Fatal("Patch failed")
	}
	if count, err := api.Pods(context.Background(), d); err != nil || count != 0 {
		t.Fatal("Pod query failed")
	}
}

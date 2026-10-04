package main

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

func randomID() string { var bytes [16]byte; rand.Read(bytes[:]); return fmt.Sprintf("%x", bytes) }

type contextReader struct {
	ctx    context.Context
	reader io.Reader
}

func (r contextReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.reader.Read(p)
}

func copyFile(ctx context.Context, source, target string, info os.FileInfo) error {
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer in.Close()
	// Replace the directory entry: Git objects may already be staged read-only.
	// An interrupted copy must also leave the previous staged file intact.
	return atomicExport(ctx, target, func(out *os.File) error {
		if _, err := io.Copy(out, contextReader{ctx, in}); err != nil {
			return err
		}
		if err := out.Chmod(info.Mode()); err != nil {
			return err
		}
		return os.Chtimes(out.Name(), info.ModTime(), info.ModTime())
	}, nil)
}

func digest(ctx context.Context, path string) ([32]byte, error) {
	var result [32]byte
	f, err := os.Open(path)
	if err != nil {
		return result, err
	}
	defer f.Close()
	hash := sha256.New()
	_, err = io.Copy(hash, contextReader{ctx, f})
	copy(result[:], hash.Sum(nil))
	return result, err
}

func atomicExport(ctx context.Context, target string, write func(*os.File) error, validate func(string) error) error {
	parent := filepath.Dir(target)
	for _, path := range []string{parent, target} {
		info, err := os.Lstat(path)
		if err == nil && info.Mode()&os.ModeSymlink != 0 {
			return backupError("Invalid staging destination.")
		}
		if err != nil && !os.IsNotExist(err) {
			return err
		}
	}
	if err := os.MkdirAll(parent, 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(parent, ".backup-*.tmp")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	defer f.Close()
	if err := write(f); err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if err := f.Sync(); err != nil {
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	if validate != nil {
		if err := validate(f.Name()); err != nil {
			return err
		}
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	return os.Rename(f.Name(), target)
}

func waitFor(ctx context.Context, timeout time.Duration, check func(context.Context) (bool, error)) error {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	for {
		if err := ctx.Err(); err != nil {
			return err
		}
		ready, err := check(ctx)
		if err != nil {
			return err
		}
		if ready {
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}

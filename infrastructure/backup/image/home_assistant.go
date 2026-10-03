package main

import (
	"archive/tar"
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

func stageHomeAssistant(ctx context.Context, source, target string, now time.Time) error {
	archives, err := filepath.Glob(filepath.Join(source, "*.tar"))
	if err != nil {
		return err
	}
	if len(archives) < 1 || len(archives) > 3 {
		return backupError("Expected one to three native archives; review native retention.")
	}
	var latest string
	var before os.FileInfo
	for _, archive := range archives {
		info, err := os.Lstat(archive)
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() || info.Size() == 0 {
			return backupError("Invalid native archive.")
		}
		if now.Sub(info.ModTime()) < 5*time.Minute {
			return backupError("A native archive was modified too recently.")
		}
		if before == nil || info.ModTime().After(before.ModTime()) {
			latest, before = archive, info
		}
	}
	if now.Sub(before.ModTime()) > 30*time.Hour {
		return backupError("The newest native archive is stale.")
	}
	f, err := os.Open(latest)
	if err != nil {
		return err
	}
	reader := tar.NewReader(contextReader{ctx, f})
	entries := 0
	for {
		_, err := reader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			f.Close()
			return err
		}
		entries++
	}
	f.Close()
	if entries == 0 {
		return backupError("The native archive is empty.")
	}
	err = atomicExport(ctx, target, func(output *os.File) error {
		archive, err := os.Open(latest)
		if err != nil {
			return err
		}
		defer archive.Close()
		if _, err := io.Copy(output, contextReader{ctx, archive}); err != nil {
			return err
		}
		after, err := os.Stat(latest)
		if err != nil {
			return err
		}
		if before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
			return backupError("Native archive changed while staging.")
		}
		return nil
	}, nil)
	if err == nil {
		fmt.Println("Completed native archive staged.")
	}
	return err
}

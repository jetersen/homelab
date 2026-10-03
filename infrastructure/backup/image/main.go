package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"
)

type backupError string

func (e backupError) Error() string { return string(e) }

func run(ctx context.Context, args []string) error {
	if len(args) != 1 {
		return backupError("Expected one backup command; use --help.")
	}
	switch args[0] {
	case "--help", "-h":
		fmt.Println("backup-helper {forgejo|forgejo-recover|home-assistant|sonarr|zigbee}")
	case "forgejo", "forgejo-recover":
		api, err := newKubernetes()
		if err != nil {
			return err
		}
		if args[0] == "forgejo-recover" {
			return recoverForgejo(ctx, api, time.Now())
		}
		layout := forgejoLayout{"/source/local", "/source/nas", "/stage", "/cache"}
		if err := layout.prepare("/proc/self/mountinfo"); err != nil {
			return err
		}
		if err := layout.copy(ctx, true); err != nil {
			return err
		}
		return stageForgejo(ctx, api, func(ctx context.Context) error { return layout.copy(ctx, false) },
			func(ctx context.Context) error { return layout.validate(ctx) })
	case "home-assistant":
		return stageHomeAssistant(ctx, "/data/backups", "/exports/backups/home-assistant.tar", time.Now())
	case "sonarr":
		return exportSonarr(ctx, "/config/config.xml", "/exports/backups/sonarr.zip", "http://sonarr:8989")
	case "zigbee":
		return exportZigbee(ctx, environment(), "/exports/backups/zigbee2mqtt.zip")
	default:
		return backupError("Unknown backup command; use --help.")
	}
	return nil
}

func main() {
	syscall.Umask(0077)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, os.Args[1:]); err != nil {
		var safe backupError
		if errors.As(err, &safe) {
			fmt.Fprintln(os.Stderr, safe)
		} else {
			fmt.Fprintln(os.Stderr, "Backup failed; private diagnostics withheld.")
		}
		os.Exit(1)
	}
}

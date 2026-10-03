package main

import (
	"context"
	"database/sql"
	"net/url"
	"strings"

	_ "modernc.org/sqlite"
)

func validateSQLite(ctx context.Context, path string, tables []string) error {
	db, err := sql.Open("sqlite", (&url.URL{Scheme: "file", Path: path, RawQuery: "mode=ro"}).String())
	if err != nil {
		return err
	}
	defer db.Close()
	db.SetMaxOpenConns(1)
	rows, err := db.QueryContext(ctx, "PRAGMA integrity_check")
	if err != nil {
		return err
	}
	count := 0
	for rows.Next() {
		var result string
		if err := rows.Scan(&result); err != nil {
			rows.Close()
			return err
		}
		if result != "ok" {
			rows.Close()
			return backupError("Staged SQLite database failed its integrity check.")
		}
		count++
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	if count != 1 {
		return backupError("Staged SQLite database failed its integrity check.")
	}
	for _, table := range tables {
		var found int
		if err := db.QueryRowContext(ctx, "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", table).Scan(&found); err != nil {
			return err
		}
		if found != 1 {
			return backupError("Native database is missing application tables.")
		}
	}
	return nil
}

func requireKey(value string) bool { return strings.TrimSpace(value) != "" }

# Paperless

Paperless stores SQLite data, original PDFs, searchable archives, and OCR models
on a retained local SSD PVC. Access `https://paperless.jetersen.dev` from the LAN
or Tailscale. The initial `joseph` login is stored in the Personal vault's
Paperless item in Proton Pass. Changing the bootstrap Secret does not reset an
existing user's password.

Upload PDFs through the web UI. Danish and English OCR run locally; PDFs with
embedded text use their existing text. Email fetching is disabled during the
manual-upload trial. No external AI provider is configured.

Use the `needs-review` inbox tag for incoming letters. Add `needs-action` and the
`Due date` custom field for confirmed deadlines, and remove `needs-action` when
finished. These fields can later drive Home Assistant reminders through a
scheduled workflow or an API integration; reminders are not enabled yet.

## Backups and recovery

The backup policy runs Paperless's native document exporter before capturing
`/storage/export` in an encrypted offsite Kopia repository. The export contains
documents and application metadata, avoiding a copy of the live SQLite file.
See [Kopiur procedures](../../cluster/kopiur/README.md) for manual snapshots
and restoring to an isolated PVC. Restore using Paperless's `document_importer`
with the matching application version and verify representative documents before
switching the live service. Retain Proton originals until recovery is verified.

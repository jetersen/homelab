"""Verify snapshots are self-contained and preserve the source."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backup import snapshot_database


class SnapshotTests(unittest.TestCase):
    def test_wal_database_restores_without_sidecars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source.sqlite", root / "snapshot.sqlite"
            with closing(sqlite3.connect(source)) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("CREATE TABLE messages(text TEXT)")
                writer.execute("INSERT INTO messages VALUES ('retained conversation')")
                writer.commit()
                snapshot_database(source, target)
                self.assertEqual(writer.execute("SELECT count(*) FROM messages").fetchone(), (1,))
            with closing(sqlite3.connect(target)) as restored:
                self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(
                    restored.execute("SELECT text FROM messages").fetchone(),
                    ("retained conversation",),
                )
            self.assertFalse(Path(str(target) + "-wal").exists())
            self.assertFalse(target.with_suffix(".partial").exists())


if __name__ == "__main__":
    unittest.main()

use crate::engine::Analysis;
use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Seek, SeekFrom, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Stamp {
    pub size: u64,
    pub modified_seconds: i64,
    pub modified_nanoseconds: i64,
    pub device: u64,
    pub inode: u64,
}
impl Stamp {
    pub fn read(path: &Path) -> Result<Self> {
        let m = path.symlink_metadata()?;
        ensure!(m.is_file(), "not a regular file");
        Ok(Self {
            size: m.len(),
            modified_seconds: m.mtime(),
            modified_nanoseconds: m.mtime_nsec(),
            device: m.dev(),
            inode: m.ino(),
        })
    }
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Clean,
    Suspect,
    Error,
    Changed,
    Unsupported,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Record {
    pub schema: u32,
    pub scope: String,
    pub path: String,
    pub stamp: Stamp,
    pub status: Status,
    pub checked_at_unix: u64,
    pub elapsed_seconds: f64,
    pub analysis: Analysis,
}
pub struct Report {
    file: File,
    cached: HashMap<String, Record>,
}
impl Report {
    pub fn open(path: &Path, scope: &str) -> Result<Self> {
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .mode(0o600)
            .open(path)?;
        file.try_lock()
            .context("another scanner holds this report")?;
        let mut cached = HashMap::new();
        let mut reader = BufReader::new(file.try_clone()?);
        let mut position = 0;
        loop {
            let mut line = Vec::new();
            let count = reader.read_until(b'\n', &mut line)?;
            if count == 0 {
                break;
            }
            if line.last() != Some(&b'\n') {
                ensure!(
                    position > 0 || line.starts_with(b"{\"schema\":1,"),
                    "unrecognized report; refusing to truncate it"
                );
                file.set_len(position)?;
                break;
            }
            let r: Record = serde_json::from_slice(&line)
                .context("invalid report record; refusing to discard history")?;
            ensure!(r.schema == 1, "unsupported report schema");
            if r.scope == scope {
                cached.insert(r.path.clone(), r);
            }
            position += count as u64;
        }
        file.seek(SeekFrom::End(0))?;
        Ok(Self { file, cached })
    }
    pub fn previous(&self, path: &str, stamp: &Stamp) -> Option<&Record> {
        self.cached
            .get(path)
            .filter(|r| r.stamp == *stamp && matches!(r.status, Status::Clean | Status::Suspect))
    }
    pub fn write(&mut self, record: &Record) -> Result<()> {
        serde_json::to_writer(&mut self.file, record)?;
        self.file.write_all(b"\n")?;
        self.file.sync_data()?;
        Ok(())
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn record() -> Record {
        Record {
            schema: 1,
            scope: "test".into(),
            path: "/a\nb.mkv".into(),
            stamp: Stamp {
                size: 1,
                modified_seconds: 1,
                modified_nanoseconds: 2,
                device: 3,
                inode: 4,
            },
            status: Status::Clean,
            checked_at_unix: 0,
            elapsed_seconds: 0.0,
            analysis: Analysis::default(),
        }
    }
    #[test]
    fn resume_lock_and_partial_tail() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("report");
        let record = record();
        let mut r = Report::open(&p, "test").unwrap();
        assert!(Report::open(&p, "test").is_err());
        r.write(&record).unwrap();
        drop(r);
        let length = p.metadata().unwrap().len();
        OpenOptions::new()
            .append(true)
            .open(&p)
            .unwrap()
            .write_all(b"{partial")
            .unwrap();
        let r = Report::open(&p, "test").unwrap();
        assert_eq!(p.metadata().unwrap().len(), length);
        assert!(r.previous(&record.path, &record.stamp).is_some());
        drop(r);
        let r = Report::open(&p, "other-engine").unwrap();
        assert!(r.previous(&record.path, &record.stamp).is_none());
        drop(r);
        OpenOptions::new()
            .append(true)
            .open(&p)
            .unwrap()
            .write_all(b"{invalid}\n")
            .unwrap();
        assert!(Report::open(&p, "test").is_err());
    }

    #[test]
    fn refuses_to_truncate_an_unrecognized_file() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("not-a-report");
        let original = b"\x1a\x45\xdf\xa3media";
        std::fs::write(&p, original).unwrap();
        assert!(Report::open(&p, "test").is_err());
        assert_eq!(std::fs::read(&p).unwrap(), original);
    }

    #[test]
    fn changed_files_and_failed_scans_are_not_cached() {
        let d = tempfile::tempdir().unwrap();
        let p = d.path().join("report");
        let mut record = record();
        let mut r = Report::open(&p, "test").unwrap();
        r.write(&record).unwrap();
        drop(r);
        let mut r = Report::open(&p, "test").unwrap();
        let mut changed = record.stamp.clone();
        changed.modified_nanoseconds += 1;
        assert!(r.previous(&record.path, &changed).is_none());
        record.status = Status::Error;
        r.write(&record).unwrap();
        drop(r);
        let r = Report::open(&p, "test").unwrap();
        assert!(r.previous(&record.path, &record.stamp).is_none());
    }
}

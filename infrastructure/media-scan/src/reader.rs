use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use std::os::unix::fs::FileExt;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, AtomicU64, Ordering},
};
use std::time::Instant;

#[derive(Default)]
pub struct Observed {
    pub bytes: AtomicU64,
    pub position: AtomicU64,
    pub error: Mutex<Option<String>>,
}

// Keep a read window across seeks. Demuxers repeatedly seek to EOF to check a
// block's bounds; ordinary BufReader::seek discards its buffer on those trips.
pub struct Reader {
    file: File,
    length: u64,
    position: u64,
    window_start: u64,
    window: Vec<u8>,
    valid: usize,
    observed: Arc<Observed>,
    stop: Arc<AtomicBool>,
    deadline: Instant,
}

impl Reader {
    pub fn new(
        file: File,
        observed: Arc<Observed>,
        stop: Arc<AtomicBool>,
        deadline: Instant,
    ) -> io::Result<Self> {
        Ok(Self {
            length: file.metadata()?.len(),
            file,
            position: 0,
            window_start: 0,
            window: vec![0; 1024 * 1024],
            valid: 0,
            observed,
            stop,
            deadline,
        })
    }

    fn check(&self) -> io::Result<()> {
        if self.stop.load(Ordering::Relaxed) || Instant::now() >= self.deadline {
            return Err(io::Error::other("scan interrupted or timed out"));
        }
        Ok(())
    }

    fn remember<T>(&self, result: io::Result<T>) -> io::Result<T> {
        if let Err(error) = &result {
            *self.observed.error.lock().unwrap() = Some(error.to_string());
        }
        result
    }
}

impl Read for Reader {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        self.remember(self.check())?;
        if out.is_empty() || self.position >= self.length {
            return Ok(0);
        }
        if self.position < self.window_start
            || self.position >= self.window_start + self.valid as u64
        {
            let result = self.file.read_at(&mut self.window, self.position);
            self.valid = self.remember(result)?;
            self.window_start = self.position;
            self.observed
                .bytes
                .fetch_add(self.valid as u64, Ordering::Relaxed);
            if self.valid == 0 && self.position < self.length {
                return self.remember(Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "file became shorter while scanning",
                )));
            }
        }
        let offset = (self.position - self.window_start) as usize;
        let n = out.len().min(self.valid - offset);
        out[..n].copy_from_slice(&self.window[offset..offset + n]);
        self.position += n as u64;
        self.observed
            .position
            .store(self.position, Ordering::Relaxed);
        Ok(n)
    }
}

impl Seek for Reader {
    fn seek(&mut self, from: SeekFrom) -> io::Result<u64> {
        self.remember(self.check())?;
        let position = match from {
            SeekFrom::Start(n) => i128::from(n),
            SeekFrom::End(n) => i128::from(self.length) + i128::from(n),
            SeekFrom::Current(n) => i128::from(self.position) + i128::from(n),
        };
        let position = u64::try_from(position)
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "invalid seek"))?;
        self.position = position;
        self.observed.position.store(position, Ordering::Relaxed);
        Ok(position)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::time::Duration;
    #[test]
    fn eof_bounds_checks_do_not_re_read_the_window() {
        let mut file = tempfile::tempfile().unwrap();
        file.write_all(&vec![7; 4096]).unwrap();
        let observed = Arc::new(Observed::default());
        let mut reader = Reader::new(
            file,
            observed.clone(),
            Arc::new(AtomicBool::new(false)),
            Instant::now() + Duration::from_secs(1),
        )
        .unwrap();
        let mut byte = [0];
        reader.read_exact(&mut byte).unwrap();
        assert_eq!(reader.seek(SeekFrom::End(0)).unwrap(), 4096);
        reader.seek(SeekFrom::Start(1)).unwrap();
        reader.read_exact(&mut byte).unwrap();
        assert_eq!(byte, [7]);
        assert_eq!(observed.bytes.load(Ordering::Relaxed), 4096);
        assert!(reader.seek(SeekFrom::Current(-10)).is_err());
    }

    #[test]
    fn cancellation_and_short_reads_remain_visible_to_the_engine() {
        let mut file = tempfile::tempfile().unwrap();
        file.write_all(&[1; 4096]).unwrap();
        let writer = file.try_clone().unwrap();
        let observed = Arc::new(Observed::default());
        let stop = Arc::new(AtomicBool::new(false));
        let mut reader = Reader::new(
            file,
            observed.clone(),
            stop.clone(),
            Instant::now() + Duration::from_secs(1),
        )
        .unwrap();
        writer.set_len(0).unwrap();
        assert!(reader.read(&mut [0]).is_err());
        assert!(
            observed
                .error
                .lock()
                .unwrap()
                .take()
                .unwrap()
                .contains("shorter")
        );
        stop.store(true, Ordering::Relaxed);
        assert!(reader.seek(SeekFrom::Start(0)).is_err());
        assert!(
            observed
                .error
                .lock()
                .unwrap()
                .take()
                .unwrap()
                .contains("interrupted")
        );
    }
}

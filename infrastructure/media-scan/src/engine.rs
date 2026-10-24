use crate::{
    reader::{Observed, Reader},
    timeline::{Stream, Timeline},
};
use anyhow::{Context, Result, anyhow};
use matroska_demuxer::{Frame, MatroskaFile, TrackType};
use nix::{
    sys::signal::{Signal, killpg},
    unistd::Pid,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::os::unix::process::CommandExt;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::{
    Arc,
    atomic::{AtomicBool, Ordering},
};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Default, Debug, Clone, Serialize, Deserialize)]
pub struct Analysis {
    pub complete: bool,
    pub streams: Vec<Stream>,
    pub findings: Vec<String>,
    pub diagnostic_count: u64,
    pub diagnostics: Vec<String>,
    pub bytes_read: u64,
}
impl Analysis {
    fn finish(&mut self, duration: Option<f64>, gap: f64) {
        if self.streams.is_empty() {
            self.complete = false;
            self.findings.push("no audio/video streams".into());
        }
        for s in &self.streams {
            if s.packets == 0 || s.first_seconds.is_none() {
                self.complete = false;
                self.findings
                    .push(format!("track {} has no timestamped packets", s.track));
            }
            if s.gap_count > 0 {
                self.findings.push(format!(
                    "track {} ({}) has {} timestamp gaps",
                    s.track, s.kind, s.gap_count
                ));
            }
        }
        let last = self
            .streams
            .iter()
            .filter_map(|s| s.end_seconds)
            .reduce(f64::max);
        if let (Some(expected), Some(last)) = (duration.filter(|v| v.is_finite() && *v > 0.0), last)
            && expected - last > gap
        {
            self.findings.push(format!(
                "media ends {:.3}s before its declared end",
                expected - last
            ));
        }
    }
}

pub fn native(path: &Path, gap: f64, timeout: Duration, stop: Arc<AtomicBool>) -> Result<Analysis> {
    let file = File::open(path)?;
    let observed = Arc::new(Observed::default());
    let reader = Reader::new(file, observed.clone(), stop, Instant::now() + timeout)?;
    let mut result = Analysis::default();
    let mut mkv = match MatroskaFile::open(reader) {
        Ok(mkv) => mkv,
        Err(e) => {
            if let Some(error) = observed.error.lock().unwrap().take() {
                return Err(anyhow!(error));
            }
            result.findings.push(format!("Matroska header: {e}"));
            result.diagnostic_count = 1;
            return Ok(result);
        }
    };
    let scale = mkv.info().timestamp_scale().get() as f64 / 1e9;
    let duration = mkv.info().duration().map(|d| d * scale);
    let mut timelines = BTreeMap::new();
    let mut defaults = BTreeMap::new();
    for track in mkv.tracks() {
        let kind = match track.track_type() {
            TrackType::Video => "video",
            TrackType::Audio => "audio",
            _ => continue,
        };
        let id = track.track_number().get();
        timelines.insert(id, Timeline::new(id, kind.into(), gap));
        defaults.insert(
            id,
            track
                .default_duration()
                .map_or(0.0, |d| d.get() as f64 / 1e9),
        );
    }
    let mut frame = Frame::default();
    loop {
        match mkv.next_frame(&mut frame) {
            Ok(true) => {
                if let Some(timeline) = timelines.get_mut(&frame.track) {
                    let d = frame
                        .duration
                        .map_or(defaults[&frame.track], |v| v as f64 * scale);
                    timeline.push(Some(frame.timestamp as f64 * scale), d);
                }
            }
            Ok(false) => {
                result.complete = true;
                break;
            }
            Err(error) => {
                result.findings.push(format!(
                    "Matroska structure near byte {}: {error}",
                    observed.position.load(Ordering::Relaxed)
                ));
                result.diagnostic_count += 1;
                break;
            }
        }
    }
    // This demuxer treats some I/O failures as EOF. Never promote those to success.
    if let Some(error) = observed.error.lock().unwrap().take() {
        return Err(anyhow!(error));
    }
    result.bytes_read = observed.bytes.load(Ordering::Relaxed);
    result.streams = timelines.into_values().map(Timeline::finish).collect();
    result.finish(duration, gap);
    Ok(result)
}

fn num(value: Option<&&str>) -> Option<f64> {
    value?.parse::<f64>().ok().filter(|v| v.is_finite())
}
fn parse_probe(reader: impl BufRead, gap: f64) -> Result<Analysis> {
    let mut timelines = BTreeMap::new();
    let mut kinds = BTreeMap::new();
    let mut expected = None;
    let mut result = Analysis::default();
    for line in reader.lines() {
        let line = line?;
        let mut parts = line.split('|');
        let kind = parts.next().unwrap_or_default();
        let values: BTreeMap<_, _> = parts.filter_map(|s| s.split_once('=')).collect();
        match kind {
            "packet" => {
                let id = values
                    .get("stream_index")
                    .context("missing packet stream index")?
                    .parse::<u64>()?;
                let timeline = timelines
                    .entry(id)
                    .or_insert_with(|| Timeline::new(id, String::new(), gap));
                timeline.push(
                    num(values.get("pts_time")).or_else(|| num(values.get("dts_time"))),
                    num(values.get("duration_time")).unwrap_or(0.0),
                );
            }
            "stream" => {
                let id = values
                    .get("index")
                    .context("missing stream index")?
                    .parse::<u64>()?;
                let kind = *values.get("codec_type").unwrap_or(&"unknown");
                if matches!(kind, "audio" | "video")
                    && values.get("disposition:attached_pic") != Some(&"1")
                {
                    kinds.insert(id, kind.to_string());
                }
            }
            "format" => {
                result.complete = true;
                expected = num(values.get("duration"))
                    .map(|d| d + num(values.get("start_time")).unwrap_or(0.0));
            }
            _ => {}
        }
    }
    for (id, kind) in kinds {
        let mut timeline = timelines
            .remove(&id)
            .unwrap_or_else(|| Timeline::new(id, kind.clone(), gap));
        timeline.stream.kind = kind;
        result.streams.push(timeline.finish());
    }
    result.finish(expected, gap);
    Ok(result)
}

pub fn ffprobe(
    path: &Path,
    binary: &Path,
    gap: f64,
    timeout: Duration,
    stop: Arc<AtomicBool>,
) -> Result<Analysis> {
    let mut child = Command::new(binary)
        .args([
            "-v",
            "warning",
            "-protocol_whitelist",
            "file,pipe",
            "-show_packets",
            "-show_streams",
            "-show_format",
            "-show_entries",
            concat!(
                "packet=stream_index,pts_time,dts_time,duration_time:",
                "stream=index,codec_type:stream_disposition=attached_pic:",
                "stream_tags=:format_tags=:format=start_time,duration"
            ),
            "-of",
            "compact=p=1:nk=0",
            "-i",
        ])
        .arg(path)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()
        .context("starting FFprobe")?;
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();
    let out = thread::spawn(move || parse_probe(BufReader::new(stdout), gap));
    let err = thread::spawn(move || -> Result<(u64, Vec<String>)> {
        let mut count = 0;
        let mut examples = Vec::new();
        for line in BufReader::new(stderr).lines() {
            let line = line?;
            if !line.trim().is_empty() {
                count += 1;
                if examples.len() < 20 {
                    examples.push(line.chars().take(4096).collect());
                }
            }
        }
        Ok((count, examples))
    });
    let started = Instant::now();
    let mut interrupted = false;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if stop.load(Ordering::Relaxed) || started.elapsed() >= timeout {
            interrupted = true;
            let _ = killpg(Pid::from_raw(child.id() as i32), Signal::SIGKILL);
            let _ = child.kill();
            break child.wait()?;
        }
        thread::sleep(Duration::from_millis(20));
    };
    let mut result = out
        .join()
        .map_err(|_| anyhow!("packet reader panicked"))??;
    (result.diagnostic_count, result.diagnostics) = err
        .join()
        .map_err(|_| anyhow!("diagnostic reader panicked"))??;
    if interrupted {
        return Err(anyhow!("scan interrupted or timed out"));
    }
    if !status.success() {
        result.complete = false;
        result
            .findings
            .push(format!("FFprobe exited with {status}"));
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    #[test]
    fn excludes_sparse_subtitles_and_detects_declared_tail_loss() {
        let s = "packet|stream_index=0|pts_time=0|duration_time=1\nstream|index=0|codec_type=video\nstream|index=1|codec_type=subtitle\nformat|duration=10\n";
        let a = parse_probe(Cursor::new(s), 2.0).unwrap();
        assert_eq!(a.streams.len(), 1);
        assert!(a.findings[0].contains("declared end"));
    }

    #[test]
    fn timeout_terminates_probe_and_its_pipe_holding_child() {
        use std::os::unix::fs::PermissionsExt;
        let directory = tempfile::tempdir().unwrap();
        let probe = directory.path().join("probe");
        std::fs::write(&probe, "#!/bin/sh\nsleep 30 &\nwait\n").unwrap();
        std::fs::set_permissions(&probe, std::fs::Permissions::from_mode(0o700)).unwrap();
        let started = Instant::now();
        let result = ffprobe(
            Path::new("unused.mkv"),
            &probe,
            2.0,
            Duration::from_millis(100),
            Arc::new(AtomicBool::new(false)),
        );
        assert!(result.unwrap_err().to_string().contains("timed out"));
        assert!(started.elapsed() < Duration::from_secs(5));
    }
}

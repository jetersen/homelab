mod engine;
mod reader;
mod report;
mod timeline;

use anyhow::{Context, Result, ensure};
use clap::{Parser, ValueEnum};
use nix::sys::{
    resource::{UsageWho, getrusage},
    time::TimeValLike,
};
use report::{Record, Report, Stamp, Status};
use serde::Serialize;
use std::collections::{BTreeMap, VecDeque};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
    mpsc,
};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use walkdir::WalkDir;

#[derive(Debug, Clone, Copy, ValueEnum, Serialize)]
#[serde(rename_all = "snake_case")]
enum Engine {
    Native,
    Ffprobe,
}
#[derive(Debug, Parser)]
#[command(
    version,
    about = "Concurrent, read-only media integrity and timestamp-gap scanning"
)]
struct Args {
    #[arg(required = true)]
    paths: Vec<PathBuf>,
    /// Append results and resume completed unchanged files. Keep outside source control.
    #[arg(long)]
    report: PathBuf,
    /// Native Matroska/WebM demuxing, or FFprobe for comparison/other formats.
    #[arg(long, value_enum, default_value = "native")]
    engine: Engine,
    #[arg(long,default_value_t=4,value_parser=clap::value_parser!(u16).range(1..=64))]
    jobs: u16,
    /// Minimum uncovered interval to flag. Shorter gaps are not reported.
    #[arg(long,default_value="2",value_parser=positive_float)]
    gap_seconds: f64,
    #[arg(long, default_value = "ffprobe")]
    ffprobe: PathBuf,
    #[arg(long,default_value_t=900,value_parser=clap::value_parser!(u64).range(1..))]
    timeout_seconds: u64,
    /// Recheck unchanged files; also use this for throughput benchmarks.
    #[arg(long)]
    force: bool,
    /// Optional stable host/filesystem identity for report reuse.
    #[arg(long)]
    source: Option<String>,
    /// Suppress progress for clean files; summary still appears on stdout.
    #[arg(long)]
    quiet: bool,
}
fn positive_float(s: &str) -> std::result::Result<f64, String> {
    s.parse::<f64>()
        .ok()
        .filter(|v| v.is_finite() && *v > 0.0)
        .ok_or_else(|| "must be positive and finite".into())
}
fn eligible(p: &Path) -> bool {
    p.extension().and_then(|s| s.to_str()).is_some_and(|s| {
        matches!(
            s.to_ascii_lowercase().as_str(),
            "mkv"
                | "webm"
                | "mp4"
                | "m4v"
                | "avi"
                | "mov"
                | "ts"
                | "m2ts"
                | "mts"
                | "mpg"
                | "mpeg"
                | "wmv"
                | "flv"
                | "vob"
                | "ogv"
                | "flac"
                | "mp3"
                | "m4a"
                | "mka"
                | "ogg"
                | "opus"
                | "wav"
                | "aac"
                | "ac3"
                | "dts"
                | "aiff"
                | "wma"
        )
    })
}
fn discover(roots: &[PathBuf]) -> Result<Vec<(String, Stamp)>> {
    let mut files = BTreeMap::new();
    for root in roots {
        ensure!(
            !root.symlink_metadata()?.file_type().is_symlink(),
            "scan roots must not be symlinks"
        );
        for entry in WalkDir::new(root.canonicalize()?).follow_links(false) {
            let entry = entry.context("media discovery failed; this scan would be incomplete")?;
            if entry.file_type().is_file() && eligible(entry.path()) {
                let path = entry
                    .path()
                    .to_str()
                    .context("media paths must be UTF-8")?
                    .to_string();
                files.insert(path, Stamp::read(entry.path())?);
            }
        }
    }
    ensure!(!files.is_empty(), "no supported media files found");
    Ok(files.into_iter().collect())
}
fn scan(path: String, stamp: Stamp, args: &Args, scope: &str, stop: Arc<AtomicBool>) -> Record {
    let started = Instant::now();
    let mut r = Record {
        schema: 1,
        scope: scope.into(),
        path,
        stamp,
        status: Status::Error,
        checked_at_unix: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
        elapsed_seconds: 0.0,
        analysis: engine::Analysis::default(),
    };
    let result = || -> Result<engine::Analysis> {
        ensure!(
            Stamp::read(Path::new(&r.path))? == r.stamp,
            "file changed since discovery"
        );
        let timeout = Duration::from_secs(args.timeout_seconds);
        match args.engine {
            Engine::Native => engine::native(Path::new(&r.path), args.gap_seconds, timeout, stop),
            Engine::Ffprobe => engine::ffprobe(
                Path::new(&r.path),
                &args.ffprobe,
                args.gap_seconds,
                timeout,
                stop,
            ),
        }
    };
    if matches!(args.engine, Engine::Native)
        && !Path::new(&r.path).extension().is_some_and(|s| {
            s.eq_ignore_ascii_case("mkv")
                || s.eq_ignore_ascii_case("webm")
                || s.eq_ignore_ascii_case("mka")
        })
    {
        r.status = Status::Unsupported;
        r.analysis.findings.push(
            "native engine supports Matroska/WebM; use --engine ffprobe for this format".into(),
        );
    } else {
        match std::panic::catch_unwind(std::panic::AssertUnwindSafe(result)) {
            Ok(Ok(a)) => {
                r.status = if a.complete && a.findings.is_empty() && a.diagnostic_count == 0 {
                    Status::Clean
                } else if a.diagnostic_count > 0 || (a.complete && !a.findings.is_empty()) {
                    Status::Suspect
                } else {
                    Status::Error
                };
                r.analysis = a;
            }
            Ok(Err(error)) => r.analysis.findings.push(format!("{error:#}")),
            Err(_) => r
                .analysis
                .findings
                .push("demuxer panicked while reading malformed media".into()),
        }
    }
    if !Stamp::read(Path::new(&r.path)).is_ok_and(|s| s == r.stamp) {
        r.status = Status::Changed;
        r.analysis
            .findings
            .push("file changed or disappeared; retry it".into());
    }
    r.elapsed_seconds = started.elapsed().as_secs_f64();
    r
}
#[derive(Default, Serialize)]
struct Summary {
    engine: String,
    jobs: u16,
    files: usize,
    bytes: u64,
    scanned: usize,
    cached: usize,
    clean: usize,
    suspect: usize,
    errors: usize,
    changed: usize,
    unsupported: usize,
    pending: usize,
    elapsed_seconds: f64,
    files_per_second: f64,
    gib_per_second: f64,
    cpu_seconds: f64,
    self_peak_rss_kib: i64,
    child_peak_rss_kib: i64,
}
impl Summary {
    fn count(&mut self, r: &Record) {
        match r.status {
            Status::Clean => self.clean += 1,
            Status::Suspect => self.suspect += 1,
            Status::Error => self.errors += 1,
            Status::Changed => self.changed += 1,
            Status::Unsupported => self.unsupported += 1,
        }
    }
}
fn execute(args: Args, stop: Arc<AtomicBool>) -> Result<i32> {
    let started = Instant::now();
    let version = if matches!(args.engine, Engine::Ffprobe) {
        let out = Command::new(&args.ffprobe)
            .arg("-version")
            .output()
            .context("FFprobe is required for --engine ffprobe")?;
        ensure!(out.status.success(), "FFprobe version check failed");
        String::from_utf8(out.stdout)?
            .lines()
            .next()
            .unwrap_or_default()
            .to_string()
    } else {
        "native-matroska-demuxer-0.8.1".into()
    };
    let source = args.source.clone().unwrap_or_else(|| {
        std::fs::read_to_string("/etc/hostname")
            .unwrap_or_else(|_| "unknown-host".into())
            .trim()
            .into()
    });
    let scope = serde_json::to_string(&(
        env!("CARGO_PKG_VERSION"),
        args.engine,
        version,
        args.gap_seconds,
        source,
    ))?;
    let mut report = Report::open(&args.report, &scope).context("opening report")?;
    let files = discover(&args.paths)?;
    let mut summary = Summary {
        engine: format!("{:?}", args.engine).to_lowercase(),
        jobs: args.jobs,
        files: files.len(),
        bytes: files.iter().map(|(_, s)| s.size).sum(),
        ..Summary::default()
    };
    let mut pending = VecDeque::new();
    for (path, stamp) in files {
        if !args.force
            && let Some(r) = report.previous(&path, &stamp)
        {
            summary.cached += 1;
            summary.count(r);
            if r.status != Status::Clean {
                eprintln!("CACHED {:?} {:?}", r.status, r.path);
            }
        } else {
            pending.push_back((path, stamp));
        }
    }
    eprintln!(
        "{} files, {:.1} GB, {} cached, {} workers, {:?}",
        summary.files,
        summary.bytes as f64 / 1e9,
        summary.cached,
        args.jobs,
        args.engine
    );
    let pending = Arc::new(Mutex::new(pending));
    let args = Arc::new(args);
    let (send, receive) = mpsc::channel();
    let mut workers = Vec::new();
    for _ in 0..usize::from(args.jobs).min(summary.files) {
        let (pending, args, scope, send, stop) = (
            pending.clone(),
            args.clone(),
            scope.clone(),
            send.clone(),
            stop.clone(),
        );
        workers.push(thread::spawn(move || {
            while !stop.load(Ordering::Relaxed) {
                let Some((path, stamp)) = pending.lock().unwrap().pop_front() else {
                    break;
                };
                if send
                    .send(scan(path, stamp, &args, &scope, stop.clone()))
                    .is_err()
                {
                    break;
                }
            }
        }));
    }
    drop(send);
    let mut write_error = None;
    for r in receive {
        if let Err(error) = report.write(&r) {
            stop.store(true, Ordering::Relaxed);
            write_error = Some(error);
            break;
        }
        summary.scanned += 1;
        summary.count(&r);
        if !args.quiet || r.status != Status::Clean {
            eprintln!(
                "[{}/{}] {:?} {:?} ({:.2}s)",
                summary.scanned + summary.cached,
                summary.files,
                r.status,
                r.path,
                r.elapsed_seconds
            );
        }
        for finding in &r.analysis.findings {
            eprintln!("  {finding}");
        }
        for diagnostic in r.analysis.diagnostics.iter().take(2) {
            eprintln!("  {diagnostic}");
        }
    }
    for worker in workers {
        worker
            .join()
            .map_err(|_| anyhow::anyhow!("worker panicked"))?;
    }
    if let Some(error) = write_error {
        return Err(error.context("saving scan result"));
    }
    summary.pending = summary.files - summary.cached - summary.scanned;
    summary.elapsed_seconds = started.elapsed().as_secs_f64();
    if summary.cached
        + summary.suspect
        + summary.errors
        + summary.changed
        + summary.unsupported
        + summary.pending
        == 0
    {
        summary.files_per_second = summary.scanned as f64 / summary.elapsed_seconds;
        summary.gib_per_second = summary.bytes as f64 / 1073741824.0 / summary.elapsed_seconds;
    }
    let own = getrusage(UsageWho::RUSAGE_SELF)?;
    let children = getrusage(UsageWho::RUSAGE_CHILDREN)?;
    summary.cpu_seconds = (own.user_time().num_microseconds()
        + own.system_time().num_microseconds()
        + children.user_time().num_microseconds()
        + children.system_time().num_microseconds()) as f64
        / 1e6;
    summary.self_peak_rss_kib = own.max_rss();
    summary.child_peak_rss_kib = children.max_rss();
    println!("{}", serde_json::to_string(&summary)?);
    Ok(if stop.load(Ordering::Relaxed) {
        130
    } else if summary.errors + summary.changed + summary.unsupported > 0 {
        2
    } else if summary.suspect > 0 {
        1
    } else {
        0
    })
}
fn main() {
    let args = Args::parse();
    let stop = Arc::new(AtomicBool::new(false));
    let signal = stop.clone();
    if let Err(error) = ctrlc::set_handler(move || {
        signal.store(true, Ordering::Relaxed);
    }) {
        eprintln!("signal handler: {error}");
        std::process::exit(2);
    }
    match execute(args, stop) {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("scan failed: {error:#}");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn discovery_deduplicates_roots_and_does_not_follow_symlinks() {
        let dir = tempfile::tempdir().unwrap();
        let media = dir.path().join("video.MKV");
        std::fs::write(&media, b"test").unwrap();
        std::os::unix::fs::symlink(&media, dir.path().join("link.mkv")).unwrap();
        let found = discover(&[dir.path().into(), media]).unwrap();
        assert_eq!(found.len(), 1);
        assert!(discover(&[dir.path().join("link.mkv")]).is_err());
        assert!(discover(&[dir.path().join("missing")]).is_err());
    }
}

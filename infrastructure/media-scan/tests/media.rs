use serde_json::Value;
use std::fs;
use std::path::Path;
use std::process::Command;

fn scan(engine: &str, path: &Path, report: &Path) -> (i32, Value) {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_media-scan"));
    cmd.args(["--engine", engine, "--jobs", "2", "--report"])
        .arg(report)
        .arg(path);
    if engine == "ffprobe" {
        cmd.arg("--ffprobe")
            .arg(std::env::var("FFPROBE").unwrap_or_else(|_| "ffprobe".into()));
    }
    let out = cmd.output().unwrap();
    assert!(
        !out.stdout.is_empty(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    (
        out.status.code().unwrap(),
        serde_json::from_slice(&out.stdout).unwrap(),
    )
}

#[test]
#[ignore = "requires ffmpeg and ffprobe (or FFMPEG/FFPROBE paths)"]
fn native_and_ffprobe_detect_zeroes_gaps_and_truncation() {
    let tmp = tempfile::tempdir().unwrap();
    let clean = tmp.path().join("clean\nvideo.mkv");
    let ffmpeg = std::env::var("FFMPEG").unwrap_or_else(|_| "ffmpeg".into());
    let out = Command::new(&ffmpeg)
        .args([
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24,noise=alls=100:allf=t",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "12",
            "-c:v",
            "ffv1",
            "-threads:v",
            "1",
            "-c:a",
            "pcm_s16le",
            "-y",
        ])
        .arg(&clean)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let original = fs::read(&clean).unwrap();
    assert!(original.len() > 12 * 1024 * 1024);
    let mut bytes = original.clone();
    bytes[4 * 1024 * 1024..12 * 1024 * 1024].fill(0);
    let zeroed = tmp.path().join("zeroed.mkv");
    fs::write(&zeroed, bytes).unwrap();
    let truncated = tmp.path().join("truncated.mkv");
    fs::write(&truncated, &original[..original.len() / 2]).unwrap();
    let gaps = tmp.path().join("gaps.mkv");
    let out = Command::new(&ffmpeg)
        .args(["-v", "error", "-i"])
        .arg(&clean)
        .args([
            "-vf",
            "select=not(between(t\\,2\\,5))",
            "-af",
            "aselect=not(between(t\\,2\\,5))",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "ffv1",
            "-threads:v",
            "1",
            "-c:a",
            "pcm_s16le",
            "-y",
        ])
        .arg(&gaps)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    for engine in ["native", "ffprobe"] {
        for (case, path, want) in [
            ("clean", &clean, 0),
            ("zeroed", &zeroed, 1),
            ("truncated", &truncated, 1),
            ("gaps", &gaps, 1),
        ] {
            let report = tmp.path().join(format!("{engine}-{case}.jsonl"));
            let (exit, summary) = scan(engine, path, &report);
            assert_eq!(exit, want, "{engine}/{case}: {summary}");
            if case == "gaps" {
                let record: Value =
                    serde_json::from_str(fs::read_to_string(&report).unwrap().trim()).unwrap();
                let streams = record["analysis"]["streams"].as_array().unwrap();
                assert_eq!(streams.len(), 2);
                assert!(
                    streams.iter().all(|s| s["gap_count"].as_u64().unwrap() > 0),
                    "{record}"
                );
            }
            let (_, resumed) = scan(engine, path, &report);
            assert_eq!(resumed["cached"], 1, "{resumed}");
            assert_eq!(resumed["scanned"], 0);
        }
    }
    assert_eq!(fs::read(&clean).unwrap(), original);
}

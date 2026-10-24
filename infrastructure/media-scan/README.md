# Media scan

Read-only audio/video integrity checks with concurrent file scanning and resumable
JSONL results. The native engine demuxes Matroska/WebM in Rust without FFmpeg or
other runtime dependencies. `--engine ffprobe` supports additional containers and
provides a comparison engine with the same timestamp-gap analysis.

Both engines inspect packets without decoding codecs. They report container
errors, gaps in each audio/video track, and premature endings when a declared
duration is available. They ignore subtitle timing and tolerate presentation
reordering. A clean result does not establish that every compressed frame decodes
correctly. Deliberate discontinuities can also produce findings; review suspect
files before replacing them.

## Build and run

Requires Rust 1.95+ on Linux. FFprobe is needed only for its comparison engine.

```sh
cargo build --locked --release --manifest-path infrastructure/media-scan/Cargo.toml
mkdir -p ~/.local/state/media-scan
infrastructure/media-scan/target/release/media-scan \
  --jobs 4 --report ~/.local/state/media-scan/results.jsonl /srv/media
```

The default gap threshold is two seconds; change it with `--gap-seconds`.
`--timeout-seconds` bounds an individual scan, apart from uninterruptible kernel
I/O. Files that change during scanning, unsupported formats, and incomplete
checks never pass. Discovery errors abort the scan. Directory symlinks and file
symlinks are not followed; scan roots must be real paths.

Each completed file is saved immediately. Repeat the same command to resume.
Unchanged clean and suspect results are reused only for the same engine,
threshold, version, and source identity. Use `--source` to keep a stable identity
across replacement containers that access the same filesystem. Use `--force` to
recheck unchanged files, including damage that preserves size and modification
time. Reports are private operational output; keep them outside the repository.

Progress goes to stderr; a JSON summary with throughput, CPU time, and peak RSS
goes to stdout. Exit status: 0 means all selected files passed, 1 means suspect
files, 2 means errors/changed/unsupported files or an incomplete scan, and 130
means interruption. RSS metrics use Linux KiB; child RSS is the largest individual
FFprobe child, not their aggregate. Throughput is selected media size divided by
wall time, not physical disk traffic. Throughput is reported only for complete,
clean scans without cached results.

## Remote execution

Copy a static binary to the target and execute it beside the files. The native
engine does not need an FFmpeg installation. Build for the target architecture;
for example, with the musl target installed in the Rust toolchain:

```sh
cargo build --locked --release --target x86_64-unknown-linux-musl \
  --manifest-path infrastructure/media-scan/Cargo.toml
scp infrastructure/media-scan/target/x86_64-unknown-linux-musl/release/media-scan \
  host:/tmp/media-scan
ssh host '/tmp/media-scan --jobs 4 --report /tmp/media-scan.jsonl /srv/media'
mkdir -p ~/.local/state/media-scan
scp host:/tmp/media-scan.jsonl ~/.local/state/media-scan/remote.jsonl
```

A static GNU build is another option when static glibc development libraries are
available. Set `RUSTFLAGS='-C target-feature=+crt-static'` and build with
`--target x86_64-unknown-linux-gnu`. On NixOS, provide `glibc.static` to the linker
with `-L native=<glibc.static store path>/lib` in `RUSTFLAGS`.

For Kubernetes, copy to a writable executable temporary directory, then run one
scanner process against an existing read-only media mount. No per-file execs,
Jellyfin plugin, or application restart are needed. Keep the report on persistent
storage if it must survive pod replacement. Native read deadlines cannot stop
an NFS hard mount stuck in uninterruptible kernel I/O; interrupt and resume once
storage is available.

## Tests and benchmarks

```sh
cargo fmt --check --manifest-path infrastructure/media-scan/Cargo.toml
cargo clippy --locked --all-targets --manifest-path infrastructure/media-scan/Cargo.toml -- -D warnings
cargo test --locked --manifest-path infrastructure/media-scan/Cargo.toml
# Includes generated clean, zero-filled, truncated, and timestamp-gap MKVs:
cargo test --locked --manifest-path infrastructure/media-scan/Cargo.toml -- --include-ignored
```

The generated-media test requires FFmpeg and FFprobe on PATH, or their paths in
`FFMPEG` and `FFPROBE`.

Benchmark a fixed set of files that both engines report as clean. Use a release
build, `--force`, and separate report paths; otherwise resume makes the comparison
invalid. Compare `--engine native` and `--engine ffprobe` with the same
`--jobs 1`, `--jobs 2`, and `--jobs 4` settings. Warm both engines first and reverse
the order on repeated runs. Use medians and report cache conditions; do not flush
production filesystem caches. CPU reductions may exceed wall-time gains when
storage bandwidth limits both engines.

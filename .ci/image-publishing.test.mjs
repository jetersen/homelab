import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";

const source = resolve(".ci");
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), "image-publication-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const cwd = join(root, "repo");
  mkdirSync(cwd);
  const env = {
    ...process.env,
    GIT_CONFIG_GLOBAL: "/dev/null",
    GIT_CONFIG_NOSYSTEM: "1",
    GIT_AUTHOR_NAME: "Test",
    GIT_AUTHOR_EMAIL: "test@example.invalid",
    GIT_COMMITTER_NAME: "Test",
    GIT_COMMITTER_EMAIL: "test@example.invalid",
  };
  function run(command, args, overrides = {}, ok = true) {
    const result = spawnSync(command, args, {
      cwd,
      env: { ...env, ...overrides },
      encoding: "utf8",
    });
    if (ok) {
      assert.equal(
        result.status,
        0,
        `${command} ${args.join(" ")}\n${result.stdout}\n${result.stderr}`,
      );
    }
    return result;
  }
  const git = (...args) => run("git", args).stdout.trim();
  const write = (path, text) => {
    mkdirSync(dirname(join(cwd, path)), { recursive: true });
    writeFileSync(join(cwd, path), text);
  };
  git("init", "-b", "main");
  run("git", ["init", "--bare", join(root, "origin.git")]);
  git("remote", "add", "origin", join(root, "origin.git"));
  mkdirSync(join(cwd, ".ci"));
  for (const file of [
    "image-inputs.sh",
    "image-release.sh",
    "publish-image.sh",
    "check-runner.sh",
    "backup-helper-cliff.toml",
    "runner-job-cliff.toml",
  ]) {
    copyFileSync(join(source, file), join(cwd, ".ci", file));
  }
  function commit(path, text, message) {
    write(path, text);
    git("add", ".");
    git("commit", "-m", message);
    git("push", "origin", "main");
    return git("rev-parse", "HEAD");
  }
  commit("infrastructure/backup/image/main.go", "helper", "feat: initial helper");
  commit("infrastructure/forgejo/runner/Dockerfile", "runner", "feat: initial runner");
  const output = join(root, "env");
  function release(component, ok = true) {
    writeFileSync(output, "");
    const result = run("bash", [".ci/image-release.sh", component], { GITHUB_ENV: output }, ok);
    return {
      result,
      values: Object.fromEntries(
        readFileSync(output, "utf8")
          .trim()
          .split("\n")
          .map((line) => line.split("=")),
      ),
    };
  }
  return { root, cwd, run, git, write, commit, release, env };
}

test("component releases are independent and immutable", (t) => {
  const f = fixture(t);
  const helper = f.release("backup-helper").values;
  const runner = f.release("runner-job").values;
  assert.equal(helper.BACKUP_HELPER_VERSION, "0.1.0");
  assert.equal(runner.RUNNER_JOB_VERSION, "0.1.0");
  f.commit("infrastructure/backup/image/main_test.go", "test", "feat: helper tests");
  f.commit("README.md", "docs", "feat: unrelated change");
  assert.deepEqual(f.release("backup-helper").values, helper);
  assert.deepEqual(f.release("runner-job").values, runner);
  f.commit("infrastructure/forgejo/runner/Dockerfile", "runner fix", "fix: runner dependency");
  assert.equal(f.release("runner-job").values.RUNNER_JOB_VERSION, "0.1.1");
  assert.deepEqual(f.release("backup-helper").values, helper);
  f.commit("infrastructure/backup/image/main.go", "helper feature", "feat: helper feature");
  assert.equal(f.release("backup-helper").values.BACKUP_HELPER_VERSION, "0.2.0");
});

test("DNSControl and tooling dependency changes release only the runner image", (t) => {
  const f = fixture(t);
  const helper = f.release("backup-helper").values;
  f.release("runner-job");
  for (const [index, path] of [
    "infrastructure/dns/compat/main.go",
    "infrastructure/dns/install.sh",
    "package.json",
    "package-lock.json",
    "requirements-dev.txt",
  ].entries()) {
    f.commit(path, "dependency update", "fix: update runner tools");
    assert.equal(f.release("runner-job").values.RUNNER_JOB_VERSION, `0.1.${index + 1}`);
    assert.deepEqual(f.release("backup-helper").values, helper);
  }
});

test("unreachable latest release fails rather than resetting the version", (t) => {
  const f = fixture(t);
  f.release("runner-job");
  f.git("checkout", "--orphan", "disconnected");
  f.git("commit", "-m", "fix: disconnected history");
  f.git("tag", "runner-job/v0.9.0");
  f.git("checkout", "main");
  f.commit("infrastructure/forgejo/runner/Dockerfile", "changed", "fix: runner");
  const { result } = f.release("runner-job", false);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /outside this history/);
});

function publisher(t, scenario = "existing") {
  const f = fixture(t);
  const values = f.release("runner-job").values;
  const bin = join(f.root, "bin");
  mkdirSync(bin);
  const log = join(f.root, "docker.log");
  writeFileSync(log, "");
  writeFileSync(
    join(bin, "docker"),
    `#!/usr/bin/env node
const fs = require('node:fs');
const args = process.argv.slice(2);
fs.appendFileSync(process.env.DOCKER_LOG, JSON.stringify(args) + '\\n');
const mode = process.env.SCENARIO;
if (args.slice(0,3).join(' ') === 'buildx imagetools inspect') {
  if (args.includes('{{json .Image}}')) {
    if (mode === 'missing') { console.error('manifest unknown'); process.exit(1); }
    if (mode === 'auth') { console.error('unauthorized: authentication required'); process.exit(1); }
    if (mode === 'network') { console.error('host not found in DNS'); process.exit(1); }
    console.log(JSON.stringify({config:{Labels:{
      'org.opencontainers.image.revision': mode === 'wrong-labels' ? 'wrong' : process.env.RUNNER_JOB_REVISION,
      'org.opencontainers.image.version': process.env.RUNNER_JOB_VERSION
    }}}));
  } else console.log(mode === 'advance-main' && args[3].endsWith(':main') && !fs.existsSync(process.env.DOCKER_LOG + '.moved') ? 'sha256:old' : 'sha256:release');
}
if (args.slice(0,3).join(' ') === 'buildx imagetools create') {
  fs.writeFileSync(process.env.DOCKER_LOG + '.moved', 'yes');
}
`,
    { mode: 0o755 },
  );
  const publish = () =>
    f.run(
      "bash",
      [".ci/publish-image.sh", "runner-job"],
      {
        ...values,
        PATH: `${bin}:${process.env.PATH}`,
        DOCKER_LOG: log,
        SCENARIO: scenario,
        REGISTRY: "registry.invalid",
        REPOSITORY: "Owner/Repo",
      },
      false,
    );
  const calls = () => readFileSync(log, "utf8").trim().split("\n").filter(Boolean).map(JSON.parse);
  return { ...f, publish, calls };
}

test("published release skips build, smoke test, push, and unchanged main", (t) => {
  const f = publisher(t);
  assert.equal(f.publish().status, 0);
  assert.ok(f.calls().every((args) => args.slice(0, 3).join(" ") === "buildx imagetools inspect"));
});
for (const scenario of ["wrong-labels", "auth", "network"]) {
  test(`${scenario} stops without building or changing the registry`, (t) => {
    const f = publisher(t, scenario);
    assert.notEqual(f.publish().status, 0);
    assert.equal(f.calls().length, 1);
  });
}
test("missing release builds, smoke tests, and pushes only the SemVer tag", (t) => {
  const f = publisher(t, "missing");
  assert.equal(f.publish().status, 0);
  const calls = f.calls();
  assert.equal(calls.filter((a) => a[0] === "build").length, 1);
  assert.equal(calls.filter((a) => a[0] === "run").length, 1);
  assert.deepEqual(
    calls.filter((a) => a[0] === "push"),
    [["push", "registry.invalid/owner/repo/runner-job:0.1.0"]],
  );
});
test("older workflow cannot rewind main when newer component inputs exist", (t) => {
  const f = publisher(t);
  const revision = f.git("rev-parse", "HEAD");
  f.commit("infrastructure/forgejo/runner/Dockerfile", "new runner", "fix: newer runner");
  f.git("checkout", "--detach", revision);
  const result = f.publish();
  assert.equal(result.status, 0);
  assert.match(result.stdout, /leaving main unchanged/);
  assert.equal(f.calls().length, 1);
});

test("moving main copies the release digest without rebuilding or wrapping it in an index", (t) => {
  const f = publisher(t, "advance-main");
  assert.equal(f.publish().status, 0);
  assert.deepEqual(
    f.calls().filter((a) => a[2] === "create"),
    [
      [
        "buildx",
        "imagetools",
        "create",
        "--prefer-index=false",
        "--tag",
        "registry.invalid/owner/repo/runner-job:main",
        "registry.invalid/owner/repo/runner-job@sha256:release",
      ],
    ],
  );
  assert.ok(!f.calls().some((a) => ["build", "push"].includes(a[0])));
});

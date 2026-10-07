import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

const script = resolve(".ci/actions/setup-tool/check.sh");

function check(t, tool, installed, pinned = "2.3.4") {
  const root = mkdtempSync(join(tmpdir(), "runner-tool-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const bin = join(root, "bin");
  mkdirSync(bin);
  symlinkSync("/usr/bin/awk", join(bin, "awk"));
  if (installed) {
    const flag = tool === "pulumi" ? "version" : "--version";
    const output = tool === "pulumi" ? `v${installed}` : `${tool} ${installed}`;
    writeFileSync(
      join(bin, tool),
      `#!/bin/sh\n[ "$1" = "${flag}" ] || exit 1\nprintf '%s\\n' '${output}'\n`,
      { mode: 0o755 },
    );
  }
  const dockerfile = join(root, "infrastructure/forgejo/runner/Dockerfile");
  mkdirSync(join(root, "infrastructure/forgejo/runner"), { recursive: true });
  writeFileSync(dockerfile, `FROM registry.invalid/${tool}:v${pinned}@sha256:abc AS ${tool}\n`);
  const output = join(root, "output");
  writeFileSync(output, "");
  const result = spawnSync("/bin/bash", [script], {
    cwd: root,
    env: { PATH: bin, TOOL: tool, GITHUB_OUTPUT: output },
    encoding: "utf8",
  });
  return { ...result, output: readFileSync(output, "utf8") };
}

for (const tool of ["pulumi", "flux", "git-cliff"]) {
  test(`${tool}: reuse the exact bundled version`, (t) => {
    const result = check(t, tool, "2.3.4");
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.output, "version=2.3.4\ninstalled=true\n");
  });
  test(`${tool}: install when absent or on a different version`, (t) => {
    for (const installed of [undefined, "2.3.3", "2.3.5"]) {
      const result = check(t, tool, installed);
      assert.equal(result.status, 0, result.stderr);
      assert.equal(result.output, "version=2.3.4\ninstalled=false\n");
    }
  });
}

test("reject unsupported tools and unpinned versions", (t) => {
  for (const result of [check(t, "unknown"), check(t, "pulumi", undefined, "latest")]) {
    assert.notEqual(result.status, 0);
    assert.equal(result.output, "");
  }
});

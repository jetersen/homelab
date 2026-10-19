import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { shouldForceRebase } from "./should-force-rebase.mjs";

test("an unchanged tree still needs regeneration for strict fast-forward, once", async () => {
  const cwd = mkdtempSync(join(tmpdir(), "renovate-rebase-"));
  const git = (...args) =>
    execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  const config = {
    branchName: "renovate/update",
    baseBranch: "main",
    rebaseWhen: "behind-base-branch",
  };
  const scm = {
    async isBranchBehindBase(branch, base) {
      try {
        git("merge-base", "--is-ancestor", base, branch);
        return false;
      } catch (error) {
        if (error.status === 1) {
          return true;
        }
        throw error;
      }
    },
  };
  try {
    git("init", "--initial-branch=main");
    git("config", "user.name", "renovate[bot]");
    git("config", "user.email", "29139614+renovate[bot]@users.noreply.github.com");
    writeFileSync(join(cwd, "dependency.txt"), "1.0.0\n");
    git("add", "dependency.txt");
    git("commit", "-m", "chore: base");
    git("switch", "-c", config.branchName);
    writeFileSync(join(cwd, "dependency.txt"), "1.0.1\n");
    git("commit", "-am", "chore(deps): update");
    const oldHead = git("rev-parse", "HEAD");
    git("switch", "main");
    git("commit", "--allow-empty", "-m", "ci: advance main without changing its tree");
    // A tree comparison alone misses the divergent history which blocks strict FF.
    assert.equal(await shouldForceRebase(config, scm), true);
    git("rebase", "main", config.branchName);
    assert.equal(git("diff", oldHead, config.branchName), "");
    assert.notEqual(git("rev-parse", config.branchName), oldHead);
    assert.equal(await shouldForceRebase(config, scm), false);
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
});

test("other rebase policies keep their existing commit behavior", async () => {
  assert.equal(
    await shouldForceRebase(
      { rebaseWhen: "conflicted" },
      {
        isBranchBehindBase: () => assert.fail("must preserve the selected rebase policy"),
      },
    ),
    false,
  );
});

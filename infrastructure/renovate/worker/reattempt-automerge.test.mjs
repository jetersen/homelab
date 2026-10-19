import assert from "node:assert/strict";
import { test } from "node:test";
import { reattemptAutomerge } from "./reattempt-automerge.mjs";

const eligible = { number: 87, platformPrOptions: { usePlatformAutomerge: true } };

test("a regenerated eligible PR is armed for native CI-gated strict fast-forward", async () => {
  const calls = [];
  await reattemptAutomerge(eligible, {
    method: "fast-forward-only",
    merge: async (...args) => calls.push(args),
  });
  assert.deepEqual(calls, [
    [
      87,
      { Do: "fast-forward-only", merge_when_checks_succeed: true, delete_branch_after_merge: true },
    ],
  ]);
});
test("review-only updates do not enable native automerge", async () => {
  let called = false;
  await reattemptAutomerge(
    { number: 87 },
    {
      method: "fast-forward-only",
      merge: async () => {
        called = true;
      },
    },
  );
  assert.equal(called, false);
});
test("unsafe repository merge defaults cannot fall back to rebase", async () => {
  for (const method of ["rebase", "merge", "squash", undefined]) {
    await assert.rejects(
      reattemptAutomerge(eligible, { method, merge: async () => assert.fail("unsafe request") }),
      /strict fast-forward-only/,
    );
  }
});
test("an existing schedule is idempotent; other failures propagate", async () => {
  const error = Object.assign(new Error("conflict"), {
    statusCode: 409,
    response: {
      body: { message: "pull request is already scheduled to auto merge when checks succeed" },
    },
  });
  await reattemptAutomerge(eligible, {
    method: "fast-forward-only",
    merge: async () => {
      throw error;
    },
  });
  error.response.body.message = "head changed";
  await assert.rejects(
    reattemptAutomerge(eligible, {
      method: "fast-forward-only",
      merge: async () => {
        throw error;
      },
    }),
    /conflict/,
  );
});

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
test("Forgejo mergeability calculation is retried before arming native automerge", async () => {
  let attempts = 0;
  const delays = [];
  await reattemptAutomerge(eligible, {
    method: "fast-forward-only",
    merge: async () => {
      if (++attempts < 3) {
        throw { statusCode: 405, response: { body: { message: "Please try again later" } } };
      }
    },
    wait: async (ms) => delays.push(ms),
  });
  assert.equal(attempts, 3);
  assert.deepEqual(delays, [1000, 2000]);
});
test("mergeability retries are bounded and do not retry other merge failures", async () => {
  let attempts = 0;
  const error = Object.assign(new Error("not mergeable"), {
    statusCode: 405,
    response: { body: { message: "Please try again later" } },
  });
  const delays = [];
  const options = {
    method: "fast-forward-only",
    merge: async () => {
      attempts++;
      throw error;
    },
    wait: async (ms) => delays.push(ms),
  };
  await assert.rejects(reattemptAutomerge(eligible, options), /not mergeable/);
  assert.equal(attempts, 6);
  assert.deepEqual(delays, [1000, 2000, 4000, 8000, 16000]);
  error.response.body.message = "PR is not ready to be merged";
  await assert.rejects(reattemptAutomerge(eligible, options), /not mergeable/);
  assert.equal(attempts, 7);
});

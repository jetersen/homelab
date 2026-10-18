import assert from "node:assert/strict";
import test from "node:test";
import { verifyChecks } from "./pr-checks-gate.mjs";

test("only selected checks must succeed; unrelated jobs must be skipped", () => {
  const valid = {
    changes: { result: "success", outputs: { csharp: "true", python: "false" } },
    csharp: { result: "success" },
    python: { result: "skipped" },
  };
  verifyChecks(valid);
  for (const [name, result] of [
    ["changes", "failure"],
    ["csharp", "skipped"],
    ["csharp", "failure"],
    ["csharp", "cancelled"],
    ["python", "success"],
  ]) {
    const invalid = structuredClone(valid);
    invalid[name].result = result;
    assert.throws(() => verifyChecks(invalid));
  }
  delete valid.csharp;
  assert.throws(() => verifyChecks(valid));
});

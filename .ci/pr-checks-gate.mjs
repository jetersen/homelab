export function verifyChecks(results) {
  if (results.changes?.result !== "success") {
    throw new Error("PR check selection did not succeed");
  }
  const selected = results.changes.outputs;
  for (const [name, required] of Object.entries(selected)) {
    const expected = required === "true" ? "success" : "skipped";
    if (!["true", "false"].includes(required) || results[name]?.result !== expected) {
      throw new Error(`PR check ${name} did not finish as ${expected}`);
    }
  }
  if (Object.keys(results).sort().join() !== ["changes", ...Object.keys(selected)].sort().join()) {
    throw new Error("PR check results do not match selected checks");
  }
}

if (process.env.CHECK_RESULTS) {
  verifyChecks(JSON.parse(process.env.CHECK_RESULTS));
  console.log("Every applicable PR check passed");
}

export async function reattemptAutomerge({ number, platformPrOptions }, { method, merge }) {
  if (!platformPrOptions?.usePlatformAutomerge) {
    return;
  }
  if (method !== "fast-forward-only") {
    throw new Error("Refusing native automerge without strict fast-forward-only");
  }
  try {
    await merge(number, {
      Do: method,
      merge_when_checks_succeed: true,
      delete_branch_after_merge: true,
    });
  } catch (error) {
    if (
      error.statusCode === 409 &&
      /already scheduled to auto merge/.test(error.response?.body?.message ?? "")
    ) {
      return;
    }
    throw error;
  }
}

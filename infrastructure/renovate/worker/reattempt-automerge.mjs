import { setTimeout as delay } from "node:timers/promises";

export async function reattemptAutomerge(
  { number, platformPrOptions },
  { method, merge, wait = delay },
) {
  if (!platformPrOptions?.usePlatformAutomerge) {
    return;
  }
  if (method !== "fast-forward-only") {
    throw new Error("Refusing native automerge without strict fast-forward-only");
  }
  const retryDelays = [1_000, 2_000, 4_000, 8_000, 16_000];
  for (let attempt = 0; ; attempt++) {
    try {
      await merge(number, {
        Do: method,
        merge_when_checks_succeed: true,
        delete_branch_after_merge: true,
      });
      return;
    } catch (error) {
      if (
        error.statusCode === 409 &&
        /already scheduled to auto merge/.test(error.response?.body?.message ?? "")
      ) {
        return;
      }
      if (
        error.statusCode === 405 &&
        error.response?.body?.message === "Please try again later" &&
        attempt < retryDelays.length
      ) {
        await wait(retryDelays[attempt]);
        continue;
      }
      throw error;
    }
  }
}

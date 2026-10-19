export async function shouldForceRebase(config, scm) {
  return (
    config.rebaseWhen === "behind-base-branch" &&
    (await scm.isBranchBehindBase(config.branchName, config.baseBranch))
  );
}

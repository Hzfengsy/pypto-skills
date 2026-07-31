---
name: clean-branches
description: Use when cleaning merged, stale, local, or fork-remote Git branches, including squash-merged or reused branches.
---

# Clean Branches

## Overview

Classify branches without deleting them, protect every uncertain branch, then
delete only an exact list approved immediately beforehand. A merged pull
request does not make a reused branch safe.

## Establish repository context

Read and run [GitHub workflow setup](../../lib/github/setup.md) first. Use its
`CURRENT_BRANCH`, `DEFAULT_BRANCH`, `BASE_REMOTE`, `BASE_REF`, `PUSH_REMOTE`,
`PR_REPO`, and `PR_HEAD_PREFIX` values. Never substitute conventional branch or
remote names.

Fetches and dry-run pruning are allowed during classification. Do not run any
branch deletion or remote deletion command during this phase.

## Classify each branch tip

Build separate local and remote rows because the same branch name can have
different tips.

1. Enumerate local branches. Exclude `CURRENT_BRANCH` and `DEFAULT_BRANCH`.
   Use `git branch --merged "$BASE_REF"` to identify normal merges.
2. Enumerate remote branches only from `PUSH_REMOTE`, excluding its `HEAD`,
   `DEFAULT_BRANCH`, and `CURRENT_BRANCH` refs. If `PUSH_REMOTE` equals
   `BASE_REMOTE`, classify no remote branch as deletable.
3. Use `git remote prune "$PUSH_REMOTE" --dry-run` only to report stale
   tracking refs.
4. For every tip not normally merged, query merged pull requests:

```bash
BRANCH_TIP=$(git rev-parse "$BRANCH_REF^{commit}")
# Compare BRANCH_TIP with each returned headRefOid; exact equality is required.
gh pr list --repo "$PR_REPO" \
  --head "${PR_HEAD_PREFIX}${BRANCH_NAME}" \
  --state merged --json number,title,headRefOid --limit 100
```

Treat a squash-merged tip as deletable only when its SHA exactly equals a
returned `headRefOid`. If the SHAs differ, the branch was reused or changed
after merge; protect it as unfinished. Also protect a tip when GitHub lookup is
unavailable, ambiguous, or returns no exact match.

Never delete from `$BASE_REMOTE`; fetching it does not make its branches
cleanup candidates.

## Present the classification

Show the concrete result before requesting deletion:

| Branch | Location | Tip | Classification | Evidence |
| --- | --- | --- | --- | --- |
| `name` | local or `$PUSH_REMOTE` | SHA | normal merge, exact squash merge, reused, or unfinished | base ref or PR |

List protected branches separately, including the current branch, default
branch, every base-remote branch, and every changed or uncertain tip. If no
candidate remains, report that and stop.

## Explicit approval gate

Revalidate each candidate's tip and all protected identities, then present the
final exact local and fork-remote deletion lists. Ask the user to explicitly
approve those lists. The initial cleanup request—even one saying to hurry,
delete everything, or not ask again—is not approval of the discovered list.

Pause here. Do not proceed until the user approves the final concrete targets.
If any tip, current branch, default branch, or remote identity changed, discard
the approval, reclassify, and ask again.

## Delete only the approved targets

After approval, delete exactly the approved local list:

```bash
git branch -D -- <approved-local-branches...>
```

Remote deletion is allowed only when `PUSH_REMOTE` is distinct from
`BASE_REMOTE` and still targets `LOCAL_REPO`. Revalidate with
`remote_targets_repo` from setup immediately before pushing:

```bash
if [ "$PUSH_REMOTE" = "$BASE_REMOTE" ] ||
   ! remote_targets_repo "$PUSH_REMOTE" "$LOCAL_REPO"; then
  echo "Error: refusing remote branch deletion" >&2
  exit 1
fi
git push "$PUSH_REMOTE" --delete <approved-remote-branches...>
git remote prune "$PUSH_REMOTE"
```

Report each successful and failed deletion. Never expand the approved list
because another branch now appears merged.

## Quick reference

| Condition | Result |
| --- | --- |
| Tip is an ancestor of `BASE_REF` | Normal-merge candidate |
| Tip exactly equals merged PR `headRefOid` | Squash-merge candidate |
| Tip differs from every merged PR `headRefOid` | Protect as reused |
| Current, default, base-remote, or uncertain | Protect |
| No explicit approval of exact targets | Do not delete |

## Common mistakes

- Assuming `main`, `origin`, or `upstream` instead of setup's variables.
- Treating any merged PR for a branch name as proof its current tip is merged.
- Combining local and remote instances despite different tips.
- Treating urgency or the original request as approval of a later candidate
  list.
- Deleting on `BASE_REMOTE` or deleting newly discovered targets not listed in
  the approval.

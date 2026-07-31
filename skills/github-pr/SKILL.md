---
name: github-pr
description: Use when creating or updating a GitHub pull request from committed or uncommitted local work, including fork, maintainer-edit, and GitHub Enterprise repositories.
---

# GitHub Pull Request

## Overview

Derive repository, host, default branch, remotes, role, and pull-request head
before writing. Keep commit policy in the repository and use the shared GitHub
references for all branch, permission, rebase, and push mechanics.

## Establish context and choose a route

Read and run [GitHub workflow setup](../../lib/github/setup.md) first. Preserve
its shell context, including `GITHUB_HOST`, `DEFAULT_BRANCH`, `BASE_REF`,
`PR_REPO`, `PR_HEAD_PREFIX`, `PUSH_REMOTE`, and `ROLE`. Use the discovered host
for every GitHub CLI command:

```bash
export GH_HOST="$GITHUB_HOST"
```

If the user supplied a PR number, take the update route. Otherwise, probe the
current head without guessing a remote name or selecting the first ambiguous
match:

```bash
if [ -n "${PR_NUMBER:-}" ]; then
  PR_ROUTE="update"
else
  HEAD_SELECTOR="${PR_HEAD_PREFIX}${CURRENT_BRANCH}"
  PR_CANDIDATES=$(GH_HOST="$GITHUB_HOST" gh pr list \
    --repo "$PR_REPO" --state open --head "$HEAD_SELECTOR" \
    --json number) || exit 1
  PR_COUNT=$(printf '%s' "$PR_CANDIDATES" | jq 'length')

  case "$PR_COUNT" in
    0) PR_ROUTE="create" ;;
    1)
      PR_ROUTE="update"
      PR_NUMBER=$(printf '%s' "$PR_CANDIDATES" | jq -r '.[0].number')
      ;;
    *)
      echo "Error: multiple open pull requests match $HEAD_SELECTOR" >&2
      exit 1
      ;;
  esac
fi
```

An existing pull request is an update route, never a reason to exit. The later
push updates its commits; `gh pr edit` updates its metadata.

## Verify an existing PR and its writable head

For the update route, read and run [pull-request
lookup](../../lib/github/lookup-pr.md) with `PR_NUMBER`, then
[permission detection](../../lib/github/detect-permission.md). This
distinguishes the author (`ROLE=owner` or `ROLE=fork`) from a maintainer and
verifies permission on `HEAD_REPO`.

When `ROLE=maintainer` and the PR head is not the current local branch, require
a clean worktree, then read and run [cross-fork
checkout](../../lib/github/checkout-fork-branch.md). Do not construct a
same-named local branch or push directly to an unverified fork. That reference
sets `WORK_BRANCH`, `PR_HEAD_BRANCH`, and `MAINTAINER_CHECKOUT_VERIFIED` for the
shared push workflow.

## Prepare the branch and commit intentionally

Inspect `git status --porcelain` and `git rev-list --count "$BASE_REF"..HEAD`.
For the create route, if `CURRENT_BRANCH` equals `DEFAULT_BRANCH`, or has no
commits ahead but has uncommitted work, obtain a user-approved
`BRANCH_SUMMARY` and any repository-required `BRANCH_PREFIX`; then read and run
[branch naming](../../lib/github/branch-naming.md). Never invent a prefix.

If uncommitted changes remain, use the repository-local `git-commit` skill.
Let that skill apply the repository's review, tests, message syntax, and commit
shape. If it is unavailable, stop and ask the user how this repository commits;
do not substitute a conventional-commit prefix or a generic checklist.

After committing, require a clean worktree and at least one commit in
`"$BASE_REF"..HEAD`. State the intended base and push target. Then read and run
[commit and push](../../lib/github/commit-and-push.md). It refreshes
`DEFAULT_BRANCH`, rebases on `BASE_REF`, selects the role-safe remote and head,
and uses an explicit `--force-with-lease` when history was rewritten. On a
conflict, resolve and retest under repository policy, or use
`git rebase --abort`; never discard work with a destructive reset.

## Create or update the pull request

Derive both title and body only from the post-rebase PR commit range:

```bash
PR_TITLE=$(git log --reverse --format='%s' "$BASE_REF"..HEAD | sed -n '1p')
PR_BODY=$(git log --reverse --format='- %s' "$BASE_REF"..HEAD)
if [ -z "$PR_TITLE" ] || [ -z "$PR_BODY" ]; then
  echo "Error: the pull-request commit range is empty" >&2
  exit 1
fi
```

Create a new PR with the fork-qualified head discovered by setup:

```bash
if [ "$PR_ROUTE" = "create" ]; then
  PR_URL=$(GH_HOST="$GITHUB_HOST" gh pr create \
    --repo "$PR_REPO" \
    --base "$DEFAULT_BRANCH" \
    --head "${PR_HEAD_PREFIX}${CURRENT_BRANCH}" \
    --title "$PR_TITLE" \
    --body "$PR_BODY") || exit 1
fi
```

Update the existing PR rather than abandoning it:

```bash
if [ "$PR_ROUTE" = "update" ]; then
  GH_HOST="$GITHUB_HOST" gh pr edit "$PR_NUMBER" \
    --repo "$PR_REPO" \
    --base "$DEFAULT_BRANCH" \
    --title "$PR_TITLE" \
    --body "$PR_BODY" || exit 1
  PR_URL=$(GH_HOST="$GITHUB_HOST" gh pr view "$PR_NUMBER" \
    --repo "$PR_REPO" --json url --jq '.url') || exit 1
fi
```

Do not add generated-by branding or issue-closing text that the commit range or
user did not supply.

## Report the result

Return the exact push target and the PR URL, number, state, base, and head:

```bash
GH_HOST="$GITHUB_HOST" gh pr view "${PR_NUMBER:-$PR_URL}" \
  --repo "$PR_REPO" \
  --json number,url,state,isDraft,baseRefName,headRefName
```

## Quick reference

| Condition | Action |
| --- | --- |
| Dirty worktree | Delegate to the repository-local `git-commit` skill |
| Default or undiverged branch with work | Apply shared branch naming policy |
| Existing PR | Verify role/head, push, then edit and report it |
| No existing PR | Push, then create with the fork-qualified head |
| Maintainer editing a fork | Verify permission and use the shared fork checkout |
| Rebase rewrites published history | Use only explicit `--force-with-lease` |

## Common mistakes

- Assuming `main`, `origin`, a public GitHub host, or the current repository is
  the PR base.
- Using a bare branch in `--head` for a fork instead of
  `${PR_HEAD_PREFIX}${CURRENT_BRANCH}`.
- Exiting when a PR already exists instead of updating its branch and metadata.
- Applying maintainer edits without verified head-repository push permission.
- Inventing commit prefixes, PR checklists, titles, or body content.

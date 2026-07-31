# Commit and Push

Prepare an existing repository-approved commit for a pull request and push it
to the exact remote selected by [setup](setup.md) or
[permission detection](detect-permission.md). Commit shape and verification
remain responsibilities of the consuming repository.

## 1. Validate context and local state

```bash
for REQUIRED_NAME in REPO_ROOT CURRENT_BRANCH DEFAULT_BRANCH BASE_REMOTE \
  BASE_REF PUSH_REMOTE PR_REPO; do
  if [ -z "${!REQUIRED_NAME:-}" ]; then
    echo "Error: required context variable $REQUIRED_NAME is unset" >&2
    exit 1
  fi
done

cd "$REPO_ROOT" || exit 1
ACTUAL_BRANCH=$(git branch --show-current)
if [ "$ACTUAL_BRANCH" != "$CURRENT_BRANCH" ]; then
  echo "Error: expected branch $CURRENT_BRANCH, found $ACTUAL_BRANCH" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Error: commit or remove worktree changes using repository-local policy" >&2
  exit 1
fi
```

## 2. Refresh and rebase on the discovered base

```bash
git fetch "$BASE_REMOTE" "$DEFAULT_BRANCH" || {
  echo "Error: failed to refresh $BASE_REMOTE/$DEFAULT_BRANCH" >&2
  exit 1
}
BASE_REF="$BASE_REMOTE/$DEFAULT_BRANCH"

BEFORE_REBASE=$(git rev-parse HEAD)
git rebase "$BASE_REF" || {
  echo "Error: rebase stopped; resolve conflicts and continue, or abort it" >&2
  exit 1
}
AFTER_REBASE=$(git rev-parse HEAD)

if [ "$BEFORE_REBASE" = "$AFTER_REBASE" ]; then
  REWRITE_REQUIRED="false"
else
  REWRITE_REQUIRED="true"
fi

COMMITS_AHEAD=$(git rev-list --count "$BASE_REF"..HEAD)
if [ "$COMMITS_AHEAD" -eq 0 ]; then
  echo "Error: $CURRENT_BRANCH has no commits ahead of $BASE_REF" >&2
  exit 1
fi
```

When rebase conflicts occur, resolve the files, stage them, and run
`git rebase --continue`. Use `git rebase --abort` if the correct resolution is
unclear. After any conflict resolution, run the consuming repository's review
and test workflow before pushing.

## 3. Identify the exact push target

For a normal owner or fork branch, `PR_HEAD_BRANCH` is either unset or equals
`CURRENT_BRANCH`. A maintainer working through
[checkout-fork-branch](checkout-fork-branch.md) pushes the local work branch to
the original pull-request head branch.

```bash
PUSH_BRANCH=${PR_HEAD_BRANCH:-$CURRENT_BRANCH}
if [ -z "$PUSH_BRANCH" ]; then
  echo "Error: push branch could not be resolved" >&2
  exit 1
fi

REMOTE_SHA=$(git ls-remote --heads "$PUSH_REMOTE" \
  "refs/heads/$PUSH_BRANCH" | awk 'NR == 1 {print $1}')
if [ -n "$REMOTE_SHA" ]; then
  git fetch "$PUSH_REMOTE" "$PUSH_BRANCH" || {
    echo "Error: failed to inspect $PUSH_REMOTE/$PUSH_BRANCH" >&2
    exit 1
  }
fi
```

State the target as `$PUSH_REMOTE:$PUSH_BRANCH` before executing a write.

## 4. Push safely

First publication of a same-named branch:

```bash
if [ -z "$REMOTE_SHA" ] && [ "$PUSH_BRANCH" = "$CURRENT_BRANCH" ]; then
  git push --set-upstream "$PUSH_REMOTE" "$CURRENT_BRANCH"
fi
```

First publication to a differently named remote branch:

```bash
if [ -z "$REMOTE_SHA" ] && [ "$PUSH_BRANCH" != "$CURRENT_BRANCH" ]; then
  git push "$PUSH_REMOTE" "$CURRENT_BRANCH:$PUSH_BRANCH"
fi
```

Fast-forward update when rebase did not rewrite history:

```bash
if [ -n "$REMOTE_SHA" ] && [ "$REWRITE_REQUIRED" = "false" ]; then
  git push "$PUSH_REMOTE" "$CURRENT_BRANCH:$PUSH_BRANCH"
fi
```

Rewritten update:

```bash
if [ -n "$REMOTE_SHA" ] && [ "$REWRITE_REQUIRED" = "true" ]; then
  if ! git merge-base --is-ancestor "$REMOTE_SHA" "$BEFORE_REBASE"; then
    echo "Error: remote branch has commits absent from the pre-rebase branch" >&2
    echo "Inspect and integrate the remote commits before rewriting" >&2
    exit 1
  fi
  git push --force-with-lease="refs/heads/$PUSH_BRANCH:$REMOTE_SHA" \
    "$PUSH_REMOTE" "$CURRENT_BRANCH:$PUSH_BRANCH"
fi
```

The explicit expected SHA makes a concurrent remote update fail instead of
overwriting it. Re-fetch, inspect the new commits, and rebase again before any
retry.

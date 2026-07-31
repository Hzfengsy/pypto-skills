# Check Out a Cross-Fork Pull-Request Branch

Create or reuse a local work branch for a pull request whose head repository
may differ from `PR_REPO`.

Requires:

- Setup context, including the `remote_repo` helper.
- `PR_NUMBER` and `PR_HEAD_BRANCH` from
  [pull-request lookup](lookup-pr.md).
- `HEAD_REPO` and `PUSH_REMOTE` from
  [permission detection](detect-permission.md).

## Validate the target

```bash
case "$PR_NUMBER" in
  ""|*[!0-9]*)
    echo "Error: PR_NUMBER must be numeric" >&2
    exit 1
    ;;
esac

REMOTE_REPO=$(remote_repo "$PUSH_REMOTE") || {
  echo "Error: repository identity for remote $PUSH_REMOTE is unavailable" >&2
  exit 1
}
if [ "$REMOTE_REPO" != "$HEAD_REPO" ]; then
  echo "Error: $PUSH_REMOTE points to $REMOTE_REPO, expected $HEAD_REPO" >&2
  exit 1
fi

git fetch "$PUSH_REMOTE" "$PR_HEAD_BRANCH" || {
  echo "Error: failed to fetch $PUSH_REMOTE/$PR_HEAD_BRANCH" >&2
  exit 1
}
if ! git rev-parse --verify \
  "$PUSH_REMOTE/$PR_HEAD_BRANCH^{commit}" >/dev/null 2>&1; then
  echo "Error: fetched PR head branch is unavailable" >&2
  exit 1
fi
```

## Create or update the local work branch

```bash
WORK_BRANCH="pr-$PR_NUMBER-work"

if git show-ref --verify --quiet "refs/heads/$WORK_BRANCH"; then
  git switch "$WORK_BRANCH" || exit 1
  git rebase "$PUSH_REMOTE/$PR_HEAD_BRANCH" || {
    echo "Error: local PR work branch could not be rebased on its remote head" >&2
    exit 1
  }
else
  git switch --create "$WORK_BRANCH" \
    --track "$PUSH_REMOTE/$PR_HEAD_BRANCH" || exit 1
fi

git branch --set-upstream-to="$PUSH_REMOTE/$PR_HEAD_BRANCH" \
  "$WORK_BRANCH" || exit 1
CURRENT_BRANCH=$(git branch --show-current)
```

The local branch name intentionally differs from the contributor's branch.
[Commit and push](commit-and-push.md) therefore pushes
`$CURRENT_BRANCH:$PR_HEAD_BRANCH` to `PUSH_REMOTE` and protects rewritten
history with an explicit lease.

## Outputs

- `WORK_BRANCH`: local work branch.
- Updated `CURRENT_BRANCH`: the checked-out local branch.
- Existing `PR_HEAD_BRANCH`: the remote branch that receives the push.

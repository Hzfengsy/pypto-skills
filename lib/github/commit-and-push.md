# Prepare, Validate, and Push

Prepare an existing repository-approved commit for a pull request and push it
to the exact remote selected by [setup](setup.md) or [permission
detection](detect-permission.md). Commit shape and validation commands remain
responsibilities of the consuming repository.

This workflow has two executable phases separated by repository validation:

1. `prepare` performs the final base fetch/rebase and writes an immutable
   checkpoint.
2. The caller validates exactly the checkpointed `HEAD`.
3. `push` refuses any local `HEAD`, base tip, or PR-head drift and never rebases
   or otherwise mutates history.

Resolve [`scripts/prepare-and-push.sh`](scripts/prepare-and-push.sh) relative to
this reference and set its absolute path in `PREPARE_PUSH_HELPER`.

## 1. Select the exact push target before rewriting

Run this section before any amend, fixup/autosquash, or other history rewrite.
It records the verified PR-head OID that a later leased push is allowed to
replace.

```bash
for REQUIRED_NAME in REPO_ROOT CURRENT_BRANCH DEFAULT_BRANCH BASE_REMOTE \
  BASE_REF PUSH_REMOTE PR_REPO ROLE; do
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

case "$ROLE" in
  owner|fork)
    EXPECTED_PUSH_REPO="$LOCAL_REPO"
    if [ -n "${PR_HEAD_BRANCH:-}" ]; then
      if [ "$PR_HEAD_BRANCH" != "$CURRENT_BRANCH" ]; then
        echo "Error: $ROLE workflow cannot redirect $CURRENT_BRANCH to $PR_HEAD_BRANCH" >&2
        exit 1
      fi
      if [ -z "${HEAD_REPO:-}" ] || [ "$HEAD_REPO" != "$LOCAL_REPO" ]; then
        echo "Error: PR head repository does not match local writable repository" >&2
        exit 1
      fi
    fi
    PUSH_BRANCH="$CURRENT_BRANCH"
    ;;
  maintainer)
    if [ -z "${PR_HEAD_BRANCH:-}" ] || [ -z "${HEAD_REPO:-}" ]; then
      echo "Error: maintainer push requires verified PR head context" >&2
      exit 1
    fi
    EXPECTED_PUSH_REPO="$HEAD_REPO"
    PUSH_BRANCH="$PR_HEAD_BRANCH"
    if [ "$PR_HEAD_BRANCH" != "$CURRENT_BRANCH" ]; then
      if [ "${MAINTAINER_CHECKOUT_VERIFIED:-}" != "true" ] ||
         [ "${WORK_BRANCH:-}" != "$CURRENT_BRANCH" ]; then
        echo "Error: differing maintainer push requires verified checkout context" >&2
        exit 1
      fi
    fi
    ;;
  *)
    echo "Error: unsupported repository role: $ROLE" >&2
    exit 1
    ;;
esac

if ! remote_targets_repo "$PUSH_REMOTE" "$EXPECTED_PUSH_REPO"; then
  echo "Error: push remote does not safely target $EXPECTED_PUSH_REPO" >&2
  exit 1
fi

EXPECTED_REMOTE_OID=$(git ls-remote --heads "$PUSH_REMOTE" \
  "refs/heads/$PUSH_BRANCH" | awk 'NR == 1 {print $1}') || {
  echo "Error: failed to inspect $PUSH_REMOTE/$PUSH_BRANCH" >&2
  exit 1
}
if [ -z "$EXPECTED_REMOTE_OID" ]; then
  EXPECTED_REMOTE_OID="-"
fi
```

Set `HISTORY_REWRITTEN=false` now. If the repository-approved commit workflow
later amends, fixups/autosquashes, rebases, or otherwise rewrites the published
PR history, set `HISTORY_REWRITTEN=true` while preserving
`EXPECTED_REMOTE_OID`. This is an explicit caller contract; a no-op final base
rebase must not reset it.

State the target as `$PUSH_REMOTE:$PUSH_BRANCH` and the expected remote OID
before doing repository-local commit work.

## 2. Prepare the final head before final validation

After repository-approved commits and folding are complete, require a clean
worktree. Set an explicit `HISTORY_REWRITTEN` value and create a checkpoint in
a caller-owned temporary directory:

```bash
case "$HISTORY_REWRITTEN" in
  true|false) ;;
  *)
    echo "Error: HISTORY_REWRITTEN must be explicitly true or false" >&2
    exit 1
    ;;
esac

PUSH_CHECKPOINT=$(mktemp) || exit 1
"$PREPARE_PUSH_HELPER" prepare "$PUSH_CHECKPOINT" \
  "$BASE_REMOTE" "$DEFAULT_BRANCH" \
  "$PUSH_REMOTE" "$CURRENT_BRANCH" "$PUSH_BRANCH" \
  "$HISTORY_REWRITTEN" "$EXPECTED_REMOTE_OID" || exit 1

PREPARED_HEAD_OID=$(sed -n 's/^PREPARED_HEAD_OID=//p' "$PUSH_CHECKPOINT")
PREPARED_BASE_OID=$(sed -n 's/^PREPARED_BASE_OID=//p' "$PUSH_CHECKPOINT")
PREPARED_REMOTE_OID=$(sed -n 's/^PREPARED_REMOTE_OID=//p' "$PUSH_CHECKPOINT")
```

The helper fetches the discovered base, performs the final rebase, verifies the
exact base and remote tips, and records:

- `PREPARED_HEAD_OID`: the only local commit that may be pushed;
- `PREPARED_BASE_OID`: the exact base tip used by the rebase;
- `PREPARED_REMOTE_OID`: the exact PR-head OID, or `UNPUBLISHED`;
- `HISTORY_REWRITTEN`: caller-supplied rewrite state OR a rewrite performed by
  the final base rebase.

When a rebase conflict occurs, resolve and restart `prepare`, or abort. Do not
reuse a checkpoint from before conflict resolution.

## 3. Validate the immutable prepared checkpoint

Run the consuming repository's focused and required broader validation now,
against `PREPARED_HEAD_OID`. Validation must not amend, rebase, commit, switch
branches, fetch into the base tracking ref, or otherwise change the prepared
checkpoint.

```bash
VALIDATED_HEAD_OID=$(git rev-parse HEAD) || exit 1
if [ "$VALIDATED_HEAD_OID" != "$PREPARED_HEAD_OID" ]; then
  echo "Error: validation did not run on the prepared HEAD" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Error: validation changed the prepared worktree" >&2
  exit 1
fi
```

If validation requires a code or history change, discard the checkpoint and
restart from target capture when the PR-head expectation changed, otherwise
restart from `prepare`. Never mutate history after validation and then push
without validating the new prepared OID.

## 4. Revalidate identity and push without mutation

Immediately before `push`, revalidate repository identity:

```bash
if ! remote_targets_repo "$PUSH_REMOTE" "$EXPECTED_PUSH_REPO"; then
  echo "Error: push remote no longer safely targets $EXPECTED_PUSH_REPO" >&2
  exit 1
fi

"$PREPARE_PUSH_HELPER" push "$PUSH_CHECKPOINT" || exit 1
```

The helper re-reads local `HEAD`, the local and remote base tips, and the remote
PR head. Any drift after validation stops before a write. A non-rewrite
fast-forward uses a normal push. Rewritten published history executes
`git push --force-with-lease` with the checkpointed
`refs/heads/$PUSH_BRANCH:$PREPARED_REMOTE_OID`. First publication uses a normal
push.

After the push, the helper verifies that the remote PR head equals
`PREPARED_HEAD_OID`. A concurrent remote update makes either the pre-push
comparison or the explicit lease fail; inspect the new commits and restart
rather than retrying with a new lease.

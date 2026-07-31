# Single-Use Pull-Request Push Transaction

Push only through one capture → mutate/commit → prepare → validate → push
transaction. Resolve these trusted files relative to this reference, never the
consuming repository:

- [`scripts/prepare-and-push.sh`](scripts/prepare-and-push.sh) as the absolute
  executable `PREPARE_PUSH_HELPER`;
- [`scripts/push-transaction.sh`](scripts/push-transaction.sh) as
  `PUSH_TRANSACTION_HELPER`, then source it.

The transaction function runs in a subshell. Authority becomes readonly only
inside that invocation and disappears on return. It stores no checkpoint.

## Select base and head identities

Run only after the final local branch is checked out. The base authority is
always the discovered PR destination; the head authority depends on role:

```bash
for REQUIRED_NAME in REPO_ROOT GITHUB_HOST PR_REPO CURRENT_BRANCH \
  DEFAULT_BRANCH BASE_REMOTE PUSH_REMOTE ROLE; do
  [ -n "${!REQUIRED_NAME:-}" ] || {
    echo "Error: required context variable $REQUIRED_NAME is unset" >&2
    exit 1
  }
done
EXPECTED_BASE_HOST="$GITHUB_HOST"
EXPECTED_BASE_REPO="$PR_REPO"
EXPECTED_HEAD_HOST="$GITHUB_HOST"

case "$ROLE" in
  owner|fork)
    EXPECTED_PUSH_REPO="$LOCAL_REPO"
    if [ -n "${PR_HEAD_BRANCH:-}" ]; then
      [ "$PR_HEAD_BRANCH" = "$CURRENT_BRANCH" ] &&
        [ "${HEAD_REPO:-}" = "$LOCAL_REPO" ] || {
        echo "Error: author checkout does not match the verified PR head" >&2
        exit 1
      }
    fi
    PUSH_BRANCH="$CURRENT_BRANCH"
    ;;
  maintainer)
    [ -n "${PR_HEAD_BRANCH:-}" ] && [ -n "${HEAD_REPO:-}" ] || {
      echo "Error: maintainer push requires verified PR head context" >&2
      exit 1
    }
    EXPECTED_PUSH_REPO="$HEAD_REPO"
    PUSH_BRANCH="$PR_HEAD_BRANCH"
    if [ "$PR_HEAD_BRANCH" != "$CURRENT_BRANCH" ]; then
      [ "${MAINTAINER_CHECKOUT_VERIFIED:-}" = "true" ] &&
        [ "${WORK_BRANCH:-}" = "$CURRENT_BRANCH" ] || {
        echo "Error: differing maintainer push requires verified checkout" >&2
        exit 1
      }
    fi
    ;;
  *) echo "Error: unsupported repository role: $ROLE" >&2; exit 1 ;;
esac

remote_targets_repo "$BASE_REMOTE" "$EXPECTED_BASE_REPO" || {
  echo "Error: base remote identity changed" >&2
  exit 1
}
remote_targets_repo "$PUSH_REMOTE" "$EXPECTED_PUSH_REPO" || {
  echo "Error: push remote identity changed" >&2
  exit 1
}

source "$PUSH_TRANSACTION_HELPER" || exit 1

apply_transaction_changes() {
  # Apply/stage/commit/fold only through repository-approved policy.
  # Set HISTORY_REWRITTEN=true here after amend/autosquash/rebase.
  :
}
validate_transaction_head() {
  # Run repository-defined focused and broader checks as child processes.
  :
}

pr_push_transaction "$PREPARE_PUSH_HELPER" \
  apply_transaction_changes validate_transaction_head \
  "$EXPECTED_BASE_HOST" "$EXPECTED_BASE_REPO" \
  "$EXPECTED_HEAD_HOST" "$EXPECTED_PUSH_REPO" \
  "$BASE_REMOTE" "$DEFAULT_BRANCH" "$PUSH_REMOTE" \
  "$CURRENT_BRANCH" "$PUSH_BRANCH" || exit 1
```

Replace the callback bodies, not the transaction mechanics. The mutation
callback runs after the exact remote head is captured and may update the
dynamically scoped `HISTORY_REWRITTEN`; it must leave a clean committed
worktree. The validation callback runs after the final base fetch/rebase and
must not source contributor code, change `HEAD`, dirty the worktree, switch
branches, or fetch.

## Identity and push guarantees

Both `prepare` and `push` receive explicit expected base host/repository and
head host/repository arguments. Before fetching/rebasing, `prepare` requires
the base remote's sole fetch URL to map to the expected base and requires every
head fetch URL plus the sole push URL to map to the expected head. `push`
repeats both identity checks, verifies local/base/head OIDs, then repeats the
URL checks immediately before its only write.

A non-rewrite uses a normal push. Rewritten published history uses explicit
`git push --force-with-lease` against the head OID captured by this invocation.
The helper rejects a same-repository base/default target.

## Retry and iteration rule

The transaction is single-use whether it succeeds or fails. If mutation,
prepare, or validation fails—or validation changes the prepared state—let the
subshell return without pushing. Fix the local issue, then call
`pr_push_transaction` again. The new invocation recaptures base/head state and
starts with fresh rewrite state; never retry an old prepared result.

After a successful push, any later fix-pr iteration also calls a new
transaction. It therefore captures the just-pushed head as its new remote OID.
Do not wrap multiple pushes in one function call or move readonly variables to
the parent shell.

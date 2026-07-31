# Prepare, Validate, and Push

Prepare a repository-approved commit and push only the verified pull-request
head. Commit shape and validation commands remain repository responsibilities.
Resolve [`scripts/prepare-and-push.sh`](scripts/prepare-and-push.sh) relative to
this reference as the absolute `PREPARE_PUSH_HELPER`.

The trust boundary is:

1. capture the write target in the parent shell before any rewrite;
2. `prepare` performs the final fetch/rebase and returns JSON;
3. parse that JSON immediately into parent-shell variables;
4. validate exactly the prepared `HEAD`;
5. pass all authority explicitly to non-mutating `push`.

Never serialize push authority to a checkpoint or other file that contributor
code can replace during validation.

## 1. Capture push authority before history edits

Run this only after the final local branch is checked out. For a create route,
branch naming and checkout therefore happen first. For an update route, run it
after the verified PR-head checkout and before amend, fixup/autosquash, or
rebase.

```bash
for REQUIRED_NAME in REPO_ROOT GITHUB_HOST CURRENT_BRANCH DEFAULT_BRANCH \
  BASE_REMOTE BASE_REF PUSH_REMOTE PR_REPO ROLE; do
  if [ -z "${!REQUIRED_NAME:-}" ]; then
    echo "Error: required context variable $REQUIRED_NAME is unset" >&2
    exit 1
  fi
done
cd "$REPO_ROOT" || exit 1
ACTUAL_BRANCH=$(git branch --show-current) || {
  echo "Error: failed to inspect the current branch" >&2
  exit 1
}
[ "$ACTUAL_BRANCH" = "$CURRENT_BRANCH" ] || {
  echo "Error: expected branch $CURRENT_BRANCH, found $ACTUAL_BRANCH" >&2
  exit 1
}

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
remote_targets_repo "$PUSH_REMOTE" "$EXPECTED_PUSH_REPO" || {
  echo "Error: push remote does not safely target $EXPECTED_PUSH_REPO" >&2
  exit 1
}

REMOTE_HEADS=$(git ls-remote --heads "$PUSH_REMOTE" \
  "refs/heads/$PUSH_BRANCH") || {
  echo "Error: failed to inspect $PUSH_REMOTE/$PUSH_BRANCH" >&2
  exit 1
}
EXPECTED_REMOTE_OID=""
REMOTE_MATCH_COUNT=0
while IFS= read -r REMOTE_LINE; do
  [ -n "$REMOTE_LINE" ] || continue
  REMOTE_MATCH_COUNT=$((REMOTE_MATCH_COUNT + 1))
  EXPECTED_REMOTE_OID=${REMOTE_LINE%%[[:space:]]*}
done <<EOF
$REMOTE_HEADS
EOF
[ "$REMOTE_MATCH_COUNT" -le 1 ] || {
  echo "Error: multiple remote heads matched the push branch" >&2
  exit 1
}
[ -n "$EXPECTED_REMOTE_OID" ] || EXPECTED_REMOTE_OID="-"
HISTORY_REWRITTEN=false
```

Preserve `EXPECTED_REMOTE_OID`. Set `HISTORY_REWRITTEN=true` after any amend,
autosquash, rebase, or other published-history rewrite; a later no-op rebase
must not clear it. State the host, repository, remote, branch, and old OID.

## 2. Prepare and parse the final head

After commit/folding work and focused editing checks, run `prepare`:

```bash
PREPARE_RESULT=$("$PREPARE_PUSH_HELPER" prepare \
  "$BASE_REMOTE" "$DEFAULT_BRANCH" "$PUSH_REMOTE" \
  "$CURRENT_BRANCH" "$PUSH_BRANCH" \
  "$HISTORY_REWRITTEN" "$EXPECTED_REMOTE_OID") || exit 1
PREPARED_FIELDS=$(printf '%s' "$PREPARE_RESULT" | jq -er '
  if .version == 1
     and (.prepared_head_oid | type == "string")
     and (.prepared_base_oid | type == "string")
     and (.prepared_remote_oid | type == "string")
     and (.history_rewritten | type == "boolean")
  then [.prepared_head_oid, .prepared_base_oid, .prepared_remote_oid,
        (.history_rewritten | tostring)] | @tsv
  else error("malformed prepare result") end') || exit 1
IFS=$'\t' read -r PREPARED_HEAD_OID PREPARED_BASE_OID \
  PREPARED_REMOTE_OID HISTORY_REWRITTEN <<EOF
$PREPARED_FIELDS
EOF
readonly GITHUB_HOST EXPECTED_PUSH_REPO BASE_REMOTE DEFAULT_BRANCH PUSH_REMOTE
readonly CURRENT_BRANCH PUSH_BRANCH PREPARED_HEAD_OID PREPARED_BASE_OID
readonly PREPARED_REMOTE_OID HISTORY_REWRITTEN PREPARE_PUSH_HELPER
```

The JSON is transient transport, not later authority. Do not write it to disk.
`prepare` verifies the final base/remote tips and preserves earlier rewrite
state. Resolve a rebase conflict and rerun `prepare`, or abort.

## 3. Validate exactly the prepared OID

Run repository-defined focused and broader validation now. Do not source
contributor scripts into this authority-holding shell. Validation must not
commit, rebase, switch branches, or fetch into the prepared base ref.

```bash
VALIDATED_HEAD_OID=$(git rev-parse HEAD) || exit 1
[ "$VALIDATED_HEAD_OID" = "$PREPARED_HEAD_OID" ] || {
  echo "Error: validation did not preserve prepared HEAD" >&2
  exit 1
}
VALIDATED_STATUS=$(git status --porcelain) || {
  echo "Error: failed to inspect the validated worktree" >&2
  exit 1
}
[ -z "$VALIDATED_STATUS" ] || {
  echo "Error: validation changed the prepared worktree" >&2
  exit 1
}
```

If validation changes code/history, return to `prepare` and validate the new
OID. If the PR head changed, restart from authority capture.

## 4. Push with explicit parent-shell authority

```bash
"$PREPARE_PUSH_HELPER" push \
  "$GITHUB_HOST" "$EXPECTED_PUSH_REPO" \
  "$BASE_REMOTE" "$DEFAULT_BRANCH" "$PUSH_REMOTE" \
  "$CURRENT_BRANCH" "$PUSH_BRANCH" \
  "$PREPARED_HEAD_OID" "$PREPARED_BASE_OID" \
  "$PREPARED_REMOTE_OID" "$HISTORY_REWRITTEN" || exit 1
```

`push` strictly validates every argument, then revalidates that the remote's
fetch URLs and single push URL still map to
`$GITHUB_HOST/$EXPECTED_PUSH_REPO`. It refuses a same-repository base/default
target and any local-head, worktree, base-tip, or remote-head drift. It never
fetches, rebases, or reads authority from disk. Non-rewrites use a normal push;
rewritten history uses explicit `git push --force-with-lease` against
`PREPARED_REMOTE_OID`. Finally it verifies the remote head equals
`PREPARED_HEAD_OID`.

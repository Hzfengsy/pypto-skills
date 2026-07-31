#!/usr/bin/env bash

set -u

usage() {
  cat >&2 <<'EOF'
Usage:
  prepare-and-push.sh prepare CHECKPOINT BASE_REMOTE DEFAULT_BRANCH \
    PUSH_REMOTE CURRENT_BRANCH PUSH_BRANCH HISTORY_REWRITTEN EXPECTED_REMOTE_OID
  prepare-and-push.sh push CHECKPOINT

EXPECTED_REMOTE_OID is the verified pre-rewrite remote head, or - when the
branch is verified to be unpublished.
EOF
  exit 2
}

fail() {
  echo "Error: $*" >&2
  exit 1
}

require_oid() {
  OID_NAME=$1
  OID_VALUE=$2
  if ! printf '%s\n' "$OID_VALUE" |
    grep -Eq '^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$'; then
    fail "$OID_NAME is not a full Git object ID"
  fi
}

require_branch() {
  BRANCH_NAME=$1
  BRANCH_VALUE=$2
  git check-ref-format --branch "$BRANCH_VALUE" >/dev/null 2>&1 ||
    fail "$BRANCH_NAME is not a valid branch name"
}

require_remote() {
  REMOTE_NAME=$1
  git remote get-url "$REMOTE_NAME" >/dev/null 2>&1 ||
    fail "Git remote $REMOTE_NAME is unavailable"
}

remote_head_oid() {
  REMOTE_NAME=$1
  BRANCH_NAME=$2
  REMOTE_OUTPUT=$(git ls-remote --heads "$REMOTE_NAME" \
    "refs/heads/$BRANCH_NAME") ||
    fail "failed to inspect $REMOTE_NAME/$BRANCH_NAME"
  REMOTE_LINE_COUNT=$(printf '%s\n' "$REMOTE_OUTPUT" | sed '/^$/d' | wc -l)
  if [ "$REMOTE_LINE_COUNT" -gt 1 ]; then
    fail "multiple remote refs matched $REMOTE_NAME/$BRANCH_NAME"
  fi
  if [ "$REMOTE_LINE_COUNT" -eq 0 ]; then
    printf '\n'
    return
  fi
  printf '%s\n' "$REMOTE_OUTPUT" | awk 'NR == 1 {print $1}'
}

checkpoint_value() {
  CHECKPOINT_PATH=$1
  CHECKPOINT_KEY=$2
  CHECKPOINT_MATCHES=$(sed -n "s/^${CHECKPOINT_KEY}=//p" "$CHECKPOINT_PATH")
  CHECKPOINT_MATCH_COUNT=$(sed -n "/^${CHECKPOINT_KEY}=/p" \
    "$CHECKPOINT_PATH" | wc -l)
  if [ "$CHECKPOINT_MATCH_COUNT" -ne 1 ]; then
    fail "checkpoint field $CHECKPOINT_KEY is missing or duplicated"
  fi
  printf '%s\n' "$CHECKPOINT_MATCHES"
}

prepare() {
  [ "$#" -eq 8 ] || usage
  CHECKPOINT_PATH=$1
  BASE_REMOTE=$2
  DEFAULT_BRANCH=$3
  PUSH_REMOTE=$4
  CURRENT_BRANCH=$5
  PUSH_BRANCH=$6
  HISTORY_REWRITTEN_INPUT=$7
  EXPECTED_REMOTE_OID=$8

  case "$HISTORY_REWRITTEN_INPUT" in
    true|false) ;;
    *) fail "HISTORY_REWRITTEN must be true or false" ;;
  esac
  case "$EXPECTED_REMOTE_OID" in
    -) ;;
    *) require_oid "EXPECTED_REMOTE_OID" "$EXPECTED_REMOTE_OID" ;;
  esac
  require_branch "DEFAULT_BRANCH" "$DEFAULT_BRANCH"
  require_branch "CURRENT_BRANCH" "$CURRENT_BRANCH"
  require_branch "PUSH_BRANCH" "$PUSH_BRANCH"
  require_remote "$BASE_REMOTE"
  require_remote "$PUSH_REMOTE"

  REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) ||
    fail "the current directory is not in a Git worktree"
  cd "$REPO_ROOT" || exit 1
  ACTUAL_BRANCH=$(git branch --show-current)
  if [ "$ACTUAL_BRANCH" != "$CURRENT_BRANCH" ]; then
    fail "expected branch $CURRENT_BRANCH, found $ACTUAL_BRANCH"
  fi
  if [ -n "$(git status --porcelain)" ]; then
    fail "worktree must be clean before prepare"
  fi

  git fetch "$BASE_REMOTE" "$DEFAULT_BRANCH" ||
    fail "failed to refresh $BASE_REMOTE/$DEFAULT_BRANCH"
  BASE_REF="refs/remotes/$BASE_REMOTE/$DEFAULT_BRANCH"
  PREPARE_BEFORE_HEAD=$(git rev-parse HEAD) ||
    fail "failed to read HEAD before prepare"
  git rebase "$BASE_REF" ||
    fail "rebase stopped; resolve and restart prepare, or abort"
  PREPARED_HEAD_OID=$(git rev-parse HEAD) ||
    fail "failed to read prepared HEAD"
  PREPARED_BASE_OID=$(git rev-parse "$BASE_REF^{commit}") ||
    fail "failed to read prepared base tip"
  REMOTE_BASE_OID=$(remote_head_oid "$BASE_REMOTE" "$DEFAULT_BRANCH")
  require_oid "remote base OID" "$REMOTE_BASE_OID"
  if [ "$REMOTE_BASE_OID" != "$PREPARED_BASE_OID" ]; then
    fail "base changed while prepare was running"
  fi
  if [ "$(git rev-list --count "$PREPARED_BASE_OID"..HEAD)" -eq 0 ]; then
    fail "$CURRENT_BRANCH has no commits ahead of the prepared base"
  fi
  if [ -n "$(git status --porcelain)" ]; then
    fail "worktree changed during prepare"
  fi

  PREPARED_REMOTE_OID=$(remote_head_oid "$PUSH_REMOTE" "$PUSH_BRANCH")
  if [ "$EXPECTED_REMOTE_OID" = "-" ]; then
    if [ -n "$PREPARED_REMOTE_OID" ]; then
      fail "remote branch exists but was expected to be unpublished"
    fi
    PREPARED_REMOTE_VALUE="UNPUBLISHED"
  else
    if [ "$PREPARED_REMOTE_OID" != "$EXPECTED_REMOTE_OID" ]; then
      fail "remote head changed before prepare checkpoint"
    fi
    PREPARED_REMOTE_VALUE=$PREPARED_REMOTE_OID
  fi

  HISTORY_REWRITTEN=$HISTORY_REWRITTEN_INPUT
  if [ "$PREPARE_BEFORE_HEAD" != "$PREPARED_HEAD_OID" ]; then
    HISTORY_REWRITTEN="true"
    if [ -n "$PREPARED_REMOTE_OID" ] &&
      ! git merge-base --is-ancestor \
        "$PREPARED_REMOTE_OID" "$PREPARE_BEFORE_HEAD"; then
      fail "remote branch is not contained in the pre-prepare history"
    fi
  fi
  if [ "$HISTORY_REWRITTEN" = "false" ] &&
    [ -n "$PREPARED_REMOTE_OID" ] &&
    ! git merge-base --is-ancestor \
      "$PREPARED_REMOTE_OID" "$PREPARED_HEAD_OID"; then
    fail "non-rewrite push would not be a fast-forward"
  fi

  CHECKPOINT_PARENT=$(dirname "$CHECKPOINT_PATH")
  [ -d "$CHECKPOINT_PARENT" ] ||
    fail "checkpoint parent directory does not exist"
  CHECKPOINT_TEMP="${CHECKPOINT_PATH}.tmp.$$"
  umask 077
  trap 'rm -f "$CHECKPOINT_TEMP"' EXIT HUP INT TERM
  {
    printf 'VERSION=1\n'
    printf 'REPO_ROOT=%s\n' "$REPO_ROOT"
    printf 'BASE_REMOTE=%s\n' "$BASE_REMOTE"
    printf 'DEFAULT_BRANCH=%s\n' "$DEFAULT_BRANCH"
    printf 'PUSH_REMOTE=%s\n' "$PUSH_REMOTE"
    printf 'CURRENT_BRANCH=%s\n' "$CURRENT_BRANCH"
    printf 'PUSH_BRANCH=%s\n' "$PUSH_BRANCH"
    printf 'PREPARED_HEAD_OID=%s\n' "$PREPARED_HEAD_OID"
    printf 'PREPARED_BASE_OID=%s\n' "$PREPARED_BASE_OID"
    printf 'PREPARED_REMOTE_OID=%s\n' "$PREPARED_REMOTE_VALUE"
    printf 'HISTORY_REWRITTEN=%s\n' "$HISTORY_REWRITTEN"
  } >"$CHECKPOINT_TEMP" || fail "failed to write checkpoint"
  chmod 0400 "$CHECKPOINT_TEMP" ||
    fail "failed to make checkpoint read-only"
  mv -f "$CHECKPOINT_TEMP" "$CHECKPOINT_PATH" ||
    fail "failed to publish checkpoint"
  trap - EXIT HUP INT TERM

  printf 'Prepared HEAD: %s\n' "$PREPARED_HEAD_OID"
  printf 'Prepared base: %s\n' "$PREPARED_BASE_OID"
  printf 'Prepared remote: %s\n' "$PREPARED_REMOTE_VALUE"
  printf 'History rewritten: %s\n' "$HISTORY_REWRITTEN"
}

push_prepared() {
  [ "$#" -eq 1 ] || usage
  CHECKPOINT_PATH=$1
  [ -f "$CHECKPOINT_PATH" ] || fail "checkpoint is unavailable"
  [ "$(wc -l <"$CHECKPOINT_PATH")" -eq 11 ] ||
    fail "checkpoint has an unexpected shape"

  VERSION=$(checkpoint_value "$CHECKPOINT_PATH" VERSION)
  [ "$VERSION" = "1" ] || fail "unsupported checkpoint version"
  REPO_ROOT=$(checkpoint_value "$CHECKPOINT_PATH" REPO_ROOT)
  BASE_REMOTE=$(checkpoint_value "$CHECKPOINT_PATH" BASE_REMOTE)
  DEFAULT_BRANCH=$(checkpoint_value "$CHECKPOINT_PATH" DEFAULT_BRANCH)
  PUSH_REMOTE=$(checkpoint_value "$CHECKPOINT_PATH" PUSH_REMOTE)
  CURRENT_BRANCH=$(checkpoint_value "$CHECKPOINT_PATH" CURRENT_BRANCH)
  PUSH_BRANCH=$(checkpoint_value "$CHECKPOINT_PATH" PUSH_BRANCH)
  PREPARED_HEAD_OID=$(checkpoint_value "$CHECKPOINT_PATH" PREPARED_HEAD_OID)
  PREPARED_BASE_OID=$(checkpoint_value "$CHECKPOINT_PATH" PREPARED_BASE_OID)
  PREPARED_REMOTE_VALUE=$(checkpoint_value \
    "$CHECKPOINT_PATH" PREPARED_REMOTE_OID)
  HISTORY_REWRITTEN=$(checkpoint_value \
    "$CHECKPOINT_PATH" HISTORY_REWRITTEN)

  require_branch "DEFAULT_BRANCH" "$DEFAULT_BRANCH"
  require_branch "CURRENT_BRANCH" "$CURRENT_BRANCH"
  require_branch "PUSH_BRANCH" "$PUSH_BRANCH"
  require_oid "PREPARED_HEAD_OID" "$PREPARED_HEAD_OID"
  require_oid "PREPARED_BASE_OID" "$PREPARED_BASE_OID"
  case "$PREPARED_REMOTE_VALUE" in
    UNPUBLISHED) ;;
    *) require_oid "PREPARED_REMOTE_OID" "$PREPARED_REMOTE_VALUE" ;;
  esac
  case "$HISTORY_REWRITTEN" in
    true|false) ;;
    *) fail "checkpoint HISTORY_REWRITTEN is invalid" ;;
  esac
  require_remote "$BASE_REMOTE"
  require_remote "$PUSH_REMOTE"

  ACTUAL_REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) ||
    fail "the current directory is not in a Git worktree"
  if [ "$ACTUAL_REPO_ROOT" != "$REPO_ROOT" ]; then
    fail "checkpoint belongs to a different worktree"
  fi
  cd "$REPO_ROOT" || exit 1
  ACTUAL_BRANCH=$(git branch --show-current)
  if [ "$ACTUAL_BRANCH" != "$CURRENT_BRANCH" ]; then
    fail "checked-out branch changed after prepare"
  fi
  ACTUAL_HEAD_OID=$(git rev-parse HEAD) ||
    fail "failed to read local HEAD"
  if [ "$ACTUAL_HEAD_OID" != "$PREPARED_HEAD_OID" ]; then
    fail "local HEAD changed after prepare"
  fi
  if [ -n "$(git status --porcelain)" ]; then
    fail "worktree changed after prepare"
  fi

  LOCAL_BASE_OID=$(git rev-parse \
    "refs/remotes/$BASE_REMOTE/$DEFAULT_BRANCH^{commit}") ||
    fail "prepared base ref is unavailable"
  REMOTE_BASE_OID=$(remote_head_oid "$BASE_REMOTE" "$DEFAULT_BRANCH")
  if [ "$LOCAL_BASE_OID" != "$PREPARED_BASE_OID" ] ||
    [ "$REMOTE_BASE_OID" != "$PREPARED_BASE_OID" ]; then
    fail "base tip changed after prepare"
  fi

  ACTUAL_REMOTE_OID=$(remote_head_oid "$PUSH_REMOTE" "$PUSH_BRANCH")
  if [ "$PREPARED_REMOTE_VALUE" = "UNPUBLISHED" ]; then
    if [ -n "$ACTUAL_REMOTE_OID" ]; then
      fail "remote head changed after prepare"
    fi
  elif [ "$ACTUAL_REMOTE_OID" != "$PREPARED_REMOTE_VALUE" ]; then
    fail "remote head changed after prepare"
  fi

  if [ "$PREPARED_REMOTE_VALUE" = "UNPUBLISHED" ]; then
    if [ "$PUSH_BRANCH" = "$CURRENT_BRANCH" ]; then
      git push --set-upstream "$PUSH_REMOTE" "$CURRENT_BRANCH" ||
        fail "normal first push failed"
    else
      git push "$PUSH_REMOTE" "$CURRENT_BRANCH:$PUSH_BRANCH" ||
        fail "normal first push failed"
    fi
    PUSH_MODE="normal"
  elif [ "$HISTORY_REWRITTEN" = "true" ]; then
    git push \
      --force-with-lease="refs/heads/$PUSH_BRANCH:$PREPARED_REMOTE_VALUE" \
      "$PUSH_REMOTE" "$CURRENT_BRANCH:$PUSH_BRANCH" ||
      fail "leased rewritten push failed"
    PUSH_MODE="leased"
  else
    git merge-base --is-ancestor \
      "$PREPARED_REMOTE_VALUE" "$PREPARED_HEAD_OID" ||
      fail "prepared normal push is not a fast-forward"
    git push "$PUSH_REMOTE" "$CURRENT_BRANCH:$PUSH_BRANCH" ||
      fail "normal push failed"
    PUSH_MODE="normal"
  fi

  PUSHED_REMOTE_OID=$(remote_head_oid "$PUSH_REMOTE" "$PUSH_BRANCH")
  if [ "$PUSHED_REMOTE_OID" != "$PREPARED_HEAD_OID" ]; then
    fail "remote head does not equal prepared HEAD after push"
  fi
  printf 'Push mode: %s\n' "$PUSH_MODE"
  printf 'Pushed HEAD: %s\n' "$PREPARED_HEAD_OID"
}

[ "$#" -ge 1 ] || usage
COMMAND=$1
shift
case "$COMMAND" in
  prepare) prepare "$@" ;;
  push) push_prepared "$@" ;;
  *) usage ;;
esac

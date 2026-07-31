#!/usr/bin/env bash

set -u

usage() {
  cat >&2 <<'EOF'
Usage:
  pr-context.sh lookup HOST PR_REPO HEAD_SELECTOR [--allow-none]
  pr-context.sh guard-branch ROLE CURRENT_BRANCH PR_HEAD_BRANCH
  pr-context.sh create-head LOCAL_REPO PR_REPO CURRENT_BRANCH IS_FORK
  pr-context.sh validate-number PR_NUMBER
EOF
  exit 2
}

fail() {
  echo "Error: $*" >&2
  exit 1
}

validate_repo_identity() {
  case "$1" in
    ""|/*|*/|*/*/*) return 1 ;;
    */*) return 0 ;;
    *) return 1 ;;
  esac
}

lookup() {
  [ "$#" -eq 3 ] || [ "$#" -eq 4 ] || usage
  GITHUB_HOST=$1
  PR_REPO=$2
  HEAD_SELECTOR=$3
  ALLOW_NONE=false
  if [ "$#" -eq 4 ]; then
    [ "$4" = "--allow-none" ] || usage
    ALLOW_NONE=true
  fi

  case "$GITHUB_HOST" in
    ""|*/*|*" "*) fail "invalid GitHub host: $GITHUB_HOST" ;;
  esac
  validate_repo_identity "$PR_REPO" ||
    fail "PR_REPO must be an owner/name identity"
  [ -n "$HEAD_SELECTOR" ] || fail "pull-request head selector is empty"

  PR_MATCHES=$(gh api --hostname "$GITHUB_HOST" --method GET \
    "repos/$PR_REPO/pulls" \
    -f state=open \
    -f "head=$HEAD_SELECTOR" \
    -f per_page=100 \
    --paginate --slurp --jq 'add') || {
    fail "pull-request lookup failed for $PR_REPO head $HEAD_SELECTOR"
  }

  if ! printf '%s' "$PR_MATCHES" | jq -e '
    type == "array" and
    all(.[];
      type == "object" and
      (.number | type == "number") and
      (.number > 0) and
      (.number == (.number | floor)) and
      (.state | type == "string" and length > 0) and
      (.head | type == "object") and
      (.head.ref | type == "string" and length > 0) and
      (.title | type == "string")
    )
  ' >/dev/null 2>&1; then
    fail "malformed pull-request response for $PR_REPO head $HEAD_SELECTOR"
  fi

  MATCH_COUNT=$(printf '%s' "$PR_MATCHES" | jq -r 'length') ||
    fail "could not count pull-request matches"
  case "$MATCH_COUNT" in
    0)
      if [ "$ALLOW_NONE" != "true" ]; then
        fail "no open pull request has head $HEAD_SELECTOR in $PR_REPO"
      fi
      printf '%s\n' '{"route":"create","match_count":0,"pr":null}'
      ;;
    1)
      printf '%s' "$PR_MATCHES" | jq -c '{
        route: "update",
        match_count: 1,
        pr: (.[0] | {
          number,
          state: (.state | ascii_upcase),
          headRefName: .head.ref,
          title
        })
      }'
      ;;
    *)
      echo "Error: multiple open pull requests have head $HEAD_SELECTOR in $PR_REPO" >&2
      printf '%s' "$PR_MATCHES" |
        jq -r '.[] | "#\(.number) [\(.state)] \(.title)"' >&2
      exit 1
      ;;
  esac
}

guard_branch() {
  [ "$#" -eq 3 ] || usage
  ROLE=$1
  CURRENT_BRANCH=$2
  PR_HEAD_BRANCH=$3
  [ -n "$CURRENT_BRANCH" ] || fail "current branch is empty"
  [ -n "$PR_HEAD_BRANCH" ] || fail "pull-request head branch is empty"

  case "$ROLE" in
    owner|fork)
      if [ "$PR_HEAD_BRANCH" != "$CURRENT_BRANCH" ]; then
        fail "$ROLE workflow is on $CURRENT_BRANCH but PR head is $PR_HEAD_BRANCH"
      fi
      ;;
    maintainer)
      ;;
    *)
      fail "unsupported repository role: $ROLE"
      ;;
  esac
}

create_head() {
  [ "$#" -eq 4 ] || usage
  LOCAL_REPO=$1
  PR_REPO=$2
  CURRENT_BRANCH=$3
  IS_FORK=$4
  validate_repo_identity "$LOCAL_REPO" ||
    fail "LOCAL_REPO must be an owner/name identity"
  validate_repo_identity "$PR_REPO" ||
    fail "PR_REPO must be an owner/name identity"
  [ -n "$CURRENT_BRANCH" ] || fail "current branch is empty"

  case "$IS_FORK" in
    true)
      [ "$LOCAL_REPO" != "$PR_REPO" ] ||
        fail "fork repository must differ from pull-request repository"
      printf '%s:%s\n' "${LOCAL_REPO%%/*}" "$CURRENT_BRANCH"
      ;;
    false)
      [ "$LOCAL_REPO" = "$PR_REPO" ] ||
        fail "non-fork repository must equal pull-request repository"
      printf '%s\n' "$CURRENT_BRANCH"
      ;;
    *)
      fail "IS_FORK must be true or false"
      ;;
  esac
}

validate_number() {
  [ "$#" -eq 1 ] || usage
  case "$1" in
    ""|*[!0-9]*) fail "PR_NUMBER must be a positive integer" ;;
    0) fail "PR_NUMBER must be a positive integer" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

[ "$#" -ge 1 ] || usage
COMMAND=$1
shift
case "$COMMAND" in
  lookup) lookup "$@" ;;
  guard-branch) guard_branch "$@" ;;
  create-head) create_head "$@" ;;
  validate-number) validate_number "$@" ;;
  *) usage ;;
esac

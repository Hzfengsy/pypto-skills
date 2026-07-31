# Look Up a Pull Request

Requires the context from [setup](setup.md). This reference resolves the
standard pull-request outputs `PR_NUMBER`, `PR_STATE`, and `PR_HEAD_BRANCH`.

## Look up a known number

```bash
if [ -n "${PR_NUMBER:-}" ]; then
  PR_DATA=$(gh pr view "$PR_NUMBER" --repo "$PR_REPO" \
    --json number,state,headRefName,title) || {
    echo "Error: pull request #$PR_NUMBER was not found in $PR_REPO" >&2
    exit 1
  }
fi
```

## Look up the current or named head branch

When no number is supplied, search with the fork prefix discovered by setup.
Set `PR_HEAD_BRANCH` before this block to search a branch other than
`CURRENT_BRANCH`.

```bash
if [ -z "${PR_NUMBER:-}" ]; then
  PR_HEAD_BRANCH=${PR_HEAD_BRANCH:-$CURRENT_BRANCH}
  HEAD_SELECTOR="${PR_HEAD_PREFIX}${PR_HEAD_BRANCH}"
  PR_MATCHES=$(gh pr list --repo "$PR_REPO" --state all \
    --head "$HEAD_SELECTOR" --json number,state,headRefName,title) || {
    echo "Error: pull requests could not be listed in $PR_REPO" >&2
    exit 1
  }
  MATCH_COUNT=$(printf '%s' "$PR_MATCHES" | jq 'length')
  if [ "$MATCH_COUNT" -eq 0 ]; then
    echo "Error: no pull request has head $HEAD_SELECTOR in $PR_REPO" >&2
    exit 1
  fi
  if [ "$MATCH_COUNT" -gt 1 ]; then
    echo "Error: multiple pull requests have head $HEAD_SELECTOR; choose a number" >&2
    printf '%s\n' "$PR_MATCHES" | jq -r '.[] | "#\(.number) [\(.state)] \(.title)"'
    exit 1
  fi
  PR_DATA=$(printf '%s' "$PR_MATCHES" | jq '.[0]')
fi
```

## Normalize and validate outputs

```bash
PR_NUMBER=$(printf '%s' "$PR_DATA" | jq -r '.number')
PR_STATE=$(printf '%s' "$PR_DATA" | jq -r '.state')
PR_HEAD_BRANCH=$(printf '%s' "$PR_DATA" | jq -r '.headRefName')

if [ -z "$PR_NUMBER" ] || [ "$PR_NUMBER" = "null" ] ||
   [ -z "$PR_STATE" ] || [ "$PR_STATE" = "null" ] ||
   [ -z "$PR_HEAD_BRANCH" ] || [ "$PR_HEAD_BRANCH" = "null" ]; then
  echo "Error: pull-request metadata is incomplete" >&2
  exit 1
fi
```

To offer a user a choice rather than guessing:

```bash
gh pr list --repo "$PR_REPO" --state open \
  --json number,title,headRefName,author
```

Never select the first result when more than one pull request matches.

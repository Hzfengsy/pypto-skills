# Common Skills First-Batch Migration Design

## Goal

Establish `hw-native-sys/pypto-skills` as the canonical source for the first
batch of cross-repository workflows:

- `clean-branches`
- `github-pr`
- `fix-pr`
- reusable GitHub workflow references required by those skills

This batch publishes and validates the common source only. Updating consumer
repositories and removing their existing copies is a separate migration.

## Evidence and source selection

`clean-branches` is already byte-identical in `pypto` and `simpler`, so it is
the safest first canonical skill.

`github-pr` and `fix-pr` exist in `pypto`, `simpler`, and `pypto-lib`, but their
copies have diverged. Use the `simpler` implementations and
`.claude/lib/github/` references as the behavioral baseline because they
already handle repository discovery, fork contributors, maintainers updating
cross-fork pull requests, and shared GitHub operations. Preserve useful PyPTO
behavior only when it is repository-independent.

Do not copy any hard-coded repository URL, organization name, project number,
default branch, commit convention, test command, or repository-specific review
rule into the common source.

## Considered approaches

### Copy the PyPTO files unchanged

This is fast but keeps `hw-native-sys/pypto`, `upstream/main`, `.claude/rules/`,
and PyPTO-specific commit/test assumptions. Other repositories would
immediately need forks of the common skills, recreating the drift this
migration is intended to remove.

### Publish only high-level workflow text

This avoids hard-coding but leaves fragile GitHub GraphQL, cross-fork, rebase,
push, comment pagination, and thread-resolution behavior to be rediscovered by
each agent. It is portable but insufficiently deterministic.

### Common workflow plus repository discovery and local policy hooks

This is the selected approach. Keep deterministic Git/GitHub mechanics in
shared references, discover repository state at runtime, and delegate commit,
test, and review policy to skills or instructions supplied by the consuming
repository.

## Repository structure

```text
pypto-skills/
├── skills/
│   ├── clean-branches/
│   │   ├── SKILL.md
│   │   └── agents/openai.yaml
│   ├── github-pr/
│   │   ├── SKILL.md
│   │   └── agents/openai.yaml
│   └── fix-pr/
│       ├── SKILL.md
│       └── agents/openai.yaml
├── lib/github/
│   ├── branch-naming.md
│   ├── checkout-fork-branch.md
│   ├── commit-and-push.md
│   ├── common-issues.md
│   ├── detect-permission.md
│   ├── fetch-comments.md
│   ├── lookup-pr.md
│   ├── reply-and-resolve.md
│   └── setup.md
└── tests/
    ├── test_skill_structure.py
    └── test_portability.py
```

The repository is consumed as a complete bundle so skills can share the
canonical `lib/github/` references without duplicating them. Consumer
installation and synchronization are intentionally outside this batch.

## Common context contract

`lib/github/setup.md` resolves the following values without assuming repository
names or branch names:

| Value | Meaning |
| --- | --- |
| `REPO_ROOT` | Current Git worktree root |
| `CURRENT_BRANCH` | Checked-out branch |
| `DEFAULT_BRANCH` | Remote repository default branch |
| `BASE_REMOTE` | Upstream repository remote |
| `BASE_REF` | `<base-remote>/<default-branch>` |
| `PUSH_REMOTE` | Remote that accepts contributor pushes |
| `PR_REPO` | Repository receiving the pull request |
| `PR_HEAD_PREFIX` | Fork owner prefix required by `gh pr create`, if any |
| `ROLE` | `owner`, `fork`, or `maintainer` |

Discovery must fail with a concrete diagnostic when authentication, repository
identity, default branch, or a required remote cannot be resolved. It must not
silently substitute `hw-native-sys/pypto` or `main`.

## Skill behavior

### `clean-branches`

Enumerate local branches and branches on the contributor's push remote. Detect
normal merges through Git and squash merges through GitHub pull requests.
Compare a merged pull request's recorded head SHA with the current branch tip
before treating a reused branch as safe.

Always show the candidate set and require explicit user approval before any
deletion. Never delete the default branch, current branch, base-repository
branches, or a reused branch containing commits after its merged pull request.

### `github-pr`

Support both creating a pull request and updating an existing pull request.
Resolve owner, fork-contributor, and maintainer cross-fork contexts through the
shared references.

If repository-local changes are uncommitted, invoke the consuming repository's
`git-commit` skill when available; otherwise stop and ask for the repository's
commit policy. Do not define a universal commit-message format.

Rebase on `BASE_REF`, use `--force-with-lease` for rewritten published history,
and generate pull-request content only from commits and diffs in
`BASE_REF..HEAD`. Never add AI attribution.

### `fix-pr`

Inspect unresolved review threads, relevant pull-request conversation comments,
out-of-diff bot findings, and CI checks. Paginate every GitHub connection.
Classify feedback by technical content rather than author.

Before changing code, present actionable findings for user confirmation. Work
on the correct owner or cross-fork branch, fold fixes into the repository's
expected commit shape, push safely, reply to resolved feedback, and re-check
until clean or until a documented iteration/stuck limit is reached.

Repository-specific rules decide whether a style suggestion is accepted.
Repository-specific testing and commit skills remain dependencies rather than
being embedded in this common skill.

## Portability rules

- Frontmatter contains only `name` and `description`.
- Skill descriptions start with `Use when` and describe triggering conditions,
  not workflow summaries.
- Paths are relative to the checked-out repository or this skill bundle.
- Default branches and remotes are detected, never assumed.
- GitHub writes state their exact target before execution.
- Destructive branch deletion always requires explicit approval.
- No Claude-only `Task`, `AskUserQuestion`, or `EnterPlanMode` syntax appears;
  instructions describe intent so Codex, Claude Code, and other compatible
  agents can map it to their native tools.
- No repository-specific build, test, lint, commit, issue-template, or project
  board policy appears in the common bundle.

## Validation

Before writing each migrated skill, run a baseline scenario against its source
copy to record the portability failure being fixed. After writing it, run the
same scenario against the common skill.

Automated validation must verify:

- every skill has valid YAML frontmatter and a matching directory name;
- every relative Markdown reference resolves;
- no banned repository identifiers or fixed `upstream/main` / `origin/main`
  references exist;
- destructive branch commands are paired with an explicit approval gate;
- shared context variables are defined before a skill references them.

Forward scenarios must cover:

1. a repository whose default branch is `trunk`;
2. an owner repository with only `origin`;
3. a fork contributor using `origin` plus `upstream`;
4. a maintainer updating a contributor's cross-fork pull request;
5. a squash-merged branch reused for new commits;
6. a pull request with paginated review threads and pending CI.

## Non-goals

- Migrating `auto-pr`, `create-issue`, `fix-issue`, or `git-commit`
- Defining organization-wide commit, test, review, or issue policies
- Updating any consumer repository
- Deleting existing skill copies
- Adding an installer, submodule, subtree, or synchronization workflow
- Migrating PyPTO-specific profiling, IR, codegen, testing, or changelog skills

## Completion criteria

The batch is complete when all three skills and shared references are present,
structural and portability tests pass, forward scenarios demonstrate the
intended behavior, and the resulting commit is pushed to
`hw-native-sys/pypto-skills`.

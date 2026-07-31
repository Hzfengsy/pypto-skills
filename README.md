# PyPTO Skills

This repository is the canonical source for portable skills shared across
PyPTO-related repositories. It keeps reusable agent workflows and their common
GitHub mechanics together so they can be validated as one bundle.

## First batch

The first migration batch covers:

- `clean-branches`
- `github-pr`
- `fix-pr`

These skills are still being migrated. Each skill becomes ready only after its
own portability and forward-validation task passes.

## Layout

- `skills/` contains discoverable skills and their agent metadata.
- `lib/github/` contains shared Git and GitHub workflow references used by the
  skills.
- `tests/` validates skill structure, local links, and portability.

Consumer installation and synchronization are not yet defined. Until that
design is complete, this repository does not prescribe how another repository
should consume the bundle.

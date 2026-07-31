# PyPTO Skills

This repository is the canonical source for portable skills shared across
PyPTO-related repositories. It keeps reusable agent workflows and their common
GitHub mechanics together so they can be validated as one bundle.

## First batch

The first validated migration batch includes:

- `clean-branches`: identify and safely remove merged local and fork branches.
- `github-pr`: prepare, publish, create, or update pull requests across forks.
- `fix-pr`: resolve review feedback and failing checks through a bounded,
  verified repair loop.

The skills, shared references, helper scripts, metadata, and tests are
validated together. Consumers must therefore copy or sync the whole bundle
until a dedicated installer is designed.

## Layout

- `skills/` contains discoverable skills and their agent metadata.
- `lib/github/` contains shared Git and GitHub workflow references used by the
  skills.
- `tests/` validates skill structure, local links, and portability.

Consumer installation and synchronization are not yet defined. This repository
does not prescribe a submodule, vendoring, or synchronization mechanism.

## Validation

Run the standard-library test suite with:

```bash
python -m unittest discover -s tests -v
```

Install the pinned CI tools and run the same static checks with:

```bash
python -m pip install --requirement requirements-ci.txt
ruff check tests
ruff format --check tests
pyright
git ls-files -z -- '*.sh' | xargs -0 -r -n 1 bash -n
```

CI additionally installs Bubblewrap and requires the production validation
sandbox to execute successfully.

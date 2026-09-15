# AGENTS.md — lemonfiber-plugins

Guidance for any AI agent working in this repo.

> **Common rules for every lemonfiber repo are canonical in the spec:**
> [50-governance/ai-contributors.md](https://github.com/lemonfiber/spec/blob/main/50-governance/ai-contributors.md).
> Read them. This file is the `lemonfiber-plugins`-specific header only.

## What this repo is

The reviewed plugin catalogue: one file per plugin saying where it is and which
revision of it somebody read. It is not where plugins live — each lives in its
own repository — and it is not the release train's list of plugins, which is the
spec's `70-operations/plugins.toml` and answers a different question. Spec page:
[30-repos/lemonfiber-plugins.md](https://github.com/lemonfiber/spec/blob/main/30-repos/lemonfiber-plugins.md).

## The rules you cannot break

- **Register, never copy** (`REPO-R60`). An entry is an origin and a commit. A
  manifest, a fixture or a proof appearing in this repository is the defect this
  design exists to avoid: two answers to what a plugin declares, with nothing to
  say which one an operator installed.
- **Nothing from a registered repository is executed** (`REPO-R62`). `check.py`
  copies data out of a fetched revision — `plugin.toml`, `fixtures/`,
  `targets.toml` — and runs this repository's own programs over it. If you find
  yourself reaching for the registered repo's `.github/interim/`, stop: that is
  running a stranger's code to decide whether the stranger's data is safe.
- **`revision` is a full commit.** Never a tag, never a branch. A name can be
  repointed after it was read.
- **The harness is the template's harness, byte for byte.** `.github/interim/`
  is copied from `plugin-template` and diffed against it in CI. Fix a validator
  bug there and bring the copy across; never fix it here alone.
- **Everything must be reviewable as a diff** (`REPO-R60`). No archives, no
  encoded blobs, no generated artefacts.
- **This is not a service** (`REPO-R59`) and nothing here is resolved at run
  time (`REPO-R58`). No backend, no database, no state beyond the repository.

## What is deliberately absent

- **A plugin's manifest and fixtures.** See above; they stay where they are
  published.
- **A version number of its own.** The catalogue is not a stream the version
  train cuts (`OPS-R59`), and a plugin landing here moves no version number in
  this organisation.
- **An entry for `plugin-template`.** The README says why: it is the thing an
  author copies rather than a thing an operator installs, and the release train
  already gates on it where that question belongs.

## Before you push

```sh
python3 registry/entry.py --self-test
python3 registry/entry.py
python3 registry/check.py          # needs git, a token, and jsonschema
```

Commit trailers are exactly `Spec: <ids>` and `Signed-off-by:`. No AI
attribution anywhere — not in commits, pull request bodies, or squash messages.
Stage paths explicitly; never `git add -A`.

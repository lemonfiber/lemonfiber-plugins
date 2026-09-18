# Task runner for lemonfiber/lemonfiber-plugins. `just` with no argument lists these.
default:
    @just --list

# Turn on the repository's own git hooks. Once per clone.
#
# There is no package manager here, so there is no `npm ci` or `composer install`
# to hang `core.hooksPath` on the way the other repos do — it is this recipe or
# nothing, and `ci` depends on it so that running the checks once turns the hooks
# on for good. The setting is per-clone local config and no commit can carry it.
#
# Turn on this clone's git hooks. Once per clone.
hooks:
    git config core.hooksPath .githooks
    @echo "hooks on: .githooks/commit-msg, .githooks/pre-push"

# Every gate CI runs over the contents of this repository, in the order CI runs
# them, plus the hooks that answer for the commit message.
#
# Five jobs are not here, and naming them is the point — a recipe that claims to
# be CI and is a subset of it teaches people to skip it and read the run instead.
#
#   commitlint, dco, attribution, spec-check   `.githooks/commit-msg` refuses all
#                                              four of these before the push, and
#                                              `hooks` above is what turns it on
#   harness                                    `.github/interim/` here is compared
#                                              byte for byte against
#                                              plugin-template's, which needs
#                                              both trees
#   shared-files, pins, workflow-pins          need a lemonfiber/spec checkout and
#                                              the forge to compare against
#   actionlint, markdown, invite               need tools this repository does not
#                                              otherwise ask for; `npx
#                                              markdownlint-cli2 "**/*.md"` and
#                                              `actionlint` are the two commands
#   osv-scanner, gitleaks, label               forge-side, and decide nothing about
#                                              a registration
#
# Every gate CI runs over this repository's contents — not the whole of CI.
ci: hooks entries plugins typos links

# The rules refuse what they exist to refuse, then every entry against them. The
# self-test runs first: a gate nobody has seen fail is a gate nobody knows the
# shape of.
#
# The rules refuse what they exist to refuse, then every entry against them.
entries:
    python3 registry/entry.py --self-test
    python3 registry/entry.py

# Every registration, fetched at the revision it names and held to what
# lemonfiber publishes.
#
# `uv run --with` rather than `pip install`, for the same reason `uvx ruff@…` is
# used elsewhere: the one dependency this repository has is pinned to the version
# CI installs and is gone when the command ends, rather than put in whatever
# interpreter happened to be on the path.
#
# It reads the forge, so give it a token — `GH_TOKEN=$(gh auth token) just
# plugins`. Without one it says which of its questions went unasked rather than
# passing them.
#
# Every registration, fetched at the revision it names. Needs a token.
plugins:
    uv run --no-project --quiet --with jsonschema==4.25.1 python3 registry/check.py

# Spell check.
typos:
    typos

# Link check.
links:
    lychee --no-progress .

#!/usr/bin/env python3
"""Hold every registered plugin, and the template they all start from, to what it declares.

`REPO-R61`: fetch the registered revision and, out of the data in that revision alone,
validate the manifest against the schema lemonfiber publishes, run every declared proof
against that plugin's own recordings, and check its declared reach statically. A
registration failing any of it is refused here rather than in review.

**Nothing from a registered repository is executed** (`REPO-R62`). Four paths are copied
out of the fetched tree and the rest of it is left where it lies: the manifest, the
recordings, the release the author says they proved against, and nothing else. The
programs that then read them are this catalogue's own copies, which is the same line
`F3-R6` draws on an operator's machine — a catalogue that ran a stranger's script in
order to decide whether the stranger's data was acceptable would be answering the
question by doing the thing the question is about.

The proofs run against recordings rather than against a live service (`F10-R4`), and are
reported as what they are (`F10-R6`): a claim about what this plugin declares, which is
weaker than a claim about a service that answered.

`--template` asks the same of the template an author starts from (`F10-R7`). It is not
registered and must not be — the README says why — but *does it still validate and prove
unmodified against the commands this catalogue runs* is a question about the format
rather than about one plugin, and it has to be asked somewhere.

Run:  python3 registry/check.py
      python3 registry/check.py --only komga
      python3 registry/check.py --template
Needs: git, a token in the environment, and `jsonschema`.
Exit 0 = every subject holds, 1 = one does not, 2 = this could not be asked.
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import entry as entries_module  # noqa: E402

UPSTREAM = "lemonfiber/lemonfiber"
REF = "main"

# The three lemonfiber publishes, read from its tree rather than from a release: they
# are committed when the change lands and attached when a release is cut, and a
# catalogue should refuse a name the day it is withdrawn rather than one release later.
SCHEMA = "plugin-manifest.schema.json"
VOCABULARY = "capability-vocabulary.json"
POINTS = "extension-points.json"
PUBLISHED = (SCHEMA, VOCABULARY, POINTS)

# What is copied out of a fetched revision. Data, and the whole of the data — a plugin
# is `plugin.toml` and its recordings, and `targets.toml` is the author's claim about
# which release they proved against.
CARRIED = ("plugin.toml", "targets.toml")
CARRIED_DIRS = ("fixtures",)

HARNESS = ROOT / ".github" / "interim"

# The template an author starts from. Not an entry and never one: it is the thing
# somebody copies rather than a thing an operator installs, and the README says why
# that distinction is worth keeping. `main` rather than a commit is the other half of
# it — a registration is a revision somebody reviewed, and this is whatever an author
# would copy today.
#
# It is asked here because nothing else asks it. The two gates either side each answer
# about a *change*: the byte-diff in `registry.yml` fails when this repository's harness
# and the template's differ, and the template's own CI fails when a commit there breaks
# it. Neither fires when the template stops holding for a reason that is a commit in
# neither repository — the schema, the capability vocabulary or the extension points
# moving under it, all three of which are read off lemonfiber's default branch on every
# run of this.
TEMPLATE = {
    "id": "plugin-template",
    "origin": "https://github.com/lemonfiber/plugin-template",
    "revision": "main",
}

# What failing these checks means, which is not the same thing for the two subjects. A
# registration this catalogue cannot stand behind is one plugin's problem; a template
# that no longer holds is every author's, because it is what they all start from.
UNHELD_REGISTRATION = "is not a registration this catalogue can stand behind"
UNHELD_TEMPLATE = (
    "no longer validates and proves unmodified against the commands this catalogue "
    "runs, and it is what every author starts from"
)


def ran(*argv: str, at: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """One command, with its output kept rather than streamed."""
    return subprocess.run(
        argv, cwd=at, capture_output=True, text=True, check=False, timeout=600
    )


def published(into: pathlib.Path) -> str | None:
    """lemonfiber's generated artefacts, or why they could not be read.

    Their absence is a regression in lemonfiber rather than a fault in any plugin, and
    saying which is the difference between a catalogue that is broken and one that is
    reporting something broken. Which is also why a failed request is not reported as
    an absent artefact until the forge has been asked whether it would answer at all:
    the workflow passes a token in the environment and a contributor running this at a
    shell has one stored by `gh`, and telling the second that lemonfiber has dropped a
    file would send them to the wrong repository.
    """
    into.mkdir(parents=True, exist_ok=True)
    for name in PUBLISHED:
        asked = ran("gh", "api", f"repos/{UPSTREAM}/contents/contract/{name}?ref={REF}")
        if asked.returncode != 0:
            if ran("gh", "auth", "status").returncode != 0:
                return (
                    "the forge would not answer: `gh` is not authenticated here and no "
                    "GH_TOKEN is set, so nothing was asked about anything"
                )
            return f"{UPSTREAM}@{REF} carries no contract/{name}"
        try:
            body = json.loads(asked.stdout)["content"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return f"the forge's answer about contract/{name} was not readable"
        (into / name).write_bytes(base64.b64decode(body))
    return None


def fetched(origin: str, revision: str, into: pathlib.Path) -> str | None:
    """The registered revision, as a tree on disk, or why not.

    A shallow fetch of the one commit. Nothing is checked out that is not in it, and no
    hook of the registered repository runs: `--no-tags`, no submodule recursion, and the
    clone is never asked to do anything but hold bytes.
    """
    into.mkdir(parents=True, exist_ok=True)
    steps = (
        ("git", "init", "--quiet"),
        ("git", "remote", "add", "origin", origin),
        ("git", "-c", "core.hooksPath=/dev/null", "fetch", "--quiet", "--depth", "1",
         "--no-tags", "origin", revision),
        ("git", "-c", "core.hooksPath=/dev/null", "checkout", "--quiet", "FETCH_HEAD"),
    )
    for step in steps:
        done = ran(*step, at=into)
        if done.returncode != 0:
            said = (done.stderr or done.stdout).strip().splitlines()
            return f"{' '.join(step[-3:])} failed: {said[-1] if said else 'no output'}"
    return None


def assembled(source: pathlib.Path, into: pathlib.Path) -> str | None:
    """This catalogue's programs, and that plugin's data, in one tree.

    The direction is the point. The harness is copied *in* from here; the manifest and
    the recordings are copied *in* from there; nothing crosses the other way and nothing
    executable crosses at all.
    """
    shutil.copytree(HARNESS, into / ".github" / "interim")
    for name in CARRIED:
        found = source / name
        if not found.is_file():
            return f"the revision read has no {name} at its root"
        shutil.copy2(found, into / name)
    for name in CARRIED_DIRS:
        found = source / name
        if not found.is_dir():
            return f"the revision read has no {name}/ at its root"
        shutil.copytree(found, into / name)
    return None


class Unaskable(Exception):
    """Something this run needed was not there, which is not a fault in a plugin."""


def against_the_schema(manifest: pathlib.Path, schema: pathlib.Path) -> list[str]:
    """The manifest, against the schema the binary publishes (`F5-R2`, `ARCH-R92`).

    A missing reader is raised rather than returned, because a registration that could
    not be checked is unproven and a list of no faults would read as clear.
    """
    import tomllib

    try:
        from jsonschema import Draft202012Validator
    except ImportError as absent:  # pragma: no cover - the workflow installs it
        raise Unaskable(
            "jsonschema is not installed, so no manifest was held to the published schema"
        ) from absent

    try:
        held = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as broken:
        return [f"plugin.toml is not readable as TOML: {broken}"]
    validator = Draft202012Validator(json.loads(schema.read_text(encoding="utf-8")))
    return [
        f"plugin.toml{''.join(f'.{step}' for step in fault.path)}: {fault.message}"
        for fault in sorted(validator.iter_errors(held), key=lambda fault: list(fault.path))
    ]


def release(where: pathlib.Path) -> str | None:
    """The lemonfiber release a `targets.toml` names, or nothing if it names none."""
    import tomllib

    try:
        return tomllib.loads(where.read_text(encoding="utf-8")).get("lemonfiber")
    except (OSError, tomllib.TOMLDecodeError):
        return None


def targeted(theirs: pathlib.Path) -> str:
    """Which release the author proved against, against the one these checks ran.

    Two different facts, and `targets.toml` says so: the plugin's is the author's
    claim, this catalogue's is the build the checks were made on. A disagreement is
    not a fault — a plugin proved against an older release may be perfectly good —
    but it is the thing a reviewer most wants told rather than left to notice.
    """
    ours = release(ROOT / "targets.toml")
    said = release(theirs)
    if said is None:
        return "its targets.toml names no lemonfiber release"
    if ours is None or said == ours:
        return f"proved by its author against {said}, which is what these checks ran"
    return f"proved by its author against {said}; these checks ran {ours}"


def one(plugin: dict, artefacts: pathlib.Path) -> tuple[bool, list[str]]:
    """One registration, and everything that has to hold for it."""
    said: list[str] = []
    with tempfile.TemporaryDirectory() as box:
        source = pathlib.Path(box) / "source"
        work = pathlib.Path(box) / "work"
        work.mkdir()

        why = fetched(plugin["origin"], plugin["revision"], source)
        if why is not None:
            return False, [f"the revision named could not be fetched: {why}"]

        why = assembled(source, work)
        if why is not None:
            return False, [why]

        faults = against_the_schema(work / "plugin.toml", artefacts / SCHEMA)
        if faults:
            return False, faults
        said.append("the published schema accepts this manifest")

        # Everything the schema cannot say: that a claimed capability is one the
        # vocabulary carries, that every probe it declares is bound, that a contribution
        # sits at a point that exists and carries what that point declares, and that no
        # recipe reaches an address or carries a value no pair permits. The last of those
        # is the static reach REPO-R61 asks for.
        held = ran(sys.executable, str(work / ".github/interim/validate.py"),
                   "--published", str(artefacts), at=work)
        if held.returncode != 0:
            return False, [held.stdout.strip() or held.stderr.strip()]
        said.append("every claim, contribution and declared reach holds")

        proved = ran(sys.executable, str(work / ".github/interim/prove.py"),
                     "--against", "fixtures", at=work)
        if proved.returncode != 0:
            return False, [proved.stdout.strip() or proved.stderr.strip()]
        said.append(proved.stdout.strip().splitlines()[-1])

        said.append(targeted(work / "targets.toml"))
    return True, said


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", metavar="ID", help="one registration rather than all of them")
    parser.add_argument(
        "--template",
        action="store_true",
        help="the template an author starts from, rather than the registrations",
    )
    args = parser.parse_args()

    if args.template and args.only:
        print("::error::--template and --only name different subjects, so ask one of them")
        return 2

    if args.template:
        found = [TEMPLATE]
    else:
        try:
            found = entries_module.entries()
        except entries_module.Refusal as refused:
            print(f"::error::{refused}")
            return 1
        if args.only:
            found = [plugin for plugin in found if plugin["id"] == args.only]
            if not found:
                print(f"::error::nothing registered is called {args.only!r}")
                return 2
        if not found:
            print("No plugins are registered yet, so there is nothing to hold to anything.")
            return 0

    with tempfile.TemporaryDirectory() as box:
        artefacts = pathlib.Path(box) / "published"
        why = published(artefacts)
        if why is not None:
            print(f"::error::{why}")
            print(
                "\nWhat a manifest is checked against is what lemonfiber publishes. "
                "Their absence is a regression there rather than a fault in anything "
                "checked here, and until it is back nothing can decide whether these "
                "manifests declare anything."
            )
            return 2
        print(f"Against {UPSTREAM}@{REF}: {', '.join(PUBLISHED)}.\n")

        refused = 0
        for plugin in found:
            try:
                held, said = one(plugin, artefacts)
            except Unaskable as unasked:
                print(f"::error::{unasked}")
                return 2
            mark = "ok  " if held else "FAIL"
            print(f"  {mark} {plugin['id']} @ {plugin['revision'][:12]}")
            for line in said:
                print(f"         {line}")
            if not held:
                refused += 1
                unheld = UNHELD_TEMPLATE if args.template else UNHELD_REGISTRATION
                print(f"::error::{plugin['id']} {unheld}")

    print(
        f"\n{len(found) - refused} of {len(found)} hold. Proofs ran against recorded "
        "responses, which is a claim about what a plugin declares rather than about a "
        "service that answered."
    )
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())

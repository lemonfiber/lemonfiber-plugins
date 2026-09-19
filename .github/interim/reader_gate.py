#!/usr/bin/env python3
"""Fail the day the reader arrives, so the stand-in cannot outlive it.

Everything under `.github/interim/` stands in for one command. `lemonfiber
plugin claims <path>` holds a manifest to the published schema, the published
vocabulary and the published points in one pass, runs every bound probe against
the recording it names, and answers with no network, no catalogue and no stack —
which is the whole of what this harness approximates, done by the reader an
operator actually runs rather than by a second program that can disagree with it.

That command ships in the release `targets.toml` names. Until it is out there is
nothing to switch to; the day it is out, this harness is the weaker of two
available answers and must go.

The danger in a stand-in is not that it is weak. It is that it is quiet: it goes
on passing after the thing it stood in for arrives, and nobody is told. So this
register points the other way, and it asks about **the release this plugin
targets** rather than about any release at all. That distinction is the whole
reason this file was rewritten: the register that stood here asked whether a
lemonfiber release carried the manifest schema as an asset, and the schema had
by then been generated, committed and published on lemonfiber's default branch
for days — where `published_gate.py` beside it, and the catalogue, both read it
from. A register that fires one release after the thing it watches for is a
register that cannot do the job its own docstring claims.

  * the pinned release is not out — the expected state. Reported, and the run
    continues.
  * it is out — this **fails**, and asks for `.github/interim/` to be deleted
    and the workflow pointed at `lemonfiber plugin claims`.

Needs the network and a token; without either it reports that it could not ask,
which is unproven rather than clear (`F3-R5`).

Exit 0 = there is still nothing to switch to, 1 = there is.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]
UPSTREAM = "lemonfiber/lemonfiber"


def pinned() -> str:
    return tomllib.loads((ROOT / "targets.toml").read_text(encoding="utf-8"))["lemonfiber"]


def releases() -> tuple[list[dict], str | None]:
    """Every published release of lemonfiber, or why none could be read."""
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        return [], "no token in the environment, so the forge was not asked"
    asked = subprocess.run(
        ["gh", "api", f"repos/{UPSTREAM}/releases", "--paginate"],
        capture_output=True, text=True, check=False,
    )
    if asked.returncode != 0:
        return [], f"the forge did not answer: {asked.stderr.strip()[:200]}"
    try:
        return json.loads(asked.stdout), None
    except ValueError as unreadable:
        return [], f"the forge's answer was not readable: {unreadable}"


def main() -> int:
    want = pinned()
    found, unreachable = releases()

    if unreachable is not None:
        print(f"Could not ask whether {want} is out: {unreachable}")
        print("Unproven, not clear. This register says nothing about this run.")
        return 0

    out = {release["tag_name"].lstrip("v") for release in found}
    if want in out:
        print(f"::error::{UPSTREAM} {want} is released, so `lemonfiber plugin claims` is out")
        print(
            f"\n{want} is the release this plugin is validated and proved against, and it ships "
            "the reader this harness stands in for. Validating with a second program is now the "
            "weaker of two available answers.\n\n"
            "Delete .github/interim/, point the workflow at `lemonfiber plugin claims .`, and "
            "delete this file with it.",
            file=sys.stderr,
        )
        return 1

    print(
        f"{UPSTREAM} {want} — the release this plugin targets, and the one that ships "
        "`lemonfiber plugin claims` — is not out.\n"
        "The expected state. The stand-in in .github/interim/ is what runs, and this check is "
        "what ends it."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

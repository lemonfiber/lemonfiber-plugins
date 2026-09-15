#!/usr/bin/env python3
"""Hold this plugin's claims to the vocabulary lemonfiber actually publishes.

Which capability names exist, and which points a contribution may be made at,
are lemonfiber's to say (`F4-R2`, `F4-R15`). `validate.py` therefore cannot
decide them, and says so rather than passing: without the published artefacts it
skips every rule that needs them and names the rules it skipped.

This is the half that asks. It reads lemonfiber's own `contract/` at `main` —
not a release asset, because the artefacts are generated and committed there
first and a plugin should go red the day a name it claims is withdrawn rather
than one release later — and runs the rules `validate.py` could not.

Deliberately unpinned. A pinned copy would be a guard that stays green against
the vocabulary as it was, which is the failure mode of every stand-in: right
about a moment that has passed. What this plugin is held to is what lemonfiber
publishes now.

  * the artefacts are there and this plugin's claims hold — pass
  * an artefact is missing — fail; they are published with every release and
    their absence is a regression in lemonfiber rather than a gap here
  * a claim does not hold — fail, naming it
  * the forge could not be asked at all — reported, and the run continues.
    Unproven is not clear, and it is not a failure of this plugin either.

Exit 0 = held, or could not be asked; 1 = does not hold.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys
import tomllib

import validate

ROOT = pathlib.Path(__file__).resolve().parents[2]
UPSTREAM = "lemonfiber/lemonfiber"
REF = "main"

# Where lemonfiber keeps its generated artefacts. The web API contract has lived
# beside these since 0.9.0, which is why this is the directory rather than a
# release asset: one is written when the change lands, the other when a release
# is cut.
PUBLISHED = (
    f"contract/{validate.VOCABULARY}",
    f"contract/{validate.EXTENSION_POINTS}",
)


def fetch(path: str) -> tuple[dict | None, str | None]:
    """One generated artefact out of lemonfiber's own tree, or why not."""
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        return None, "no token in the environment, so the forge was not asked"
    asked = subprocess.run(
        ["gh", "api", f"repos/{UPSTREAM}/contents/{path}?ref={REF}"],
        capture_output=True, text=True, check=False,
    )
    if asked.returncode != 0:
        if "Not Found" in asked.stderr or "404" in asked.stderr:
            return None, f"absent: {UPSTREAM}@{REF} carries no {path}"
        return None, f"the forge did not answer: {asked.stderr.strip()[:200]}"
    try:
        answered = json.loads(asked.stdout)
        return json.loads(base64.b64decode(answered["content"])), None
    except (KeyError, ValueError) as unreadable:
        return None, f"{path} was not readable: {unreadable}"


def main() -> int:
    artefacts: list[dict] = []
    for path in PUBLISHED:
        found, why = fetch(path)
        if why is not None and why.startswith("absent:"):
            print(f"::error::{why}")
            print(
                "\nThe published artefacts are what a plugin claims against. One that is not "
                "there is a regression in lemonfiber, not a gap in this plugin — and until it "
                "is back, nothing can decide whether these claims are claims of anything.",
                file=sys.stderr,
            )
            return 1
        if why is not None:
            print(f"Could not ask what lemonfiber publishes: {why}")
            print("Unproven, not clear. This register says nothing about this run.")
            return 0
        artefacts.append(found)

    published = validate.Published(artefacts[0], artefacts[1])
    manifest = tomllib.loads((ROOT / validate.MANIFEST).read_text(encoding="utf-8"))
    report = validate.Report()
    validate.validate(manifest, report, published)

    if report.faults:
        for fault in report.faults:
            print(f"::error file={validate.MANIFEST}::{fault}")
        print(f"\n{len(report.faults)} violation(s) against what {UPSTREAM}@{REF} publishes.",
              file=sys.stderr)
        return 1

    names = ", ".join(sorted(published.names()))
    points = ", ".join(sorted(published.point_names()))
    print(
        f"Held to {UPSTREAM}@{REF}: capability vocabulary generation "
        f"{artefacts[0].get('vocabulary_version')}, extension points generation "
        f"{artefacts[1].get('extension_points_version')}.\n"
        f"  capabilities: {names}\n"
        f"  points:       {points}\n"
        "Every claim and every contribution this manifest makes holds against them."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

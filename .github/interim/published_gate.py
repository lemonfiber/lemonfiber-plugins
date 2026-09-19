#!/usr/bin/env python3
"""Hold this plugin to the three artefacts lemonfiber publishes.

What a manifest may contain, which capability names exist, and which points a
contribution may be made at are all lemonfiber's to say (`ARCH-R92`, `F4-R2`,
`F4-R15`). `validate.py` therefore decides none of them on its own and says so
rather than passing: without the published artefacts it skips every rule that
needs them and names the rules it skipped.

This is the half that asks. It reads lemonfiber's own `contract/` at `main` —
not a release asset, because the artefacts are generated and committed there
first and a plugin should go red the day a name it claims is withdrawn rather
than one release later — and runs everything `validate.py` could not.

Deliberately unpinned. A pinned copy would be a guard that stays green against
the contract as it was, which is the failure mode of every stand-in: right about
a moment that has passed. What this plugin is held to is what lemonfiber
publishes now.

  * the artefacts are there and this plugin holds — pass
  * an artefact is missing — fail; they are published with every release and
    their absence is a regression in lemonfiber rather than a gap here
  * the manifest does not hold — fail, naming every violation in one pass
  * the forge could not be asked at all — reported, and the run continues.
    Unproven is not clear, and it is not a failure of this plugin either.

Needs `jsonschema`, which is the one library this harness asks for and is a
schema reader rather than anything that knows what a plugin is.

Exit 0 = held, or could not be asked; 1 = does not hold.
"""

from __future__ import annotations

import base64
import json
import pathlib
import subprocess
import sys
import tempfile

import validate

UPSTREAM = "lemonfiber/lemonfiber"
REF = "main"

# Where lemonfiber keeps its generated artefacts. The web API contract has lived
# beside these since 0.9.0, which is why this is the directory rather than a
# release asset: one is written when the change lands, the other when a release
# is cut.
PUBLISHED = (validate.SCHEMA, validate.VOCABULARY, validate.EXTENSION_POINTS)


def fetch(name: str, into: pathlib.Path) -> str | None:
    """One generated artefact out of lemonfiber's own tree, or why not.

    The forge is asked before anything is concluded about whether it could be. A
    token in the environment is how the workflow authenticates and it is not how an
    author at a shell does — `gh` holds one for them — and refusing to ask because
    one variable is unset reported *unproven* to somebody who could have had the
    answer. Unproven when the answer was available is the failure this file exists
    to avoid, not an instance of caution.
    """
    asked = subprocess.run(
        ["gh", "api", f"repos/{UPSTREAM}/contents/contract/{name}?ref={REF}"],
        capture_output=True, text=True, check=False,
    )
    if asked.returncode != 0:
        if "Not Found" in asked.stderr or "404" in asked.stderr:
            return f"absent: {UPSTREAM}@{REF} carries no contract/{name}"
        return f"the forge did not answer: {asked.stderr.strip()[:200]}"
    try:
        answered = json.loads(asked.stdout)
        (into / name).write_bytes(base64.b64decode(answered["content"]))
    except (KeyError, ValueError) as unreadable:
        return f"{name} was not readable: {unreadable}"
    return None


def main() -> int:
    with tempfile.TemporaryDirectory() as box:
        where = pathlib.Path(box)
        for name in PUBLISHED:
            why = fetch(name, where)
            if why is not None and why.startswith("absent:"):
                print(f"::error::{why}")
                print(
                    "\nThe published artefacts are what a plugin is held to. One that is not "
                    "there is a regression in lemonfiber, not a gap in this plugin — and until "
                    "it is back, nothing can decide whether this manifest declares anything.",
                    file=sys.stderr,
                )
                return 1
            if why is not None:
                print(f"Could not ask what lemonfiber publishes: {why}")
                print("Unproven, not clear. This register says nothing about this run.")
                return 0

        published = validate.read_published(str(where))
        if not published.asked:
            print(f"::error::{UPSTREAM}@{REF} answered with something that is not "
                  f"{', '.join(PUBLISHED)}")
            return 1

        manifest, why = validate.manifest_here()
        if manifest is None:
            print(f"::error file={validate.MANIFEST}::{why}")
            return 1

        report = validate.Report()
        try:
            validate.validate(manifest, report, published)
        except validate.Unreadable as unread:
            print(f"::error::{unread}")
            return 1

    if report.faults:
        for fault in report.faults:
            print(f"::error file={validate.MANIFEST}::{fault}")
        print(f"\n{len(report.faults)} violation(s) against what {UPSTREAM}@{REF} publishes.",
              file=sys.stderr)
        return 1

    names = ", ".join(sorted(published.names()))
    points = ", ".join(sorted(published.point_names()))
    print(
        f"Held to {UPSTREAM}@{REF}: the generated manifest schema, capability vocabulary "
        f"generation {published.vocabulary.get('vocabulary_version')}, extension points "
        f"generation {published.points.get('extension_points_version')}.\n"
        f"  capabilities: {names}\n"
        f"  points:       {points}\n"
        "This manifest conforms to the schema, and every claim and contribution it makes "
        "holds against them."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

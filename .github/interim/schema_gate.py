#!/usr/bin/env python3
"""Fail the day the published schema exists, so the stand-in cannot outlive it.

`F3-R2` requires a manifest to be validated against a **published schema**, and
`ARCH-R92` requires that schema to be generated from lemonfiber's own types and
published with every release. Nothing publishes one yet, so this repository
validates against the contract by hand — a weaker check, and one that can
disagree with the parser an operator actually runs.

The danger in a stand-in is not that it is weak. It is that it is quiet: it goes
on passing after the thing it stood in for arrives, and nobody is told. So this
register points the other way. It asks lemonfiber's releases whether a plugin
manifest schema is published, and:

  * none published, and the pinned release is unreleased — the expected state.
    Reported, and the run continues.
  * one published — this **fails**, and asks for `.github/interim/` to be
    deleted and `ci.yml` pointed at the schema. The stand-in has outlived what
    it described.

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

# What the published artefact would be called. The web API contract is already
# attached to every release as `web-api.contract.json`, so a schema for the other
# contract would arrive the same way and be named for it.
SCHEMA_NAMES = ("plugin-manifest.schema.json", "plugin.schema.json", "plugin-manifest.contract.json")


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


def published(found: list[dict]) -> list[tuple[str, str]]:
    return [
        (release["tag_name"], asset["name"])
        for release in found
        for asset in release.get("assets", [])
        if asset["name"] in SCHEMA_NAMES
    ]


def main() -> int:
    want = pinned()
    found, unreachable = releases()

    if unreachable is not None:
        print(f"Could not ask whether a schema is published: {unreachable}")
        print("Unproven, not clear. This register says nothing about this run.")
        return 0

    carrying = published(found)
    if carrying:
        for tag, name in carrying:
            print(f"::error::{UPSTREAM} {tag} publishes {name}")
        print(
            "\nThe published schema exists. Validating against a hand-written stand-in "
            "is now the weaker of two available answers, and `F10-R2` is explicit that "
            "a second description of this format must not stand beside the generated "
            "one.\n\n"
            "Delete .github/interim/validate.py, point ci.yml at the published schema, "
            "and delete this file with it.",
            file=sys.stderr,
        )
        return 1

    tags = {release["tag_name"].lstrip("v") for release in found}
    if want in tags:
        print(f"::error::{UPSTREAM} {want} is released and publishes no plugin manifest schema")
        print(
            f"\nARCH-R92 requires the schema to be published with every release. "
            f"{want} is out and carries none, so a plugin author has nothing to validate "
            "against on the release this plugin targets.",
            file=sys.stderr,
        )
        return 1

    print(
        f"No lemonfiber release publishes a plugin manifest schema, and {want} — the "
        f"release this plugin targets — is not out.\n"
        "The expected state. The stand-in in .github/interim/ is what runs, and this "
        "check is what ends it."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

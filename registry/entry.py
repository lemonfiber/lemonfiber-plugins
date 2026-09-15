#!/usr/bin/env python3
"""The entries, and what an entry is allowed to say.

An entry is an origin and the revision of it somebody read (`REPO-R60`). It is not a
copy of the plugin: the manifest, the recordings and the proofs belong to the
repository the entry points at, and a second copy here would be a second answer to
*what does this plugin declare*, with nothing to say which of the two an operator
installed.

So there is very little to check, and all of it is about the pointer rather than about
the plugin. What the plugin declares is checked by `check.py`, against the revision
this names.

Run:  python3 registry/entry.py            # read and check every entry
      python3 registry/entry.py --self-test
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tomllib
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGINS = ROOT / "plugins"

SCHEMA = 1

# The permitted keys, and nothing else. A key this does not know is refused by name
# rather than ignored, because an entry carrying a field the catalogue does not read
# is an author believing something is in force that is not.
REQUIRED = ("id", "origin", "revision")
OPTIONAL = ("note",)

ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class Refusal(Exception):
    """One entry, refused, with where and why."""


def entries(directory: pathlib.Path | None = None) -> list[dict]:
    """Every entry, in the order a reader meets them."""
    where = PLUGINS if directory is None else directory
    if not where.is_dir():
        return []
    return [read(path) for path in sorted(where.glob("*.toml"))]


def read(path: pathlib.Path) -> dict:
    """One entry file, or a refusal naming the file and the field."""
    try:
        held = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as broken:
        raise Refusal(f"{path.name}: not readable as TOML: {broken}") from broken

    if held.get("schema") != SCHEMA:
        raise Refusal(
            f"{path.name}: schema is {held.get('schema')!r}, and this catalogue reads {SCHEMA}"
        )
    plugin = held.get("plugin")
    if not isinstance(plugin, dict):
        raise Refusal(f"{path.name}: has no [plugin] table")

    for field in REQUIRED:
        if field not in plugin:
            raise Refusal(f"{path.name}: [plugin] is missing {field!r}")
    for field in sorted(set(plugin) - set(REQUIRED) - set(OPTIONAL)):
        raise Refusal(
            f"{path.name}: [plugin].{field} is not something an entry says; "
            f"it takes: {', '.join(sorted(set(REQUIRED) | set(OPTIONAL)))}"
        )

    named = plugin["id"]
    if not isinstance(named, str) or ID.match(named) is None:
        raise Refusal(f"{path.name}: [plugin].id {named!r} is not a plugin id")
    if named != path.stem:
        raise Refusal(
            f"{path.name}: registers {named!r}, so the file is {named}.toml — "
            "the name on disk is how two entries for one plugin become one conflict "
            "rather than two rows nobody compared"
        )

    origin(plugin["origin"], path.name)
    revision(plugin["revision"], path.name)
    return plugin


def origin(where: object, file: str) -> None:
    """Where the plugin is, as something a fetch can be pointed at and a person can read."""
    if not isinstance(where, str):
        raise Refusal(f"{file}: [plugin].origin must be a URL")
    split = urlsplit(where)
    if split.scheme != "https":
        raise Refusal(
            f"{file}: [plugin].origin is {split.scheme or 'schemeless'}, and this reads https. "
            "An ssh remote is an account's, and a catalogue anybody can check out from is not"
        )
    if "@" in split.netloc:
        raise Refusal(f"{file}: [plugin].origin carries credentials, which are not registrable")
    if not split.netloc or not split.path.strip("/"):
        raise Refusal(f"{file}: [plugin].origin {where!r} names no repository")
    if split.query or split.fragment:
        raise Refusal(
            f"{file}: [plugin].origin carries a query or a fragment, and what is fetched "
            "has to be the whole of what was read"
        )


def revision(commit: object, file: str) -> None:
    """The revision that was read — a commit, because a tag is a name somebody can move."""
    if not isinstance(commit, str) or COMMIT.match(commit) is None:
        raise Refusal(
            f"{file}: [plugin].revision {commit!r} is not a full commit. A tag or a branch "
            "would let the tree change after it was read, which is the whole of what "
            "registering it was for"
        )


def collisions(found: list[dict]) -> list[str]:
    """Two entries that cannot both stand.

    `F5-R12` refuses two plugins of the same name from different origins. One file per
    id settles the names; this is the other direction — one origin registered twice
    under two names, which is the same ambiguity wearing a different hat.
    """
    seen: dict[str, str] = {}
    said: list[str] = []
    for plugin in found:
        at = plugin["origin"].rstrip("/").removesuffix(".git")
        if at in seen:
            said.append(f"{at} is registered as both {seen[at]!r} and {plugin['id']!r}")
        seen[at] = plugin["id"]
    return said


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true",
                        help="prove each rule refuses the shape it exists to refuse")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    try:
        found = entries()
    except Refusal as refused:
        print(f"::error::{refused}")
        return 1

    clashing = collisions(found)
    for clash in clashing:
        print(f"::error::{clash}")
    if clashing:
        return 1

    if not found:
        print("No plugins are registered yet.")
        return 0
    for plugin in found:
        print(f"  {plugin['id']:<20} {plugin['origin']} @ {plugin['revision'][:12]}")
    print(f"\n{len(found)} registered, and every entry says what an entry may say.")
    return 0


GOOD = """schema = 1

[plugin]
id       = "komga"
origin   = "https://github.com/lemonfiber/plugin-komga"
revision = "0123456789abcdef0123456789abcdef01234567"
"""


def self_test() -> int:
    """Each rule, against the shape it exists to refuse."""
    import tempfile

    cases: list[tuple[str, str, str]] = [
        ("a complete entry is read", "komga.toml", GOOD),
        ("a schema this does not read refused", "komga.toml", GOOD.replace("schema = 1", "schema = 2")),
        ("a missing [plugin] refused", "komga.toml", "schema = 1\n"),
        ("a missing revision refused", "komga.toml",
         GOOD.replace('revision = "0123456789abcdef0123456789abcdef01234567"\n', "")),
        ("a field nothing reads refused", "komga.toml", GOOD + 'summary = "no"\n'),
        ("an id that is not one refused", "Komga.toml", GOOD.replace('"komga"', '"Komga"')),
        ("a file named for another plugin refused", "kavita.toml", GOOD),
        ("an ssh origin refused", "komga.toml", GOOD.replace("https://github.com/", "ssh://git@github.com/")),
        ("an origin carrying credentials refused", "komga.toml",
         GOOD.replace("https://github.com/", "https://token@github.com/")),
        ("an origin naming no repository refused", "komga.toml",
         GOOD.replace("https://github.com/lemonfiber/plugin-komga", "https://github.com")),
        ("an origin carrying a fragment refused", "komga.toml",
         GOOD.replace("plugin-komga", "plugin-komga#anything")),
        ("a branch where a commit belongs refused", "komga.toml",
         GOOD.replace('"0123456789abcdef0123456789abcdef01234567"', '"main"')),
        ("a short commit refused", "komga.toml",
         GOOD.replace('"0123456789abcdef0123456789abcdef01234567"', '"0123456"')),
    ]

    failures = 0
    for index, (what, name, text) in enumerate(cases):
        with tempfile.TemporaryDirectory() as box:
            path = pathlib.Path(box) / name
            path.write_text(text, encoding="utf-8")
            try:
                read(path)
                refused = False
            except Refusal:
                refused = True
        wanted = index != 0
        if refused == wanted:
            print(f"  ok   {what}")
        else:
            print(f"  FAIL {what}")
            failures += 1

    twice = [
        {"id": "komga", "origin": "https://github.com/lemonfiber/plugin-komga", "revision": "a" * 40},
        {"id": "comics", "origin": "https://github.com/lemonfiber/plugin-komga.git", "revision": "b" * 40},
    ]
    if collisions(twice):
        print("  ok   one origin registered under two names refused")
    else:
        print("  FAIL one origin registered under two names refused")
        failures += 1

    print("\nself-test passed." if not failures else f"\n{failures} rule(s) did not refuse.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

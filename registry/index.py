#!/usr/bin/env python3
"""Write the index a catalogue release signs: what was reviewed, and nothing else.

A release is a tag whose assets are this index and a signature over exactly its bytes
(`REPO-R57`, ADR-0034). What is reviewed here is the register — each plugin's origin and
the revision somebody read — so the index is that register, with one more fact per plugin
that the register cannot hold without copying what it registers: the digest of the
manifest at that revision. lemonfiber installs a name only through an index whose
signature verified, installs the revision it names, and holds the manifest it fetches to
this digest, so what an operator installs is what was reviewed and not what the origin
serves today. Each entry also carries what an operator choosing a plugin reads before
installing it, taken from the same manifest: its name, description, version and what the
household is without it (`REPO-R108`). lemonfiber lists them only from an index whose
signature verified, so the list says nothing the catalogue did not sign.

The digest is taken from the revision fetched as data, exactly as `check.py` fetches it:
one commit, no hooks, nothing run (`REPO-R62`). Nothing is written into this repository;
the index is a release asset (`REPO-R60`).

The index names the release it is with a serial, inside what the signature covers
(`REPO-R63`). lemonfiber refuses an index whose serial is lower than the highest it has
verified, so a release this catalogue has replaced cannot be served in place of the one
that replaced it. The serial is the number of commits on `main` up to the tagged one: it
is read off the commit alone, and a release cut from a later commit always carries a
higher one. The release workflow refuses a serial that is not above the last release's,
which is what a second tag on the same commit would carry. The index also names the date
it was published: the committer date of that commit, in UTC, so two runs over one commit
write the same bytes.

Run:  python3 registry/index.py              writes index.json here
      python3 registry/index.py --self-test
Needs: git, this repository's history, and the network to fetch the registered
revisions.
Exit 0 = written, 1 = an entry or a revision could not be read.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys
import tempfile
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402
import entry as entries_module  # noqa: E402
import tree  # noqa: E402

#: The shape of the index, so a reader can refuse one it does not know.
SCHEMA = 1

#: The one file of a revision whose digest the index carries.
MANIFEST = tree.MANIFEST

#: How a digest names the algorithm it was taken with.
DIGEST = tree.DIGEST

#: What each entry carries from the manifest's `[plugin]` table, for an operator to choose by.
LISTED = ("name", "description", "version", "without_it")

#: The name the index is written under, in the directory this is run from. Fixed,
#: because the release publishes exactly this file and nothing else is written.
INDEX = pathlib.Path("index.json")


def indexed(entries: list[dict], read: dict[str, dict], serial: int, published: str) -> dict:
    """The index, from the entries, what each one's manifest at its revision holds, the
    serial of the release it is and the date it was published.

    Kept apart from the fetching, so what the index says can be held to the entries
    without a network. Ordered by id, so one register always writes one index.
    """
    return {
        "schema": SCHEMA,
        "serial": serial,
        "published": published,
        "plugins": [
            {
                "id": one["id"],
                "origin": one["origin"],
                "revision": one["revision"],
                **read[one["id"]],
            }
            for one in sorted(entries, key=lambda one: one["id"])
        ],
    }


def written(index: dict) -> bytes:
    """The bytes that are signed: sorted keys, two-space indent, one trailing newline."""
    return (json.dumps(index, indent=2, sort_keys=True) + "\n").encode("utf-8")


def serial_of() -> tuple[int | None, str | None]:
    """The serial of a release cut from the commit checked out: how many commits `main`
    holds up to it, or why that could not be counted."""
    counted = check.ran("git", "rev-list", "--count", "HEAD", at=HERE.parent)
    said = counted.stdout.strip()
    if counted.returncode != 0 or not said.isdigit():
        why = (counted.stderr or said).strip().splitlines()
        return None, f"the commits could not be counted: {why[-1] if why else 'no output'}"
    return int(said), None


def published_of() -> tuple[str | None, str | None]:
    """The date a release cut from the commit checked out is published: that commit's
    committer date, in UTC, or why it could not be read."""
    dated = check.ran("git", "log", "-1", "--format=%ct", "HEAD", at=HERE.parent)
    said = dated.stdout.strip()
    if dated.returncode != 0 or not said.isdigit():
        why = (dated.stderr or said).strip().splitlines()
        return None, f"the commit's date could not be read: {why[-1] if why else 'no output'}"
    return stamped(int(said)), None


def stamped(seconds: int) -> str:
    """A moment, as the index writes it: UTC, to the second, RFC 3339."""
    at = datetime.datetime.fromtimestamp(seconds, tz=datetime.UTC)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def digest(manifest: bytes) -> str:
    """A manifest's digest, as the index and the bundle write it."""
    return DIGEST + hashlib.sha256(manifest).hexdigest()


def listed(manifest: bytes) -> tuple[dict | None, str | None]:
    """What an entry carries from a manifest's `[plugin]` table, or which fact it lacks."""
    try:
        plugin = tomllib.loads(manifest.decode("utf-8")).get("plugin", {})
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as broken:
        return None, f"its {MANIFEST} cannot be read: {broken}"
    lacking = [key for key in LISTED if not isinstance(plugin.get(key), str) or not plugin[key]]
    if lacking:
        return None, f"its {MANIFEST} names no {', '.join(lacking)}"
    return {key: plugin[key] for key in LISTED}, None


def read_of(plugin: dict, into: pathlib.Path) -> tuple[dict | None, str | None]:
    """What the index carries from the manifest at the registered revision: its digest and
    what an operator chooses by, or why it could not be taken."""
    failed = check.fetched(plugin["origin"], plugin["revision"], into)
    if failed:
        return None, f"{plugin['id']}: {failed}"
    manifest = into / MANIFEST
    if not manifest.is_file():
        return None, f"{plugin['id']}: the revision holds no {MANIFEST}"
    held = manifest.read_bytes()
    facts, why = listed(held)
    if why:
        return None, f"{plugin['id']}: {why}"
    return {"manifest": digest(held), **facts}, None


def self_test() -> int:
    """Hold `indexed` and `written` to what the release signs, without a network."""
    broken: list[str] = []
    entries = [
        {"id": "uptime-kuma", "origin": "https://example.invalid/b", "revision": "b" * 40},
        {"id": "komga", "origin": "https://example.invalid/a", "revision": "a" * 40},
    ]
    facts = {"name": "Komga", "description": "Reads comics", "version": "1.2.3", "without_it": "No comics"}
    read = {
        "komga": {"manifest": DIGEST + "1" * 64, **facts},
        "uptime-kuma": {"manifest": DIGEST + "2" * 64, **facts},
    }
    published = stamped(1_700_000_000)
    index = indexed(entries, read, 41, published)
    if [one["id"] for one in index["plugins"]] != ["komga", "uptime-kuma"]:
        broken.append("the index is not ordered by id")
    if index["plugins"][0] != {
        "id": "komga",
        "origin": "https://example.invalid/a",
        "revision": "a" * 40,
        "manifest": DIGEST + "1" * 64,
        **facts,
    }:
        broken.append(
            "an entry carries something other than its id, origin, revision, digest and what "
            "its manifest lists"
        )
    if written(index) != written(indexed(list(reversed(entries)), read, 41, published)):
        broken.append("one register wrote two different indexes")
    if b'"serial": 41' not in written(index):
        broken.append("the serial is not inside the bytes that are signed")
    if written(index) == written(indexed(entries, read, 42, published)):
        broken.append("two releases wrote the same index")
    if b'"published": "2023-11-14T22:13:20Z"' not in written(index):
        broken.append("the date published is not inside the bytes that are signed, in UTC")
    taken, why = listed(
        b'[plugin]\nname = "Komga"\ndescription = "Reads comics"\nversion = "1.2.3"\n'
        b'without_it = "No comics"\nlicense = "MIT"\n'
    )
    if why or taken != facts:
        broken.append(f"a manifest's listed facts were not taken as it states them: {why}")
    _, why = listed(b'[plugin]\nname = "Komga"\nversion = "1.2.3"\nwithout_it = ""\n')
    if not why or "description, without_it" not in why:
        broken.append("a manifest lacking a listed fact was not refused by name")
    _, why = listed(b"[plugin\n")
    if not why:
        broken.append("a manifest that cannot be read was not refused")
    _, why = published_of()
    if why:
        broken.append(f"this checkout's date could not be read: {why}")
    serial, why = serial_of()
    if why or not serial:
        broken.append(f"this checkout's serial could not be read: {why}")
    if not written(index).endswith(b"}\n"):
        broken.append("the signed bytes do not end in one newline")
    for line in broken:
        print(f"::error::{line}")
    if broken:
        return 1
    print(
        "self-test: one register writes one index, ordered by id, carrying what was "
        "reviewed, what each manifest lists, the serial of the release and its date."
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--self-test", action="store_true", help="prove the index's shape")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    try:
        entries = entries_module.entries()
    except entries_module.Refusal as refused:
        print(f"::error::{refused}")
        return 1
    serial, why = serial_of()
    if why or serial is None:
        print(f"::error::{why}")
        print("::error::no index was written: a release that cannot say which it is is refused")
        return 1

    published, why = published_of()
    if why or published is None:
        print(f"::error::{why}")
        print("::error::no index was written: a release that cannot say when it was cut is refused")
        return 1

    read: dict[str, dict] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as work:
        for plugin in entries:
            taken, why = read_of(plugin, pathlib.Path(work) / plugin["id"])
            if why or taken is None:
                failures.append(why or f"{plugin['id']}: nothing was read")
            else:
                read[plugin["id"]] = taken
    if failures:
        for why in failures:
            print(f"::error::{why}")
        print("::error::no index was written: a release signs every registration or none")
        return 1

    INDEX.write_bytes(written(indexed(entries, read, serial, published)))
    print(f"wrote {INDEX} for {len(entries)} plugin(s), as release {serial}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

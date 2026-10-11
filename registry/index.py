#!/usr/bin/env python3
"""Write the index a catalogue release signs: what was reviewed, and nothing else.

A release is a tag whose assets are this index and a signature over exactly its bytes
(`REPO-R57`, ADR-0034). What is reviewed here is the register — each plugin's origin and
the revision somebody read — so the index is that register, with one more fact per plugin
that the register cannot hold without copying what it registers: the digest of the
manifest at that revision. lemonfiber installs a name only through an index whose
signature verified, installs the revision it names, and holds the manifest it fetches to
this digest, so what an operator installs is what was reviewed and not what the origin
serves today.

The digest is taken from the revision fetched as data, exactly as `check.py` fetches it:
one commit, no hooks, nothing run (`REPO-R62`). Nothing is written into this repository;
the index is a release asset (`REPO-R60`).

The index names the release it is with a serial, inside what the signature covers
(`REPO-R63`). lemonfiber refuses an index whose serial is lower than the highest it has
verified, so a release this catalogue has replaced cannot be served in place of the one
that replaced it. The serial is the number of commits on `main` up to the tagged one: it
is read off the commit alone, and a release cut from a later commit always carries a
higher one. The release workflow refuses a serial that is not above the last release's,
which is what a second tag on the same commit would carry.

Run:  python3 registry/index.py              writes index.json here
      python3 registry/index.py --self-test
Needs: git, this repository's history, and the network to fetch the registered
revisions.
Exit 0 = written, 1 = an entry or a revision could not be read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402
import entry as entries_module  # noqa: E402

#: The shape of the index, so a reader can refuse one it does not know.
SCHEMA = 1

#: The one file of a revision whose digest the index carries.
MANIFEST = "plugin.toml"

#: How a digest names the algorithm it was taken with.
DIGEST = "sha256:"

#: The name the index is written under, in the directory this is run from. Fixed,
#: because the release publishes exactly this file and nothing else is written.
INDEX = pathlib.Path("index.json")


def indexed(entries: list[dict], digests: dict[str, str], serial: int) -> dict:
    """The index, from the entries, the manifest digest each one's revision holds, and
    the serial of the release it is.

    Kept apart from the fetching, so what the index says can be held to the entries
    without a network. Ordered by id, so one register always writes one index.
    """
    return {
        "schema": SCHEMA,
        "serial": serial,
        "plugins": [
            {
                "id": one["id"],
                "origin": one["origin"],
                "revision": one["revision"],
                "manifest": digests[one["id"]],
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


def digest(manifest: bytes) -> str:
    """A manifest's digest, as the index and the bundle write it."""
    return DIGEST + hashlib.sha256(manifest).hexdigest()


def digest_of(plugin: dict, into: pathlib.Path) -> tuple[str | None, str | None]:
    """The manifest's digest at the registered revision, or why it could not be taken."""
    failed = check.fetched(plugin["origin"], plugin["revision"], into)
    if failed:
        return None, f"{plugin['id']}: {failed}"
    manifest = into / MANIFEST
    if not manifest.is_file():
        return None, f"{plugin['id']}: the revision holds no {MANIFEST}"
    return digest(manifest.read_bytes()), None


def self_test() -> int:
    """Hold `indexed` and `written` to what the release signs, without a network."""
    broken: list[str] = []
    entries = [
        {"id": "uptime-kuma", "origin": "https://example.invalid/b", "revision": "b" * 40},
        {"id": "komga", "origin": "https://example.invalid/a", "revision": "a" * 40},
    ]
    digests = {"komga": DIGEST + "1" * 64, "uptime-kuma": DIGEST + "2" * 64}
    index = indexed(entries, digests, 41)
    if [one["id"] for one in index["plugins"]] != ["komga", "uptime-kuma"]:
        broken.append("the index is not ordered by id")
    if index["plugins"][0] != {
        "id": "komga",
        "origin": "https://example.invalid/a",
        "revision": "a" * 40,
        "manifest": DIGEST + "1" * 64,
    }:
        broken.append("an entry carries something other than its id, origin, revision and digest")
    if written(index) != written(indexed(list(reversed(entries)), digests, 41)):
        broken.append("one register wrote two different indexes")
    if b'"serial": 41' not in written(index):
        broken.append("the serial is not inside the bytes that are signed")
    if written(index) == written(indexed(entries, digests, 42)):
        broken.append("two releases wrote the same index")
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
        "reviewed and the serial of the release."
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

    digests: dict[str, str] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as work:
        for plugin in entries:
            taken, why = digest_of(plugin, pathlib.Path(work) / plugin["id"])
            if why:
                failures.append(why)
            else:
                digests[plugin["id"]] = taken
    if failures:
        for why in failures:
            print(f"::error::{why}")
        print("::error::no index was written: a release signs every registration or none")
        return 1

    INDEX.write_bytes(written(indexed(entries, digests, serial)))
    print(f"wrote {INDEX} for {len(entries)} plugin(s), as release {serial}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

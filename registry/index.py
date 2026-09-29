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

Run:  python3 registry/index.py --out index.json
      python3 registry/index.py --self-test
Needs: git, and the network to fetch the registered revisions.
Exit 0 = written, 1 = an entry or a revision could not be read, 2 = bad arguments.
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


def indexed(entries: list[dict], digests: dict[str, str]) -> dict:
    """The index, from the entries and the manifest digest each one's revision holds.

    Kept apart from the fetching, so what the index says can be held to the entries
    without a network. Ordered by id, so one register always writes one index.
    """
    return {
        "schema": SCHEMA,
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


def digest_of(plugin: dict, into: pathlib.Path) -> tuple[str | None, str | None]:
    """The manifest's digest at the registered revision, or why it could not be taken."""
    failed = check.fetched(plugin["origin"], plugin["revision"], into)
    if failed:
        return None, f"{plugin['id']}: {failed}"
    manifest = into / MANIFEST
    if not manifest.is_file():
        return None, f"{plugin['id']}: the revision holds no {MANIFEST}"
    return "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest(), None


def self_test() -> int:
    """Hold `indexed` and `written` to what the release signs, without a network."""
    broken: list[str] = []
    entries = [
        {"id": "uptime-kuma", "origin": "https://example.invalid/b", "revision": "b" * 40},
        {"id": "komga", "origin": "https://example.invalid/a", "revision": "a" * 40},
    ]
    digests = {"komga": "sha256:" + "1" * 64, "uptime-kuma": "sha256:" + "2" * 64}
    index = indexed(entries, digests)
    if [one["id"] for one in index["plugins"]] != ["komga", "uptime-kuma"]:
        broken.append("the index is not ordered by id")
    if index["plugins"][0] != {
        "id": "komga",
        "origin": "https://example.invalid/a",
        "revision": "a" * 40,
        "manifest": "sha256:" + "1" * 64,
    }:
        broken.append("an entry carries something other than its id, origin, revision and digest")
    if written(index) != written(indexed(list(reversed(entries)), digests)):
        broken.append("one register wrote two different indexes")
    if not written(index).endswith(b"}\n"):
        broken.append("the signed bytes do not end in one newline")
    for line in broken:
        print(f"::error::{line}")
    if broken:
        return 1
    print("self-test: one register writes one index, ordered by id, carrying what was reviewed.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=pathlib.Path, help="where to write the index")
    ap.add_argument("--self-test", action="store_true", help="prove the index's shape")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.out is None:
        print("::error::--out is required unless --self-test")
        return 2

    try:
        entries = entries_module.entries()
    except entries_module.Refusal as refused:
        print(f"::error::{refused}")
        return 1

    digests: dict[str, str] = {}
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as work:
        for plugin in entries:
            digest, why = digest_of(plugin, pathlib.Path(work) / plugin["id"])
            if why:
                failures.append(why)
            else:
                digests[plugin["id"]] = digest
    if failures:
        for why in failures:
            print(f"::error::{why}")
        print("::error::no index was written: a release signs every registration or none")
        return 1

    args.out.write_bytes(written(indexed(entries, digests)))
    print(f"wrote {args.out} for {len(entries)} plugin(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

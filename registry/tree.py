#!/usr/bin/env python3
"""A plugin's tree, and the digest a bundle pins it by (ARCH-R267).

The tree is every file the binary carries from a plugin, at the paths its repository
holds them: `plugin.toml`, every file under `config/<service id>/` for each service
the manifest declares, every recording the manifest names, and everything under
`conformance/`. Its digest is the SHA-256 of a listing of those files sorted by path
bytewise, one line each: the file's SHA-256 in lowercase hex, two spaces, its path
relative to the repository root with `/` between segments, and a line feed. That
listing is what `sha256sum` prints for the same files in that order.

Bytewise means the path's UTF-8 bytes, compared as bytes: `config/example-db/` sorts
before `config/example/`, because `-` is 0x2d and `/` is 0x2f. A sort by path
component orders them the other way and gives another digest.

Run:  python3 registry/tree.py <directory>     prints the listing and the digest
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import sys
import tomllib

#: The manifest, at the root of a plugin's repository.
MANIFEST = "plugin.toml"

#: Where each service's starting files sit, under the service's id.
CONFIG = "config"

#: Where a plugin that speaks a contract keeps its conformance.
CONFORMANCE = "conformance"

#: The key every recording a manifest names is written under.
RECORDING = "fixture"

#: How a digest names the algorithm it was taken with.
DIGEST = "sha256:"

#: ARCH-R271's bounds on one service's starting files.
MOST_STARTING_FILES = 64
MOST_STARTING_BYTES = 1024 * 1024


class Unreadable(Exception):
    """A tree that cannot be listed, with every reason."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def recordings(manifest: object) -> list[str]:
    """Every recording a manifest names, wherever it names one."""
    if isinstance(manifest, dict):
        named = [value for key, value in manifest.items() if key == RECORDING and isinstance(value, str)]
        return named + [one for value in manifest.values() for one in recordings(value)]
    if isinstance(manifest, list):
        return [one for value in manifest for one in recordings(value)]
    return []


def service_ids(manifest: dict) -> list[str]:
    """The id of every service a manifest declares."""
    services = manifest.get("service")
    if not isinstance(services, list):
        return []
    return [one["id"] for one in services if isinstance(one, dict) and isinstance(one.get("id"), str)]


def relative(path: str) -> bool:
    """Whether `path` is a path inside a repository, written with `/` and nothing that leaves it."""
    parts = path.split("/")
    return bool(path) and "\\" not in path and not path.startswith("/") and all(
        part not in ("", ".", "..") for part in parts
    )


def linked(root: pathlib.Path, path: str) -> str | None:
    """The first segment of `path` under `root` that is a symbolic link, if one is."""
    parts = path.split("/")
    for depth in range(1, len(parts) + 1):
        said = "/".join(parts[:depth])
        if (root / said).is_symlink():
            return said
    return None


def inside(root: pathlib.Path, path: pathlib.Path) -> bool:
    """Whether `path`, every link followed, is `root` or beneath it."""
    base = os.path.realpath(root)
    return os.path.commonpath([base, os.path.realpath(path)]) == base


def walked(root: pathlib.Path, under: str) -> tuple[list[str], list[str]]:
    """Every file under `under` in `root`, and every symbolic link or other non-file there."""
    link = linked(root, under)
    if link is not None:
        return [], [f"{link} is a symbolic link"]
    base = os.path.realpath(root)
    start = os.path.realpath(os.path.join(base, under))
    if start != base and not start.startswith(base + os.sep):
        return [], [f"{under} is outside the tree"]
    if not os.path.isdir(start):
        return [], []
    top = pathlib.Path(base)
    found: list[str] = []
    refused: list[str] = []
    for at, directories, files in os.walk(start, followlinks=False):
        here = pathlib.Path(at)
        for name in sorted([*directories, *files]):
            path = here / name
            said = path.relative_to(top).as_posix()
            if path.is_symlink():
                refused.append(f"{said} is a symbolic link")
            elif name in files and not path.is_file():
                refused.append(f"{said} is not a regular file")
            elif name in files:
                found.append(said)
        directories[:] = [name for name in directories if not (here / name).is_symlink()]
    return found, refused


def starting_files(root: pathlib.Path, service: str) -> tuple[list[str], list[str]]:
    """A service's starting files under `config/<id>/`, and every reason they cannot be carried."""
    if not relative(service) or "/" in service:
        return [], [f"service id {service!r} is not a directory name"]
    found, refused = walked(root, f"{CONFIG}/{service}")
    weight = sum((root / one).stat().st_size for one in found)
    if len(found) > MOST_STARTING_FILES:
        refused.append(f"service {service} starts with {len(found)} files, more than {MOST_STARTING_FILES}")
    if weight > MOST_STARTING_BYTES:
        refused.append(f"service {service} starts with {weight} bytes, more than {MOST_STARTING_BYTES}")
    return found, refused


def named(root: pathlib.Path, manifest: dict) -> tuple[list[str], list[str]]:
    """Every recording the manifest names, and every one that is not a file of the tree."""
    found: list[str] = []
    refused: list[str] = []
    for recording in sorted(set(recordings(manifest))):
        if not relative(recording):
            refused.append(f"the recording {recording!r} is not a path inside the repository")
        elif linked(root, recording) is not None or not inside(root, root / recording):
            refused.append(f"the recording {recording} is reached through a symbolic link")
        elif not (root / recording).is_file():
            refused.append(f"the recording {recording} is not in the tree")
        else:
            found.append(recording)
    return found, refused


def paths(root: pathlib.Path, manifest: dict) -> list[str]:
    """The tree's paths, sorted bytewise, or every reason they cannot be listed."""
    held = {MANIFEST}
    problems: list[str] = []
    if (root / MANIFEST).is_symlink() or not (root / MANIFEST).is_file():
        problems.append(f"{MANIFEST} is not a file at the root")
    parts = [starting_files(root, service) for service in service_ids(manifest)]
    parts += [named(root, manifest), walked(root, CONFORMANCE)]
    for found, refused in parts:
        held.update(found)
        problems += refused
    if problems:
        raise Unreadable(problems)
    return sorted(held, key=lambda one: one.encode("utf-8"))


def listing(files: list[tuple[str, bytes]]) -> bytes:
    """The listing of `files`, each a path and its bytes, as `sha256sum` prints it in path order."""
    ordered = sorted(files, key=lambda one: one[0].encode("utf-8"))
    return b"".join(
        f"{hashlib.sha256(content).hexdigest()}  {path}\n".encode() for path, content in ordered
    )


def digest(files: list[tuple[str, bytes]]) -> str:
    """The tree digest of `files`, written `sha256:<64 hex>`."""
    return DIGEST + hashlib.sha256(listing(files)).hexdigest()


def read(root: pathlib.Path, manifest: dict) -> list[tuple[str, bytes]]:
    """The tree in `root`, each path with its bytes, in listing order."""
    return [(path, (root / path).read_bytes()) for path in paths(root, manifest)]


def manifest_of(root: pathlib.Path) -> dict:
    """The manifest at `root`, read as TOML, or a refusal."""
    try:
        return tomllib.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as broken:
        raise Unreadable([f"{MANIFEST} cannot be read: {broken}"]) from broken


#: The vector the tree digest is held to here, and that any other reader can be held to.
VECTOR_MANIFEST = b"""schema_version = 1

[plugin]
id = "example"

[[service]]
id = "example"

[[service]]
id = "example-db"

[[claim]]
capability = "media.serve"

[[claim.probe]]
id = "catalogue"
fixture = "recordings/example/catalogue.json"
"""

VECTOR_FILES: dict[str, bytes] = {
    MANIFEST: VECTOR_MANIFEST,
    "config/example/settings.ini": b"[main]\nport = 8080\n",
    "config/example-db/init.sql": b"CREATE TABLE seen (id INTEGER);\n",
    "recordings/example/catalogue.json": b'{"status": 200}\n',
    "recordings/example/unused.json": b"{}\n",
    "conformance/media.serve.json": b"{}\n",
    "README.md": b"# Example\n",
}

VECTOR_PATHS = [
    "config/example-db/init.sql",
    "config/example/settings.ini",
    "conformance/media.serve.json",
    MANIFEST,
    "recordings/example/catalogue.json",
]

VECTOR_LISTING = (
    b"6e174a2633a59381bd17b8119908c22e4e8f01c3674c97c0811d3dcd7d9c0f47  config/example-db/init.sql\n"
    b"275a814ae5de8dc3a28e8de2cd66fc9188651dba5d3fbcd419f6c8781f5c4fe1  config/example/settings.ini\n"
    b"ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356  conformance/media.serve.json\n"
    b"32a4e386817bdf93699b3a1188b9776f2af6a34298df7497a2efdfcc1698829f  plugin.toml\n"
    b"9e80cc1a864b04a50ef8b57bff6c0f51fb4e822becc0482cf95f2bcb07f95c8e  recordings/example/catalogue.json\n"
)

VECTOR_DIGEST = "sha256:083641a4cacc0289f6d0acc96e7e1b67b2dafc17b8d5df47265eaaaf5ce35a77"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: tree.py <directory>", file=sys.stderr)
        return 2
    root = pathlib.Path(sys.argv[1])
    try:
        files = read(root, manifest_of(root))
    except Unreadable as unread:
        for problem in unread.problems:
            print(f"::error::{problem}")
        return 1
    sys.stdout.write(listing(files).decode())
    print(digest(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())

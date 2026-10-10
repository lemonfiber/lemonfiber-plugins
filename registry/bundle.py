#!/usr/bin/env python3
"""Hold the default bundle to the origins it pins (REPO-R91, REPO-R92).

`bundle/bundle.toml` pins each first-party plugin at a release, a revision and the
digest of its manifest there, and `bundle/plugins/<id>.toml` is that manifest, copied
byte for byte. It is the one copy this catalogue holds (REPO-R60), because the core
compiles the bundle in and installs a stack offline. A copy that is not the origin's
manifest at the pinned revision would be a second answer to what the plugin declares,
so every copy is fetched again and compared.

Refused: a bundle that does not say what a bundle may say; a copy no pin names, or a
pin with no copy; a copy whose digest is not its pin's, whose id is not its pin's,
whose adapter service is not tagged at the pinned release, or which claims to fill a
capability it neither provides nor speaks; a copy that differs from the manifest
fetched from its origin at the pinned revision; and a pinned revision failing a check
`check.py` holds a registration to (REPO-R61). The fetch and those checks are
`check.py`'s own, so nothing from a pinned repository is executed (REPO-R62).

A pinned revision has to be on its origin's default branch. A commit pushed to a fork
on the same forge can be fetched through the origin's address, so a revision that
fetches is not yet one the plugin published; its ancestry from the origin's default
branch is what says so.

`--apply ID REVISION --origin URL` is the train's half (OPS-R86): it moves a pinned
plugin to the revision its pin pull request merged, taking the release from the adapter
service's tag there and the digest from its manifest, and copies that manifest in. The
origin is the repository asking, and has to be the one the bundle pins for that id.
Only a plugin the bundle already pins is moved; a plugin enters the bundle through a
person's pull request, because what it fills is a person's choice. `--carry` first
moves every pin that the bundle on stdin holds at another revision than this one, which
is how the one rolling pull request keeps the moves it already carries. It prints the
moves as JSON.

Run:  python3 registry/bundle.py
      python3 registry/bundle.py --apply jellyfin <commit> --origin <url> [--carry < bundle.toml]
      python3 registry/bundle.py --self-test
Needs: git, and the network to fetch the release and the pinned revisions.
Exit 0 = the bundle holds or was moved, 1 = it does not or could not be, 2 = this
could not be asked.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import tempfile
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402
import entry as entries_module  # noqa: E402
import index  # noqa: E402

#: The bundle's file, and where it and the copies sit.
BUNDLE_FILE = "bundle.toml"
BUNDLE = ROOT / "bundle" / BUNDLE_FILE
COPIES = ROOT / "bundle" / "plugins"

SCHEMA = 1

#: The array of tables naming each pinned plugin.
TABLE = "plugin"

#: Every field a pin carries, in the order the bundle writes them.
FIELDS = ("id", "origin", "release", "revision", "manifest", "fills")

#: What keeps the copies' directory in git while it holds no copy.
PLACEHOLDER = ".gitkeep"

#: A release as the train tags it, without the `v`.
RELEASE = re.compile(r"\A\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?\Z")
MANIFEST_DIGEST = re.compile(rf"\A{re.escape(index.DIGEST)}[0-9a-f]{{64}}\Z")

#: Where the pins begin: everything above is the file's own commentary and `schema`.
PINS_START = re.compile(rf"^(?:\[\[{TABLE}\]\]|{TABLE}\s*=)", re.MULTILINE)


class Refusal(Exception):
    """The bundle, refused, with why."""


def quoted(value: str) -> str:
    """A TOML basic string."""
    return json.dumps(value)


def rendered(pins: list[dict]) -> str:
    """The pins as the bundle writes them: one table each, ordered by id, keys aligned."""
    if not pins:
        return f"{TABLE} = []\n"
    width = max(len(field) for field in FIELDS)
    tables = []
    for pin in sorted(pins, key=lambda one: one["id"]):
        lines = [f"[[{TABLE}]]"]
        for field in FIELDS:
            value = pin[field]
            said = (
                "[" + ", ".join(quoted(one) for one in value) + "]"
                if isinstance(value, list)
                else quoted(value)
            )
            lines.append(f"{field:<{width}} = {said}")
        tables.append("\n".join(lines) + "\n")
    return "\n".join(tables)


def read(text: str, file: str = BUNDLE_FILE) -> list[dict]:
    """The pins a bundle names, or a refusal naming the first thing wrong with it."""
    try:
        held = tomllib.loads(text)
    except tomllib.TOMLDecodeError as broken:
        raise Refusal(f"{file}: not readable as TOML: {broken}") from broken
    if held.get("schema") != SCHEMA:
        raise Refusal(f"{file}: schema is {held.get('schema')!r}, and this catalogue reads {SCHEMA}")
    for key in sorted(set(held) - {"schema", TABLE}):
        raise Refusal(f"{file}: {key} is not something a bundle says; it says schema and {TABLE}")
    pins = held.get(TABLE)
    if not isinstance(pins, list):
        raise Refusal(f"{file}: names no [[{TABLE}]] list, not even an empty one")
    distinct(pins, file)

    found = PINS_START.search(text)
    expected = rendered(pins)
    if found is None or found.start() != len(text) - len(expected) or not text.endswith(expected):
        raise Refusal(
            f"{file}: the pins are not written as the bundle writes them — one [[{TABLE}]] "
            f"per plugin, ordered by id, fields in the order {', '.join(FIELDS)} — "
            "so a move would rewrite lines nobody changed"
        )
    return pins


def distinct(pins: list, file: str) -> None:
    """Every pin well formed, and no plugin or origin pinned twice."""
    seen: set[str] = set()
    for pin in pins:
        one(pin, file)
        if pin["id"] in seen:
            raise Refusal(f"{file}: pins {pin['id']!r} twice")
        seen.add(pin["id"])
    for clash in entries_module.collisions(pins):
        raise Refusal(f"{file}: {clash}")


def one(pin: object, file: str) -> None:
    """One pin, and the shape of each thing it says."""
    if not isinstance(pin, dict):
        raise Refusal(f"{file}: a [[{TABLE}]] entry is not a table")
    named = pin.get("id")
    if not isinstance(named, str) or entries_module.ID.match(named) is None:
        raise Refusal(f"{file}: {named!r} is not a plugin id")
    where = f"{file} ({named})"
    for field in FIELDS:
        if field not in pin:
            raise Refusal(f"{where}: is missing {field!r}")
    for field in sorted(set(pin) - set(FIELDS)):
        raise Refusal(f"{where}: {field} is not something a pin says; it says {', '.join(FIELDS)}")
    try:
        entries_module.origin(pin["origin"], where)
        entries_module.revision(pin["revision"], where)
    except entries_module.Refusal as refused:
        raise Refusal(str(refused)) from refused
    if not isinstance(pin["release"], str) or RELEASE.match(pin["release"]) is None:
        raise Refusal(f"{where}: release {pin['release']!r} is not a tag the train cuts, without its v")
    if not isinstance(pin["manifest"], str) or MANIFEST_DIGEST.match(pin["manifest"]) is None:
        raise Refusal(f"{where}: manifest {pin['manifest']!r} is not {index.DIGEST}<64 hex>")
    fills = pin["fills"]
    if not isinstance(fills, list) or not all(isinstance(it, str) and it for it in fills):
        raise Refusal(f"{where}: fills is not a list of capabilities")
    if len(set(fills)) != len(fills):
        raise Refusal(f"{where}: fills names a capability twice")


def copies(directory: pathlib.Path) -> dict[str, pathlib.Path]:
    """Every copy, by the id its file is named for, or a refusal naming a stray file."""
    if not directory.is_dir():
        return {}
    found: dict[str, pathlib.Path] = {}
    for path in sorted(directory.iterdir()):
        if path.name == PLACEHOLDER:
            continue
        if path.suffix != ".toml" or not path.is_file() or entries_module.ID.match(path.stem) is None:
            raise Refusal(f"bundle/plugins/{path.name} is not a copy of a manifest, named <id>.toml")
        found[path.stem] = path
    return found


def paired(pins: list[dict], held: dict[str, pathlib.Path]) -> list[str]:
    """A copy no pin names, and a pin with no copy."""
    pinned = {pin["id"] for pin in pins}
    return [
        *(f"bundle/plugins/{name}.toml is a copy no pin names" for name in sorted(set(held) - pinned)),
        *(f"{name} is pinned with no copy at bundle/plugins/{name}.toml"
          for name in sorted(pinned - set(held))),
    ]


def contract(spoken: str) -> str:
    """The capability a `speaks` entry names, without its major."""
    return spoken.partition("@")[0]


def listed(table: dict, key: str) -> list:
    """A list a manifest table holds under `key`, or nothing where it holds no list."""
    value = table.get(key)
    return value if isinstance(value, list) else []


def services_of(manifest: dict) -> list[dict]:
    """Every service a manifest declares."""
    return [one for one in listed(manifest, "service") if isinstance(one, dict)]


def adapters_of(services: list[dict]) -> list[dict]:
    """The services that speak a contract: the plugin's adapters."""
    return [one for one in services if listed(one, "speaks")]


def parsed(manifest: bytes) -> dict:
    """A manifest read as TOML, or a refusal."""
    try:
        return tomllib.loads(manifest.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as broken:
        raise Refusal(f"the manifest is not readable as TOML: {broken}") from broken


def held_to_pin(pin: dict, copy: bytes) -> list[str]:
    """Everything a copy has to say for its pin that needs no fetch."""
    said = []
    if index.digest(copy) != pin["manifest"]:
        said.append(f"the copy's digest is {index.digest(copy)}, not the pinned {pin['manifest']}")
    try:
        manifest = parsed(copy)
    except Refusal as refused:
        return [*said, str(refused)]

    plugin = manifest.get("plugin")
    declared = plugin.get("id") if isinstance(plugin, dict) else None
    if declared != pin["id"]:
        said.append(f"the copy declares [plugin].id {declared!r}, not {pin['id']!r}")

    services = services_of(manifest)
    adapters = adapters_of(services)
    if not adapters:
        said.append("the copy declares no adapter service, so nothing in it is tagged at the pinned release")
    for adapter in adapters:
        if adapter.get("tag") != pin["release"]:
            said.append(
                f"the adapter service {adapter.get('id')!r} is tagged {adapter.get('tag')!r}, "
                f"not the pinned release {pin['release']!r}"
            )

    filled = {name for one in services for name in listed(one, "provides")}
    filled |= {contract(name) for one in adapters for name in listed(one, "speaks") if isinstance(name, str)}
    said += [
        f"fills {name!r}, which no service of the copy provides or speaks"
        for name in pin["fills"]
        if name not in filled
    ]
    return said


def on_main(origin: str, revision: str) -> str | None:
    """Why `revision` is not on the origin's default branch, or nothing where it is.

    Only the default branch's commits are fetched, without their trees, and the
    revision has to be among their ancestry: fetching the revision itself proves
    nothing, because a forge serves a fork's commit through the origin's address.
    """
    with tempfile.TemporaryDirectory() as box:
        steps = (
            ("git", "init", "--quiet"),
            ("git", "remote", "add", "origin", origin),
            ("git", "-c", "core.hooksPath=/dev/null", "fetch", "--quiet", "--filter=tree:0",
             "--no-tags", "origin", "HEAD"),
        )
        for step in steps:
            done = check.ran(*step, at=pathlib.Path(box))
            if done.returncode != 0:
                said = (done.stderr or done.stdout).strip().splitlines()
                return f"its default branch could not be fetched: {said[-1] if said else 'no output'}"
        held = check.ran("git", "merge-base", "--is-ancestor", revision, "FETCH_HEAD", at=pathlib.Path(box))
    if held.returncode != 0:
        return f"{revision[:12]} is not on the origin's default branch"
    return None


def fetched(pin: dict, revision: str, into: pathlib.Path) -> bytes:
    """The manifest at `revision` of the pin's origin, fetched as data into `into`."""
    why = check.fetched(pin["origin"], revision, into)
    if why is not None:
        raise Refusal(f"{pin['id']} at {revision[:12]} could not be fetched: {why}")
    why = on_main(pin["origin"], revision)
    if why is not None:
        raise Refusal(f"{pin['id']}: {why}")
    theirs = into / index.MANIFEST
    if not theirs.is_file():
        raise Refusal(f"{pin['id']} at {revision[:12]} has no {index.MANIFEST} at its root")
    return theirs.read_bytes()


def held_to_origin(pin: dict, copy: bytes) -> tuple[bool, list[str]]:
    """The copy against the origin's manifest at the pinned revision, and that revision
    against everything `check.py` holds a registration to."""
    with tempfile.TemporaryDirectory() as box:
        source = pathlib.Path(box) / "source"
        try:
            theirs = fetched(pin, pin["revision"], source)
        except Refusal as refused:
            return False, [str(refused)]
        if theirs != copy:
            return False, [f"the copy differs from {index.MANIFEST} at the pinned revision"]
        holds, said = check.holds(source)
        return holds, ["the copy is the origin's manifest at the pinned revision", *said]


def released(manifest: bytes) -> str:
    """The release a manifest's adapter services are tagged at, or a refusal."""
    tags = {one.get("tag") for one in adapters_of(services_of(parsed(manifest)))}
    if len(tags) != 1:
        raise Refusal(f"the manifest's adapter services are tagged {sorted(map(str, tags))}, not at one release")
    tag = tags.pop()
    if not isinstance(tag, str) or RELEASE.match(tag) is None:
        raise Refusal(f"the adapter service is tagged {tag!r}, which is not a release the train cuts")
    return tag


def moved(pin: dict, revision: str, manifest: bytes) -> dict:
    """The pin at `revision`, whose manifest is `manifest`, or a refusal naming why it cannot be."""
    entries_module.revision(revision, pin["id"])
    to = {**pin, "release": released(manifest), "revision": revision, "manifest": index.digest(manifest)}
    said = held_to_pin(to, manifest)
    if said:
        raise Refusal(f"{pin['id']} at {revision[:12]}: {'; '.join(said)}")
    return to


def wanted(asked: tuple[str, str], carried: list[dict], pins: list[dict]) -> list[tuple[str, str]]:
    """Each (id, revision) to move to: the carried pins this bundle holds elsewhere, then the one asked."""
    here = {pin["id"]: pin["revision"] for pin in pins}
    moves = [(one["id"], one["revision"]) for one in carried
             if one["id"] in here and one["id"] != asked[0] and one["revision"] != here[one["id"]]]
    return [*moves, asked]


def bound(pins: list[dict], name: str, origin: str) -> None:
    """Refuse a move asked for by any repository but the one the bundle pins for `name`."""
    pinned = {pin["id"]: pin["origin"] for pin in pins}
    if name not in pinned:
        raise Refusal(
            f"the bundle pins no {name!r}; a plugin enters it through a person's pull request, "
            "which says what it fills"
        )
    if entries_module.repository(origin) != entries_module.repository(pinned[name]):
        raise Refusal(f"{origin} asked to move {name!r}, which the bundle pins from {pinned[name]}")


def applied(
    asked: tuple[str, str],
    origin: str,
    carry: str | None,
    bundle: pathlib.Path = BUNDLE,
    held: pathlib.Path = COPIES,
) -> list[dict]:
    """Move the pins and write the bundle and the copies, returning what moved."""
    entries_module.revision(asked[1], asked[0])
    text = bundle.read_text(encoding="utf-8")
    pins = read(text)
    bound(pins, asked[0], origin)
    carried = read(carry, "the rolling branch's bundle") if carry is not None else []
    by_id = {pin["id"]: pin for pin in pins}
    moves = []
    for name, revision in wanted(asked, carried, pins):
        was = by_id[name]
        with tempfile.TemporaryDirectory() as box:
            manifest = fetched(was, revision, pathlib.Path(box) / "source")
        now = moved(was, revision, manifest)
        by_id[name] = now
        (held / f"{name}.toml").write_bytes(manifest)
        if now != was:
            moves.append({"id": name, "from": was, "to": now})
    start = PINS_START.search(text)
    bundle.write_text(text[: start.start()] + rendered(list(by_id.values())), encoding="utf-8")
    return moves


def apply(asked: tuple[str, str], origin: str, carry: bool) -> int:
    """The train's move, printed as JSON, with the rolling branch's bundle on stdin where carried.

    A refusal goes to stderr, so the JSON a caller keeps is never a refusal."""
    try:
        moves = applied(asked, origin, sys.stdin.read() if carry else None)
    except (Refusal, entries_module.Refusal, OSError) as refused:
        print(f"::error::{refused}", file=sys.stderr)
        return 1
    print(json.dumps({"moves": moves}, indent=2))
    return 0


def holds(pin: dict, copy: bytes) -> bool:
    """One pin and its copy, held to everything, and said."""
    said = held_to_pin(pin, copy)
    held = not said
    if held:
        held, said = held_to_origin(pin, copy)
    print(f"  {'ok  ' if held else 'FAIL'} {pin['id']} {pin['release']} @ {pin['revision'][:12]}")
    for line in said:
        print(f"         {line}")
    if not held:
        print(f"::error::{pin['id']} is not a pin the bundle can carry")
    return held


def checked() -> int:
    """The bundle in this checkout, held to its origins."""
    try:
        pins = read(BUNDLE.read_text(encoding="utf-8"))
        held = copies(COPIES)
    except (Refusal, OSError) as refused:
        print(f"::error::{refused}")
        return 1
    unpaired = paired(pins, held)
    for problem in unpaired:
        print(f"::error::{problem}")
    if unpaired:
        return 1
    if not pins:
        print("The bundle pins no first-party plugin yet, so there is no copy to hold to an origin.")
        return 0
    try:
        version = check.a_reader_is_here()
    except check.Unaskable as unasked:
        print(f"::error::{unasked}")
        return 2
    print(f"Asked of lemonfiber {version}, the release this catalogue targets.\n")
    refused = sum(not holds(pin, held[pin["id"]].read_bytes()) for pin in pins)
    print(f"\n{len(pins) - refused} of {len(pins)} pinned plugins hold.")
    return 1 if refused else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true",
                        help="prove each rule refuses the shape it exists to refuse")
    parser.add_argument("--apply", nargs=2, metavar=("ID", "REVISION"),
                        help="move a pinned plugin to the revision its pin pull request merged")
    parser.add_argument("--origin", metavar="URL",
                        help="with --apply: the repository asking, which the bundle pins for ID")
    parser.add_argument("--carry", action="store_true",
                        help="with --apply: first move each pin the bundle on stdin holds elsewhere")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if bool(args.apply) != bool(args.origin) or (args.carry and not args.apply):
        print("::error::--apply takes --origin, and --origin and --carry are part of --apply")
        return 2
    if args.apply:
        return apply(tuple(args.apply), args.origin, args.carry)
    return checked()


EMPTY = """# commentary

schema = 1

plugin = []
"""

PIN = {
    "id": "jellyfin",
    "origin": "https://github.com/lemonfiber/plugin-jellyfin",
    "release": "0.18.0",
    "revision": "0123456789abcdef0123456789abcdef01234567",
    "manifest": index.DIGEST + "0" * 64,
    "fills": ["media.serve"],
}

COPY = b"""schema_version = 1

[plugin]
id = "jellyfin"

[[service]]
id = "jellyfin"
tag = "10.10.7"
provides = ["media.serve"]

[[service]]
id = "adapter"
tag = "0.18.0"
speaks = ["media.serve@1", "identity.source@1"]
fronts = "jellyfin"
"""


def ancestry() -> tuple[str | None, str | None]:
    """`on_main` against a repository whose default branch holds one commit and whose
    other branch holds another, the way a fork's commit is served through its parent."""
    with tempfile.TemporaryDirectory() as box:
        origin = pathlib.Path(box)
        git = ("git", "-c", "user.name=self-test", "-c", "user.email=self-test@invalid",
               "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null")
        check.ran("git", "init", "--quiet", "--initial-branch=main", at=origin)
        check.ran(*git, "commit", "--quiet", "--allow-empty", "-m", "main", at=origin)
        held = check.ran("git", "rev-parse", "HEAD", at=origin).stdout.strip()
        check.ran("git", "checkout", "--quiet", "-b", "fork", at=origin)
        check.ran(*git, "commit", "--quiet", "--allow-empty", "-m", "fork", at=origin)
        forked = check.ran("git", "rev-parse", "HEAD", at=origin).stdout.strip()
        check.ran("git", "checkout", "--quiet", "main", at=origin)
        return on_main(str(origin), held), on_main(str(origin), forked)


#: What every bundle the self-test writes opens with.
OPENING = f"schema = {SCHEMA}\n\n"

OTHER = {**PIN, "id": "komga", "origin": "https://github.com/lemonfiber/plugin-komga"}

#: One self-test case: what it shows, what it should come to, and what it came to.
Case = tuple[str, bool, bool]


def bundle_of(*pins: dict) -> str:
    return OPENING + rendered(list(pins))


def refuses(call, *refusals: type[Exception]) -> bool:
    """Whether `call` refuses, with one of `refusals` or a bundle `Refusal`."""
    try:
        call()
    except (Refusal, *refusals):
        return True
    return False


def shapes() -> list[Case]:
    """`read`, against each shape of bundle it exists to refuse."""
    good = bundle_of(PIN)
    refused = [
        ("a schema this does not read refused", good.replace("schema = 1", "schema = 2")),
        ("a bundle naming no list refused", "schema = 1\n"),
        ("a key a bundle does not say refused", "forms = []\n" + good),
        ("a pin missing a field refused", good.replace('fills    = ["media.serve"]\n', "")),
        ("a field a pin does not say refused", good + 'note     = "no"\n'),
        ("an id that is not one refused", good.replace('"jellyfin"', '"Jellyfin"')),
        ("an ssh origin refused", good.replace("https://github.com/", "ssh://git@github.com/")),
        ("a branch where a revision belongs refused", good.replace(f'"{PIN["revision"]}"', '"main"')),
        ("a release carrying its v refused", good.replace('"0.18.0"', '"v0.18.0"')),
        ("a digest without its algorithm refused", good.replace(index.DIGEST, "")),
        ("fills that is not a list refused", good.replace('["media.serve"]', '"media.serve"')),
        ("a capability filled twice refused", good.replace('["media.serve"]', '["media.serve", "media.serve"]')),
        ("one plugin pinned twice refused", OPENING + rendered([PIN]) + "\n" + rendered([PIN])),
        ("one origin pinned under two ids refused", bundle_of(PIN, {**OTHER, "origin": PIN["origin"]})),
        ("pins out of id order refused", OPENING + rendered([OTHER]) + "\n" + rendered([PIN])),
        ("a pin written another way refused", good.replace("id       =", "id =")),
    ]
    return [
        ("an empty bundle is read", False, refuses(lambda: read(EMPTY))),
        ("a bundle of two pins is read", False, refuses(lambda: read(bundle_of(PIN, OTHER)))),
        ("the bundle writes back what it reads", True, OPENING + rendered(read(good)) == good),
        *((what, True, refuses(lambda text=text: read(text))) for what, text in refused),
    ]


def pairs() -> list[Case]:
    """`copies` and `paired`, over a directory of copies."""
    with tempfile.TemporaryDirectory() as box:
        directory = pathlib.Path(box)
        (directory / PLACEHOLDER).touch()
        (directory / "jellyfin.toml").write_bytes(COPY)
        found = copies(directory)
        said = [
            ("the placeholder is not a copy", True, set(found) == {"jellyfin"}),
            ("a pin and its copy pair", True, not paired([PIN], found)),
            ("a copy no pin names refused", True, bool(paired([], found))),
            ("a pin with no copy refused", True, bool(paired([PIN, OTHER], found))),
        ]
        (directory / "notes.md").write_text("no", encoding="utf-8")
        return [*said, ("a file that is not a copy refused", True, refuses(lambda: copies(directory)))]


def held_copies() -> list[Case]:
    """`held_to_pin`, against each way a copy can fail to say what its pin says."""
    pinned = {**PIN, "manifest": index.digest(COPY)}
    changed = [
        ("an adapter tagged at another release refused", COPY.replace(b'"0.18.0"', b'"0.17.0"')),
        ("a copy with no adapter service refused",
         COPY.replace(b'speaks = ["media.serve@1", "identity.source@1"]\n', b"")),
        ("a copy declaring another id refused",
         COPY.replace(b'id = "jellyfin"\n\n[[service]]', b'id = "emby"\n\n[[service]]', 1)),
        ("a copy that is not TOML refused", COPY + b"[["),
    ]
    return [
        ("a copy that says what its pin says holds", True, not held_to_pin(pinned, COPY)),
        ("a copy whose digest is not its pin's refused", True, bool(held_to_pin(PIN, COPY))),
        *((what, True, bool(held_to_pin({**PIN, "manifest": index.digest(text)}, text))) for what, text in changed),
        ("a capability spoken by the adapter may be filled", True,
         not held_to_pin({**pinned, "fills": ["identity.source"]}, COPY)),
        ("a capability the copy neither provides nor speaks refused", True,
         bool(held_to_pin({**pinned, "fills": ["request.intake"]}, COPY))),
    ]


def moves() -> list[Case]:
    """`released`, `moved` and `wanted`: what a move takes, keeps and carries."""
    to = moved(PIN, "f" * 40, COPY)
    rolling = [{**PIN, "revision": "a" * 40}, {**OTHER, "revision": "b" * 40}]
    unreleased = [
        ("a manifest with no adapter has no release", COPY.replace(b"speaks", b"listens")),
        ("adapters at two releases have no release",
         COPY + b'\n[[service]]\nid = "second"\ntag = "0.17.0"\nspeaks = ["media.serve@1"]\n'),
        ("an adapter tagged with its v has no release", COPY.replace(b'"0.18.0"', b'"v0.18.0"')),
    ]
    return [
        ("the release is the adapter's tag", True, released(COPY) == "0.18.0"),
        *((what, True, refuses(lambda text=text: released(text))) for what, text in unreleased),
        ("a move takes the revision, the release and the digest", True,
         (to["revision"], to["release"], to["manifest"]) == ("f" * 40, "0.18.0", index.digest(COPY))),
        ("a move keeps what a person chose", True, (to["origin"], to["fills"]) == (PIN["origin"], PIN["fills"])),
        ("a move to a branch refused", True, refuses(lambda: moved(PIN, "main", COPY), entries_module.Refusal)),
        ("a move to a manifest that cannot fill the pin refused", True,
         refuses(lambda: moved({**PIN, "fills": ["request.intake"]}, "f" * 40, COPY))),
        ("the rolling branch's other moves are carried, the one asked last", True,
         wanted(("komga", "c" * 40), rolling, [PIN, OTHER]) == [("jellyfin", "a" * 40), ("komga", "c" * 40)]),
        ("a pin the rolling branch holds where main does is not moved again", True,
         wanted(("komga", "c" * 40), [PIN], [PIN, OTHER]) == [("komga", "c" * 40)]),
        ("a pin main no longer holds is not carried", True,
         wanted(("jellyfin", "c" * 40), rolling, [PIN]) == [("jellyfin", "c" * 40)]),
    ]


def bindings() -> list[Case]:
    """`bound`, `applied` and `on_main`: who may move a pin, and to what."""
    good = bundle_of(PIN)
    with tempfile.TemporaryDirectory() as box:
        directory = pathlib.Path(box)
        (directory / BUNDLE_FILE).write_text(good, encoding="utf-8")
        elsewhere = refuses(lambda: applied(("jellyfin", "f" * 40), OTHER["origin"], None,
                                            directory / BUNDLE_FILE, directory))
        untouched = (directory / BUNDLE_FILE).read_text(encoding="utf-8") == good
    on, off = ancestry()
    return [
        ("a move asked for by another repository refused, the bundle untouched", True, elsewhere and untouched),
        ("a move asked for by the pinned repository is bound to it", False,
         refuses(lambda: bound([PIN], "jellyfin", PIN["origin"] + ".git"))),
        ("a move of a plugin the bundle does not pin refused", True,
         refuses(lambda: bound([PIN], "komga", OTHER["origin"]))),
        ("a revision on the origin's default branch is on it", True, on is None),
        ("a revision only on another branch refused", True, off is not None),
    ]


def self_test() -> int:
    """Each rule, against the shape it exists to refuse."""
    failures = 0
    for what, expected, got in (*shapes(), *pairs(), *held_copies(), *moves(), *bindings()):
        print(f"  {'ok  ' if expected == got else 'FAIL'} {what}")
        failures += expected != got
    print("\nself-test passed." if not failures else f"\n{failures} rule(s) did not refuse.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

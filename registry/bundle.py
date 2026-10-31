#!/usr/bin/env python3
"""Hold the default bundle to the bundle contract and to the origins it pins (REPO-R91, REPO-R92).

`bundle/bundle.toml` is read at `schema = 1` or `schema = 2`, and any other schema is
refused naming both (ARCH-R265).

At schema 1 the bundle pins first-party plugins alone, each at a release, a revision
and the digest of its manifest there, and `bundle/plugins/<id>.toml` is that manifest,
copied byte for byte. Each copy's adapter service is tagged at the pinned release.

At schema 2 the bundle also declares the stack's `[[profile]]`, `[[form]]`, `[[wiring]]`
and `[[removed]]`, and may pin `[fence]`, the image a fenced service runs behind, by its
registry path, tag and digest (ARCH-R363), and each `[[plugin]]` names its revision, the digests of its manifest
and of its tree (ARCH-R267), what it fills, whether lemonfiber assembles or installs it,
its profile, the upstream's last release, and the release that tagged it where it
builds an image (ARCH-R266, OPS-R86). `bundle/plugins/<id>/` is the plugin's tree at
the pinned revision, each file at its path in the plugin's repository. The ids,
published ports and proxy hostnames every pinned plugin declares, and every hostname
the proxy's configuration in its copy answers on, are reserved, and none is taken
twice (ARCH-R269).

Every copy is fetched again from its origin at the pinned revision and compared, the
revision has to be on its origin's default branch, and it is held to what `check.py`
holds a registration to (REPO-R61). A revision whose service of the plugin's id still
runs the image its `Dockerfile` builds on, at any digest, rather than
`ghcr.io/lemonfiber/<id>`, is held by no pin and moved to by no apply: it ships nothing
until the first pin of the image it builds merges (ARCH-R285). Nothing from a pinned
repository is executed (REPO-R62).

`--offline` holds the bundle and every copy to the contract with nothing fetched. The
train runs it on the files it is about to commit.

`--apply ID REVISION --origin URL` is the train's half (OPS-R86): it moves a pinned
plugin to the revision its pin pull request merged and copies what that revision holds.
At schema 1 the release is the adapter service's tag; at schema 2 it is the tag of every
image the plugin builds, and a plugin that builds no image is moved by a person's pull
request instead. The origin is the repository asking, and has to be the one the bundle
pins for that id. `--carry` first moves every pin that the bundle on stdin holds at
another revision than this one, which is how the one rolling pull request keeps the
moves it already carries. It prints the moves as JSON.

Run:  python3 registry/bundle.py
      python3 registry/bundle.py --offline
      python3 registry/bundle.py --apply jellyfin <commit> --origin <url> [--carry < bundle.toml]
      python3 registry/bundle.py --self-test
Needs: git, the network to fetch the release and the pinned revisions, and cargo where
`targets.toml` names a commit.
Exit 0 = the bundle holds or was moved, 1 = it does not or could not be, 2 = this
could not be asked.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import pathlib
import re
import shutil
import sys
import tempfile
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import check  # noqa: E402
import entry as entries_module  # noqa: E402
import index  # noqa: E402
import parts  # noqa: E402
import tree  # noqa: E402

BUNDLE_FILE = "bundle.toml"
BUNDLE = ROOT / "bundle" / BUNDLE_FILE
COPIES = ROOT / "bundle" / "plugins"

SCHEMAS = (1, 2)

TABLE = "plugin"

STACK_TABLES = ("profile", "form", "wiring", "removed")

FIELDS = {
    1: ("id", "origin", "release", "revision", "manifest", "fills"),
    2: ("id", "origin", "release", "revision", "manifest", "tree", "fills", "stage", "profile", "last_release"),
}

OPTIONAL = {1: (), 2: ("release",)}

SHAPES = {
    "profile": (("id", "name", "description"), ("protocol",)),
    "form": (("id", "name", "description", "profiles"), ("composable",)),
    "removed": (("id", "removed_in", "reason"), ("replaced_by",)),
    "wiring": (("by", "why"), ("asks", "filled_by", "to")),
}

#: The images the bundle pins apart from its parts, each by the table named for its
#: service and the registry path it is published to (ARCH-R363). A train tag moves one.
IMAGES = {"fence": "ghcr.io/lemonfiber/fence"}

IMAGE_FIELDS = ("image", "tag", "digest")

IMAGE_TAG = re.compile(r"\A(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?\Z")
IMAGE_DIGEST = re.compile(r"\Asha256:[0-9a-f]{64}\Z")

STAGES = (parts.ASSEMBLED, "installed")
PROTOCOLS = ("usenet", "torrent")

PLACEHOLDER = ".gitkeep"

RELEASE = re.compile(r"\A(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")
DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

PINS_START = re.compile(rf"^(?:\[\[{TABLE}\]\]|{TABLE}\s*=)", re.MULTILINE)


class Refusal(Exception):
    """The bundle, refused, with every reason."""

    def __init__(self, *problems: str) -> None:
        super().__init__("\n".join(problems))
        self.problems = list(problems)


@dataclasses.dataclass
class Bundle:
    """A bundle as read: its schema, its pins and, at schema 2, the stack's own tables."""

    schema: int
    pins: list[dict]
    tables: dict[str, list[dict]] = dataclasses.field(default_factory=dict)
    images: dict[str, dict] = dataclasses.field(default_factory=dict)

    def table(self, name: str) -> list[dict]:
        return self.tables.get(name, [])


def today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()


def quoted(value: str) -> str:
    """A TOML basic string."""
    return json.dumps(value)


def rendered(pins: list[dict], schema: int = 1) -> str:
    """The pins as the bundle writes them: one table each, ordered by id, keys aligned."""
    if not pins:
        return f"{TABLE} = []\n" if schema == 1 else ""
    fields = FIELDS[schema]
    width = max(len(field) for field in fields)
    tables = []
    for pin in sorted(pins, key=lambda one: one["id"]):
        lines = [f"[[{TABLE}]]"]
        for field in fields:
            if field not in pin:
                continue
            value = pin[field]
            said = (
                "[" + ", ".join(quoted(one) for one in value) + "]"
                if isinstance(value, list)
                else quoted(value)
            )
            lines.append(f"{field:<{width}} = {said}")
        tables.append("\n".join(lines) + "\n")
    return "\n".join(tables)


def read(text: str, file: str = BUNDLE_FILE) -> Bundle:
    """The bundle a text declares, or a refusal naming everything wrong with it."""
    try:
        held = tomllib.loads(text)
    except tomllib.TOMLDecodeError as broken:
        raise Refusal(f"{file}: not readable as TOML: {broken}") from broken
    schema = held.get("schema")
    if isinstance(schema, bool) or schema not in SCHEMAS:
        raise Refusal(f"{file}: schema is {schema!r}, and this catalogue reads 1 and 2")
    if schema == 1 and TABLE not in held:
        raise Refusal(f"{file}: names no [[{TABLE}]] list, not even an empty one")
    tables, problems = tables_of(held, schema, file)
    images, pinned_images = images_of(held, schema, file)
    problems += pinned_images
    pins = tables.pop(TABLE)
    pinned = pin_problems(pins, schema, file)
    problems += pinned
    if schema == 2:
        problems += stack_problems(tables, pins, file)
    if not pinned:
        problems += written_problems(text, pins, schema, file)
    if problems:
        raise Refusal(*problems)
    return Bundle(schema, pins, tables, images)


def images_of(held: dict, schema: int, file: str) -> tuple[dict[str, dict], list[str]]:
    """Each image the bundle pins apart from its parts, and everything wrong with each."""
    if schema != 2:
        return {}, []
    images, problems = {}, []
    for name, published in IMAGES.items():
        if name not in held:
            continue
        pin = held[name]
        where = f"{file} [{name}]"
        if not isinstance(pin, dict):
            problems.append(f"{where}: is not a table")
            continue
        missing = [field for field in IMAGE_FIELDS if field not in pin]
        extra = sorted(set(pin) - set(IMAGE_FIELDS))
        problems += [f"{where}: is missing {field!r}" for field in missing]
        problems += [f"{where}: {field} is not something it says; it says {', '.join(IMAGE_FIELDS)}"
                     for field in extra]
        if missing or extra:
            continue
        if pin["image"] != published:
            problems.append(f"{where}: image is {pin['image']!r}, and {name} is published as {published}")
        if not isinstance(pin["tag"], str) or not IMAGE_TAG.match(pin["tag"]):
            problems.append(f"{where}: tag {pin['tag']!r} is not a version the train tags, without its v")
        if not isinstance(pin["digest"], str) or not IMAGE_DIGEST.match(pin["digest"]):
            problems.append(f"{where}: digest {pin['digest']!r} is not sha256:<64 hex>")
        images[name] = pin
    return images, problems


def tables_of(held: dict, schema: int, file: str) -> tuple[dict[str, list[dict]], list[str]]:
    """Each array of tables a bundle at `schema` says, absent ones empty, and every key it does not say."""
    names = (TABLE, *STACK_TABLES) if schema == 2 else (TABLE,)
    said = (*names, *IMAGES) if schema == 2 else names
    problems = [f"{file}: {key} is not something a bundle at schema {schema} says; it says "
                f"{' and '.join(('schema', *said))}" for key in sorted(set(held) - {"schema", *said})]
    tables = {}
    for name in names:
        value = held.get(name, [])
        if not isinstance(value, list) or not all(isinstance(one, dict) for one in value):
            problems.append(f"{file}: {name} is not a list of [[{name}]] tables")
            value = []
        tables[name] = value
    return tables, problems


def written_problems(text: str, pins: list[dict], schema: int, file: str) -> list[str]:
    """Whether the pins close the file, written as the bundle writes them."""
    found = PINS_START.search(text)
    expected = rendered(pins, schema)
    if not expected and found is None:
        return []
    if found is not None and found.start() == len(text) - len(expected) and text.endswith(expected):
        return []
    return [(
        f"{file}: the pins are not written as the bundle writes them — one [[{TABLE}]] per "
        f"plugin, last in the file, ordered by id, fields in the order {', '.join(FIELDS[schema])} — "
        "so a move would rewrite lines nobody changed"
    )]


def pin_problems(pins: list[dict], schema: int, file: str) -> list[str]:
    """Every pin well formed, and no plugin or origin pinned twice."""
    problems = [problem for pin in pins for problem in one(pin, file, schema)]
    seen: set[str] = set()
    for named in (pin.get("id") for pin in pins if isinstance(pin.get("id"), str)):
        if named in seen:
            problems.append(f"{file}: pins {named!r} twice")
        seen.add(named)
    if not problems:
        problems += [f"{file}: {clash}" for clash in entries_module.collisions(pins)]
    return problems


def one(pin: dict, file: str, schema: int = 1) -> list[str]:
    """One pin, and the shape of each thing it says."""
    named = pin.get("id")
    if not isinstance(named, str) or entries_module.ID.match(named) is None:
        return [f"{file}: {named!r} is not a plugin id"]
    where = f"{file} ({named})"
    fields = FIELDS[schema]
    problems = [f"{where}: is missing {field!r}" for field in fields
                if field not in pin and field not in OPTIONAL[schema]]
    problems += [f"{where}: {field} is not something a pin says; it says {', '.join(fields)}"
                 for field in sorted(set(pin) - set(fields))]
    if problems:
        return problems
    problems = pointer_problems(pin, where) + digest_problems(pin, where, schema) + fills_problems(pin, where)
    return problems + (part_fields(pin, where) if schema == 2 else [])


def pointer_problems(pin: dict, where: str) -> list[str]:
    """Where a pin points: an https origin, a full revision, and a release as the train tags one."""
    problems = []
    try:
        entries_module.origin(pin["origin"], where)
        entries_module.revision(pin["revision"], where)
    except entries_module.Refusal as refused:
        problems.append(str(refused))
    if "release" in pin and (not isinstance(pin["release"], str) or RELEASE.match(pin["release"]) is None):
        problems.append(f"{where}: release {pin['release']!r} is not a tag the train cuts, three numbers without its v")
    return problems


def digest_problems(pin: dict, where: str, schema: int) -> list[str]:
    """Each digest a pin carries, written `sha256:<64 hex>`."""
    return [f"{where}: {field} {pin[field]!r} is not {index.DIGEST}<64 hex>"
            for field in (("manifest",) if schema == 1 else ("manifest", "tree"))
            if not isinstance(pin[field], str) or tree.DIGEST_SHAPE.match(pin[field]) is None]


def fills_problems(pin: dict, where: str) -> list[str]:
    """What a pin fills: a list of capabilities, none twice."""
    fills = pin["fills"]
    if not isinstance(fills, list) or not all(isinstance(it, str) and it for it in fills):
        return [f"{where}: fills is not a list of capabilities"]
    return [f"{where}: fills names a capability twice"] if len(set(fills)) != len(fills) else []


def part_fields(pin: dict, where: str) -> list[str]:
    """What a schema 2 pin adds: its stage, its profile and the upstream's last release."""
    problems = []
    if pin["stage"] not in STAGES:
        problems.append(f"{where}: stage {pin['stage']!r} is not {' or '.join(STAGES)}")
    if not isinstance(pin["profile"], str) or not pin["profile"].strip():
        problems.append(f"{where}: profile is not a profile's id")
    released = pin["last_release"]
    try:
        when = datetime.date.fromisoformat(released) if DATE.match(str(released)) else None
    except ValueError:
        when = None
    if when is None:
        problems.append(f"{where}: last_release {released!r} is not YYYY-MM-DD")
    elif when > today():
        problems.append(f"{where}: last_release {released} is in the future")
    return problems


def shaped(name: str, rows: list[dict], file: str) -> list[str]:
    """Each row of a stack table carries what it must, says nothing else, and says it as text."""
    required, optional = SHAPES[name]
    problems = []
    for number, row in enumerate(rows, 1):
        where = f"{file}: [[{name}]] {row.get('id', row.get('by', f'#{number}'))!r}"
        problems += [f"{where} is missing {field!r}" for field in required if field not in row]
        problems += [
            f"{where}: {field} is not something a [[{name}]] says; it says "
            f"{', '.join((*required, *optional))}"
            for field in sorted(set(row) - {*required, *optional})
        ]
        problems += [
            f"{where}: {field} is not text"
            for field, value in row.items()
            if field in (*required, *optional)
            and field not in ("profiles", "composable")
            and (not isinstance(value, str) or not value.strip())
        ]
    return problems


def unique(name: str, rows: list[dict], file: str) -> list[str]:
    """No id twice within one table."""
    seen: set[str] = set()
    problems = []
    for row in rows:
        if row["id"] in seen:
            problems.append(f"{file}: [[{name}]] {row['id']!r} is declared twice")
        seen.add(row["id"])
    return problems


def stack_problems(tables: dict[str, list[dict]], pins: list[dict], file: str) -> list[str]:
    """The stack's own tables, held to each other and to the pins (ARCH-R265, ARCH-R268)."""
    problems = [problem for name in STACK_TABLES for problem in shaped(name, tables[name], file)]
    if problems:
        return problems
    profiles = {row["id"] for row in tables["profile"]}
    pinned = {pin.get("id") for pin in pins if isinstance(pin.get("id"), str)}
    return [
        *(problem for name in ("profile", "form", "removed") for problem in unique(name, tables[name], file)),
        *protocol_problems(tables["profile"], file),
        *(problem for row in tables["form"] for problem in form_problems(row, profiles, file)),
        *(problem for row in tables["removed"] for problem in removed_problems(row, pinned, file)),
        *wiring_shapes(tables["wiring"], file),
        *(f"{file} ({pin['id']}): profile {pin['profile']!r} is no declared [[profile]]" for pin in pins
          if isinstance(pin.get("id"), str) and isinstance(pin.get("profile"), str) and pin["profile"] not in profiles),
    ]


def protocol_problems(profiles: list[dict], file: str) -> list[str]:
    """Each `protocol` a permitted value, on at most one profile."""
    declaring: dict[str, list[str]] = {}
    for row in (row for row in profiles if "protocol" in row):
        declaring.setdefault(row["protocol"], []).append(row["id"])
    problems = [f"{file}: [[profile]] {row['id']!r}: protocol {row['protocol']!r} is not {' or '.join(PROTOCOLS)}"
                for row in profiles if "protocol" in row and row["protocol"] not in PROTOCOLS]
    return problems + [f"{file}: [[profile]] {' and '.join(map(repr, held))} both declare protocol {protocol!r}"
                       for protocol, held in declaring.items() if len(held) > 1]


def form_problems(row: dict, profiles: set[str], file: str) -> list[str]:
    """A form's closure names declared profiles, and `composable` is true or false."""
    where = f"{file}: [[form]] {row['id']!r}"
    closure = row["profiles"]
    if not isinstance(closure, list) or not all(isinstance(it, str) for it in closure):
        problems = [f"{where}: profiles is not a list of profiles"]
    else:
        problems = [f"{where}: names profile {it!r}, which no [[profile]] declares" for it in closure
                    if it not in profiles]
    if "composable" in row and not isinstance(row["composable"], bool):
        problems.append(f"{where}: composable is not true or false")
    return problems


def removed_problems(row: dict, pinned: set[str], file: str) -> list[str]:
    """A removed service is no pinned plugin, and what replaced it is one."""
    where = f"{file}: [[removed]] {row['id']!r}"
    problems = [f"{where} is a pinned plugin, which the catalogue still carries"] if row["id"] in pinned else []
    if "replaced_by" in row and row["replaced_by"] not in pinned:
        problems.append(f"{where}: replaced_by {row['replaced_by']!r} is no pinned plugin")
    return problems


def wiring_shape(row: dict, where: str) -> list[str]:
    """One wiring: exactly one of `asks` and `to`, `filled_by` with `asks` alone, and never its own `by`."""
    asks, to = "asks" in row, "to" in row
    problems = []
    if asks == to:
        problems.append(f"{where} carries {'both asks and to' if asks else 'neither asks nor to'}; it names one")
    if asks and "filled_by" not in row:
        problems.append(f"{where} asks with no filled_by: an ask belongs in the asker's [[ask]]")
    if "filled_by" in row and not asks:
        problems.append(f"{where} names filled_by without asks")
    if row["by"] in (row.get("to"), row.get("filled_by")):
        problems.append(f"{where} names its own by")
    return problems


def wiring_shapes(rows: list[dict], file: str) -> list[str]:
    """Each wiring a choice of filler or a link by name, and none of them twice (ARCH-R268)."""
    problems = []
    seen: dict[tuple, str] = {}
    for row in rows:
        named = parts.wiring_named(row)
        problems += wiring_shape(row, f"{file}: {named}")
        key = (row["by"], "asks", row["asks"]) if "asks" in row else (row["by"], "to", row.get("to"))
        if key in seen:
            problems.append(f"{file}: {named} repeats {seen[key]}")
        seen.setdefault(key, named)
    return problems


def copy_path(name: str, schema: int) -> str:
    """Where a pin's copy sits, from the catalogue's root."""
    return f"bundle/plugins/{name}.toml" if schema == 1 else f"bundle/plugins/{name}/"


def copies(directory: pathlib.Path, schema: int = 1) -> dict[str, pathlib.Path]:
    """Every copy, by the id it is named for, or a refusal naming a stray entry."""
    if not directory.is_dir():
        return {}
    found: dict[str, pathlib.Path] = {}
    strays = []
    for path in sorted(directory.iterdir()):
        if path.name == PLACEHOLDER:
            continue
        name = path.stem if schema == 1 else path.name
        shaped_right = (
            path.suffix == ".toml" and path.is_file() if schema == 1 else path.is_dir()
        ) and not path.is_symlink()
        if not shaped_right or entries_module.ID.match(name) is None:
            strays.append(f"bundle/plugins/{path.name} is not a copy, named {copy_path('<id>', schema)}")
            continue
        found[name] = path
    if strays:
        raise Refusal(*strays)
    return found


def paired(pins: list[dict], held: dict[str, pathlib.Path], schema: int = 1) -> list[str]:
    """A copy no pin names, and a pin with no copy."""
    pinned = {pin["id"] for pin in pins}
    return [
        *(f"{copy_path(name, schema)} is a copy no pin names" for name in sorted(set(held) - pinned)),
        *(f"{name} is pinned with no copy at {copy_path(name, schema)}" for name in sorted(pinned - set(held))),
    ]


def parsed(manifest: bytes) -> dict:
    """A manifest read as TOML, or a refusal."""
    try:
        return tomllib.loads(manifest.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as broken:
        raise Refusal(f"the manifest is not readable as TOML: {broken}") from broken


def held_to_pin(pin: dict, copy: bytes) -> list[str]:
    """Everything a schema 1 copy has to say for its pin that needs no fetch."""
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

    services = parts.services_of(manifest)
    adapters = parts.adapters_of(services)
    if not adapters:
        said.append("the copy declares no adapter service, so nothing in it is tagged at the pinned release")
    for adapter in adapters:
        if adapter.get("tag") != pin["release"]:
            said.append(
                f"the adapter service {adapter.get('id')!r} is tagged {adapter.get('tag')!r}, "
                f"not the pinned release {pin['release']!r}"
            )
    filled = parts.filled_by(services)
    said += [
        f"fills {name!r}, which no service of the copy provides or speaks"
        for name in pin["fills"]
        if name not in filled
    ]
    return said


def held_to_tree(pin: dict, root: pathlib.Path) -> tuple[list[str], dict | None]:
    """Everything a schema 2 copy has to say for its pin that needs no fetch, and its manifest."""
    manifest_path = root / tree.MANIFEST
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return [f"the copy holds no {tree.MANIFEST}"], None
    copy = manifest_path.read_bytes()
    said = []
    if index.digest(copy) != pin["manifest"]:
        said.append(f"the copy's manifest digest is {index.digest(copy)}, not the pinned {pin['manifest']}")
    try:
        manifest = parsed(copy)
    except Refusal as refused:
        return [*said, str(refused)], None
    try:
        files = tree.read(root, manifest)
    except tree.Unreadable as unread:
        return [*said, *unread.problems], manifest
    if tree.digest(files) != pin["tree"]:
        said.append(f"the copy's tree digest is {tree.digest(files)}, not the pinned {pin['tree']}")
    everything, refused = tree.walked(root, ".")
    paths = {path for path, _ in files}
    said += [f"the copy holds {path}, which is not in the plugin's tree" for path in everything if path not in paths]
    return [*said, *refused], manifest


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


def fetched_tree(pin: dict, revision: str, into: pathlib.Path) -> pathlib.Path:
    """The pin's origin at `revision`, fetched as data into `into`, on its default branch."""
    why = check.fetched(pin["origin"], revision, into)
    if why is not None:
        raise Refusal(f"{pin['id']} at {revision[:12]} could not be fetched: {why}")
    why = on_main(pin["origin"], revision)
    if why is not None:
        raise Refusal(f"{pin['id']}: {why}")
    if not (into / index.MANIFEST).is_file():
        raise Refusal(f"{pin['id']} at {revision[:12]} has no {index.MANIFEST} at its root")
    return into


def differing(ours: list[tuple[str, bytes]], theirs: list[tuple[str, bytes]]) -> list[str]:
    """Every path at which a copy's tree and its origin's differ."""
    mine, origin = dict(ours), dict(theirs)
    return [
        f"{path} is in the copy and not in the origin's tree" if path not in origin
        else f"{path} is in the origin's tree and not in the copy" if path not in mine
        else f"{path} differs from the origin's"
        for path in sorted({*mine, *origin}, key=lambda one: one.encode("utf-8"))
        if mine.get(path) != origin.get(path)
    ]


def held_to_origin(pin: dict, copy: bytes | pathlib.Path) -> tuple[bool, list[str]]:
    """The copy against the origin at the pinned revision, and that revision against
    everything `check.py` holds a registration to."""
    with tempfile.TemporaryDirectory() as box:
        source = pathlib.Path(box) / "source"
        try:
            fetched_tree(pin, pin["revision"], source)
        except Refusal as refused:
            return False, [str(refused)]
        if isinstance(copy, bytes):
            if (source / index.MANIFEST).read_bytes() != copy:
                return False, [f"the copy differs from {index.MANIFEST} at the pinned revision"]
            holds, said = check.holds(source)
            return holds, ["the copy is the origin's manifest at the pinned revision", *said]
        try:
            theirs = tree.read(source, tree.manifest_of(source))
            ours = tree.read(copy, tree.manifest_of(copy))
        except tree.Unreadable as unread:
            return False, unread.problems
        differs = differing(ours, theirs)
        if differs:
            return False, differs
        unshipped = parts.unshipped_problems(pin["id"], parsed((source / tree.MANIFEST).read_bytes()), source)
        if unshipped:
            return False, unshipped
        holds, said = check.holds(source, [path for path, _ in theirs if path != tree.MANIFEST])
        return holds, ["the copy is the origin's tree at the pinned revision", *said]


def released(manifest: bytes, schema: int = 1) -> str:
    """The release a manifest's adapter services (schema 1) or built images (schema 2) are tagged at."""
    services = parts.services_of(parsed(manifest))
    tagged = parts.adapters_of(services) if schema == 1 else parts.built_of(services)
    tags = {str(one.get("tag")) for one in tagged}
    what = "adapter services" if schema == 1 else "images it builds"
    if not tagged:
        raise Refusal(
            f"the manifest has no {what}, so nothing in it is tagged at a release"
            + ("" if schema == 1 else "; a plugin that builds none is moved by a person's pull request")
        )
    if len(tags) != 1:
        raise Refusal(f"the manifest's {what} are tagged {sorted(tags)}, not at one release")
    tag = tags.pop()
    if RELEASE.match(tag) is None:
        raise Refusal(f"the manifest's {what} are tagged {tag!r}, which is not a release the train cuts")
    return tag


def moved(pin: dict, revision: str, manifest: bytes) -> dict:
    """A schema 1 pin at `revision`, whose manifest is `manifest`, or a refusal naming why it cannot be."""
    entries_module.revision(revision, pin["id"])
    to = {**pin, "release": released(manifest), "revision": revision, "manifest": index.digest(manifest)}
    said = held_to_pin(to, manifest)
    if said:
        raise Refusal(f"{pin['id']} at {revision[:12]}: {'; '.join(said)}")
    return to


def moved_tree(pin: dict, revision: str, source: pathlib.Path, bundle: Bundle) -> tuple[dict, list]:
    """A schema 2 pin at `revision`, whose tree is in `source`, with that tree, or a refusal."""
    entries_module.revision(revision, pin["id"])
    manifest = (source / tree.MANIFEST).read_bytes()
    release = released(manifest, 2)
    try:
        files = tree.read(source, parsed(manifest))
    except tree.Unreadable as unread:
        raise Refusal(f"{pin['id']} at {revision[:12]}: {'; '.join(unread.problems)}") from unread
    to = {
        **pin,
        "release": release,
        "revision": revision,
        "manifest": index.digest(manifest),
        "tree": tree.digest(files),
    }
    said = [*parts.part_problems(to, parsed(manifest), bundle.table("form")),
            *parts.unshipped_problems(pin["id"], parsed(manifest), source)]
    if said:
        raise Refusal(f"{pin['id']} at {revision[:12]}: {'; '.join(said)}")
    return to, files


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


def written_tree(directory: pathlib.Path, files: list[tuple[str, bytes]]) -> None:
    """Replace a copy with `files`, each at its path."""
    if directory.exists():
        shutil.rmtree(directory)
    for path, content in files:
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        (directory / path).write_bytes(content)


def applied(
    asked: tuple[str, str],
    origin: str,
    carry: str | None,
    bundle_file: pathlib.Path = BUNDLE,
    held: pathlib.Path = COPIES,
) -> list[dict]:
    """Move the pins and write the bundle and the copies, returning what moved."""
    entries_module.revision(asked[1], asked[0])
    text = bundle_file.read_text(encoding="utf-8")
    bundle = read(text)
    bound(bundle.pins, asked[0], origin)
    carried = read(carry, "the rolling branch's bundle").pins if carry is not None else []
    by_id = {pin["id"]: pin for pin in bundle.pins}
    moves = []
    for name, revision in wanted(asked, carried, bundle.pins):
        was = by_id[name]
        with tempfile.TemporaryDirectory() as box:
            source = fetched_tree(was, revision, pathlib.Path(box) / "source")
            if bundle.schema == 1:
                manifest = (source / index.MANIFEST).read_bytes()
                now = moved(was, revision, manifest)
                (held / f"{name}.toml").write_bytes(manifest)
            else:
                now, files = moved_tree(was, revision, source, bundle)
                written_tree(held / name, files)
        by_id[name] = now
        if now != was:
            moves.append({"id": name, "from": was, "to": now})
    start = PINS_START.search(text)
    bundle_file.write_text(text[: start.start()] + rendered(list(by_id.values()), bundle.schema), encoding="utf-8")
    return moves


def apply(asked: tuple[str, str], origin: str, carry: bool) -> int:
    """The train's move, printed as JSON, with the rolling branch's bundle on stdin where carried.

    A refusal goes to stderr, so the JSON a caller keeps is never a refusal."""
    try:
        moves = applied(asked, origin, sys.stdin.read() if carry else None)
    except (Refusal, entries_module.Refusal, OSError) as refused:
        for line in str(refused).splitlines():
            print(f"::error::{line}", file=sys.stderr)
        return 1
    print(json.dumps({"moves": moves}, indent=2))
    return 0


def said_pin(pin: dict) -> str:
    """A pin in one line: its id, its release where it names one, and its revision."""
    return f"{pin['id']} {pin.get('release', 'unreleased')} @ {pin['revision'][:12]}"


def holds(pin: dict, copy: bytes | pathlib.Path, offline_said: list[str]) -> bool:
    """One pin and its copy, held to everything, and said."""
    said = offline_said
    held = not said
    if held:
        held, said = held_to_origin(pin, copy)
    print(f"  {'ok  ' if held else 'FAIL'} {said_pin(pin)}")
    for line in said:
        print(f"         {line}")
    if not held:
        print(f"::error::{pin['id']} is not a pin the bundle can carry")
    return held


def offline_problems(bundle: Bundle, held: dict[str, pathlib.Path]) -> dict[str, list[str]]:
    """Every copy against its pin and the contract, with nothing fetched, by pin, and under `""`
    what holds across the pinned plugins."""
    if bundle.schema == 1:
        return {pin["id"]: held_to_pin(pin, held[pin["id"]].read_bytes()) for pin in bundle.pins}
    found: dict[str, list[str]] = {}
    manifests: dict[str, dict] = {}
    for pin in bundle.pins:
        found[pin["id"]], manifest = held_to_tree(pin, held[pin["id"]])
        if manifest is not None:
            manifests[pin["id"]] = manifest
            found[pin["id"]] += parts.part_problems(pin, manifest, bundle.table("form"))
            found[pin["id"]] += parts.fenced_problems(pin["id"], manifest, bundle.images.get("fence"))
    complete = len(manifests) == len(bundle.pins)
    found[""] = parts.across(bundle.table("wiring"), manifests, held) if complete else []
    return found


def offline_holds(bundle: Bundle, held: dict[str, pathlib.Path]) -> int:
    """Every copy against its pin, with nothing fetched."""
    said = [f"{name or 'the bundle'}: {line}" for name, lines in offline_problems(bundle, held).items()
            for line in lines]
    for line in said:
        print(f"::error::{line}")
    if not said:
        print(f"{len(bundle.pins)} pinned plugins' copies are what their pins name.")
    return 1 if said else 0


def checked(offline: bool = False) -> int:
    """The bundle in this checkout, held to its origins, or offline to what needs no fetch."""
    try:
        bundle = read(BUNDLE.read_text(encoding="utf-8"))
        held = copies(COPIES, bundle.schema)
    except (Refusal, OSError) as refused:
        for line in str(refused).splitlines():
            print(f"::error::{line}")
        return 1
    unpaired = paired(bundle.pins, held, bundle.schema)
    for problem in unpaired:
        print(f"::error::{problem}")
    if unpaired:
        return 1
    if not bundle.pins:
        print(f"The bundle, at schema {bundle.schema}, pins no first-party plugin yet, so there is no copy "
              "to hold to an origin.")
        return 0
    if offline:
        return offline_holds(bundle, held)
    try:
        version = check.a_reader_is_here()
    except check.Unaskable as unasked:
        print(f"::error::{unasked}")
        return 2
    print(f"Asked of {version}, which this catalogue targets.\n")
    found = offline_problems(bundle, held)
    general = found.pop("", [])
    for line in general:
        print(f"::error::the bundle: {line}")
    refused = sum(
        not holds(pin, held[pin["id"]].read_bytes() if bundle.schema == 1 else held[pin["id"]], found[pin["id"]])
        for pin in bundle.pins
    )
    print(f"\n{len(bundle.pins) - refused} of {len(bundle.pins)} pinned plugins hold.")
    return 1 if refused or general else 0


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
    parser.add_argument("--offline", action="store_true",
                        help="hold every copy to its pin without fetching anything")
    args = parser.parse_args()
    if args.self_test:
        import test_bundle

        return test_bundle.self_test()
    if bool(args.apply) != bool(args.origin) or (args.carry and not args.apply):
        print("::error::--apply takes --origin, and --origin and --carry are part of --apply")
        return 2
    if args.apply:
        return apply(tuple(args.apply), args.origin, args.carry)
    return checked(args.offline)


if __name__ == "__main__":
    sys.exit(main())

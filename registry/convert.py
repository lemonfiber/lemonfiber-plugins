#!/usr/bin/env python3
"""Write one part of the media stack as its own plugin repository (ADR-0045).

The media stack and plugin-template are each read at a commit, never from a working
tree, so the same two commits and the same part always write the same bytes. Into an
empty directory beneath the working directory it writes:

- `plugin.toml`, the part's `services/<id>.toml` in the plugin manifest's vocabulary:
  the plugin's id and name are the service's, `[plugin]` takes the service's
  `describes`, `without_it`, `upstream` and `license`, `forms` names exactly the forms
  whose closure holds the service's profile (ARCH-R96), each `[[wiring]]` asking a
  capability by the service becomes an `[[ask]]`, its claims become `[[claim]]`, and
  the service declares `replaces` naming its own id, which is how a manifest takes an
  id, a port and a hostname the bundle reserves (ARCH-R222);
- every file under `config/<id>/`, byte for byte (ARCH-R271);
- every recording the part's claims name, byte for byte, at its path (ARCH-R267);
- the plugin-template variant `--variant` names laid over the template's root: the
  variant's files, the root's that the variant's documentation keeps, and a README and
  an AGENTS.md written for the part. `bundled-part` names the upstream's image;
  `built-part` builds one here, so it also writes a `Dockerfile` from the image, tag and
  digest the stack pins, and the variant has to hold one;
- `proofs.json`, where `--lemonfiber` names a build of the commit the variant's
  `targets.toml` names, written by the template's reader.

What the plugin manifest cannot say is refused by name and nothing is written: a field
it has no place for, a profile, a link or a recording the stack does not hold, a part
that builds an image written from `bundled-part`, a part written from `built-part` that
pins no image, tag or digest, and anything the bundle would refuse of the manifest written. The
profile, the upstream's last release and the links by name and choices of filler stay
the bundle's, and are printed for the pin. Last it prints the manifest's digest and the
tree's (ARCH-R267).

Run:  python3 registry/convert.py --stack DIR [--stack-at REV] --template DIR [--template-at REV]
                                  [--variant bundled-part|built-part] [--lemonfiber BINARY] ID OUT
      python3 registry/convert.py --self-test
Needs: git.
Exit 0 = written, 1 = refused, or written with a proof that did not pass, 2 = could not be asked.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import entry  # noqa: E402
import index  # noqa: E402
import parts  # noqa: E402
import tree  # noqa: E402

MANIFEST = tree.MANIFEST
STACK_MANIFEST = "stack.toml"
SERVICES = "services"
RECORDINGS = "recordings"
VARIANT = "bundled-part"
BUILT = "built-part"
VARIANTS = (VARIANT, BUILT)
DOCKERFILE = "Dockerfile"
POSTURE = "posture/"
READER = ".github/reader/reader.py"
PROOFS = "proofs.json"
TARGETS = "targets.toml"
README = "README.md"
AGENTS = "AGENTS.md"
SCHEMA_VERSION = 1

CARRIED = (
    "id", "name", "image", "digest", "tag", "port", "bind", "listens", "publish", "health",
    "criticality", "memory_mib", "mem_limit_mib", "reaches", "asks_for", "provides", "api",
    "takes_data", "config_path", "config_ro", "mount", "tmpfs", "user_mode", "posture",
    "network", "shape", "media_types", "replaces", "env",
)
SECTIONS = ("env",)
TO_PLUGIN = {"describes": "description", "without_it": "without_it", "upstream": "upstream",
             "license": "license"}
PLUGIN_ORDER = ("id", "name", "version", "description", "without_it", "upstream", "license", "forms")
FOR_THE_BUNDLE = ("profile", "last_release")
CLAIM = "claim"
QUIET_WHEN_FALSE = ("host_managed",)
ASK_KEYS = {"by", "asks", "each", "filled_by", "why"}
LINK_KEYS = {"by", "to", "why"}

PART_PATHS = (MANIFEST, PROOFS, f"{tree.CONFIG}/", f"{RECORDINGS}/", POSTURE, DOCKERFILE)
WRITTEN = (README, AGENTS)
KEPT = (
    ".editorconfig", ".githooks/", ".markdownlint.jsonc", "typos.toml", "LICENSE", "CLAUDE.md",
    ".github/CODEOWNERS", ".github/labeler.yml", ".github/workflows/labels.yml",
    ".github/workflows/stale.yml",
)
DROPPED = (
    "fixtures/", PROOFS, ".github/reader/", "ruff.toml", "docs/", ".github/workflows/bundle.yml",
    ".github/workflows/built-part.yml", *(f"{one}/" for one in VARIANTS),
)
NOTE = re.compile(r"\A(?:>[^\n]*\n)+\n")
BARE_KEY = re.compile(r"\A[A-Za-z0-9_-]+\Z")
REVISION = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._/~^-]{0,255}\Z")
COMMIT = re.compile(r"\A[0-9a-f]{40}\Z")
EXECUTABLE = 0o755
READABLE = 0o644


def plain(path: str) -> bool:
    """Whether `path` is a plain relative path inside a tree: `/` between segments, no `.` or `..`
    segment, nothing absolute, no backslash and no NUL."""
    return isinstance(path, str) and "\0" not in path and tree.relative(path)


def unplain(manifest: dict) -> list[str]:
    """Every recording the manifest names that is not a plain relative path."""
    return [f"the recording {one!r} is not a plain relative path inside the tree"
            for one in tree.recordings(manifest) if not plain(one)]


class Refused(Exception):
    """The part cannot be written as a plugin, with every reason."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclasses.dataclass
class Part:
    """A part as the plugin repository holds it, and what stays the bundle's."""

    manifest: dict
    files: dict[str, bytes]
    profile: str
    last_release: str
    links: list[dict]
    choices: list[dict]
    left: list[str]


def snapshot(repository: pathlib.Path, revision: str, into: pathlib.Path) -> str:
    """`repository` at `revision`, written into `into` as git holds it, links as links; the
    commit it resolved to."""
    if not REVISION.fullmatch(revision):
        raise OSError(f"{revision!r} is not a revision this will hand to git")
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}").decode().strip()
    if not COMMIT.fullmatch(commit):
        raise OSError(f"{revision!r} in {repository} resolved to {commit!r}, which is not a commit")
    archive = git(repository, "archive", "--format=tar", commit)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive)) as held:
            held.extractall(into, filter="data")
    except tarfile.FilterError as outside:
        raise OSError(f"{repository} at {commit} holds what leaves it: {outside}") from None
    return commit


def git(repository: pathlib.Path, *asked: str) -> bytes:
    """What git says in `repository`, or why it could not be asked."""
    done = subprocess.run(["git", *asked], cwd=repository, capture_output=True, check=False)
    if done.returncode != 0:
        raise OSError(f"git {' '.join(asked[:2])} in {repository}: {done.stderr.decode().strip()}")
    return done.stdout


def inside_here(path: pathlib.Path) -> pathlib.Path:
    """`path` resolved, where it lies beneath the working directory; refused where it does not."""
    base = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(os.path.join(base, path))
    if not resolved.startswith(base + os.sep):
        raise Refused([f"{path} is not beneath the working directory, {base}"])
    return pathlib.Path(resolved)


def toml_of(root: pathlib.Path, path: str, problems: list[str]) -> dict:
    """The TOML file at `path` under `root`, or nothing with the reason in `problems`."""
    try:
        return tomllib.loads((root / path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as unread:
        problems.append(f"{path} cannot be read: {unread}")
        return {}


def service_of(stack: pathlib.Path, name: str, problems: list[str]) -> dict:
    """The one service `services/<name>.toml` declares, where the stack includes it."""
    path = f"{SERVICES}/{name}.toml"
    included = parts.listed(toml_of(stack, STACK_MANIFEST, problems), "include")
    if path not in included:
        problems.append(f"{STACK_MANIFEST} includes no {path}, so the stack holds no part {name!r}")
        return {}
    held = toml_of(stack, path, problems)
    services = parts.listed(held, "service")
    others = sorted(set(held) - {"service"})
    if others:
        problems.append(f"{path} declares {others} beside its service, which a plugin manifest has no place for")
    if len(services) != 1 or not isinstance(services[0], dict):
        problems.append(f"{path} declares {len(services)} services, and a part is one")
        return {}
    if services[0].get("id") != name:
        problems.append(f"{path} declares service {services[0].get('id')!r}, not {name!r}")
    return services[0]


def unplaced(service: dict, path: str) -> list[str]:
    """Each field of the stack service that a plugin manifest has no place for."""
    placed = {*CARRIED, *TO_PLUGIN, *FOR_THE_BUNDLE, CLAIM}
    said = []
    for key, value in service.items():
        if key in QUIET_WHEN_FALSE and value is False:
            continue
        if key not in placed or key == "replaces":
            said.append(f"{path}: {key} = {value!r} has no place in a plugin manifest")
    return said


def built(service: dict, path: str, variant: str) -> list[str]:
    """A part whose image lemonfiber builds is not one the bundled-part variant carries, and a part
    the built-part variant builds names the image it is built from."""
    if variant == VARIANT and str(service.get("image", "")).startswith(parts.OWN_IMAGES):
        return [(f"{path}: image {service['image']} is one lemonfiber builds, and the {VARIANT} variant "
                 f"carries no image build or release")]
    if variant == BUILT:
        return [f"{path}: the {BUILT} variant builds from the image the service names, and it names no {field}"
                for field in ("image", "tag", "digest") if not isinstance(service.get(field), str) or not service[field]]
    return []


def kind_of(row: dict) -> str:
    """Whether a wiring row is an ask, a link by name, or neither."""
    if "asks" in row and "to" not in row and set(row) <= ASK_KEYS:
        return "ask"
    if "to" in row and "asks" not in row and set(row) <= LINK_KEYS:
        return "link"
    return "neither"


def asks_of(stack_manifest: dict, name: str) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    """The part's asks as `[[ask]]`, the bundle's choices of filler and links by name from it, and
    every wiring row by it that is neither."""
    rows = [row for row in parts.listed(stack_manifest, "wiring") if isinstance(row, dict) and row.get("by") == name]
    asked = [row for row in rows if kind_of(row) == "ask"]
    asks = [{"capability": row["asks"], **({"each": True} if row.get("each") is True else {})} for row in asked]
    choices = [row for row in asked if "filled_by" in row]
    links = [row for row in rows if kind_of(row) == "link"]
    problems = [f"{STACK_MANIFEST} {parts.wiring_named(row)} is neither an ask nor a link by name"
                for row in rows if kind_of(row) == "neither"]
    return asks, choices, links, problems


def forms_holding(stack_manifest: dict, profile: str, problems: list[str]) -> list[str]:
    """The forms whose closure holds `profile`, in the order the stack declares them."""
    profiles = {row.get("id") for row in parts.listed(stack_manifest, "profile") if isinstance(row, dict)}
    if profile not in profiles:
        problems.append(f"the service sits in profile {profile!r}, which {STACK_MANIFEST} does not declare")
    return [str(row.get("id")) for row in parts.listed(stack_manifest, "form")
            if isinstance(row, dict) and profile in parts.listed(row, "profiles")]


def claims_of(service: dict) -> list[dict]:
    """The service's claims, as a plugin's top-level `[[claim]]`."""
    return [claim for claim in parts.listed(service, CLAIM) if isinstance(claim, dict)]


def manifest_of(service: dict, plugin: dict, asks: list[dict]) -> dict:
    """The plugin manifest of a part of one service."""
    carried = {key: service[key] for key in CARRIED if key in service}
    carried["replaces"] = service.get("id")
    manifest: dict = {
        "schema_version": SCHEMA_VERSION,
        "plugin": {key: plugin[key] for key in PLUGIN_ORDER if key in plugin},
        "service": [{key: carried[key] for key in CARRIED if key in carried}],
    }
    if asks:
        manifest["ask"] = asks
    claims = claims_of(service)
    if claims:
        manifest[CLAIM] = claims
    return manifest


def files_of(stack: pathlib.Path, name: str, manifest: dict, problems: list[str]) -> tuple[dict[str, bytes], list[str]]:
    """The starting files and the claimed recordings, each at its path, and the recordings under
    `recordings/<id>/` its claims do not name."""
    starting, refused = tree.starting_files(stack, name)
    problems.extend(f"config/{name}/: {reason}" for reason in refused)
    named, missing = tree.named(stack, {CLAIM: manifest.get(CLAIM, [])})
    problems.extend(missing)
    found = {path: (stack / path).read_bytes() for path in [*starting, *named]}
    held, _ = tree.walked(stack, f"{RECORDINGS}/{name}")
    return found, sorted(set(held) - set(named))


def converted(stack: pathlib.Path, name: str, version: str, variant: str = VARIANT) -> Part:
    """The part `name` of the stack snapshot at `stack`, or every reason it cannot be one."""
    if not isinstance(name, str) or not entry.ID.match(name):
        raise Refused([f"the part id {name!r} is not a plain id, lowercase words joined by '-'"])
    problems: list[str] = []
    stack_manifest = toml_of(stack, STACK_MANIFEST, problems)
    service = service_of(stack, name, problems)
    if not service:
        raise Refused(problems)
    path = f"{SERVICES}/{name}.toml"
    problems += unplaced(service, path) + built(service, path, variant)
    profile = str(service.get("profile", ""))
    plugin = {
        "id": name,
        "name": service.get("name"),
        "version": version,
        **{to: service[key] for key, to in TO_PLUGIN.items() if key in service},
        "forms": forms_holding(stack_manifest, profile, problems),
    }
    asks, choices, links, unasked = asks_of(stack_manifest, name)
    problems += unasked
    manifest = manifest_of(service, plugin, asks)
    unsafe = unplain(manifest)
    if unsafe:
        raise Refused(problems + unsafe)
    files, left = files_of(stack, name, manifest, problems)
    pin = {"id": name, "stage": parts.ASSEMBLED, "profile": profile,
           "fills": sorted(parts.filled_by(manifest["service"]))}
    problems += [f"the bundle would refuse it: {said}"
                 for said in parts.part_problems(pin, manifest, parts.listed(stack_manifest, "form"))]
    if problems:
        raise Refused(problems)
    return Part(manifest, files, profile, str(service.get("last_release", "")), links, choices, left)


def key_of(name: str) -> str:
    """A TOML key, bare where it can be."""
    return name if BARE_KEY.match(name) else json.dumps(name, ensure_ascii=False)


def value_of(value: object) -> str:
    """A TOML value written on one line."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(value_of(one) for one in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{key_of(key)} = {value_of(one)}" for key, one in value.items())
        return "{ " + inner + " }" if inner else "{}"
    raise Refused([f"{value!r} is no value a manifest holds"])


def tables(value: object) -> bool:
    """Whether `value` is an array written as tables of its own."""
    return isinstance(value, list) and bool(value) and all(isinstance(one, dict) for one in value)


def table_of(header: str, table: dict) -> list[str]:
    """One table, its own keys aligned, then its sections and arrays of tables."""
    inline = {key: value for key, value in table.items()
              if not tables(value) and not (key in SECTIONS and isinstance(value, dict))}
    width = max((len(key_of(key)) for key in inline), default=0)
    lines = [header] if header else []
    lines += [f"{key_of(key).ljust(width)} = {value_of(value)}" for key, value in inline.items()]
    prefix = header.strip("[]") + "." if header else ""
    for key, value in table.items():
        if key in SECTIONS and isinstance(value, dict):
            lines += ["", *table_of(f"[{prefix}{key}]", value)]
        elif tables(value):
            for one in value:
                lines += ["", *table_of(f"[[{prefix}{key}]]", one)]
    return lines


def written(manifest: dict) -> str:
    """The manifest as `plugin.toml`, which reads back as the manifest it was written from."""
    lines = [f"schema_version = {manifest['schema_version']}"]
    for key in ("plugin",):
        lines += ["", *table_of(f"[{key}]", manifest[key])]
    for key in ("service", "ask", CLAIM):
        for one in manifest.get(key, []):
            lines += ["", *table_of(f"[[{key}]]", one)]
    text = "\n".join(lines) + "\n"
    if tomllib.loads(text) != manifest:
        raise Refused(["plugin.toml as written does not read back as the manifest it was written from"])
    return text


def sentence(text: str) -> str:
    """`text` ending in one full stop."""
    return text.rstrip().rstrip(".") + "."


def dockerfile(service: dict) -> str:
    """The Dockerfile a built part starts from: its upstream's image at the digest the stack pins."""
    return f"FROM {service['image']}:{service['tag']}@{service['digest']}\n"


def readme(plugin: dict, service: dict, files: dict[str, bytes], builds: bool = False) -> str:
    """The part's README."""
    name, ident = plugin["name"], plugin["id"]
    carried = (f"Until its adapter ships, lemonfiber assembles {name} into the stack it ships as a\n"
               "stack service, and reaches it through the in-process adapter its `api` names."
               if "api" in service else
               f"lemonfiber assembles {name} into the stack it ships as a stack service.")
    rows = ["| `plugin.toml` | The part's manifest |"]
    if any(path.startswith(f"{tree.CONFIG}/") for path in files):
        rows.append(f"| `config/{ident}/` | The files {name} starts with, written into its configuration directory |")
    if any(path.startswith(f"{RECORDINGS}/") for path in files):
        rows.append(f"| `recordings/{ident}/` | The responses its claims are proved against |")
    if builds:
        rows += ["| `Dockerfile` | How its image is built |"]
    rows += ["| `targets.toml` | The lemonfiber its checks run against |",
             "| `proofs.json` | What those checks said, committed |"]
    return "\n".join([
        f"# {name} for lemonfiber",
        "",
        f"**{sentence(plugin['description'])}**",
        f"{name} is one of the parts the stack lemonfiber ships is built from.",
        f"Without it: {sentence(plugin['without_it'])}",
        "",
        "## How lemonfiber carries it",
        "",
        "The default bundle in",
        "[lemonfiber-plugins](https://github.com/lemonfiber/lemonfiber-plugins) pins this",
        "repository by a revision and the digests of its manifest and its tree, and",
        "lemonfiber compiles that tree in.",
        carried,
        *([f"Its image is built here from {name}'s, with what the posture it runs under",
           "does not hold taken out. Every commit on main publishes it, the release train",
           "tags this repository, and the bundle pins the tag."] if builds else
          [f"Its image is {name}'s own, so the release train never tags this repository, and",
           "its pin moves by a reviewed pull request on the catalogue."]),
        "",
        "## What is here",
        "",
        "| Path | What it is |",
        "| --- | --- |",
        *rows,
        "",
        "## Checks",
        "",
        "The plugin verdict is one job of spec's",
        "[`first-party-plugin`](https://github.com/lemonfiber/spec/blob/main/.github/workflows/first-party-plugin.yml)",
        "workflow: the manifest as the lemonfiber `targets.toml` names reads it, every",
        "claim against its recording, and every pinned digest. This repository holds no",
        "Python of its own. `just ci` runs the gates that need nothing but this tree.",
        *(["The image is one job of spec's",
           "[`first-party-image`](https://github.com/lemonfiber/spec/blob/main/.github/workflows/first-party-image.yml)",
           "workflow: built and run under the posture its manifest declares on a pull",
           "request, and published, run again and pinned from main and a train tag."] if builds else []),
        "",
        "## Licence",
        "",
        "The data in this repository is under the licence in `LICENSE`.",
        *([f"{name} itself is under {plugin['license']}, and the image built here from it",
           "carries it under the same licence."] if builds else
          [f"{name} itself is under {plugin['license']} and is not distributed here: this",
           "repository names an image, it does not contain one."]),
        "",
    ])


def agents(plugin: dict, builds: bool = False) -> str:
    """The part's AGENTS.md."""
    name, ident = plugin["name"], plugin["id"]
    return "\n".join([
        f"# AGENTS.md — plugin-{ident}",
        "",
        "> **Start at the roadmap and board on [lemonfiber.app](https://lemonfiber.app),",
        "> rendered from the report of where every unreleased version stands. Then the",
        "> rules** every repository shares:",
        "> [working in the repositories](https://github.com/lemonfiber/spec/blob/main/50-governance/working-in-the-repositories.md)",
        "> and [the rules for agents](https://github.com/lemonfiber/spec/blob/main/50-governance/ai-contributors.md).",
        "> This file holds only what is true of this repository.",
        "",
        "## What this repo is",
        "",
        f"A bundled part: {name}, as the stack lemonfiber ships carries it. The",
        "[bundle contract](https://github.com/lemonfiber/spec/blob/main/20-architecture/contracts/bundle.md)",
        "says how the catalogue pins it and how lemonfiber carries it.",
        "",
        "## The rules you cannot break",
        "",
        "- **The plugin id is the service's id** (`ARCH-R266`). The container, the",
        "  configuration directory, the settings and the journal keep their names.",
        "- **One service, speaking no contract**, while the bundle assembles it. It",
        "  declares `replaces` naming its own id, which is how it takes the id, the port",
        "  and the hostname the bundle reserves for it (`ARCH-R222`).",
        f"- **Its claims' recordings sit under `recordings/{ident}/`**, and its starting",
        f"  files, where it has any, under `config/{ident}/` (`ARCH-R271`).",
        "- **Every service declares `reaches` and `asks_for`** (`ARCH-R270`).",
        "- **No Python here.** The reader is spec's `first-party-plugin` workflow's.",
        *(["- **The image is built here** (`OPS-R90`). The `Dockerfile` builds it from",
           f"  {name}'s, and it runs under the posture its manifest declares (`ARCH-R250`);",
           "  `posture/prepare`, where there is one, gives it what lemonfiber writes at",
           "  install. Its pin moves on the release app's rolling pull request."] if builds else
          [f"- **The image is {name}'s own**, so this repository is never tagged. Moving",
           "  the digest means recording every response again against the new image in",
           "  the same change, and committing the `proofs.json` the checks write."]),
        "",
    ])


def classified(path: str, variant: set[str]) -> str:
    """What becomes of one file of the template's root: replaced, kept or dropped."""
    if path in variant:
        return "replaced"
    if any(path == one or (one.endswith("/") and path.startswith(one)) for one in KEPT):
        return "kept"
    if any(path == one or (one.endswith("/") and path.startswith(one)) for one in DROPPED):
        return "dropped"
    return "unclassified"


def part_owned(path: str) -> bool:
    """Whether a path of the variant is the variant's own part's, which the converted part's replaces."""
    return any(path == one or (one.endswith("/") and path.startswith(one)) for one in PART_PATHS)


def template_files(template: pathlib.Path, chosen: str = VARIANT) -> tuple[dict[str, pathlib.Path], dict, list[str]]:
    """The file a part's repository takes from the template at each of its paths, the variant's own
    manifest, and every template file nothing says what becomes of."""
    everything, refused = tree.walked(template, ".")
    problems = list(refused)
    under = f"{chosen}/"
    variant = {path[len(under):] for path in everything if path.startswith(under)}
    taken = {path: template / under / path for path in sorted(variant)
             if not part_owned(path) and path not in WRITTEN}
    for path in everything:
        if path.startswith(under):
            continue
        fate = classified(path, variant)
        if fate == "kept":
            taken[path] = template / path
        elif fate == "unclassified":
            problems.append(f"plugin-template's {path} is neither kept, dropped nor replaced by {chosen}/")
    needed = (MANIFEST, TARGETS, *WRITTEN, *((DOCKERFILE,) if chosen == BUILT else ()))
    problems += [f"plugin-template's {chosen}/ holds no {one}" for one in needed if one not in variant]
    own = toml_of(template / chosen, MANIFEST, problems) if MANIFEST in variant else {}
    return taken, own, problems


def held_to_variant(template: pathlib.Path, own: dict, files: dict[str, bytes], chosen: str = VARIANT) -> list[str]:
    """The variant's README and AGENTS.md are what this writes for the variant's own part."""
    plugin = parts.plugin_of(own)
    services = parts.services_of(own)
    if not plugin or len(services) != 1:
        return [f"plugin-template's {chosen}/plugin.toml is not a part of one service"]
    builds = chosen == BUILT
    expected = {README: readme(plugin, services[0], files, builds), AGENTS: agents(plugin, builds)}
    said = []
    for path, text in expected.items():
        held = (template / chosen / path).read_text(encoding="utf-8")
        if NOTE.sub("", held, count=1) != text:
            said.append(f"plugin-template's {chosen}/{path} is not what this writes for its own part, so "
                        f"the two disagree on what a part's {path} says")
    return said


def variant_files(template: pathlib.Path, chosen: str = VARIANT) -> dict[str, bytes]:
    """The variant's own part's files, as the repository made from it holds them."""
    root = template / chosen
    found, _ = tree.walked(root, ".")
    return {path: (root / path).read_bytes() for path in found if part_owned(path) and path != PROOFS}


def prove(out: pathlib.Path, template: pathlib.Path, binary: pathlib.Path) -> int:
    """Write `proofs.json` in `out` with the template's reader, asking `binary`."""
    spec = importlib.util.spec_from_file_location("template_reader", template / READER)
    if spec is None or spec.loader is None:
        raise OSError(f"plugin-template's {READER} cannot be loaded")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    reader.ROOT, reader.MANIFEST = out, out / MANIFEST
    reader.TARGETS, reader.REPORT = out / TARGETS, out / PROOFS
    reader.binary = lambda: binary
    try:
        return reader.proofs()
    except reader.Unasked as unasked:
        raise OSError(f"the template's reader asked {binary} nothing: {unasked}") from None


def outside(base: pathlib.Path, files: dict[str, bytes]) -> list[str]:
    """Every path of `files` that does not resolve strictly inside `base`."""
    said = []
    for path in sorted(files):
        target = (base / path).resolve() if plain(path) else None
        if target is None or target == base or not tree.inside(base, target):
            said.append(f"{path!r} is not a path inside the directory written into")
    return said


def write(out: pathlib.Path, files: dict[str, bytes], executable: set[str]) -> None:
    """Every file at its path under `out`, executable where its source is; nothing where any path
    would land outside it."""
    base = out.resolve()
    refused = outside(base, files)
    if refused:
        raise Refused(refused)
    for path, body in sorted(files.items()):
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or not tree.inside(base, target.parent.resolve()):
            raise Refused([f"{path!r} would be written through a symbolic link"])
        target.write_bytes(body)
        target.chmod(EXECUTABLE if path in executable else READABLE)


def convert(stack_repo: pathlib.Path, stack_at: str, template_repo: pathlib.Path, template_at: str,
            name: str, out: pathlib.Path, binary: pathlib.Path | None = None, chosen: str = VARIANT) -> int:
    """Write the part `name` into `out`, and say what the bundle pins it by."""
    out = inside_here(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refused([f"{out} is not an empty directory"])
    with tempfile.TemporaryDirectory() as scratch:
        stack, template = pathlib.Path(scratch) / "stack", pathlib.Path(scratch) / "template"
        stack_commit = snapshot(stack_repo, stack_at, stack)
        template_commit = snapshot(template_repo, template_at, template)
        if chosen not in VARIANTS:
            raise Refused([f"{chosen!r} is not one of plugin-template's variants, {', '.join(VARIANTS)}"])
        builds = chosen == BUILT
        taken, own, problems = template_files(template, chosen)
        version = str(parts.plugin_of(own).get("version", ""))
        if not version:
            problems.append(f"plugin-template's {chosen}/plugin.toml names no [plugin].version to give the part")
        try:
            part = converted(stack, name, version, chosen)
        except Refused as refused:
            raise Refused(problems + refused.problems) from None
        problems += held_to_variant(template, own, variant_files(template, chosen), chosen)
        if problems:
            raise Refused(problems)
        manifest_text = written(part.manifest)
        plugin = part.manifest["plugin"]
        files = {**{path: source.read_bytes() for path, source in taken.items()}, **part.files, MANIFEST: manifest_text.encode(),
                 README: readme(plugin, part.manifest["service"][0], part.files, builds).encode(),
                 AGENTS: agents(plugin, builds).encode(),
                 **({DOCKERFILE: dockerfile(part.manifest["service"][0]).encode()} if builds else {})}
        executable = {path for path, source in taken.items() if os.access(source, os.X_OK)}
        out.mkdir(parents=True, exist_ok=True)
        write(out, files, executable)
        proved = prove(out, template, binary) if binary is not None else 0
    carried = tree.read(out, part.manifest)
    print(f"plugin-{name}: {len(files)} files, from media stack {stack_commit} and plugin-template "
          f"{template_commit}")
    print(f"for the bundle: profile = {part.profile!r}, last_release = {part.last_release!r}, "
          f"fills = {sorted(parts.filled_by(part.manifest['service']))}")
    for row in part.choices:
        print(f"for the bundle: {parts.wiring_named(row)} filled_by {row['filled_by']!r}")
    for row in part.links:
        print(f"for the bundle: {parts.wiring_named(row)}, by name")
    for path in part.left:
        print(f"left behind: {path}, which no claim names")
    print(f"manifest {index.digest(manifest_text.encode())}")
    print(f"tree {tree.digest(carried)}")
    return proved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true", help="prove each rule against the shape it refuses")
    parser.add_argument("--stack", type=pathlib.Path, help="a clone of lemonfiber-media-stack")
    parser.add_argument("--stack-at", default="HEAD", help="the media stack's commit to read")
    parser.add_argument("--template", type=pathlib.Path, help="a clone of plugin-template")
    parser.add_argument("--template-at", default="HEAD", help="plugin-template's commit to read")
    parser.add_argument("--variant", default=VARIANT, choices=VARIANTS,
                        help="the plugin-template variant the repository is made from")
    parser.add_argument("--lemonfiber", type=pathlib.Path,
                        help="a build of the commit the variant's targets.toml names, to write proofs.json")
    parser.add_argument("part", nargs="?", help="the part's id, its service's")
    parser.add_argument("out", nargs="?", type=pathlib.Path,
                        help="an empty directory beneath the working directory to write into")
    args = parser.parse_args()
    if args.self_test:
        import test_convert

        return test_convert.self_test()
    if not (args.stack and args.template and args.part and args.out):
        print("::error::--stack, --template, the part's id and the directory to write into are all needed")
        return 2
    try:
        return convert(args.stack, args.stack_at, args.template, args.template_at, args.part, args.out,
                       args.lemonfiber, args.variant)
    except Refused as refused:
        for problem in refused.problems:
            print(f"::error::{problem}")
        return 1
    except (OSError, tree.Unreadable) as unread:
        print(f"::error::{unread}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

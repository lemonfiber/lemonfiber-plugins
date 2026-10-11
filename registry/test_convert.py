"""`convert.py --self-test`: a part written from a media stack and a template made here, the same
bytes every time, and each shape the converter exists to refuse."""

from __future__ import annotations

import contextlib
import io
import os
import pathlib
import shutil
import subprocess
import tempfile
import tomllib

import convert
import index
import tree

Case = tuple[str, bool, bool]

SCRATCH: list[pathlib.Path] = []

STACK = """schema_version = 1
include = ["services/part.toml", "services/other.toml"]

[[profile]]
id = "search"
name = "Indexers"
description = "Finding things"

[[profile]]
id = "tv"
name = "Television"
description = "TV automation"

[[form]]
id = "search"
name = "Search"
description = "Find things"
profiles = ["search"]

[[form]]
id = "tv"
name = "TV"
description = "Television"
profiles = ["search", "tv"]

[[form]]
id = "library"
name = "Library"
description = "Serve"
profiles = ["tv"]

[[wiring]]
by = "part"
asks = "library.curate"
each = true

[[wiring]]
by = "part"
asks = "indexer.proxy"
filled_by = "other"
why = "The stack's choice."

[[wiring]]
by = "part"
to = "other"
why = "It is configured in the other's own terms."

[[wiring]]
by = "other"
asks = "download.usenet"
"""

PART = """[[service]]
id = "part"
name = "Part"
profile = "search"
image = "lscr.io/linuxserver/part"
tag = "1.2.3"
digest = "sha256:%s"
port = 9696
bind = "loopback"
criticality = "core"
memory_mib = 200
license = "GPL-3.0-only"
upstream = "https://github.com/example/part"
last_release = "2026-09-16"
describes = "Holds your indexers"
without_it = "Every app needs indexers configured separately"
reaches = "the indexers you configured"
asks_for = "Runs the searches everything else asks for."
provides = ["indexer.search"]
health = { kind = "http", path = "/ping", timeout_s = 60 }
api = { kind = "servarr", key_source = "config-xml", path = "/config/config.xml", version = 1 }
listens = 9696
takes_data = true
user_mode = "puid-env"
host_managed = false

[service.env]
LOG_LEVEL = { setting = "part:log-level", default = "info" }
"WEIRD KEY" = "1"

[[service.mount]]
from = "cache"
to = "/cache"

[[service.claim]]
capability = "indexer.search"

[[service.claim.probe]]
id = "indexers"
request = { method = "GET", path = "/api/v1/indexer" }
expect = { status = 200, json_types = { "/indexers" = "list" } }
fixture = "recordings/part/indexers.json"
""" % ("a" * 64)

OTHER = """[[service]]
id = "other"
name = "Other"
profile = "search"
image = "ghcr.io/example/other"
tag = "1"
digest = "sha256:%s"
criticality = "enhancing"
license = "MIT"
upstream = "https://github.com/example/other"
last_release = "2026-09-01"
describes = "Other"
without_it = "Nothing"
reaches = "nowhere"
asks_for = "Nothing."
provides = ["indexer.proxy"]
""" % ("b" * 64)

STACK_FILES = {
    "stack.toml": STACK,
    "services/part.toml": PART,
    "services/other.toml": OTHER,
    "config/part/part.ini": "[main]\nport = 9696\n",
    "config/part/nested/extra.yml": "a: 1\n",
    "recordings/part/indexers.json": '{"status": 200}\n',
    "recordings/part/unused.json": "{}\n",
    "recordings/other/x.json": "{}\n",
}

OWN = """schema_version = 1

[plugin]
id          = "own"
name        = "Own"
version     = "1.0.0"
description = "Does its own thing"
without_it  = "Nothing of its own"
upstream    = "https://github.com/example/own"
license     = "MIT"
forms       = ["search"]

[[service]]
id          = "own"
name        = "Own"
image       = "docker.io/example/own"
digest      = "sha256:%s"
tag         = "1"
criticality = "core"
reaches     = "nowhere"
asks_for    = "Nothing."
replaces    = "own"
""" % ("c" * 64)

READER = '''import json
ROOT = MANIFEST = TARGETS = REPORT = CACHE = None
class Unasked(RuntimeError):
    pass
def binary():
    raise RuntimeError("the build was not the one given")
def proofs():
    REPORT.write_text(json.dumps({"lemonfiber": TARGETS.read_text().strip(), "asked": str(binary()),
                                  "of": MANIFEST.read_text().splitlines()[0]}) + "\\n")
    return 0
'''

TEMPLATE_ROOT = {
    ".editorconfig": "root = true\n",
    ".githooks/commit-msg": "#!/bin/sh\nexit 0\n",
    ".github/CODEOWNERS": "* @someone\n",
    ".github/labeler.yml": "ci: []\n",
    ".github/dependabot.yml": "version: 2\n",
    ".github/reader/reader.py": READER,
    ".github/workflows/labels.yml": "name: labels\n",
    ".github/workflows/stale.yml": "name: stale\n",
    ".github/workflows/bundle.yml": "name: bundle\n",
    ".github/workflows/plugin.yml": "name: root plugin\n",
    ".gitignore": ".lemonfiber/\n",
    ".markdownlint.jsonc": "{}\n",
    "AGENTS.md": "# root agents\n",
    "CLAUDE.md": "See AGENTS.md\n",
    "LICENSE": "licence\n",
    "README.md": "# root\n",
    "docs/development.md": "# development\n",
    "fixtures/x.json": "{}\n",
    "justfile": "ci:\n",
    "plugin.toml": "schema_version = 1\n",
    "proofs.json": "{}\n",
    "ruff.toml": "line-length = 110\n",
    "targets.toml": 'lemonfiber = "0.16.0"\n',
    "typos.toml": "[default]\n",
}


def own_files() -> dict[str, str]:
    """The variant: its own part, and the files every part's repository takes from it."""
    plugin = tomllib.loads(OWN)
    files = {"plugin.toml": OWN, "config/own/own.ini": "x\n", "recordings/own/r.json": "{}\n"}
    marks = {path: b"" for path in files}
    files.update({
        "README.md": "> **The variant.** Delete this note.\n\n"
                     + convert.readme(plugin["plugin"], plugin["service"][0], marks),
        "AGENTS.md": convert.agents(plugin["plugin"]),
        "targets.toml": 'commit = "' + "d" * 40 + '"\n',
        "justfile": "ci: typos\n",
        ".gitignore": ".lemonfiber/\n.github/reader/\n",
        ".github/dependabot.yml": "version: 2\n# variant\n",
        ".github/workflows/plugin.yml": "name: plugin\n",
        "proofs.json": '{"own": true}\n',
    })
    return files


def template_files() -> dict[str, str]:
    return {**TEMPLATE_ROOT, **{f"{convert.VARIANT}/{path}": text for path, text in own_files().items()}}


def committed(directory: pathlib.Path, files: dict[str, str], links: dict[str, str] | None = None) -> str:
    """A repository at `directory` holding `files` and `links` in one commit; that commit."""
    for path, text in files.items():
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        target.chmod(0o755 if text.startswith("#!") else 0o644)
    for path, pointing in (links or {}).items():
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(pointing, directory / path)
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for command in (["init", "--quiet"], ["add", "--all"],
                    ["-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false",
                     "commit", "--quiet", "--message", "fixture"]):
        subprocess.run(["git", "-C", str(directory), *command], check=True, env=environment)
    return subprocess.run(["git", "-C", str(directory), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def ran(stack: dict[str, str], template: dict[str, str], name: str = "part",
        links: dict[str, str] | None = None, prepared: bool = False,
        binary: bool = False, outside: bool = False) -> tuple[int | None, list[str], pathlib.Path, str, dict[str, bytes]]:
    """Convert `name` from a stack and a template made of these files: the exit, what was refused,
    the output directory, what was printed, and every file written."""
    scratch = pathlib.Path(tempfile.mkdtemp())
    SCRATCH.append(scratch)
    committed(scratch / "stack", stack, links)
    committed(scratch / "template", template)
    out = scratch / "out"
    if prepared:
        out.mkdir()
        (out / "already").write_text("here\n")
    printed = io.StringIO()
    refused: list[str] = []
    code: int | None = None
    built = scratch / "lemonfiber" if binary else None
    with contextlib.redirect_stdout(printed), contextlib.chdir(scratch):
        try:
            code = convert.convert(scratch / "stack", "HEAD", scratch / "template", "HEAD", name,
                                   pathlib.Path("..", "elsewhere") if outside else pathlib.Path(out.name), built)
        except convert.Refused as refusal:
            refused = refusal.problems
    held = {path.relative_to(out).as_posix(): path.read_bytes()
            for path in sorted(out.rglob("*")) if path.is_file()} if out.is_dir() else {}
    return code, refused, out, printed.getvalue(), held


def says(refused: list[str], *words: str) -> bool:
    return any(all(word in line for word in words) for line in refused)


def written_cases() -> list[Case]:
    code, refused, out, printed, held = ran(STACK_FILES, template_files())
    manifest = tomllib.loads(held.get("plugin.toml", b"").decode()) if "plugin.toml" in held else {}
    plugin = manifest.get("plugin", {})
    service = (manifest.get("service") or [{}])[0]
    expected_paths = {
        ".editorconfig", ".githooks/commit-msg", ".github/CODEOWNERS", ".github/labeler.yml",
        ".github/dependabot.yml", ".github/workflows/labels.yml", ".github/workflows/stale.yml",
        ".github/workflows/plugin.yml", ".gitignore", ".markdownlint.jsonc", "AGENTS.md", "CLAUDE.md",
        "LICENSE", "README.md", "justfile", "plugin.toml", "targets.toml", "typos.toml",
        "config/part/part.ini", "config/part/nested/extra.yml", "recordings/part/indexers.json",
    }
    carried = tree.read(out, manifest) if manifest else []
    again = ran(STACK_FILES, template_files())
    return [
        ("a part of the stack is written", True, code == 0 and not refused),
        ("the repository holds the variant over the kept root, and the part's own files", True,
         set(held) == expected_paths),
        ("the plugin is the service: its id, name, and describes and without_it as the plugin's", True,
         (plugin.get("id"), plugin.get("name"), plugin.get("description"), plugin.get("without_it"))
         == ("part", "Part", "Holds your indexers", "Every app needs indexers configured separately")),
        ("the plugin's version is the variant's, and its licence and upstream the service's", True,
         (plugin.get("version"), plugin.get("license"), plugin.get("upstream"))
         == ("1.0.0", "GPL-3.0-only", "https://github.com/example/part")),
        ("forms names the forms whose closure holds the profile, in the stack's order", True,
         plugin.get("forms") == ["search", "tv"]),
        ("the service keeps every field the model shares, and replaces its own id", True,
         service.get("replaces") == "part" and service.get("api", {}).get("kind") == "servarr"
         and service.get("env", {}).get("WEIRD KEY") == "1" and service.get("mount") == [{"from": "cache", "to": "/cache"}]),
        ("profile, last_release, host_managed and the stack's own wording stay out of the manifest", True,
         not {"profile", "last_release", "host_managed", "describes", "license", "claim"} & set(service)),
        ("every ask by it is an [[ask]], each where it reaches every filler", True,
         manifest.get("ask") == [{"capability": "library.curate", "each": True}, {"capability": "indexer.proxy"}]),
        ("its claims are the plugin's", True,
         [claim.get("capability") for claim in manifest.get("claim", [])] == ["indexer.search"]),
        ("the starting files and the claimed recording are byte for byte the stack's", True,
         held.get("config/part/nested/extra.yml") == b"a: 1\n"
         and held.get("recordings/part/indexers.json") == b'{"status": 200}\n'),
        ("a recording no claim names is left behind, and said", True,
         "recordings/part/unused.json" not in held and "left behind: recordings/part/unused.json" in printed),
        ("what stays the bundle's is printed for the pin", True,
         "profile = 'search', last_release = '2026-09-16'" in printed
         and "filled_by 'other'" in printed and "to 'other', by name" in printed),
        ("the variant's files replace the root's, and the variant's own part goes", True,
         held.get(".github/dependabot.yml") == b"version: 2\n# variant\n"
         and "proofs.json" not in held and not any(path.endswith("/own") or "/own/" in path for path in held)),
        ("a hook stays executable, and nothing else is", True,
         os.access(out / ".githooks/commit-msg", os.X_OK) and not os.access(out / "plugin.toml", os.X_OK)),
        ("the README and AGENTS.md are the part's", True,
         held.get("README.md", b"").startswith(b"# Part for lemonfiber\n")
         and b"`config/part/`" in held.get("README.md", b"")
         and held.get("AGENTS.md", b"").startswith(b"# AGENTS.md \xe2\x80\x94 plugin-part\n")),
        ("the digests printed are the manifest's and the tree's", True,
         f"manifest {index.digest(held.get('plugin.toml', b''))}" in printed
         and f"tree {tree.digest(carried)}" in printed),
        ("the same commits write the same bytes", True, again[4] == held),
    ]


def readme_cases() -> list[Case]:
    plugin = {"id": "bare", "name": "Bare", "description": "Bare.", "without_it": "Less", "license": "MIT"}
    bare = convert.readme(plugin, {}, {})
    return [
        ("a part with no starting file, recording or api has no row or sentence for them", True,
         "config/" not in bare and "recordings/" not in bare and "`api`" not in bare),
        ("a description ends in one full stop", True, "**Bare.**" in bare and "Without it: Less." in bare),
    ]


def changed(path: str, old: str, new: str) -> dict[str, str]:
    files = dict(STACK_FILES)
    assert old in files[path], old
    files[path] = files[path].replace(old, new)
    return files


def refusal_cases() -> list[Case]:
    shapes: list[tuple[str, dict[str, str], dict[str, str], tuple[str, ...], dict]] = [
        ("a field a plugin manifest has no place for", changed("services/part.toml", 'tag = "1.2.3"',
         'tag = "1.2.3"\ngrants = ["x"]'), template_files(), ("grants", "no place"), {}),
        ("host_managed set", changed("services/part.toml", "host_managed = false", "host_managed = true"),
         template_files(), ("host_managed", "no place"), {}),
        ("a part the stack does not include", STACK_FILES, template_files(), ("includes no services/absent.toml",),
         {"name": "absent"}),
        ("an image lemonfiber builds", changed("services/part.toml", "lscr.io/linuxserver/part",
         "ghcr.io/lemonfiber/part"), template_files(), ("ghcr.io/lemonfiber/part", "builds"), {}),
        ("a profile the stack does not declare", changed("services/part.toml", 'profile = "search"',
         'profile = "nowhere"'), template_files(), ("nowhere", "does not declare"), {}),
        ("critical without the egress guard's shape", changed("services/part.toml", 'criticality = "core"',
         'criticality = "critical"'), template_files(), ("would refuse", "critical"), {}),
        ("a claim recorded outside recordings/<id>/", changed("services/part.toml", "recordings/part/indexers.json",
         "recordings/other/x.json"), template_files(), ("outside recordings/part/",), {}),
        ("a claim naming a recording the stack does not hold", changed("services/part.toml",
         "recordings/part/indexers.json", "recordings/part/gone.json"), template_files(),
         ("recordings/part/gone.json", "not in the tree"), {}),
        ("a starting file that is a symbolic link", STACK_FILES, template_files(), ("config/part/", "symbolic link"),
         {"links": {"config/part/linked.ini": "../../stack.toml"}}),
        ("a wiring row that is neither an ask nor a link", changed("stack.toml", 'to = "other"',
         'to = "other"\nasks = "x.y"'), template_files(), ("neither an ask nor a link",), {}),
        ("a template file nothing says what becomes of", STACK_FILES, {**template_files(), "surprise.txt": "?\n"},
         ("surprise.txt", "neither kept"), {}),
        ("a variant README the converter would not write", STACK_FILES,
         {**template_files(), f"{convert.VARIANT}/README.md": "# Own\n"}, ("README.md", "disagree"), {}),
        ("a part id that climbs out", STACK_FILES, template_files(), ("not a plain id",), {"name": "../stack"}),
        ("a part id that is absolute", STACK_FILES, template_files(), ("not a plain id",), {"name": "/etc"}),
        ("a recording that climbs out", changed("services/part.toml", "recordings/part/indexers.json",
         "recordings/part/../../stack.toml"), template_files(), ("not a plain relative path",), {}),
        ("a recording that is absolute", changed("services/part.toml", "recordings/part/indexers.json",
         "/etc/passwd"), template_files(), ("not a plain relative path",), {}),
        ("a recording written with backslashes", changed("services/part.toml", "recordings/part/indexers.json",
         "recordings\\\\part\\\\indexers.json"), template_files(), ("not a plain relative path",), {}),
        ("a recording holding a NUL", changed("services/part.toml", "recordings/part/indexers.json",
         "recordings/part/indexers\\u0000.json"), template_files(), ("not a plain relative path",), {}),
        ("a recording reached through a symbolic link", changed("services/part.toml",
         "recordings/part/indexers.json", "recordings/linked/indexers.json"), template_files(),
         ("symbolic link",), {"links": {"recordings/linked": "part"}}),
        ("a directory already holding something", STACK_FILES, template_files(), ("not an empty directory",),
         {"prepared": True}),
        ("a directory outside the working directory", STACK_FILES, template_files(),
         ("not beneath the working directory",), {"outside": True}),
    ]
    cases: list[Case] = []
    for what, stack, template, words, extra in shapes:
        code, refused, _, _, held = ran(stack, template, **extra)
        nothing = set(held) <= {"already"}
        cases.append((f"refused, by name, with nothing written: {what}", True,
                      code is None and says(refused, *words) and nothing))
    return cases


def proving_cases() -> list[Case]:
    code, refused, _, _, held = ran(STACK_FILES, template_files(), binary=True)
    report = held.get("proofs.json", b"").decode()
    return [
        ("with a build given, the template's reader writes proofs.json for the part, asking that build",
         True, code == 0 and not refused and '"asked": "' in report and report.count("lemonfiber") == 2
         and '"of": "schema_version = 1"' in report),
    ]


def write_cases() -> list[Case]:
    cases: list[Case] = []
    for what, path in (("climbs out", "../escaped"), ("is absolute", "/tmp/escaped"),
                       ("uses a backslash", "a\\..\\escaped"), ("holds a NUL", "a\0b"),
                       ("climbs out from inside", "config/../../escaped"), ("is the directory itself", ".")):
        scratch = pathlib.Path(tempfile.mkdtemp())
        SCRATCH.append(scratch)
        out = scratch / "out"
        out.mkdir()
        try:
            convert.write(out, {"plugin.toml": b"x", path: b"y"}, set())
            refused = False
        except convert.Refused as refusal:
            refused = says(refusal.problems, "not a path inside")
        cases.append((f"nothing is written where a path {what}", True,
                      refused and not any(out.iterdir()) and not (scratch / "escaped").exists()))
    scratch = pathlib.Path(tempfile.mkdtemp())
    SCRATCH.append(scratch)
    out = scratch / "out"
    (out / "config").mkdir(parents=True)
    os.symlink(scratch, out / "config" / "linked")
    try:
        convert.write(out, {"config/linked/escaped": b"y"}, set())
        refused = False
    except convert.Refused:
        refused = True
    cases.append(("nothing is written through a symbolic link in the directory", True,
                  refused and not (scratch / "escaped").exists()))
    return cases


def option_cases() -> list[Case]:
    scratch = pathlib.Path(tempfile.mkdtemp())
    SCRATCH.append(scratch)
    committed(scratch / "stack", STACK_FILES)
    try:
        convert.snapshot(scratch / "stack", "--output=/tmp/x", scratch / "into")
        refused = False
    except OSError as why:
        refused = "not a revision" in str(why)
    return [("a revision that would reach git as an option is refused", True, refused)]


def round_trip_cases() -> list[Case]:
    manifest = tomllib.loads(convert.written(tomllib.loads(OWN)))
    odd = {"schema_version": 1, "plugin": {"id": "x"},
           "service": [{"id": "x", "env": {"A B": {"setting": "x:y", "default": "q\"uote\n"}},
                        "publish": [{"port": 1}, {"port": 2, "listens": 3}]}],
           "claim": [{"capability": "c", "probe": [{"id": "p", "expect": {"json": {"a": [1, True]}}}]}]}
    return [
        ("a manifest reads back as what it was written from", True, manifest == tomllib.loads(OWN)),
        ("quoted keys, a section, arrays of tables and nested values read back", True,
         tomllib.loads(convert.written(odd)) == odd),
    ]


def self_test() -> int:
    """Each rule, against the shape it exists to refuse."""
    failures = 0
    try:
        cases = [*written_cases(), *readme_cases(), *refusal_cases(), *proving_cases(), *write_cases(), *option_cases(),
                 *round_trip_cases()]
    finally:
        for scratch in SCRATCH:
            shutil.rmtree(scratch, ignore_errors=True)
    for what, expected, got in cases:
        print(f"  {'ok  ' if expected == got else 'FAIL'} {what}")
        failures += expected != got
    print("\nself-test passed." if not failures else f"\n{failures} rule(s) did not hold.")
    return 1 if failures else 0

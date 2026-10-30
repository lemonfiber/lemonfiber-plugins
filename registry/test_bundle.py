"""`bundle.py --self-test`: each rule of the bundle and its copies, against the shape it
exists to refuse, at both schemas, and the tree digest against its vector."""

from __future__ import annotations

import contextlib
import io
import os
import pathlib
import tempfile

import check
import entry as entries_module
import index
import parts
import tree

import bundle

Case = tuple[str, bool, bool]

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

OTHER = {**PIN, "id": "komga", "origin": "https://github.com/lemonfiber/plugin-komga"}

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

OPENING = "schema = 1\n\n"

A_COMMIT = "5e3ef10f7037f6a53d5bfd2cf87ed1c69cbc4387"


def bundle_of(*pins: dict) -> str:
    return OPENING + bundle.rendered(list(pins))


def refuses(call, *refusals: type[Exception]) -> bool:
    """Whether `call` refuses, with one of `refusals` or a bundle `Refusal`."""
    try:
        call()
    except (bundle.Refusal, *refusals):
        return True
    return False


def shapes() -> list[Case]:
    """`read` at schema 1, against each shape of bundle it exists to refuse."""
    good = bundle_of(PIN)
    refused = [
        ("a schema this does not read refused", good.replace("schema = 1", "schema = 3")),
        ("a schema that is true refused", good.replace("schema = 1", "schema = true")),
        ("a bundle naming no list refused", "schema = 1\n"),
        ("a key a bundle does not say refused", "forms = []\n" + good),
        ("a stack table at schema 1 refused", 'profile = []\n' + good),
        ("a pin missing a field refused", good.replace('fills    = ["media.serve"]\n', "")),
        ("a field a pin does not say refused", good + 'note     = "no"\n'),
        ("an id that is not one refused", good.replace('"jellyfin"', '"Jellyfin"')),
        ("an ssh origin refused", good.replace("https://github.com/", "ssh://git@github.com/")),
        ("a branch where a revision belongs refused", good.replace(f'"{PIN["revision"]}"', '"main"')),
        ("a release carrying its v refused", good.replace('"0.18.0"', '"v0.18.0"')),
        ("a pre-release refused", good.replace('"0.18.0"', '"0.18.0-rc.1"')),
        ("a release with a leading zero refused", good.replace('"0.18.0"', '"0.018.0"')),
        ("a release of two numbers refused", good.replace('"0.18.0"', '"0.18"')),
        ("a digest without its algorithm refused", good.replace(index.DIGEST, "")),
        ("fills that is not a list refused", good.replace('["media.serve"]', '"media.serve"')),
        ("a capability filled twice refused", good.replace('["media.serve"]', '["media.serve", "media.serve"]')),
        ("one plugin pinned twice refused", OPENING + bundle.rendered([PIN]) + "\n" + bundle.rendered([PIN])),
        ("one origin pinned under two ids refused", bundle_of(PIN, {**OTHER, "origin": PIN["origin"]})),
        ("pins out of id order refused", OPENING + bundle.rendered([OTHER]) + "\n" + bundle.rendered([PIN])),
        ("a pin written another way refused", good.replace("id       =", "id =")),
    ]
    named_both = ""
    try:
        bundle.read(good.replace("schema = 1", "schema = 3"))
    except bundle.Refusal as refusal:
        named_both = str(refusal)
    return [
        ("an empty bundle is read", False, refuses(lambda: bundle.read(EMPTY))),
        ("a bundle of two pins is read", False, refuses(lambda: bundle.read(bundle_of(PIN, OTHER)))),
        ("the bundle writes back what it reads", True, OPENING + bundle.rendered(bundle.read(good).pins) == good),
        ("a refused schema names both it reads", True, "1 and 2" in named_both),
        *((what, True, refuses(lambda text=text: bundle.read(text))) for what, text in refused),
    ]


def pairs() -> list[Case]:
    """`copies` and `paired` over a directory of schema 1 copies."""
    with tempfile.TemporaryDirectory() as box:
        directory = pathlib.Path(box)
        (directory / bundle.PLACEHOLDER).touch()
        (directory / "jellyfin.toml").write_bytes(COPY)
        found = bundle.copies(directory)
        said = [
            ("the placeholder is not a copy", True, set(found) == {"jellyfin"}),
            ("a pin and its copy pair", True, not bundle.paired([PIN], found)),
            ("a copy no pin names refused", True, bool(bundle.paired([], found))),
            ("a pin with no copy refused", True, bool(bundle.paired([PIN, OTHER], found))),
        ]
        pinned = {**PIN, "manifest": index.digest(COPY)}
        with contextlib.redirect_stdout(io.StringIO()):
            said += [
                ("copies that are the bytes their pins name hold offline", True,
                 bundle.offline_holds(bundle.Bundle(1, [pinned]), found) == 0),
                ("a copy that is not the bytes its pin names refused offline", True,
                 bundle.offline_holds(bundle.Bundle(1, [PIN]), found) == 1),
            ]
        (directory / "notes.md").write_text("no", encoding="utf-8")
        said.append(("a file that is not a copy refused", True, refuses(lambda: bundle.copies(directory))))
        (directory / "notes.md").unlink()
        said.append(("a directory is not a copy at schema 1", True, refuses(
            lambda: (directory / "komga").mkdir() or bundle.copies(directory))))
        return said


def held_copies() -> list[Case]:
    """`held_to_pin`, against each way a schema 1 copy can fail to say what its pin says."""
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
        ("a copy that says what its pin says holds", True, not bundle.held_to_pin(pinned, COPY)),
        ("a copy whose digest is not its pin's refused", True, bool(bundle.held_to_pin(PIN, COPY))),
        *((what, True, bool(bundle.held_to_pin({**PIN, "manifest": index.digest(text)}, text)))
          for what, text in changed),
        ("a capability spoken by the adapter may be filled", True,
         not bundle.held_to_pin({**pinned, "fills": ["identity.source"]}, COPY)),
        ("a capability the copy neither provides nor speaks refused", True,
         bool(bundle.held_to_pin({**pinned, "fills": ["request.intake"]}, COPY))),
    ]


def moves() -> list[Case]:
    """`released`, `moved` and `wanted` at schema 1: what a move takes, keeps and carries."""
    to = bundle.moved(PIN, "f" * 40, COPY)
    rolling = [{**PIN, "revision": "a" * 40}, {**OTHER, "revision": "b" * 40}]
    unreleased = [
        ("a manifest with no adapter has no release", COPY.replace(b"speaks", b"listens")),
        ("adapters at two releases have no release",
         COPY + b'\n[[service]]\nid = "second"\ntag = "0.17.0"\nspeaks = ["media.serve@1"]\n'),
        ("an adapter tagged with its v has no release", COPY.replace(b'"0.18.0"', b'"v0.18.0"')),
        ("an adapter tagged at a pre-release has no release", COPY.replace(b'"0.18.0"', b'"0.18.0-rc.1"')),
    ]
    return [
        ("the release is the adapter's tag", True, bundle.released(COPY) == "0.18.0"),
        *((what, True, refuses(lambda text=text: bundle.released(text))) for what, text in unreleased),
        ("a move takes the revision, the release and the digest", True,
         (to["revision"], to["release"], to["manifest"]) == ("f" * 40, "0.18.0", index.digest(COPY))),
        ("a move keeps what a person chose", True, (to["origin"], to["fills"]) == (PIN["origin"], PIN["fills"])),
        ("a move to a branch refused", True,
         refuses(lambda: bundle.moved(PIN, "main", COPY), entries_module.Refusal)),
        ("a move to a manifest that cannot fill the pin refused", True,
         refuses(lambda: bundle.moved({**PIN, "fills": ["request.intake"]}, "f" * 40, COPY))),
        ("the rolling branch's other moves are carried, the one asked last", True,
         bundle.wanted(("komga", "c" * 40), rolling, [PIN, OTHER]) == [("jellyfin", "a" * 40), ("komga", "c" * 40)]),
        ("a pin the rolling branch holds where main does is not moved again", True,
         bundle.wanted(("komga", "c" * 40), [PIN], [PIN, OTHER]) == [("komga", "c" * 40)]),
        ("a pin main no longer holds is not carried", True,
         bundle.wanted(("jellyfin", "c" * 40), rolling, [PIN]) == [("jellyfin", "c" * 40)]),
    ]


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
        return bundle.on_main(str(origin), held), bundle.on_main(str(origin), forked)


def bindings() -> list[Case]:
    """`bound`, `applied` and `on_main`: who may move a pin, and to what."""
    good = bundle_of(PIN)
    with tempfile.TemporaryDirectory() as box:
        directory = pathlib.Path(box)
        (directory / bundle.BUNDLE_FILE).write_text(good, encoding="utf-8")
        elsewhere = refuses(lambda: bundle.applied(("jellyfin", "f" * 40), OTHER["origin"], None,
                                                   directory / bundle.BUNDLE_FILE, directory))
        untouched = (directory / bundle.BUNDLE_FILE).read_text(encoding="utf-8") == good
    on, off = ancestry()
    return [
        ("a move asked for by another repository refused, the bundle untouched", True, elsewhere and untouched),
        ("a move asked for by the pinned repository is bound to it", False,
         refuses(lambda: bundle.bound([PIN], "jellyfin", PIN["origin"] + ".git"))),
        ("a move of a plugin the bundle does not pin refused", True,
         refuses(lambda: bundle.bound([PIN], "komga", OTHER["origin"]))),
        ("a revision on the origin's default branch is on it", True, on is None),
        ("a revision only on another branch refused", True, off is not None),
    ]


def vector() -> list[Case]:
    """The tree digest, against the vector any reader of it can be held to (ARCH-R267)."""
    with tempfile.TemporaryDirectory() as box:
        root = pathlib.Path(box)
        for path, content in tree.VECTOR_FILES.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_bytes(content)
        files = tree.read(root, tree.manifest_of(root))
        (root / "config" / "example" / "linked").symlink_to(root / "README.md")
        linked = refuses(lambda: tree.read(root, tree.manifest_of(root)), tree.Unreadable)
        (root / "config" / "example" / "linked").unlink()
        (root / "recordings" / "example" / "catalogue.json").unlink()
        unrecorded = refuses(lambda: tree.read(root, tree.manifest_of(root)), tree.Unreadable)
    return [
        ("the tree is the manifest, starting files, named recordings and conformance", True,
         [path for path, _ in files] == tree.VECTOR_PATHS),
        ("the listing is sha256sum's, sorted bytewise", True, tree.listing(files) == tree.VECTOR_LISTING),
        ("the digest is the vector's", True, tree.digest(files) == tree.VECTOR_DIGEST),
        ("a symbolic link in a tree refused", True, linked),
        ("a recording the manifest names and the tree lacks refused", True, unrecorded),
        ("a recording outside the repository refused", True, not tree.relative("../fixtures/a.json")),
        ("too many starting files refused", True, refuses(lambda: crowded(tree.MOST_STARTING_FILES + 1, 1),
                                                          tree.Unreadable)),
        ("starting files too heavy refused", True, refuses(lambda: crowded(1, tree.MOST_STARTING_BYTES + 1),
                                                           tree.Unreadable)),
        ("starting files at the bounds are read", False, refuses(lambda: crowded(tree.MOST_STARTING_FILES, 1),
                                                                 tree.Unreadable)),
    ]


def crowded(count: int, size: int) -> list:
    """A tree whose one service starts with `count` files of `size` bytes."""
    with tempfile.TemporaryDirectory() as box:
        root = pathlib.Path(box)
        (root / "config" / "one").mkdir(parents=True)
        (root / tree.MANIFEST).write_bytes(b"")
        for number in range(count):
            (root / "config" / "one" / f"{number}.conf").write_bytes(b"x" * size)
        return tree.read(root, {"service": [{"id": "one"}]})


SAB = b"""schema_version = 1

[plugin]
id = "sabnzbd"
upstream = "https://github.com/sabnzbd/sabnzbd"
license = "GPL-2.0-only"
forms = ["dl", "full"]

[[service]]
id = "sabnzbd"
image = "docker.io/linuxserver/sabnzbd"
tag = "4.5.3"
port = 8080
bind = "loopback"
criticality = "enhancing"
reaches = "The Usenet servers you name"
asks_for = "The articles a download needs"
provides = ["download.usenet"]

[[claim]]
capability = "download.usenet"

[[claim.probe]]
id = "queue"
fixture = "recordings/sabnzbd/queue.json"
"""

JELLY = b"""schema_version = 1

[plugin]
id = "jellyfin"
upstream = "https://github.com/jellyfin/jellyfin"
license = "GPL-2.0-only"
forms = ["full"]

[[service]]
id = "jellyfin"
image = "docker.io/jellyfin/jellyfin"
tag = "10.10.7"
port = 8096
bind = "lan"
criticality = "essential"
reaches = ""
asks_for = "Nothing"
provides = ["media.serve"]
replaces = "jellyfin"

[[service]]
id = "jellyfin-adapter"
image = "ghcr.io/lemonfiber/plugin-jellyfin"
tag = "0.18.0"
reaches = ""
asks_for = "Nothing"
speaks = ["media.serve@1", "identity.source@1"]
fronts = "jellyfin"

[[ask]]
service = "jellyfin"
capability = "download.usenet"
"""

CADDY = b"""schema_version = 1

[plugin]
id = "caddy"
upstream = "https://github.com/caddyserver/caddy"
license = "Apache-2.0"
forms = ["full"]

[[service]]
id = "caddy"
image = "docker.io/library/caddy"
tag = "2.11.6"
port = 80
bind = "lan"
criticality = "optional"
reaches = ""
asks_for = "Nothing"
provides = ["proxy.front"]
"""

CADDYFILE = b"""# Routes.
watch.{$DOMAIN:home.local} {
\treverse_proxy jellyfin:8096
}

# sabnzbd.{$DOMAIN:home.local} { reverse_proxy sabnzbd:8080 }
"""

TREES = {
    "sabnzbd": {
        "plugin.toml": SAB,
        "config/sabnzbd/sabnzbd.ini": b"[misc]\nport = 8080\n",
        "recordings/sabnzbd/queue.json": b'{"status": 200}\n',
    },
    "jellyfin": {
        "plugin.toml": JELLY,
        "conformance/media.serve.json": b"{}\n",
    },
    "caddy": {
        "plugin.toml": CADDY,
        "config/caddy/Caddyfile": CADDYFILE,
    },
}

STACK = """schema = 2

[[profile]]
id          = "usenet"
name        = "Usenet"
description = "Usenet downloading"
protocol    = "usenet"

[[profile]]
id          = "media"
name        = "Media"
description = "Serving the library"

[[form]]
id          = "dl"
name        = "Download"
description = "Download from Usenet"
profiles    = ["usenet"]

[[form]]
id          = "full"
name        = "Everything"
description = "All of it"
profiles    = ["usenet", "media"]

[[wiring]]
by        = "jellyfin"
asks      = "download.usenet"
filled_by = "sabnzbd"
why       = "The one download client here."

[[wiring]]
by  = "sabnzbd"
to  = "jellyfin"
why = "It is about that service."

[[removed]]
id          = "readarr"
removed_in  = "0.1.0"
reason      = "Discontinued upstream."
replaced_by = "sabnzbd"

"""


def pinned(name: str, files: dict[str, bytes], **fields: object) -> dict:
    """A schema 2 pin for a tree, with its digests taken from it."""
    pin = {
        "id": name,
        "origin": f"https://github.com/lemonfiber/plugin-{name}",
        "revision": "1" * 40,
        "manifest": index.digest(files["plugin.toml"]),
        "tree": tree.digest(list(files.items())),
        "fills": [],
        "stage": "assembled",
        "profile": "media",
        "last_release": "2026-01-01",
    }
    return {**pin, **fields}


PINS = {
    "sabnzbd": pinned("sabnzbd", TREES["sabnzbd"], fills=["download.usenet"], profile="usenet"),
    "jellyfin": pinned("jellyfin", TREES["jellyfin"], release="0.18.0", fills=["media.serve", "identity.source"],
                       stage="installed"),
    "caddy": pinned("caddy", TREES["caddy"], fills=["proxy.front"]),
}


def stack_of(pins: dict[str, dict]) -> str:
    return STACK + bundle.rendered(list(pins.values()), 2)


def laid(directory: pathlib.Path, trees: dict[str, dict[str, bytes]]) -> dict[str, pathlib.Path]:
    """Copies of `trees` under `directory`, as the bundle holds them."""
    for name, files in trees.items():
        for path, content in files.items():
            (directory / name / path).parent.mkdir(parents=True, exist_ok=True)
            (directory / name / path).write_bytes(content)
    return bundle.copies(directory, 2)


def offline(text: str, trees: dict[str, dict[str, bytes]] | None = None) -> list[str]:
    """Every problem the bundle `text` and copies of `trees` have, with nothing fetched."""
    with tempfile.TemporaryDirectory() as box:
        try:
            read = bundle.read(text)
        except bundle.Refusal as refusal:
            return refusal.problems
        held = laid(pathlib.Path(box), TREES if trees is None else trees)
        unpaired = bundle.paired(read.pins, held, 2)
        if unpaired:
            return unpaired
        return [line for lines in bundle.offline_problems(read, held).values() for line in lines]


def changed(name: str, path: str, old: bytes, new: bytes) -> tuple[str, dict[str, dict[str, bytes]]]:
    """The bundle and its copies with one file of one tree changed, the pin following it."""
    trees = {key: dict(files) for key, files in TREES.items()}
    trees[name][path] = trees[name][path].replace(old, new)
    pins = dict(PINS)
    kept = {key: value for key, value in PINS[name].items()
            if key not in ("manifest", "tree", "id")}
    pins[name] = pinned(name, trees[name], **kept)
    return stack_of(pins), trees


def stack_shapes() -> list[Case]:
    """`read` at schema 2, against each shape of the stack's tables it exists to refuse."""
    good = stack_of(PINS)
    refused = [
        ("a profile with no name refused", good.replace('name        = "Usenet"\n', "")),
        ("a profile with a field it does not say refused", good.replace('protocol    = "usenet"\n',
                                                                       'protocol    = "usenet"\ncolour = "x"\n')),
        ("a protocol that is not one refused", good.replace('protocol    = "usenet"', 'protocol    = "ftp"')),
        ("two profiles of one protocol refused", good.replace(
            'description = "Serving the library"', 'description = "Serving the library"\nprotocol = "usenet"')),
        ("a profile declared twice refused", good.replace('id          = "media"', 'id          = "usenet"')),
        ("a form naming an undeclared profile refused", good.replace('["usenet", "media"]', '["usenet", "tv"]')),
        ("composable that is not a bool refused", good.replace('profiles    = ["usenet"]\n',
                                                              'profiles    = ["usenet"]\ncomposable = "yes"\n')),
        ("a removed service that is pinned refused", good.replace('id          = "readarr"', 'id          = "caddy"')),
        ("a removed service with no reason refused", good.replace('reason      = "Discontinued upstream."\n', "")),
        ("a replaced_by naming no pinned plugin refused", good.replace('replaced_by = "sabnzbd"',
                                                                      'replaced_by = "bindery"')),
        ("a wiring with both asks and to refused", good.replace('filled_by = "sabnzbd"',
                                                               'filled_by = "sabnzbd"\nto = "caddy"')),
        ("a wiring with neither asks nor to refused", good.replace('to  = "jellyfin"\n', "")),
        ("an ask without filled_by refused", good.replace('filled_by = "sabnzbd"\n', "")),
        ("filled_by without asks refused", good.replace('to  = "jellyfin"', 'to  = "jellyfin"\nfilled_by = "caddy"')),
        ("a blank why refused", good.replace('why = "It is about that service."', 'why = " "')),
        ("a wiring naming its own by refused", good.replace('to  = "jellyfin"', 'to  = "sabnzbd"')),
        ("a wiring repeated refused", good.replace("[[removed]]",
                                                   '[[wiring]]\nby = "sabnzbd"\nto = "jellyfin"\nwhy = "Again."\n\n'
                                                   "[[removed]]")),
        ("a pin in an undeclared profile refused", good.replace('profile      = "usenet"', 'profile      = "tv"')),
        ("a stage that is not one refused", good.replace('stage        = "installed"', 'stage        = "running"')),
        ("a last release in the future refused", good.replace('"2026-01-01"', '"2999-01-01"', 1)),
        ("a last release that is not a date refused", good.replace('"2026-01-01"', '"2026-13-01"', 1)),
        ("a pin without its tree refused", good.replace(f'tree         = "{PINS["caddy"]["tree"]}"\n', "")),
        ("a tree digest without its algorithm refused", good.replace(f'"{PINS["caddy"]["tree"]}"',
                                                                    f'"{PINS["caddy"]["tree"][7:]}"')),
        ("a pre-release refused", good.replace('"0.18.0"', '"0.18.0-rc.1"')),
        ("a table the bundle does not say refused", "service = []\n" + good),
        ("plugin = [] beside the stack's tables refused", good.replace("schema = 2\n", "schema = 2\nplugin = []\n")),
        ("pins before the stack's tables refused",
         "schema = 2\n\n" + bundle.rendered(list(PINS.values()), 2) + "\n" + STACK.removeprefix("schema = 2\n")),
    ]
    return [
        ("a schema 2 bundle is read", False, refuses(lambda: bundle.read(good))),
        ("a schema 2 bundle with no pins is read", False,
         refuses(lambda: bundle.read(STACK.replace('replaced_by = "sabnzbd"\n', "")))),
        ("a schema 2 bundle writes back what it reads", True,
         STACK + bundle.rendered(bundle.read(good).pins, 2) == good),
        ("a release is optional at schema 2", True, "release" not in bundle.read(good).pins[0]),
        *((what, True, refuses(lambda text=text: bundle.read(text))) for what, text in refused),
    ]


def tree_refusals() -> list[tuple[str, str, tuple[str, dict]]]:
    """Each way a schema 2 copy can fail its pin or the contract, what is said of it, and the
    bundle and copies, each pin following its digests."""
    return [
        ("an assembled plugin of two services refused", 'declares 2 services, not exactly one',
         changed("sabnzbd", "plugin.toml", b"[[claim]]", b'[[service]]\nid = "extra"\nreaches = ""\n'
                 b'asks_for = "x"\n\n[[claim]]')),
        ("an assembled plugin that speaks a contract refused", "service 'sabnzbd' speaks",
         changed("sabnzbd", "plugin.toml", b'provides = ["download.usenet"]',
                 b'provides = ["download.usenet"]\nspeaks = ["download.usenet@1"]')),
        ("an assembled plugin whose one service is another's refused", "its one service is 'nzb', not 'sabnzbd'",
         changed("sabnzbd", "plugin.toml", b'id = "sabnzbd"\nimage', b'id = "nzb"\nimage')),
        ("an assembled plugin's claim recorded outside recordings/<id>/ refused", 'outside recordings/sabnzbd/',
         changed("sabnzbd", "plugin.toml", b'"recordings/sabnzbd/queue.json"', b'"config/sabnzbd/sabnzbd.ini"')),
        ("an installed plugin's service not replacing its id refused", 'jellyfin.replaces is None',
         changed("jellyfin", "plugin.toml", b'replaces = "jellyfin"\n', b"")),
        ("an installed plugin naming an in-process adapter refused", 'jellyfin-adapter.api',
         changed("jellyfin", "plugin.toml", b'fronts = "jellyfin"', b'fronts = "jellyfin"\napi = { kind = "x" }')),
        ("replaces naming another id refused", "caddy.replaces 'x' is not its own id",
         changed("caddy", "plugin.toml", b'provides = ["proxy.front"]', b'provides = ["proxy.front"]\nreplaces = "x"')),
        ("a copy declaring another [plugin].id refused", "[plugin].id 'proxy', not 'caddy'",
         changed("caddy", "plugin.toml", b'id = "caddy"\nupstream', b'id = "proxy"\nupstream')),
        ("a service without asks_for refused", 'does not declare both reaches and asks_for',
         changed("caddy", "plugin.toml", b'asks_for = "Nothing"\n', b"")),
        ("a blank asks_for refused", 'caddy.asks_for is blank',
         changed("caddy", "plugin.toml", b'asks_for = "Nothing"', b'asks_for = ""')),
        ("critical without the egress guard's shape refused", 'critical without shape',
         changed("caddy", "plugin.toml", b'"optional"', b'"critical"')),
        ("forms that are not the profile's closures refused", "[plugin].forms is ['dl']",
         changed("sabnzbd", "plugin.toml", b'forms = ["dl", "full"]', b'forms = ["dl"]')),
        ("a licence that is not OSI refused", "'Plex-EULA' is not an OSI identifier",
         changed("caddy", "plugin.toml", b'"Apache-2.0"', b'"Plex-EULA"')),
        ("lemonfiber's own image under another licence refused", 'carries Hippocratic-3.0',
         changed("jellyfin", "plugin.toml", b'"https://github.com/jellyfin/jellyfin"',
                 b'"https://github.com/lemonfiber/plugin-jellyfin"')),
        ("a built image not tagged at the release refused", "not the pinned release '0.18.0'",
         changed("jellyfin", "plugin.toml", b'tag = "0.18.0"', b'tag = "main-0123456789ab"')),
        ("a fill nothing provides refused", "fills 'proxy.front'",
         changed("caddy", "plugin.toml", b'provides = ["proxy.front"]', b"provides = []")),
        ("a port reserved twice refused", "port '8096' is reserved by caddy and jellyfin",
         changed("caddy", "plugin.toml", b"port = 80", b"port = 8096")),
        ("a hostname reserved twice refused", "hostname 'jellyfin' is reserved by caddy and jellyfin",
         changed("caddy", "plugin.toml", b'provides = ["proxy.front"]',
                 b'provides = ["proxy.front"]\n\n[[wiring]]\nhostname = "jellyfin"')),
        ("a hostname the proxy's configuration answers on, taken by another, refused", "hostname 'jellyfin' is reserved by caddy and jellyfin",
         changed("caddy", "config/caddy/Caddyfile", b"# Routes.", b"jellyfin.{$DOMAIN} { reverse_proxy nowhere:1 }")),
        ("a wiring by a plugin that does not ask it refused", "asks no 'download.usenet'",
         changed("jellyfin", "plugin.toml", b'capability = "download.usenet"', b'capability = "indexer.search"')),
        ("a wiring by a plugin that asks each refused", 'of each filler',
         changed("jellyfin", "plugin.toml", b'capability = "download.usenet"',
                 b'capability = "download.usenet"\neach = true')),
        ("a filled_by that does not fill the capability refused", 'sabnzbd neither provides nor speaks',
         changed("sabnzbd", "plugin.toml", b'provides = ["download.usenet"]', b'provides = ["download.torrent"]')),
    ]


def trees_held() -> list[Case]:
    """Each schema 2 copy against its pin and the contract, offline (ARCH-R266, ARCH-R267, ARCH-R269)."""
    good = stack_of(PINS)
    stray = {key: dict(files) for key, files in TREES.items()}
    stray["caddy"]["notes.md"] = b"no\n"
    unpinned = {key: dict(files) for key, files in TREES.items()}
    unpinned["caddy"]["config/caddy/Caddyfile"] += b"\n"
    released_without_image = stack_of({**PINS, "caddy": {**PINS["caddy"], "release": "0.18.0"}})
    unbuilt_jelly = changed("jellyfin", "plugin.toml", b'"ghcr.io/lemonfiber/plugin-jellyfin"',
                            b'"docker.io/jellyfin/adapter"')
    return [
        ("copies that are their pins' trees hold", True, offline(good) == []),
        ("a hostname the proxy answers on for the service holding it is not taken twice", True, offline(
            *changed("caddy", "config/caddy/Caddyfile", b"# Routes.",
                     b"jellyfin.{$DOMAIN} { reverse_proxy jellyfin:8096 }")) == []),
        *((what, True, any(said in line for line in offline(*case))) for what, said, case in tree_refusals()),
        ("a file in a copy outside the plugin's tree refused", True, bool(offline(good, stray))),
        ("a copy whose tree is not its pin's refused", True, bool(offline(good, unpinned))),
        ("a release named by a plugin that builds no image refused", True, bool(offline(released_without_image))),
        ("a pin of an image-building plugin may name no release", True, offline(
            stack_of({**PINS, "jellyfin": {k: v for k, v in PINS["jellyfin"].items() if k != "release"}})) == []),
        ("a release names a plugin that builds an image", True, bool(offline(*unbuilt_jelly))),
        ("a copy no pin names refused", True,
         bool(offline(stack_of({k: v for k, v in PINS.items() if k != "caddy"})))),
    ]


def proxy() -> list[Case]:
    """What a proxy configuration answers on, as the reserved register reads it."""
    text = (
        "# prose about {$DOMAIN} with no label\n"
        "watch.{$DOMAIN:home.local} {\n\treverse_proxy door:8096\n}\n"
        "# sonarr.{$DOMAIN:home.local}      { reverse_proxy sonarr:8989 }\n"
        "bare.{$DOMAIN:home.local} {\n\trespond 404\n}\n"
    )
    return [
        ("each label is read with the service it routes to, commented-out ones included", True,
         parts.answered(text) == [("watch", "door"), ("sonarr", "sonarr"), ("bare", None)]),
    ]


def tree_moves() -> list[Case]:
    """`released` and `moved_tree` at schema 2: the release is every built image's tag."""
    read = bundle.read(stack_of(PINS))
    with tempfile.TemporaryDirectory() as box:
        source = pathlib.Path(box)
        laid(source, {"jellyfin": TREES["jellyfin"], "caddy": TREES["caddy"]})
        to, files = bundle.moved_tree(PINS["jellyfin"], "f" * 40, source / "jellyfin", read)
        unbuilt = refuses(lambda: bundle.moved_tree(PINS["caddy"], "f" * 40, source / "caddy", read))
    return [
        ("a move takes the release from the images the plugin builds", True, to["release"] == "0.18.0"),
        ("a move takes the revision and both digests", True,
         (to["revision"], to["manifest"], to["tree"]) == ("f" * 40, PINS["jellyfin"]["manifest"],
                                                          PINS["jellyfin"]["tree"])),
        ("a move carries the tree", True, [path for path, _ in files] == sorted(TREES["jellyfin"])),
        ("a plugin that builds no image is not moved by the train", True, unbuilt),
    ]


def committed(origin: pathlib.Path, files: dict[str, bytes]) -> str:
    """A repository at `origin` whose default branch holds `files`, and its commit."""
    git = ("git", "-c", "user.name=self-test", "-c", "user.email=self-test@invalid",
           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null")
    origin.mkdir(parents=True)
    check.ran("git", "init", "--quiet", "--initial-branch=main", at=origin)
    for path, content in files.items():
        (origin / path).parent.mkdir(parents=True, exist_ok=True)
        (origin / path).write_bytes(content)
    check.ran("git", "add", "--all", at=origin)
    check.ran(*git, "commit", "--quiet", "-m", "tree", at=origin)
    return check.ran("git", "rev-parse", "HEAD", at=origin).stdout.strip()


@contextlib.contextmanager
def served(origin: pathlib.Path, address: str):
    """Fetches of `address` served from `origin`, as a forge would serve them."""
    said = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{origin}.insteadOf", "GIT_CONFIG_VALUE_0": address}
    kept = {key: os.environ.get(key) for key in said}
    os.environ.update(said)
    try:
        yield
    finally:
        for key, value in kept.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def tree_apply() -> list[Case]:
    """`applied` at schema 2, against an origin served locally: the train's whole move."""
    with tempfile.TemporaryDirectory() as box:
        root = pathlib.Path(box)
        moved_files = {**TREES["jellyfin"], "conformance/media.serve.json": b'{"moved": true}\n'}
        revision = committed(root / "origin", {**moved_files, "README.md": b"# not carried\n"})
        catalogue = root / "catalogue"
        held = catalogue / "plugins"
        laid(held, TREES)
        (catalogue / bundle.BUNDLE_FILE).write_text(stack_of(PINS), encoding="utf-8")
        with served(root / "origin", PINS["jellyfin"]["origin"]), contextlib.redirect_stderr(io.StringIO()):
            moves = bundle.applied(("jellyfin", revision), PINS["jellyfin"]["origin"], None,
                                   catalogue / bundle.BUNDLE_FILE, held)
            pinned_now = next(one for one in bundle.read(
                (catalogue / bundle.BUNDLE_FILE).read_text(encoding="utf-8")).pins if one["id"] == "jellyfin")
            kept, check.holds = check.holds, lambda source, carried=None: (True, [f"carried {carried}"])
            try:
                same = bundle.held_to_origin(pinned_now, held / "jellyfin")
                (held / "jellyfin" / "conformance" / "media.serve.json").write_bytes(b"{}\n")
                drifted = bundle.held_to_origin(pinned_now, held / "jellyfin")
            finally:
                check.holds = kept
            (held / "jellyfin" / "conformance" / "media.serve.json").write_bytes(moved_files["conformance/media.serve.json"])
        after = bundle.read((catalogue / bundle.BUNDLE_FILE).read_text(encoding="utf-8"))
        copied = sorted(str(path.relative_to(held / "jellyfin")) for path in
                        (held / "jellyfin").rglob("*") if path.is_file())
        theirs = [(path, content) for path, content in moved_files.items()]
        with contextlib.redirect_stdout(io.StringIO()):
            holds = bundle.offline_holds(after, bundle.copies(held, 2)) == 0
    pin = next(one for one in after.pins if one["id"] == "jellyfin")
    return [
        ("the train moves an image-building plugin to the merged revision", True,
         [move["id"] for move in moves] == ["jellyfin"] and pin["revision"] == revision),
        ("the moved pin names the origin's tree", True, pin["tree"] == tree.digest(theirs)),
        ("the copy is the origin's tree and nothing else of it", True, copied == sorted(moved_files)),
        ("the moved bundle holds offline", True, holds),
        ("a copy that is its origin's tree holds, carrying the tree but its manifest", True,
         same == (True, ["the copy is the origin's tree at the pinned revision",
                         "carried ['conformance/media.serve.json']"])),
        ("a copy that differs from its origin's tree is refused at the path", True,
         drifted == (False, ["conformance/media.serve.json differs from the origin's"])),
        ("a copy and its origin that differ are named at the path", True,
         bundle.differing([("a", b"1"), ("b", b"2")], [("a", b"1"), ("b", b"3"), ("c", b"4")])
         == ["b differs from the origin's", "c is in the origin's tree and not in the copy"]),
    ]


def target_shapes() -> list[Case]:
    """`check.target` takes a release or a full commit of lemonfiber's main, and refuses
    anything else (`REPO-R56`)."""
    commit = A_COMMIT
    said = {
        "a release taken": ('lemonfiber = "0.17.0"\n', False),
        "a full commit of main taken": (f'commit = "{commit}"\n', False),
        "a short commit refused": (f'commit = "{commit[:12]}"\n', True),
        "a commit in capitals refused": (f'commit = "{commit.upper()}"\n', True),
        "a release and a commit both refused": (f'lemonfiber = "0.17.0"\ncommit = "{commit}"\n', True),
        "neither a release nor a commit refused": ('note = "nothing"\n', True),
        "a release that is not text refused": ("lemonfiber = 17\n", True),
        "a targets.toml that is not TOML refused": ("lemonfiber = \n", True),
    }
    cases: list[Case] = []
    kept = check.reader.TARGETS
    with tempfile.TemporaryDirectory() as box:
        check.reader.TARGETS = pathlib.Path(box) / "targets.toml"
        try:
            for what, (text, refused) in said.items():
                check.reader.TARGETS.write_text(text, encoding="utf-8")
                cases.append((what, refused, refuses(check.target, check.Unaskable)))
        finally:
            check.reader.TARGETS = kept
    named = check.reader.Target(commit, commit=True)
    cases.append(("a commit reported as main's", True, check.described(named) == f"lemonfiber's main at {commit}"))
    cases.append(("a release reported by its number", True,
                  check.described(check.reader.Target("0.17.0", commit=False)) == "lemonfiber 0.17.0"))
    return cases


def template_targets() -> list[Case]:
    """The template is asked under its own `targets.toml` while this catalogue targets a
    commit, and under this catalogue's otherwise; a registration always under this
    catalogue's (`REPO-R56`)."""
    commit = f'commit = "{A_COMMIT}"\n'
    release = 'lemonfiber = "0.16.0"\n'
    cases: list[Case] = []
    kept = check.reader.TARGETS, check.reader.CACHE
    with tempfile.TemporaryDirectory() as box:
        root = pathlib.Path(box)
        check.reader.TARGETS, check.reader.CACHE = root / "ours.toml", root / "cache"
        check.reader.CACHE.mkdir()
        try:
            for ours, template_own in ((commit, True), (release, False)):
                check.reader.TARGETS.write_text(ours, encoding="utf-8")
                said = "a commit" if template_own else "a release"
                asked = "its own" if template_own else "this catalogue's"
                cases.append((f"the template asked under {asked} targets.toml where this catalogue targets {said}",
                              template_own, check.asked_under_its_own(True)))
                cases.append((f"a registration asked under this catalogue's where it targets {said}",
                              False, check.asked_under_its_own(False)))
            source = root / "source"
            source.mkdir()
            (source / "plugin.toml").write_text('schema_version = 1\n', encoding="utf-8")
            (source / "targets.toml").write_text(release, encoding="utf-8")
            check.reader.TARGETS.write_text(commit, encoding="utf-8")
            for which, targets, expected in (("its own", source / "targets.toml", release),
                                             ("this catalogue's", check.reader.TARGETS, commit)):
                work = root / f"work-{len(cases)}"
                work.mkdir()
                check.assembled(source, work, [], targets)
                cases.append((f"the reader is handed {which} targets.toml", True,
                              (work / "targets.toml").read_text(encoding="utf-8") == expected
                              and (work / check.THEIRS).read_text(encoding="utf-8") == release))
        finally:
            check.reader.TARGETS, check.reader.CACHE = kept
    return cases


UPSTREAM_DIGEST = "sha256:" + "3a" * 32
BUILT_ON_UPSTREAM = f"FROM docker.io/jellyfin/jellyfin:10.10.7@{UPSTREAM_DIGEST}\nUSER 1000:1000\n".encode()
BUILT_ON_A_BASE = f"FROM gcr.io/distroless/static@{UPSTREAM_DIGEST}\n".encode()


def first_pins() -> list[Case]:
    """A built part's revision still running what its `Dockerfile` builds on is neither moved to
    nor held: only one running the image it builds reaches the bundle (ARCH-R285)."""
    read = bundle.read(stack_of(PINS))
    with tempfile.TemporaryDirectory() as box:
        root = pathlib.Path(box)
        trees = {name: {**TREES["jellyfin"], "Dockerfile": dockerfile} for name, dockerfile in (
            ("upstream", BUILT_ON_UPSTREAM), ("base", BUILT_ON_A_BASE),
            ("untagged", b"FROM docker.io/jellyfin/jellyfin\n"))}
        laid(root / "trees", {**trees, "none": TREES["jellyfin"]})
        unshipped = {name: parts.unshipped_problems("jellyfin", bundle.parsed(TREES["jellyfin"]["plugin.toml"]),
                                                    root / "trees" / name)
                     for name in ("upstream", "base", "untagged", "none")}
        own = bundle.parsed(TREES["jellyfin"]["plugin.toml"].replace(
            b'image = "docker.io/jellyfin/jellyfin"', b'image = "ghcr.io/lemonfiber/jellyfin"'))
        refused_move = refuses(lambda: bundle.moved_tree(PINS["jellyfin"], "f" * 40, root / "trees" / "upstream", read))
        moved_beside_a_base, _ = bundle.moved_tree(PINS["jellyfin"], "f" * 40, root / "trees" / "base", read)
        revision = committed(root / "origin", trees["upstream"])
        laid(root / "held", {"jellyfin": TREES["jellyfin"]})
        pinned = {**PINS["jellyfin"], "revision": revision}
        kept, check.holds = check.holds, lambda source, carried=None: (True, [])
        try:
            with served(root / "origin", PINS["jellyfin"]["origin"]), contextlib.redirect_stderr(io.StringIO()):
                held, said = bundle.held_to_origin(pinned, root / "held" / "jellyfin")
        finally:
            check.holds = kept
    return [
        ("the last FROM names the image, its flags, tag, digest and stage aside", True,
         [parts.built_on(text) for text in (
             f"FROM rust@{UPSTREAM_DIGEST} AS build\nFROM --platform=$BUILDPLATFORM caddy:2.11.6@{UPSTREAM_DIGEST} AS door\n",
             "from localhost:5000/x/y:1\n", "RUN true\n")] == ["caddy", "localhost:5000/x/y", None]),
        ("a part still running what its Dockerfile builds on ships nothing, at any digest", True,
         bool(unshipped["upstream"]) and bool(unshipped["untagged"])
         and "ghcr.io/lemonfiber/jellyfin" in unshipped["upstream"][0]),
        ("a Dockerfile building on another image, or none, ships", True,
         unshipped["base"] == [] and unshipped["none"] == []),
        ("a part running the image it builds ships", True,
         parts.unshipped_problems("jellyfin", own, root) == []),
        ("the train does not move a pin to a revision before its first pin", True, refused_move),
        ("the train moves a pin to a revision building on another image", True,
         moved_beside_a_base["revision"] == "f" * 40),
        ("a pin of a revision before its first pin does not hold", True,
         held is False and any("ships only once" in line for line in said)),
    ]


def self_test() -> int:
    """Each rule, against the shape it exists to refuse."""
    failures = 0
    for what, expected, got in (*shapes(), *pairs(), *held_copies(), *moves(), *bindings(), *vector(),
                                *stack_shapes(), *trees_held(), *proxy(), *tree_moves(), *tree_apply(), *target_shapes(),
                                *template_targets(), *first_pins()):
        print(f"  {'ok  ' if expected == got else 'FAIL'} {what}")
        failures += expected != got
    print("\nself-test passed." if not failures else f"\n{failures} rule(s) did not refuse.")
    return 1 if failures else 0

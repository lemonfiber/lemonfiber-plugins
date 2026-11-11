"""The stack's own tables at schema 2, the offered pins and the beside profiles, each against
the shape it exists to refuse; run by `bundle.py --self-test` through `test_bundle`."""

from __future__ import annotations

import parts
from test_bundle import CADDY, PINS, STACK, TREES, Case, offline, pinned, refuses, stack_of

import bundle


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


def offered_shapes() -> list[Case]:
    """`read` of an `[[offered]]` pin, and each shape of one it exists to refuse (ARCH-R394)."""
    pins = {**PINS, "caddy": pinned("caddy", TREES["caddy"], **bundle.AS_OFFERED)}
    good = stack_of(pins)
    read = bundle.read(good)
    caddy = next(pin for pin in read.pins if pin["id"] == "caddy")
    offered = good[good.index("[[offered]]"):]
    trees = {**TREES, "caddy": {**TREES["caddy"], "plugin.toml": CADDY.replace(
        b'provides = ["proxy.front"]', b'provides = ["proxy.front"]\nreplaces = "caddy"')}}
    replacing = stack_of({**PINS, "caddy": pinned("caddy", trees["caddy"], **bundle.AS_OFFERED)})
    closed = {**TREES, "caddy": {**TREES["caddy"], "plugin.toml": CADDY.replace(
        b'license = "Apache-2.0"', b'license = "Proprietary"')}}
    proprietary = stack_of({**PINS, "caddy": pinned("caddy", closed["caddy"], **bundle.AS_OFFERED)})
    as_a_part = stack_of({**PINS, "caddy": pinned("caddy", closed["caddy"], fills=["proxy.front"])})
    refused = [
        ("an offered plugin naming fills refused", good.replace(
            '[[offered]]\nid           = "caddy"', '[[offered]]\nid           = "caddy"\nfills = []')),
        ("an offered plugin naming a stage refused", good.replace(
            '[[offered]]\nid           = "caddy"', '[[offered]]\nid           = "caddy"\nstage = "installed"')),
        ("an offered plugin without its tree refused", good.replace(f'tree         = "{caddy["tree"]}"\n', "")),
        ("a part at the offered stage refused", good.replace('stage        = "installed"', 'stage        = "offered"')),
        ("a plugin pinned as a part and as offered refused",
         good + "\n" + offered.replace("[[offered]]", "[[offered]]", 1)),
    ]
    return [
        ("an offered plugin is read filling nothing, at its own stage", True,
         caddy["fills"] == [] and caddy["stage"] == "offered"),
        ("an offered plugin is written back as [[offered]], after every part", True,
         STACK + bundle.rendered(read.pins, 2) == good and "fills" not in offered and "stage" not in offered),
        ("an offered plugin's copy holds", True, offline(good) == []),
        ("an offered plugin whose service declares replaces does not hold", True,
         any("it is offered and service caddy declares replaces" in line for line in offline(replacing, trees))),
        ("an offered plugin of a proprietary upstream holds, which no part does", True,
         offline(proprietary, closed) == [] and any("licence" in line for line in offline(as_a_part, closed))),
        *((what, True, refuses(lambda text=text: bundle.read(text))) for what, text in refused),
    ]


BESIDE = """[[profile]]
id          = "notify"
name        = "Notifications"
description = "A self-hosted push channel"
beside      = true

"""


def beside_shapes() -> list[Case]:
    """A profile that runs beside whichever forms run, and each shape of one it refuses (ARCH-R410)."""
    stack = STACK.replace("[[form]]", BESIDE + "[[form]]", 1)
    every = {**TREES, "caddy": {**TREES["caddy"], "plugin.toml": CADDY.replace(
        b'forms = ["full"]', b'forms = ["dl", "full"]')}}
    good = stack + bundle.rendered(list({**PINS, "caddy": pinned(
        "caddy", every["caddy"], **{**bundle.AS_OFFERED, "profile": "notify"})}.values()), 2)
    narrow = stack + bundle.rendered(list({**PINS, "caddy": pinned(
        "caddy", TREES["caddy"], **{**bundle.AS_OFFERED, "profile": "notify"})}.values()), 2)
    refused = [
        ("beside that is not true or false refused", good.replace("beside      = true", 'beside      = "yes"')),
        ("a form listing a beside profile refused", good.replace('profiles    = ["usenet"]\n',
                                                                'profiles    = ["usenet", "notify"]\n')),
    ]
    return [
        ("a beside profile no form lists is read", False, refuses(lambda: bundle.read(good))),
        ("a plugin in a beside profile naming every form holds", True, offline(good, every) == []),
        ("a plugin in a beside profile naming only the forms that hold it does not", True,
         any("runs beside every form" in line for line in offline(narrow))),
        ("a profile not marked beside is held to its closures", True,
         parts.beside([{"id": "media"}, {"id": "notify", "beside": False}]) == set()),
        *((what, True, refuses(lambda text=text: bundle.read(text))) for what, text in refused),
    ]


def cases() -> list[Case]:
    """Every case this module holds."""
    return [*stack_shapes(), *offered_shapes(), *beside_shapes()]

#!/usr/bin/env python3
"""Hold `plugin.toml` to what lemonfiber publishes, and to nothing written here.

**This is CI harness, not plugin content.** A plugin is `plugin.toml` and
`fixtures/`; nothing under `.github/` is part of what an operator installs, and
nothing here is ever run by lemonfiber (`F3-R6`).

**Nothing in this file describes the manifest format.** Which tables a manifest
may carry, which fields each one takes, of what kind, out of which closed set and
within which bounds is `plugin-manifest.schema.json`'s to say. That schema is
generated from the types lemonfiber deserialises (`ARCH-R92`), published with
every release, and is the same document lemonfiber's own conformance stage walks
a manifest against before it parses one — so an off-the-shelf reader and the
binary reach the same verdict about the shape of a file. `F3-R2` asks for exactly
that, and `F10-R2` forbids a second, hand-maintained description standing beside
it.

One stood here, and the reason that mattered is not tidiness. It had drifted from
the reader in both directions. It refused a `version` that is not semver, a
`hostname` that is not a DNS label, a `dashboard_group` outside four words, a
`form` or a `media_type` outside two lists copied off the stack, an upper-case
digest, a recipe carrying no step, a captured value whose `origin` was outside
four words, and a set of proofs that only ever read a status — and lemonfiber
refuses none of those. An author who changed a manifest to satisfy it changed it
for no reason, and an author who could not was stuck on a rule nobody had
written down anywhere else.

What is left restates nothing the schema states. It is the reader's own
refusals — what lemonfiber decides *after* a file has been accepted as a
manifest — in the one place they can be asked before the reader exists:

  * what lemonfiber publishes elsewhere — which capability names exist, which
    points a contribution may be made at, and what a row at one carries;
  * what spans two places in the document — a claim and the `provides` it
    answers, a remedy and the check it names, a substitution and the step that
    captured it;
  * what needs the source on disk — a recording a binding names;
  * what a value means rather than what shape it is — a digest that fixes what
    runs, an image that carries no second pin, a configuration directory that is
    not the library, a call that names something rather than somewhere and uses
    a verb a runner could make.

Every rule here was read off `lemonfiber-plugin` before it was written. Being
weaker than the reader is what a stand-in is; disagreeing with it is the defect,
so a rule that refused something lemonfiber accepts has been deleted rather than
kept, and nothing is added here without checking the reader first.

    validate.py --published <dir>  the manifest, against the three artefacts
    validate.py                    the rules that need none of them, which is few
    validate.py --self-test        each rule refuses the shape it exists to refuse

The three are fetched by `published_gate.py`; this reads them off a directory so
that the catalogue can supply its own copy. Every violation is reported in one
pass, each naming its location (`ARCH-R94`, `F1-R9`, `F10-R10`). Exit 0 =
conforms, 1 = does not.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import string
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = "plugin.toml"

# The three artefacts lemonfiber generates and publishes. Named here only so that
# a directory can be read; what is *in* them is never restated in this file.
SCHEMA = "plugin-manifest.schema.json"
VOCABULARY = "capability-vocabulary.json"
EXTENSION_POINTS = "extension-points.json"

# The capability that runs a recipe. A manifest declaring one and not asking for
# this would be installed on a build that parses the block and skips it, which is
# a plugin whose behaviour is narrower than its manifest.
RECIPE_CAPABILITY = "recipe.run"

# The reader's own constants, and the only reason they are repeated here: each is
# a refusal `lemonfiber-plugin` makes about what a value *means*, which the
# generated schema does not state and a `pattern` in it could not state in the
# same terms. Read off the reader; check it before changing one.
DIGEST_PREFIX = "sha256:"
DIGEST_LENGTH = 64
ID_LETTERS = frozenset(string.ascii_lowercase + string.digits + "-")
DATA = "/data"
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# The one key an expectation can carry that says something about the network path
# rather than about the answer. Everything else `Expect` declares is a body
# constraint, and which keys those are is read out of the published schema rather
# than listed here.
NOT_A_BODY = "status"


class Published:
    """What lemonfiber says, or the fact that nobody asked it.

    Absent is not empty. A validator holding an empty vocabulary would refuse
    every core capability by name and read as though the plugin were wrong; one
    holding `None` knows it did not ask, skips those rules, and says which ones
    it skipped.
    """

    def __init__(self, schema: dict | None, vocabulary: dict | None, points: dict | None) -> None:
        self.schema = schema
        self.vocabulary = vocabulary
        self.points = points

    @property
    def asked(self) -> bool:
        return self.schema is not None and self.vocabulary is not None and self.points is not None

    def capability(self, name: str) -> dict | None:
        for entry in (self.vocabulary or {}).get("capabilities", []):
            if entry.get("name") == name:
                return entry
        return None

    def removed(self, name: str) -> dict | None:
        for entry in (self.vocabulary or {}).get("removed", []):
            if entry.get("name") == name:
                return entry
        return None

    def names(self) -> list[str]:
        return [entry.get("name", "") for entry in (self.vocabulary or {}).get("capabilities", [])]

    def point(self, name: str) -> dict | None:
        for entry in (self.points or {}).get("points", []):
            if entry.get("name") == name:
                return entry
        return None

    def point_names(self) -> list[str]:
        return [entry.get("name", "") for entry in (self.points or {}).get("points", [])]

    def occupied(self) -> dict[str, str]:
        """Every identity a bundled row holds, and which point holds it.

        Across all points rather than per point, because a remedy names a check:
        a `for` pointing at a bundled check is a collision with `doctor.check`'s
        register while sitting in a `doctor.remedy` row, and looking only at its
        own point's occupied set would miss exactly that.
        """
        return {
            identity: entry.get("name", "")
            for entry in (self.points or {}).get("points", [])
            for identity in entry.get("occupied", [])
        }

    def body_constraints(self) -> set[str]:
        """The keys an expectation can constrain a body with.

        Read out of the published schema rather than written down, which is the
        whole of this file's rule: `Expect` is a closed set there, so the set of
        keys that are not the status is derivable and a copy of it would be one
        more thing to keep in step.
        """
        expect = ((self.schema or {}).get("$defs", {}).get("Expect") or {}).get("properties", {})
        return set(expect) - {NOT_A_BODY}


def listed(value: object) -> list:
    """A value as the list it should be, or an empty one.

    Every rule below runs after the schema has had its say and *whatever* the
    schema said: a manifest is reported whole, so a block the schema refused is
    still walked. Reading it defensively is what keeps that from becoming a
    stack trace, and a stack trace in a gate is a gate nobody can tell apart
    from a broken manifest.
    """
    return value if isinstance(value, list) else []


def table(value: object) -> dict:
    """The same, for a value that should be a table."""
    return value if isinstance(value, dict) else {}


def shaped(document: object, holding: str) -> dict | None:
    """The artefact, if it is the shape this reads, and nothing if it is not.

    This file reads documents it does not own and cannot describe — which is the
    whole point of them being published. A shape it does not recognise has to
    become a refusal that names the artefact, because the alternative is a stack
    trace, and a stack trace in a gate is a gate nobody can tell apart from a
    broken manifest.
    """
    if not isinstance(document, dict):
        return None
    entries = document.get(holding)
    if not isinstance(entries, list) or not all(isinstance(one, dict) for one in entries):
        return None
    return document


def a_schema(document: object) -> dict | None:
    """The generated schema, if what was read is one.

    Only that it is a JSON object declaring the draft it is written in. What it
    *says* is not this file's to check — a reader is what decides that, and
    describing the schema here would be the thing this file no longer does.
    """
    if not isinstance(document, dict) or "$schema" not in document:
        return None
    return document


def read_published(directory: str | None) -> Published:
    if directory is None:
        return Published(None, None, None)
    where = pathlib.Path(directory)

    def read(name: str) -> object | None:
        path = where / name
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    return Published(
        a_schema(read(SCHEMA)),
        shaped(read(VOCABULARY), "capabilities"),
        shaped(read(EXTENSION_POINTS), "points"),
    )


class Report:
    """Every violation, named with its location, reported in one pass."""

    def __init__(self) -> None:
        self.faults: list[str] = []
        self.unasked: list[str] = []

    def fail(self, where: str, what: str) -> None:
        self.faults.append(f"{where}: {what}")

    def check(self, ok: bool, where: str, what: str) -> bool:
        if not ok:
            self.fail(where, what)
        return ok

    def skipped(self, what: str) -> None:
        self.unasked.append(what)


class Unreadable(Exception):
    """The schema reader is not installed, so nothing was held to the schema.

    Raised rather than reported, because a run that could not hold a manifest to
    the schema has decided nothing about its shape, and a list of no faults would
    read as clear.
    """


def readable_expectations(published: Published, report: Report) -> None:
    """That the published schema still says what an expectation may constrain.

    The body rules below read that set out of the schema rather than carrying a
    copy. A schema this cannot find it in would make every one of them decide
    *no body is constrained*, which reads as a fault in the plugin — so it is
    named as what it is instead.
    """
    if published.schema is not None and not published.body_constraints():
        report.fail(
            SCHEMA,
            "declares no `Expect` this can read, so what an expectation may constrain about a "
            "body is not readable out of it",
        )


def against_the_schema(manifest: dict, published: Published, report: Report) -> None:
    """The whole of the manifest's shape, decided by an off-the-shelf reader.

    Which is the point: the reader is a library nobody here wrote, the schema is
    generated from the types lemonfiber parses with, and what passes here is what
    passes lemonfiber's own conformance stage. An author's editor does this same
    thing against this same document with nothing installed.
    """
    if published.schema is None:
        report.skipped("the manifest's shape, which the published schema decides")
        return
    try:
        from jsonschema import Draft202012Validator
    except ImportError as absent:  # pragma: no cover - the workflow installs it
        raise Unreadable(
            "jsonschema is not installed, so nothing was held to the published schema"
        ) from absent

    validator = Draft202012Validator(published.schema)
    for fault in sorted(validator.iter_errors(manifest), key=lambda one: list(one.path)):
        where = "".join(f".{step}" for step in fault.path)
        report.fail(f"{MANIFEST}{where}" if where else MANIFEST, fault.message)


def validate_plugin(plugin: dict, report: Report) -> None:
    """Who the plugin says it is, and whether an operator could go and check.

    The licence is recorded rather than constrained: the bundled set is a list
    this project stands behind and a plugin is the operator's own choice, so
    refusing to install proprietary software on somebody else's machine would be
    the tool standing between an operator and their stack. An absent one is a
    different matter — it is the operator not being told.
    """
    where = "[plugin]"
    licence = plugin.get("license")
    if isinstance(licence, str):
        report.check(
            licence.strip() != "", f"{where}.license",
            "is blank; an operator choosing whether to run somebody else's software is owed the "
            "one fact that says what running it commits them to",
        )
    name = plugin.get("id")
    if isinstance(name, str):
        report.check(
            bool(name) and all(letter in ID_LETTERS for letter in name),
            f"{where}.id",
            f"{name!r} is not a plain lowercase name; it is the namespace every capability and "
            "contribution this plugin declares is prefixed with, so a separator in it would make "
            "two different plugins able to write the same identity",
        )
    upstream = plugin.get("upstream")
    if isinstance(upstream, str):
        report.check(
            upstream.startswith("https://"), f"{where}.upstream",
            f"{upstream!r} is not an https address; it is how an operator judges the thing being "
            "installed rather than the wrapper around it",
        )
    forms = plugin.get("forms")
    if isinstance(forms, list):
        report.check(
            bool(forms), f"{where}.forms",
            "names no form, so the service it installs would join nothing and start with nothing",
        )


def validate_service(service: dict, report: Report) -> None:
    """What runs, and whether what runs is fixed.

    A tag is not a pin: it is a name its publisher can repoint, so the thing
    somebody read in a diff and the thing running on an operator's machine can
    differ with nothing in the manifest changing. A digest can always be
    obtained, which is why its absence is a fault in the manifest rather than a
    limitation of a registry.
    """
    where = "[[service]]"
    digest = service.get("digest")
    if isinstance(digest, str):
        after = digest[len(DIGEST_PREFIX):] if digest.startswith(DIGEST_PREFIX) else None
        report.check(
            after is not None and len(after) == DIGEST_LENGTH
            and all(letter in string.hexdigits for letter in after),
            f"{where}.digest",
            f"{digest!r} is not a {DIGEST_PREFIX} digest of {DIGEST_LENGTH} hexadecimal "
            "characters, so what actually runs is not fixed by this manifest",
        )
    image = service.get("image")
    if isinstance(image, str):
        # Read after the last `/` on purpose: a registry host may carry a port,
        # and `:5000` in `localhost:5000/komga` is where that host answers rather
        # than which version runs.
        report.check(
            "@" not in image and ":" not in image.rsplit("/", 1)[-1],
            f"{where}.image",
            f"{image!r} carries its own tag or digest; what runs is declared once, in `digest`, "
            "so a second pin here could disagree with it",
        )
    tag = service.get("tag")
    if isinstance(tag, str):
        report.check(
            tag.strip() != "", f"{where}.tag",
            "is blank; the digest says what runs and the tag is the readable name beside it, "
            "without which a diff shows sixty-four characters and no version",
        )
    report.check(
        service.get("port") is None or service.get("bind") is not None,
        f"{where}.bind",
        "is not declared and a port is; the tier is what decides whether the service is "
        "reachable by name, and lemonfiber assigns the address from it",
    )
    validate_config_path(service, report)


def validate_config_path(service: dict, report: Report) -> None:
    """Where the service's one configuration directory lands inside its container.

    The number of mounts and their sources are lemonfiber's, and that is what
    makes what a plugin can reach answerable from the format. Only the target is
    the plugin's: one inside the library would be a second mount over the
    operator's media wearing a different name.
    """
    path = service.get("config_path")
    if not isinstance(path, str):
        return
    where = "[[service]].config_path"
    if not path.startswith("/") or path == "/" or ".." in path or "$" in path:
        report.fail(
            where,
            f"{path!r} is not one plain absolute directory; what is permitted is a single "
            "absolute path that is not the root, with no `..` and nothing interpolated",
        )
        return
    report.check(
        path != DATA and not path.startswith(f"{DATA}/"),
        where,
        f"{path!r} is inside {DATA}, which is the library mount; a configuration directory there "
        "would be a second mount over the operator's media under another name",
    )


def its_own(name: object, plugin_id: str) -> bool:
    """Whether a capability name is this plugin's own rather than lemonfiber's.

    Its id, a colon, and something after it. A name that is not this is held to
    the published vocabulary, which is the only thing that can say whether it
    names anything.
    """
    if not isinstance(name, str):
        return False
    prefix, _, rest = name.partition(":")
    return prefix == plugin_id and bool(rest)


def core_claims(service: dict, plugin_id: str) -> list[str]:
    """Every capability a service claims that is not its own to define."""
    return [
        name for name in listed(service.get("provides"))
        if isinstance(name, str) and not its_own(name, plugin_id)
    ]


def validate_provides(service: dict, plugin_id: str, published: Published, report: Report) -> None:
    """Capabilities claimed (`F4-R1`, `ARCH-R102`).

    Two shapes and no third. A core name is lemonfiber's, comes from the
    published vocabulary, and has to be demonstrated by a `[[claim]]`; a
    namespaced one is this plugin's, is inert until something asks for it, and
    has no published contract to satisfy. Which of the two a name is, is read off
    the name; whether the first kind names anything is the vocabulary's to say.
    """
    where = "[[service]].provides"
    claimed = core_claims(service, plugin_id)
    if not published.asked:
        if claimed:
            report.skipped("whether each capability claimed is one the published vocabulary carries")
        return

    for name in claimed:
        if published.capability(name) is not None:
            continue
        gone = published.removed(name)
        if gone is not None:
            report.fail(
                where,
                f"{name!r} was removed in vocabulary generation {gone.get('removed_in')!r}; "
                f"{gone.get('replaced_by') or 'nothing'} took it over",
            )
        else:
            report.fail(
                where,
                f"{name!r} names no capability the published vocabulary carries, and is not "
                f"namespaced with this plugin's id ({plugin_id}:…); available: "
                f"{', '.join(sorted(published.names()))}",
            )


def validate_claims(claims: list, service: dict, plugin_id: str,
                    published: Published, report: Report) -> None:
    """The probes a core capability is demonstrated by (`F4-R24`, `ARCH-R109`, `ARCH-R116`).

    `provides` and this are a declaration and its evidence rather than two lists,
    so each half is held to the other: a core name with no claim asserts, and a
    claim for a name nothing declares demonstrates something the service never
    said it could do. Neither half is readable from the other's schema.
    """
    where = "[[claim]]"
    declared = core_claims(service, plugin_id)
    seen: list[str] = []

    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        name = claim.get("capability")
        at = f"{where} {name or f'#{index + 1}'}"
        if not isinstance(name, str):
            continue
        report.check(name not in seen, at, f"{name!r} is claimed twice")
        seen.append(name)
        report.check(
            name in declared,
            at,
            f"{name!r} is not in this service's `provides`, so the service has not said it can do it",
        )
        validate_claim_probes(claim, at, published, report)

    for name in declared:
        report.check(
            name in seen,
            where,
            f"{name!r} is declared in `provides` and claimed by no [[claim]]; a core capability "
            "is demonstrated, not asserted",
        )


def validate_claim_probes(claim: dict, at: str, published: Published, report: Report) -> None:
    """One claim's bindings, against the probes its capability declares.

    Every one of them, exactly once, and no others. The vocabulary owns what must
    be shown and the claimant owns where to ask it, so a binding that is missing
    is a contract half-satisfied and one that is invented is evidence for nothing.
    """
    probes = [one for one in listed(claim.get("probe")) if isinstance(one, dict)]

    bound: list[str] = []
    for probe in probes:
        name = probe.get("id")
        where = f"{at}.probe {name}"
        if isinstance(name, str):
            report.check(name not in bound, where, f"{name!r} is bound twice")
            bound.append(name)
        validate_fixture(probe.get("fixture"), where, report)
        validate_probe_asks_nothing_of_the_library(probe.get("expect"), where, report)

    capability = claim.get("capability")
    if not published.asked:
        report.skipped(f"whether {capability!r} binds every probe the vocabulary declares")
        return

    entry = published.capability(capability) if isinstance(capability, str) else None
    if entry is None:
        return

    declares = {one.get("id"): one for one in listed(entry.get("probes")) if isinstance(one, dict)}
    for name in declares:
        report.check(
            name in bound,
            at,
            f"binds no probe {name!r}, which {capability!r} declares; "
            f"it declares: {', '.join(sorted(str(one) for one in declares))}",
        )
    for probe in probes:
        name = probe.get("id")
        wanted = declares.get(name)
        where = f"{at}.probe {name}"
        if wanted is None:
            report.fail(
                where,
                f"{name!r} is not a probe {capability!r} declares; "
                f"it declares: {', '.join(sorted(str(one) for one in declares))}",
            )
            continue
        validate_binding(probe.get("expect"), wanted, where, published, report)


def carries(expect: dict, constraint: str, published: Published) -> bool:
    """Whether an expectation says the thing a constraint is.

    A key that is present and asserts nothing does not count. `json_is_absent =
    false` reads as a constraint and no runner evaluates it, and every empty
    collection is the same shape of nothing — a claim could satisfy a body
    requirement by writing a word, and then the runner would report a capability
    demonstrated because something answered `200`. A port proxy answers `200`.

    `json_array_min = 0` stays a constraint: the check behind it still requires
    the body to parse as an array, which is what *reads as a list* means.
    """
    if constraint not in published.body_constraints():
        return False
    held = expect.get(constraint)
    if constraint == "json_is_absent":
        return held is True
    if constraint == "json_array_min":
        return isinstance(held, int)
    if isinstance(held, (dict, list, str)):
        return bool(held)
    return held is not None


def validate_binding(expect: object, probe: dict, where: str,
                     published: Published, report: Report) -> None:
    """One binding's expectation, against what its probe permits.

    A claim demonstrated by the wrong evidence is an undemonstrated claim, and
    the two ways that happens are a status the probe does not accept as an answer
    and a body nothing is said about.
    """
    if not isinstance(expect, dict):
        return
    requires = table(probe.get("requires"))
    statuses = listed(requires.get("status"))
    report.check(
        expect.get("status") in statuses,
        where,
        f"expects status {expect.get('status')!r}, and the probe permits "
        f"{', '.join(str(one) for one in statuses)}",
    )

    wants_body = listed(requires.get("body"))
    if wants_body:
        report.check(
            any(carries(expect, str(one), published) for one in wants_body),
            where,
            f"constrains no body, and the probe requires one of: "
            f"{', '.join(sorted(str(one) for one in wants_body))}",
        )


def validate_probe_asks_nothing_of_the_library(expect: object, where: str, report: Report) -> None:
    """A probe gates an install, so it asks what the service does (`F4-R25`, `ARCH-R119`).

    A count above zero is the only way an expectation can say something about how
    much the operator has; everything else it can say is about shape. So that is
    where the rule is enforceable, and it is the mistake both plugins written
    against this vocabulary made within an hour of it being published — *at least
    one series* reads as the stronger proof and is a plugin nobody can install
    until they have copied their library over.

    A contributed check is deliberately not held to this. It reports on a running
    stack rather than gating an install, so one that fails on a fresh machine is
    a check doing its job.
    """
    if not isinstance(expect, dict):
        return
    least = expect.get("json_array_min")
    if isinstance(least, int) and least > 0:
        report.fail(
            f"{where}.expect.json_array_min",
            f"{least!r} asserts the operator has put something there, and a probe gates an "
            "install — `0` says the answer reads as a list without saying how long it is",
        )
    for key, minimum in table(expect.get("json_at_least")).items():
        if isinstance(minimum, (int, float)) and minimum > 0:
            report.fail(
                f"{where}.expect.json_at_least",
                f"{key} at least {minimum!r} asserts the operator has put something there, and "
                "a probe gates an install; a check may say this and a probe may not",
            )


def validate_fixture(named: object, where: str, report: Report) -> None:
    """The recorded response (`F10-R4`, `F10-R5`).

    That it names one is the schema's to say. That the source carries it is not
    readable from the manifest at all, and a proof that cannot be run is a proof
    that establishes nothing.
    """
    if not isinstance(named, str) or not named:
        return
    report.check(
        (ROOT / named).is_file(),
        f"{where}.fixture",
        f"{named!r} is not in this source",
    )


def validate_contributions(entries: list, plugin_id: str, requires: dict,
                           published: Published, report: Report) -> None:
    """Rows in registers lemonfiber already runs (`F3-R33`, `F4-R21`, `F4-R22`, `ARCH-R113`).

    Which points exist, and what a row at one carries, are lemonfiber's to say
    and are published — a manifest's `[[contribution]]` is the union of every row
    shape, so the schema cannot narrow one to the point it is made at. What is
    checked without the points is what this manifest can be held to on its own:
    that every identity is namespaced, that a remedy names a check declared here,
    and that no check is left without one.
    """
    where = "[[contribution]]"
    prefix = f"{plugin_id}:"
    identities: set[str] = set()
    checks: set[str] = set()
    remedied: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        name = entry.get("id")
        point = entry.get("at")
        at = f"{where} {name or f'#{index + 1}'}"
        if not isinstance(point, str) or not isinstance(name, str):
            continue
        report.check(
            name.startswith(prefix) and len(name) > len(prefix),
            f"{at}.id",
            f"{name!r} is not namespaced with this plugin's id ({prefix}…); a contribution is the "
            "plugin's and is attributed to it wherever it appears",
        )
        report.check(name not in identities, at, f"{name!r} is declared twice")
        identities.add(name)

        if point == "doctor.check":
            checks.add(name)
            validate_fixture(entry.get("fixture"), at, report)
        if point == "doctor.remedy":
            for_check = entry.get("for")
            if isinstance(for_check, str):
                remedied.add(for_check)

        if published.asked:
            validate_contribution_row(entry, at, point, published, report)
            needs = (published.point(point) or {}).get("requires")
            if needs is not None:
                report.check(
                    needs in listed(requires.get("capabilities")),
                    "[requires].capabilities",
                    f"a manifest contributing at {point!r} asks for {needs!r} by name, so a "
                    "lemonfiber that does not take contributions there refuses this manifest "
                    "rather than reading the row and dropping it",
                )

    for entry in entries:
        if not isinstance(entry, dict) or entry.get("at") != "doctor.remedy":
            continue
        for_check = entry.get("for")
        at = f"{where} {entry.get('id')}"
        report.check(
            isinstance(for_check, str) and for_check in checks,
            f"{at}.for",
            f"{for_check!r} names no check this manifest declares; a remedy for a bundled check "
            "would be a plugin editing what lemonfiber says about itself",
        )

    for name in sorted(checks):
        report.check(
            name in remedied,
            f"{where} {name}",
            "carries no remedy; a check that can say something is wrong and nothing about what "
            "to do has moved the work rather than done it",
        )

    if not published.asked:
        report.skipped("whether each contribution's point exists and its row carries what that point declares")


def validate_contribution_row(entry: dict, at: str, point: str,
                              published: Published, report: Report) -> None:
    published_point = published.point(point)
    if published_point is None:
        report.fail(
            f"{at}.at",
            f"{point!r} names no extension point this lemonfiber publishes; "
            f"it publishes: {', '.join(sorted(published.point_names()))}",
        )
        return

    occupied = published.occupied()
    for field in ("id", "for"):
        value = entry.get(field)
        held = occupied.get(value) if isinstance(value, str) else None
        if held is not None:
            report.fail(
                f"{at}.{field}",
                f"{value!r} is the identity a bundled row already holds at {held!r}; adding is "
                "not overriding, and standing in for something bundled is not a manifest's to assert",
            )

    row = published_point.get("row", {})
    if not isinstance(row, dict):
        report.fail(f"{at}.at", f"{point!r} publishes no row shape this can read")
        return
    required = listed(row.get("required"))
    optional = listed(row.get("optional"))
    for field in required:
        report.check(field in entry, at, f"missing {field!r}, which {point!r} requires")
    for field in sorted(set(entry) - {"at"} - set(required) - set(optional)):
        report.fail(
            f"{at}.{field}",
            f"{field!r} is outside what {point!r} declares; it takes: "
            f"{', '.join(sorted(set(required) | set(optional)))}",
        )
    enums = row.get("enums", {})
    bounds_by_field = row.get("bounds", {})
    if not isinstance(enums, dict) or not isinstance(bounds_by_field, dict):
        report.fail(
            f"{at}.at",
            f"{point!r} publishes its closed sets or its bounds in a shape this cannot read; "
            "each is a table keyed by the field it constrains",
        )
        return
    for field, values in enums.items():
        if field in entry:
            report.check(
                entry[field] in values,
                f"{at}.{field}",
                f"{entry[field]!r} is not one of {', '.join(values)}",
            )
    for field, bounds in bounds_by_field.items():
        if field not in entry:
            continue
        value = entry[field]
        report.check(
            isinstance(value, int) and bounds.get("min", value) <= value <= bounds.get("max", value),
            f"{at}.{field}",
            f"{value!r} is outside the bounds {point!r} sets: "
            f"{bounds.get('min')}–{bounds.get('max')}",
        )


def validate_recipes(recipes: list, requires: dict, report: Report) -> None:
    """The ordered calls that configure what it installed (`F3-R35`, `ARCH-R117`).

    Nothing here runs one. What is checked is what F8 requires to be decidable
    without running it, and none of it is decidable from one field: every
    substitution refers to something an earlier step captured, every value that
    could reach a destination has a declared pair behind it, and the whole
    manifest asks for the capability that would run any of it.
    """
    report.check(
        RECIPE_CAPABILITY in listed(requires.get("capabilities")),
        "[requires].capabilities",
        f"a manifest declaring a recipe asks for {RECIPE_CAPABILITY!r} by name, so a lemonfiber "
        "that cannot run one refuses this manifest rather than parsing the block and skipping it",
    )

    named: set[str] = set()
    for index, recipe in enumerate(recipes):
        if not isinstance(recipe, dict):
            continue
        name = recipe.get("id")
        at = f"{'[[recipe]]'} {name or f'#{index + 1}'}"
        if isinstance(name, str):
            report.check(name not in named, at, f"{name!r} is declared twice, so naming one names both")
            named.add(name)
        validate_recipe_steps(recipe, at, report)


def validate_recipe_steps(recipe: dict, at: str, report: Report) -> None:
    pairs = {
        (pair.get("value"), pair.get("to"))
        for pair in listed(recipe.get("pair"))
        if isinstance(pair, dict)
    }
    captured: set[str] = set()

    for index, step in enumerate(listed(recipe.get("step"))):
        if not isinstance(step, dict):
            continue
        call = step.get("call")
        where = f"{at}.step {step.get('id') or f'#{index + 1}'}"
        if not isinstance(call, dict):
            continue
        destination = call.get("to")
        validate_destination(destination, f"{where}.call.to", report)
        report.check(
            call.get("method") in METHODS, f"{where}.call.method",
            f"{call.get('method')!r} is not one of: {', '.join(METHODS)}",
        )

        for reference in substitutions(call):
            report.check(
                reference in captured,
                f"{where}.call",
                f"substitutes {reference!r}, which no earlier step captured",
            )
            report.check(
                (reference, destination) in pairs,
                f"{where}.call",
                f"would carry {reference!r} to {destination!r}, and no [[recipe.pair]] permits it",
            )

        for capture in listed(step.get("capture")):
            if isinstance(capture, dict) and isinstance(capture.get("name"), str):
                captured.add(capture["name"])


def substitutions(call: dict) -> list[str]:
    """Every name a call substitutes into what it carries.

    The body and the headers, which is where lemonfiber looks: a substitution in
    the path is not a value carried to the destination, and reading one as though
    it were would refuse a flow the runner permits.
    """
    carried = [call.get("body"), *table(call.get("headers")).values()]
    return [
        piece.split("}}", 1)[0].strip()
        for text in carried if isinstance(text, str)
        for piece in text.split("{{")[1:]
        if "}}" in piece
    ]


def validate_destination(destination: object, where: str, report: Report) -> None:
    """Whether a call names something rather than somewhere.

    A destination is a service in this stack or a DNS name outside it, never an
    address. An address is a machine on the operator's network that the manifest
    chose, which is a reach nothing in the declaration bounds — and every part
    between the dots being a number is what an address is and what no DNS name
    can be, because the last label of a name is never all digits.
    """
    if not isinstance(destination, str):
        return
    parts = destination.split(".")
    numeric = len(parts) > 1 and all(part.isdigit() for part in parts)
    report.check(
        ":" not in destination and not numeric,
        where,
        f"{destination!r} is an address rather than a name; a call names a service in this stack "
        "or a DNS name outside it, so that where it goes is a thing the operator can read",
    )


def validate(manifest: dict, report: Report, published: Published | None = None) -> None:
    published = published or Published(None, None, None)
    against_the_schema(manifest, published, report)
    readable_expectations(published, report)

    plugin = table(manifest.get("plugin"))
    plugin_id = plugin.get("id", "")
    if plugin:
        validate_plugin(plugin, report)

    services = manifest.get("service")
    first: dict = {}
    if isinstance(services, list):
        # One service, because this generation of the format describes one
        # addition to a stack that already exists. Two would make "which one did
        # I install" a question with no good answer, and none would make the rest
        # of the manifest describe nothing.
        report.check(
            len(services) == 1, "[[service]]",
            f"this generation of the format describes exactly one service and {len(services)} "
            "are declared",
        )
        for service in services:
            if isinstance(service, dict):
                validate_service(service, report)
        if services and isinstance(services[0], dict):
            first = services[0]
            validate_provides(first, plugin_id, published, report)

    requires = table(manifest.get("requires"))

    claims = manifest.get("claim")
    if claims is not None or core_claims(first, plugin_id):
        validate_claims(
            [one for one in listed(claims) if isinstance(one, dict)],
            first, plugin_id, published, report,
        )

    for proof in listed(manifest.get("proof")):
        if isinstance(proof, dict):
            validate_fixture(proof.get("fixture"), f"[[proof]] {proof.get('id')}", report)

    contributions = listed(manifest.get("contribution"))
    if contributions:
        validate_contributions(contributions, plugin_id, requires, published, report)

    recipes = listed(manifest.get("recipe"))
    if recipes:
        validate_recipes(recipes, requires, report)


# A schema, a vocabulary and a set of points small enough to read and shaped
# exactly as the published ones are. Held here rather than fetched: a self-test
# that needs the network is one that reports nothing about the run that could not
# reach it. None of the three describes the manifest format — each is a fixture
# the rules below are driven against, and the run that decides this repository's
# manifest fetches the real ones.
SAMPLE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "plugin"],
    "properties": {"schema_version": {"type": "integer"}},
    "$defs": {
        "Expect": {
            "properties": {
                "status": {}, "json": {}, "json_has_keys": {}, "json_types": {},
                "json_at_least": {}, "json_array_min": {}, "json_is_absent": {},
                "content_type": {}, "body_starts_with": {},
            },
        },
    },
}

SAMPLE_VOCABULARY = {
    "vocabulary": "service-capabilities",
    "vocabulary_version": 1,
    "capabilities": [
        {
            "name": "media.serve",
            "probes": [
                {"id": "guarded", "credential": "none",
                 "requires": {"status": [401, 403], "body": []}},
                {"id": "catalogue", "credential": "operator",
                 "requires": {"status": [200], "body": ["json_has_keys", "json_array_min"]}},
            ],
        },
    ],
    "removed": [{"name": "media.stream", "removed_in": 2, "replaced_by": "media.serve"}],
}

SAMPLE_POINTS = {
    "extension_points_version": 1,
    "points": [
        {
            "name": "doctor.check",
            "row": {
                "required": ["id", "title", "category", "request", "expect", "why", "fixture"],
                "optional": ["timeout_s", "service"],
                "bounds": {"timeout_s": {"min": 1, "max": 30}},
                "enums": {"category": ["services", "network"]},
            },
            "occupied": ["storage.space"],
            "requires": "doctor.contribute",
        },
        {
            "name": "doctor.remedy",
            "row": {"required": ["id", "for", "action", "why"], "optional": ["detail"]},
            "occupied": [],
            "requires": "doctor.contribute",
        },
    ],
}


def a_recording() -> str:
    """One recording this repository actually carries, for the synthetic cases.

    Named by looking rather than by being written down, because this file is the
    same in every plugin repository and each of them records different things.
    """
    found = sorted(one.name for one in (ROOT / "fixtures").glob("*.json"))
    return f"fixtures/{found[0]}" if found else "fixtures/none.json"


def synthetic() -> dict:
    """The smallest manifest that exercises the blocks a real one may not carry."""
    recording = a_recording()
    return {
        "schema_version": 1,
        "plugin": {
            "id": "sample", "name": "Sample", "version": "1.0.0",
            "description": "A manifest built to be broken", "without_it": "Nothing",
            "upstream": "https://example.invalid", "license": "MIT", "forms": ["full"],
        },
        "service": [{
            "id": "sample", "name": "Sample", "image": "example.invalid/sample",
            "digest": "sha256:" + "0" * 64, "tag": "1.0.0", "criticality": "enhancing",
            "provides": ["media.serve", "sample:extra"],
        }],
        "claim": [{
            "capability": "media.serve",
            "probe": [
                {"id": "guarded", "request": {"method": "GET", "path": "/x"},
                 "expect": {"status": 401}, "fixture": recording},
                {"id": "catalogue", "request": {"method": "GET", "path": "/x"},
                 "expect": {"status": 200, "json_has_keys": ["a"]}, "fixture": recording},
            ],
        }],
        "proof": [{
            "id": "sample.answers", "title": "It answers", "why": "Because it must",
            "request": {"method": "GET", "path": "/x"},
            "expect": {"status": 200, "json_has_keys": ["a"]}, "fixture": recording,
        }],
        "contribution": [
            {"at": "doctor.check", "id": "sample:guarded", "title": "It refuses a stranger",
             "category": "services", "request": {"method": "GET", "path": "/x"},
             "expect": {"status": 401}, "why": "Because it must", "fixture": recording,
             "timeout_s": 10},
            {"at": "doctor.remedy", "id": "sample:let-it-in", "for": "sample:guarded",
             "action": "Sign in", "why": "It is guarded"},
        ],
        "requires": {"capabilities": ["service.add", "doctor.contribute"]},
    }


def a_recipe(steps: list, pairs: list | None = None) -> list:
    """One recipe carrying the steps a case is about, and nothing else."""
    recipe: dict = {"id": "seed", "title": "Seed it", "why": "Because", "step": steps}
    if pairs is not None:
        recipe["pair"] = pairs
    return [recipe]


def refuses(label: str, manifest: dict, expected: str, published: Published) -> bool:
    report = Report()
    validate(manifest, report, published)
    said = " ".join(report.faults)
    if expected not in said:
        print(f"::error::self-test: {label} was not refused by name — said: {said or '(nothing)'}")
        return False
    print(f"  ok   {label} refused")
    return True


# Each case is a manifest broken one way, and the words its refusal must carry.
# A gate nobody has seen fail is a gate nobody knows the shape of.
#
# Every one of them is a rule no schema can state: it spans two places in the
# document, or it is decided by an artefact lemonfiber publishes separately, or
# it needs the source on disk. A case a schema would catch belongs to the schema,
# and the first case here is the whole of that arm — it proves the manifest
# reaches a reader, not what the reader says, because what it says is generated
# somewhere else and is not this file's to assert.
BROKEN = (
    ("a manifest the published schema refuses",
     lambda m: m.pop("schema_version"), "'schema_version' is a required property"),
    ("a licence nobody declared",
     lambda m: m["plugin"].__setitem__("license", "  "), "is blank"),
    ("an id a second plugin could write over",
     lambda m: m["plugin"].__setitem__("id", "Sample:One"), "is not a plain lowercase name"),
    ("an upstream an operator cannot go and read",
     lambda m: m["plugin"].__setitem__("upstream", "http://example.invalid"),
     "is not an https address"),
    ("a plugin joining no form at all",
     lambda m: m["plugin"].__setitem__("forms", []), "names no form"),
    ("two services in one plugin",
     lambda m: m["service"].append(dict(m["service"][0])), "exactly one service"),
    ("a digest that is not one",
     lambda m: m["service"][0].__setitem__("digest", "sha256:nope"), "hexadecimal characters"),
    ("an image carrying a second pin",
     lambda m: m["service"][0].__setitem__("image", "example.invalid/sample:1.0.0"),
     "carries its own tag or digest"),
    ("a tag that says nothing",
     lambda m: m["service"][0].__setitem__("tag", " "), "is blank"),
    ("a port with no tier",
     lambda m: m["service"][0].__setitem__("port", 8080), "is not declared and a port is"),
    ("a configuration directory inside the library",
     lambda m: m["service"][0].__setitem__("config_path", "/data/sample"),
     "is inside /data"),
    ("a configuration directory that is the container root",
     lambda m: m["service"][0].__setitem__("config_path", "/"),
     "is not one plain absolute directory"),
    ("a configuration directory that walks out of itself",
     lambda m: m["service"][0].__setitem__("config_path", "/config/../data"),
     "is not one plain absolute directory"),
    ("a configuration directory that interpolates",
     lambda m: m["service"][0].__setitem__("config_path", "/config/$HOME"),
     "is not one plain absolute directory"),
    ("a core capability with no claim behind it",
     lambda m: m.pop("claim"), "is demonstrated, not asserted"),
    ("a claim for something the service never said it could do",
     lambda m: m["service"][0]["provides"].remove("media.serve"), "has not said it can do it"),
    ("one capability claimed twice",
     lambda m: m["claim"].append(dict(m["claim"][0])), "is claimed twice"),
    ("a claim leaving one of its capability's probes unbound",
     lambda m: m["claim"][0]["probe"].pop(), "binds no probe"),
    ("a probe the capability does not declare",
     lambda m: m["claim"][0]["probe"][0].__setitem__("id", "vibes"), "is not a probe"),
    ("one probe bound twice",
     lambda m: m["claim"][0]["probe"].append(dict(m["claim"][0]["probe"][0])), "is bound twice"),
    ("a binding with a status the probe does not permit",
     lambda m: m["claim"][0]["probe"][0]["expect"].__setitem__("status", 200),
     "and the probe permits"),
    ("a binding constraining no body where the probe requires one",
     lambda m: m["claim"][0]["probe"][1].__setitem__("expect", {"status": 200}),
     "constrains no body"),
    ("a binding whose body constraint asserts nothing",
     lambda m: m["claim"][0]["probe"][1]["expect"].__setitem__("json_has_keys", []),
     "constrains no body"),
    ("a probe asserting the operator has put something there",
     lambda m: m["claim"][0]["probe"][1]["expect"].__setitem__("json_array_min", 1),
     "asserts the operator has put something there"),
    ("a probe asserting a count of something the operator holds",
     lambda m: m["claim"][0]["probe"][1]["expect"].__setitem__("json_at_least", {"total": 1}),
     "asserts the operator has put something there"),
    ("a binding naming a recording that is not here",
     lambda m: m["claim"][0]["probe"][0].__setitem__("fixture", "fixtures/nowhere.json"),
     "is not in this source"),
    ("a proof naming a recording that is not here",
     lambda m: m["proof"][0].__setitem__("fixture", "fixtures/nowhere.json"),
     "is not in this source"),
    ("a capability the vocabulary no longer carries",
     lambda m: (m["service"][0]["provides"].__setitem__(0, "media.stream"),
                m["claim"][0].__setitem__("capability", "media.stream")),
     "was removed in vocabulary generation"),
    ("a capability the vocabulary never carried",
     lambda m: (m["service"][0]["provides"].__setitem__(0, "media.beam"),
                m["claim"][0].__setitem__("capability", "media.beam")),
     "names no capability the published vocabulary carries"),
    ("a capability namespaced with somebody else's id",
     lambda m: (m["service"][0]["provides"].__setitem__(0, "other:extra"),
                m["claim"][0].__setitem__("capability", "other:extra")),
     "names no capability the published vocabulary carries"),
    ("a contribution at a point lemonfiber does not publish",
     lambda m: m["contribution"][0].__setitem__("at", "dashboard.panel"),
     "names no extension point this lemonfiber publishes"),
    ("a contribution that is not namespaced",
     lambda m: m["contribution"][0].__setitem__("id", "guarded"), "is not namespaced"),
    ("a contribution taking a bundled identity",
     lambda m: (m["contribution"][0].__setitem__("id", "storage.space"),
                m["contribution"][1].__setitem__("for", "storage.space")),
     "the identity a bundled row already holds"),
    ("two contributions sharing an identity",
     lambda m: m["contribution"][1].__setitem__("id", m["contribution"][0]["id"]),
     "is declared twice"),
    ("a contributed check missing what its point requires",
     lambda m: m["contribution"][0].pop("category"), "which 'doctor.check' requires"),
    ("a contributed check carrying a field the point does not declare",
     lambda m: m["contribution"][0].__setitem__("detail", "extra"),
     "is outside what 'doctor.check' declares"),
    ("a contributed check in a category the doctor has not got",
     lambda m: m["contribution"][0].__setitem__("category", "vibes"), "is not one of"),
    ("a contributed check outside the bounds its point sets",
     lambda m: m["contribution"][0].__setitem__("timeout_s", 600), "is outside the bounds"),
    ("a contributed check with no remedy",
     lambda m: m["contribution"].pop(), "carries no remedy"),
    ("a remedy for a check this manifest did not declare",
     lambda m: m["contribution"][1].__setitem__("for", "vibes.check"),
     "names no check this manifest declares"),
    ("contributions on a manifest that never asked to make one",
     lambda m: m["requires"]["capabilities"].remove("doctor.contribute"),
     "asks for 'doctor.contribute' by name"),
    ("a recipe on a manifest that never asked to run one",
     lambda m: m.__setitem__("recipe", a_recipe(
         [{"id": "one", "call": {"method": "POST", "to": "sample", "path": "/x"}}])),
     "asks for 'recipe.run' by name"),
    ("two recipes sharing an id",
     lambda m: (m["requires"]["capabilities"].append("recipe.run"),
                m.__setitem__("recipe", a_recipe([]) + a_recipe([]))),
     "is declared twice, so naming one names both"),
    ("a recipe addressing a machine rather than naming one",
     lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", a_recipe(
         [{"id": "one", "call": {"method": "POST", "to": "192.168.1.1", "path": "/x"}}]))),
     "is an address rather than a name"),
    ("a recipe reaching a bare host port",
     lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", a_recipe(
         [{"id": "one", "call": {"method": "POST", "to": "sample:8080", "path": "/x"}}]))),
     "is an address rather than a name"),
    ("a recipe substituting something nothing captured",
     lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", a_recipe(
         [{"id": "one", "call": {"method": "POST", "to": "sample", "path": "/x",
                                 "body": "{{token}}"}}]))),
     "which no earlier step captured"),
    ("a recipe calling with a verb no runner could make",
     lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", a_recipe(
         [{"id": "one", "call": {"method": "FETCH", "to": "sample", "path": "/x"}}]))),
     "is not one of: GET, POST"),
    ("a recipe carrying a value to a destination no pair permits",
     lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", a_recipe(
         [
             {"id": "one", "call": {"method": "POST", "to": "sample", "path": "/a"},
              "capture": [{"name": "token", "from": "json.token", "origin": "stack-service"}]},
             {"id": "two", "call": {"method": "POST", "to": "elsewhere.example",
                                    "path": "/b", "body": "{{token}}"}},
         ]))),
     "no [[recipe.pair]] permits it"),
)


def self_test() -> int:
    """Every rule above refuses the shape it exists to refuse."""
    published = Published(SAMPLE_SCHEMA, SAMPLE_VOCABULARY, SAMPLE_POINTS)

    report = Report()
    validate(tomllib.loads((ROOT / MANIFEST).read_text(encoding="utf-8")), report)
    if report.faults:
        print("::error::self-test: the manifest in this repository was refused")
        for fault in report.faults:
            print(f"  {fault}")
        return 1
    print("  ok   the manifest in this repository is accepted")

    report = Report()
    validate(synthetic(), report, published)
    if report.faults:
        print("::error::self-test: the synthetic manifest was refused")
        for fault in report.faults:
            print(f"  {fault}")
        return 1
    print("  ok   the synthetic manifest is accepted against a published set")

    for label, break_it, expected in BROKEN:
        broken = synthetic()
        break_it(broken)
        if not refuses(label, broken, expected, published):
            return 1

    # An artefact in a shape this cannot read is a refusal naming the artefact,
    # never a stack trace: a gate that crashes is one nobody can tell apart from a
    # manifest that is wrong.
    reshaped = json.loads(json.dumps(SAMPLE_POINTS))
    reshaped["points"][0]["row"]["enums"] = [{"field": "category", "values": ["services"]}]
    if not refuses(
        "an extension point publishing its closed sets in a shape this cannot read",
        synthetic(), "in a shape this cannot read",
        Published(SAMPLE_SCHEMA, SAMPLE_VOCABULARY, reshaped),
    ):
        return 1

    unreadable = json.loads(json.dumps(SAMPLE_SCHEMA))
    unreadable["$defs"].pop("Expect")
    if not refuses(
        "a schema this cannot read what an expectation may constrain out of",
        synthetic(), "declares no `Expect` this can read",
        Published(unreadable, SAMPLE_VOCABULARY, SAMPLE_POINTS),
    ):
        return 1

    # Every block the wrong kind at once. The schema refuses all of it and this
    # walks it anyway, because a manifest is reported whole — so what must not
    # happen is a traceback where a list of violations belongs.
    report = Report()
    validate(
        {"schema_version": "one", "plugin": 1, "service": 2, "claim": 3, "proof": 4,
         "contribution": 5, "recipe": 6, "requires": 7},
        report, published,
    )
    if not report.faults:
        print("::error::self-test: a manifest of the wrong kinds throughout was not refused")
        return 1
    print("  ok   a manifest of the wrong kinds throughout is refused, not crashed into")

    if read_published("/nowhere-at-all").asked:
        print("::error::self-test: a directory that is not there read as published")
        return 1
    print("  ok   a directory that is not there is not a published set")

    # One pass, every violation: three faults at once, and all three named.
    broken = synthetic()
    broken["claim"][0]["probe"][0]["expect"]["status"] = 200
    broken["contribution"][0]["category"] = "vibes"
    broken["contribution"][0]["timeout_s"] = 600
    report = Report()
    validate(broken, report, published)
    if len(report.faults) < 3:
        print(f"::error::self-test: three violations reported as {len(report.faults)}; "
              "every one is named in one pass")
        return 1
    print("  ok   three violations reported in one pass, not the first of them")

    # Absent is not empty: without the published artefacts the rules that need
    # them are skipped and said to be, rather than passing on nothing.
    report = Report()
    validate(synthetic(), report)
    if not report.unasked:
        print("::error::self-test: with nothing published, no rule reported itself skipped")
        return 1
    print("  ok   the rules that need the published artefacts report themselves skipped")

    print("\nself-test passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true",
                        help="prove each rule refuses the shape it exists to refuse")
    parser.add_argument("--published", metavar="DIR",
                        help=f"a directory holding lemonfiber's published {SCHEMA}, "
                             f"{VOCABULARY} and {EXTENSION_POINTS}")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    path = ROOT / MANIFEST
    if not path.is_file():
        print(f"::error::{MANIFEST} is missing from the root of this plugin's source")
        return 1

    report = Report()
    try:
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as broken:
        print(f"::error file={MANIFEST}::not readable as TOML: {broken}")
        return 1

    published = read_published(args.published)
    if args.published is not None and not published.asked:
        missing = [
            name for name, found in ((SCHEMA, published.schema),
                                     (VOCABULARY, published.vocabulary),
                                     (EXTENSION_POINTS, published.points))
            if found is None
        ]
        print(f"::error::{args.published} does not carry {' or '.join(missing)}")
        return 1

    try:
        validate(manifest, report, published)
    except Unreadable as unread:
        print(f"::error::{unread}")
        return 1

    if report.faults:
        for fault in report.faults:
            print(f"::error file={MANIFEST}::{fault}")
        print(f"\n{len(report.faults)} violation(s).", file=sys.stderr)
        return 1

    if report.unasked:
        print(f"{MANIFEST} holds on every rule this run could decide. Not asked, for want of\n"
              "lemonfiber's published artefacts — run again with --published:")
        for one in report.unasked:
            print(f"    {one}")
        return 0

    print(
        f"{MANIFEST} conforms to the published schema and holds against the published "
        "vocabulary\nand the published extension points. What lemonfiber refuses beyond that "
        "is answered by\nlemonfiber; this is a stand-in and the weaker of the two."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Validate `plugin.toml` against the manifest contract — until a schema exists.

**This is CI harness, not plugin content.** A plugin is `plugin.toml` and
`fixtures/`; nothing under `.github/` is part of what an operator installs, and
nothing here is ever run by lemonfiber (`F3-R6`).

`F3-R2` requires a manifest to be validated against a **published schema**, and
`ARCH-R92` requires that schema to be *generated from the types lemonfiber
deserialises* and published with every release. No release publishes one yet:
the plugin machinery is `0.16.0`, which is `planned`. So there is nothing to
validate against, and the honest options are to report this plugin unvalidated
or to check it against the contract by hand.

This does the second and says so. It is deliberately **not** a schema and must
never be published as one: `F10-R2` forbids a second, hand-maintained
description of the manifest format precisely because it can disagree with the
parser, and a plugin that validates in an author's editor and is refused on an
operator's machine is the failure that rule exists to prevent. When the schema
is published, `ci.yml` switches to it and this file is deleted — and until then
`schema_gate.py` is what fails the day it appears.

Two of the things a manifest declares into are **published by lemonfiber** and
not describable here at all: the core capability vocabulary and the extension
points. Which names exist is lemonfiber's to say, so every rule that depends on
knowing them is skipped without `--published <dir>` and **reported as skipped**
rather than passed — a validator that quietly checked less than it claimed is
the same defect as a stand-in that outlives what it stood in for.

    validate.py                    the rules that need nothing outside this file
    validate.py --published <dir>  those, and every rule the published artefacts decide
    validate.py --self-test        each rule refuses the shape it exists to refuse

Every violation is reported in one pass, each naming its location (`ARCH-R94`,
`F1-R9`, `F10-R10`). Exit 0 = conforms, 1 = does not.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = "plugin.toml"

SUPPORTED_SCHEMA_VERSIONS = {1}

TOP_LEVEL = (
    "schema_version", "plugin", "service", "claim", "wiring", "proof",
    "contribution", "recipe", "secret", "override", "requires",
)

PLUGIN_REQUIRED = ("id", "name", "version", "description", "without_it", "upstream", "license", "forms")
SERVICE_REQUIRED = ("id", "name", "image", "digest", "tag", "criticality")
SERVICE_OPTIONAL = (
    "port", "bind", "health", "media_types", "takes_data", "provides", "config_path",
)
WIRING_PERMITTED = ("hostname", "dashboard_group")
PROOF_REQUIRED = ("id", "title", "request", "expect", "why")
PROOF_OPTIONAL = ("fixture",)
CLAIM_REQUIRED = ("capability", "probe")
PROBE_REQUIRED = ("id", "request", "expect", "fixture")
# What an `expect` may constrain. Anything else is a proof this runner would
# silently not check, which is worse than one that fails.
EXPECT_PERMITTED = (
    "status", "json", "json_has_keys", "json_types", "json_at_least",
    "json_array_min", "json_is_absent", "content_type", "body_starts_with",
)
# An expectation that says something about the body rather than the network path.
# At least one proof must carry one (ARCH-R105).
BODY_CONSTRAINTS = frozenset(EXPECT_PERMITTED) - {"status"}

# `stack.toml`'s vocabulary minus the one value a plugin may not assign itself
# (`ARCH-R97`). Named in full so a refusal can list what was available.
CRITICALITIES = ("core", "important", "enhancing", "optional")
FORBIDDEN_CRITICALITY = "critical"

BINDS = ("loopback", "lan")
HEALTH_KINDS = ("http", "tcp", "container")
MEDIA_TYPES = ("tv", "movies", "music", "books", "comics")

# The bundled dashboard's groups, which is what a plugin's entry joins.
DASHBOARD_GROUPS = ("Watch", "Library", "Automation", "Acquisition")

# A single DNS label: what may go in front of the operator's own domain.
DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
# A name, not an address: what a recipe may reach outside the stack.
DNS_NAME = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
IP_LITERAL = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$|^\[?[0-9a-fA-F:]*:[0-9a-fA-F:]*\]?$")

# The two shapes a capability name may take, and nothing else. A core name is
# lemonfiber's and a namespaced one is the plugin's, and which kind a name is has
# to be decidable by reading it rather than by looking it up.
CORE_CAPABILITY = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
NAMESPACED = re.compile(r"^([a-z0-9][a-z0-9-]*):([a-z0-9][a-z0-9-]*(?:[.\-][a-z0-9]+)*)$")

# The capability that runs a recipe. A manifest declaring one and not asking for
# this would be installed on a build that parses the block and skips it, which is
# a plugin whose behaviour is narrower than its manifest.
RECIPE_CAPABILITY = "recipe.run"

# The forms `lemonfiber-media-stack` declares. Read from the stack rather than
# listed here would be better and is what lemonfiber will do; this file has no
# stack to read.
STACK_FORMS = (
    "search", "dl", "hunt", "tv", "movies", "music", "books",
    "auto", "library", "full", "proxy",
)

# The fields `stack.toml` has that a plugin's service may not (`ARCH-R84`), each
# refused by name rather than ignored.
FORBIDDEN_SERVICE_FIELDS = (
    "grants", "depends_on", "host_managed", "profile", "api", "last_release", "environment",
)

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+].*)?$")

VOCABULARY = "capability-vocabulary.json"
EXTENSION_POINTS = "extension-points.json"


class Published:
    """What lemonfiber says exists, or the fact that nobody asked it.

    Absent is not empty. A validator holding an empty vocabulary would refuse
    every core capability by name and read as though the plugin were wrong; one
    holding `None` knows it did not ask, skips those rules, and says which ones
    it skipped.
    """

    def __init__(self, vocabulary: dict | None, points: dict | None) -> None:
        self.vocabulary = vocabulary
        self.points = points

    @property
    def asked(self) -> bool:
        return self.vocabulary is not None and self.points is not None

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


def shaped(document: object, holding: str) -> dict | None:
    """The artefact, if it is the shape this reads, and nothing if it is not.

    This file reads two documents it does not own and cannot describe — which is
    the whole point of them being published. A shape it does not recognise has to
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


def read_published(directory: str | None) -> Published:
    if directory is None:
        return Published(None, None)
    where = pathlib.Path(directory)

    def read(name: str, holding: str) -> dict | None:
        path = where / name
        if not path.is_file():
            return None
        try:
            return shaped(json.loads(path.read_text(encoding="utf-8")), holding)
        except ValueError:
            return None

    return Published(read(VOCABULARY, "capabilities"), read(EXTENSION_POINTS, "points"))


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


def validate_plugin(table: dict, report: Report) -> None:
    where = "[plugin]"
    for field in PLUGIN_REQUIRED:
        report.check(field in table, where, f"missing required field {field!r}")

    for field in ("id", "name", "version", "description", "without_it", "upstream", "license"):
        if field in table:
            report.check(
                isinstance(table[field], str) and table[field].strip(),
                f"{where}.{field}",
                "must be a non-empty string",
            )

    if isinstance(table.get("id"), str):
        report.check(
            table["id"] == table["id"].lower() and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*", table["id"])),
            f"{where}.id",
            f"{table['id']!r} must be lowercase, and the name it is installed and journalled under",
        )

    if isinstance(table.get("version"), str):
        report.check(SEMVER.match(table["version"]) is not None, f"{where}.version",
                     f"{table['version']!r} is not semver")

    forms = table.get("forms")
    if forms is not None and report.check(
        isinstance(forms, list) and forms,
        f"{where}.forms",
        "must be a non-empty array of forms the stack declares",
    ):
        for form in forms:
            report.check(
                form in STACK_FORMS,
                f"{where}.forms",
                f"{form!r} names no form the stack declares; available: {', '.join(STACK_FORMS)}",
            )


def validate_health(health: dict, report: Report) -> None:
    where = "[[service]].health"
    kind = health.get("kind")
    if not report.check(kind in HEALTH_KINDS, where,
                        f"kind {kind!r} is not one of {', '.join(HEALTH_KINDS)}"):
        return
    if kind == "http":
        report.check("path" in health, where, "an http health declares the path it asks for")
    if "timeout_s" in health:
        report.check(
            isinstance(health["timeout_s"], int) and health["timeout_s"] > 0,
            f"{where}.timeout_s",
            "must be a positive integer",
        )


def validate_config_path(service: dict, report: Report) -> None:
    """Where the one configuration directory lands inside the container (ARCH-R100).

    The mount set is lemonfiber's and unchanged. What is checked here is that the
    target names one place, is a place, and is not the library — a path beneath
    the data root would be a second mount over somebody's media wearing a
    different name.
    """
    where = "[[service]].config_path"
    declared = service.get("config_path")
    if declared is None:
        return
    if not report.check(isinstance(declared, str) and declared, where, "must be a non-empty string"):
        return
    report.check(declared.startswith("/"), where, f"{declared!r} is not an absolute path")
    report.check(declared != "/", where, "the container root is not a configuration directory")
    report.check(".." not in declared.split("/"), where, f"{declared!r} walks out of itself")
    report.check("$" not in declared, where, f"{declared!r} interpolates; the path is data, not a template")
    report.check(
        declared != "/data" and not declared.startswith("/data/"),
        where,
        f"{declared!r} is inside the data root, which would be a second mount over the library",
    )


def validate_provides(service: dict, published: Published, report: Report) -> None:
    """Capabilities claimed (F4-R1, ARCH-R102).

    Two shapes and no third. A core name is lemonfiber's, comes from the
    published vocabulary, and has to be demonstrated by a `[[claim]]`; a
    namespaced one is this plugin's, is inert until something asks for it, and
    has no published contract to satisfy.
    """
    where = "[[service]].provides"
    claims = service.get("provides")
    if claims is None:
        return
    if not report.check(isinstance(claims, list), where, "must be an array of capability names"):
        return
    prefix = f"{service.get('id', '')}:"
    for claim in claims:
        if not report.check(isinstance(claim, str) and claim, where, f"{claim!r} is not a capability name"):
            continue
        if claim.startswith(prefix) and NAMESPACED.match(claim):
            continue
        if CORE_CAPABILITY.match(claim):
            continue
        report.fail(
            where,
            f"{claim!r} is neither a core name — `area.verb`, lowercase, one dot — nor namespaced "
            f"with this plugin's id ({prefix}…)",
        )

    if not published.asked:
        if any(isinstance(c, str) and CORE_CAPABILITY.match(c) for c in claims):
            report.skipped("whether each core name is one the published vocabulary carries")
        return

    for claim in claims:
        if not (isinstance(claim, str) and CORE_CAPABILITY.match(claim)):
            continue
        if published.capability(claim) is not None:
            continue
        gone = published.removed(claim)
        if gone is not None:
            report.fail(
                where,
                f"{claim!r} was removed in vocabulary generation {gone.get('removed_in')!r}; "
                f"{gone.get('replaced_by') or 'nothing'} took it over",
            )
        else:
            report.fail(
                where,
                f"{claim!r} names no capability the published vocabulary carries; "
                f"available: {', '.join(sorted(published.names()))}",
            )


def core_claims(service: dict) -> list[str]:
    return [
        name for name in service.get("provides", [])
        if isinstance(name, str) and CORE_CAPABILITY.match(name)
    ]


def validate_claims(claims: list, service: dict, published: Published, report: Report) -> None:
    """The probes a core capability is demonstrated by (F4-R24, ARCH-R109, ARCH-R116).

    `provides` and this are a declaration and its evidence rather than two lists,
    so each half is held to the other: a core name with no claim asserts, and a
    claim for a name nothing declares demonstrates something the service never
    said it could do.
    """
    where = "[[claim]]"
    if not report.check(isinstance(claims, list), where, "must be an array of claims"):
        return

    declared = core_claims(service)
    seen: list[str] = []

    for index, claim in enumerate(claims):
        name = claim.get("capability") if isinstance(claim, dict) else None
        at = f"{where} {name or f'#{index + 1}'}"
        if not report.check(isinstance(claim, dict), at, "must be a table"):
            continue
        for field in CLAIM_REQUIRED:
            report.check(field in claim, at, f"missing required field {field!r}")
        for field in sorted(set(claim) - set(CLAIM_REQUIRED)):
            report.fail(f"{at}.{field}", f"{field!r} is outside the permitted set")
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
    probes = claim.get("probe")
    if not report.check(isinstance(probes, list) and probes, at,
                        "a claim binds at least one probe"):
        return

    bound: list[str] = []
    for index, probe in enumerate(probes):
        name = probe.get("id") if isinstance(probe, dict) else None
        where = f"{at}.probe {name or f'#{index + 1}'}"
        if not report.check(isinstance(probe, dict), where, "must be a table"):
            continue
        for field in PROBE_REQUIRED:
            report.check(field in probe, where, f"missing required field {field!r}")
        for field in sorted(set(probe) - set(PROBE_REQUIRED)):
            report.fail(f"{where}.{field}", f"{field!r} is outside the permitted set")
        if isinstance(name, str):
            report.check(name not in bound, where, f"{name!r} is bound twice")
            bound.append(name)
        validate_request(probe.get("request"), where, report)
        validate_expect(probe.get("expect"), where, report)
        validate_fixture(probe.get("fixture"), where, report)
        validate_probe_asks_nothing_of_the_library(probe.get("expect"), where, report)

    capability = claim.get("capability")
    if not published.asked:
        report.skipped(f"whether {capability!r} binds every probe the vocabulary declares")
        return

    entry = published.capability(capability) if isinstance(capability, str) else None
    if entry is None:
        return

    declared = {one.get("id"): one for one in entry.get("probes", [])}
    for name in declared:
        report.check(
            name in bound,
            at,
            f"binds no probe {name!r}, which {capability!r} declares; "
            f"it declares: {', '.join(sorted(declared))}",
        )
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        name = probe.get("id")
        wanted = declared.get(name)
        where = f"{at}.probe {name}"
        if wanted is None:
            report.fail(
                where,
                f"{name!r} is not a probe {capability!r} declares; "
                f"it declares: {', '.join(sorted(declared))}",
            )
            continue
        requires = wanted.get("requires", {})
        expect = probe.get("expect")
        if not isinstance(expect, dict):
            continue
        statuses = requires.get("status", [])
        report.check(
            expect.get("status") in statuses,
            where,
            f"expects status {expect.get('status')!r}, and the probe permits "
            f"{', '.join(str(one) for one in statuses)}",
        )
        wants_body = requires.get("body", [])
        if wants_body:
            report.check(
                bool(set(expect) & set(wants_body)),
                where,
                f"constrains no body, and the probe requires one of: {', '.join(sorted(wants_body))}",
            )


def validate_probe_asks_nothing_of_the_library(expect: object, where: str, report: Report) -> None:
    """A probe gates an install, so it asks what the service does (F4-R25, ARCH-R119).

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
    for key, minimum in (expect.get("json_at_least") or {}).items():
        if isinstance(minimum, (int, float)) and minimum > 0:
            report.fail(
                f"{where}.expect.json_at_least",
                f"{key} at least {minimum!r} asserts the operator has put something there, and "
                "a probe gates an install; a check may say this and a probe may not",
            )


def validate_wiring(wiring: dict, service: dict, report: Report) -> None:
    """How the stack's own proxy and dashboard reach it (F3-R31, ARCH-R103, ARCH-R104)."""
    where = "[wiring]"
    for field in sorted(set(wiring) - set(WIRING_PERMITTED)):
        report.fail(
            f"{where}.{field}",
            f"{field!r} is outside the permitted set; permitted: {', '.join(WIRING_PERMITTED)}. "
            "A plugin declares which label and which group, never a stanza or an entry.",
        )

    hostname = wiring.get("hostname")
    if hostname is not None:
        report.check(
            isinstance(hostname, str) and DNS_LABEL.match(hostname) is not None,
            f"{where}.hostname",
            f"{hostname!r} is not a single DNS label; it goes in front of the operator's own "
            "domain and may not be a name, an address or a port",
        )
        report.check(
            service.get("bind") == "lan",
            f"{where}.hostname",
            f"this service binds {service.get('bind')!r}, and only a lan service is proxied — "
            "the tier decides whether it is reachable by name, not the plugin",
        )

    group = wiring.get("dashboard_group")
    if group is not None:
        report.check(
            group in DASHBOARD_GROUPS,
            f"{where}.dashboard_group",
            f"{group!r} is not one of {', '.join(DASHBOARD_GROUPS)}",
        )


def validate_request(request: object, where: str, report: Report) -> None:
    if not isinstance(request, dict):
        return
    report.check("method" in request and "path" in request, f"{where}.request",
                 "names the method and the path it asks for")
    report.check(
        str(request.get("path", "")).startswith("/"),
        f"{where}.request.path",
        f"{request.get('path')!r} is not a path on the service",
    )


def validate_expect(expect: object, where: str, report: Report) -> None:
    if not isinstance(expect, dict):
        return
    report.check(bool(expect), f"{where}.expect", "declares nothing, so nothing can be decided")
    for field in sorted(set(expect) - set(EXPECT_PERMITTED)):
        report.fail(
            f"{where}.expect.{field}",
            f"{field!r} is not something this can check; permitted: {', '.join(EXPECT_PERMITTED)}",
        )


def validate_fixture(named: object, where: str, report: Report) -> None:
    """The recorded response (F10-R4, F10-R5).

    Named and present, because a recording nobody can read is a place for
    something to hide and a recording that is not there is a proof that cannot be
    run at all.
    """
    if named is None:
        return
    if not report.check(isinstance(named, str) and named, f"{where}.fixture",
                        "must name a recorded response"):
        return
    report.check(
        (ROOT / named).is_file(),
        f"{where}.fixture",
        f"{named!r} is not in this source",
    )


def validate_proofs(proofs: list, report: Report) -> None:
    """What must hold before it is installed (F3-R1, ARCH-R105)."""
    if not report.check(isinstance(proofs, list) and proofs, "[[proof]]", "a plugin declares at least one proof"):
        return

    seen: set[str] = set()
    constrains_a_body = False

    for index, proof in enumerate(proofs):
        name = proof.get("id") or f"#{index + 1}"
        where = f"[[proof]] {name}"
        for field in PROOF_REQUIRED:
            report.check(field in proof, where, f"missing required field {field!r}")
        for field in sorted(set(proof) - set(PROOF_REQUIRED) - set(PROOF_OPTIONAL)):
            report.fail(f"{where}.{field}", f"{field!r} is outside the permitted set")

        if isinstance(proof.get("id"), str):
            report.check(proof["id"] not in seen, where, f"{proof['id']!r} is declared twice")
            seen.add(proof["id"])

        validate_request(proof.get("request"), where, report)
        validate_expect(proof.get("expect"), where, report)
        validate_fixture(proof.get("fixture"), where, report)

        expect = proof.get("expect")
        if isinstance(expect, dict) and set(expect) & BODY_CONSTRAINTS:
            constrains_a_body = True

        if isinstance(proof.get("why"), str):
            report.check(proof["why"].strip() != "", f"{where}.why",
                         "says nothing; a proof nobody can justify is one nobody will maintain")

    report.check(
        constrains_a_body,
        "[[proof]]",
        "every proof constrains only a response status. Docker publishes a port by putting a "
        "proxy in front of it, and that proxy accepts before knowing whether anything inside is "
        "listening — so none of these would fail against a container that had been emptied",
    )


def validate_contributions(entries: list, plugin_id: str, requires: dict,
                           published: Published, report: Report) -> None:
    """Rows in registers lemonfiber already runs (F3-R33, F4-R21, F4-R22, ARCH-R113).

    Which points exist, and what a row at one carries, are lemonfiber's to say
    and are published. What is checked without them is what this manifest can be
    held to on its own: that every identity is namespaced, that a remedy names a
    check declared here, and that no check is left without one.
    """
    where = "[[contribution]]"
    if not report.check(isinstance(entries, list) and entries, where,
                        "must be a non-empty array of contributions"):
        return

    prefix = f"{plugin_id}:"
    identities: set[str] = set()
    checks: set[str] = set()
    remedied: set[str] = set()

    for index, entry in enumerate(entries):
        name = entry.get("id") if isinstance(entry, dict) else None
        at = f"{where} {name or f'#{index + 1}'}"
        if not report.check(isinstance(entry, dict), at, "must be a table"):
            continue
        point = entry.get("at")
        if not report.check(isinstance(point, str) and point, f"{at}.at",
                            "names the extension point this is made at"):
            continue
        if not report.check(isinstance(name, str) and name, f"{at}.id",
                            "names the identity this row holds"):
            continue
        report.check(
            name.startswith(prefix) and NAMESPACED.match(name) is not None,
            f"{at}.id",
            f"{name!r} is not namespaced with this plugin's id ({prefix}…); a contribution is the "
            "plugin's and is attributed to it wherever it appears",
        )
        report.check(name not in identities, at, f"{name!r} is declared twice")
        identities.add(name)

        if point == "doctor.check":
            checks.add(name)
            validate_request(entry.get("request"), at, report)
            validate_expect(entry.get("expect"), at, report)
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
                    needs in requires.get("capabilities", []),
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


def validate_contribution_row(entry: dict, at: str, point: str, published: Published, report: Report) -> None:
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
    required = row.get("required", [])
    optional = row.get("optional", [])
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


def validate_recipes(recipes: list, requires: dict, service_id: str, report: Report) -> None:
    """The ordered calls that configure what it installed (F3-R35, ARCH-R117).

    Nothing here runs one. What is checked is what F8 requires to be decidable
    without running it: every destination is a name rather than an address, every
    substitution refers to something captured earlier, and every value that could
    reach a destination has a declared pair behind it.
    """
    where = "[[recipe]]"
    if not report.check(isinstance(recipes, list) and recipes, where,
                        "must be a non-empty array of recipes"):
        return

    report.check(
        RECIPE_CAPABILITY in requires.get("capabilities", []),
        "[requires].capabilities",
        f"a manifest declaring a recipe asks for {RECIPE_CAPABILITY!r} by name, so a lemonfiber "
        "that cannot run one refuses this manifest rather than parsing the block and skipping it",
    )

    for index, recipe in enumerate(recipes):
        name = recipe.get("id") if isinstance(recipe, dict) else None
        at = f"{where} {name or f'#{index + 1}'}"
        if not report.check(isinstance(recipe, dict), at, "must be a table"):
            continue
        for field in ("id", "title", "why", "step"):
            report.check(field in recipe, at, f"missing required field {field!r}")
        for field in sorted(set(recipe) - {"id", "title", "why", "step", "pair"}):
            report.fail(f"{at}.{field}", f"{field!r} is outside the permitted set")
        validate_recipe_steps(recipe, at, service_id, report)


def validate_recipe_steps(recipe: dict, at: str, service_id: str, report: Report) -> None:
    steps = recipe.get("step")
    if not report.check(isinstance(steps, list) and steps, at, "a recipe is an ordered list of calls"):
        return

    pairs = {
        (pair.get("value"), pair.get("to"))
        for pair in recipe.get("pair", [])
        if isinstance(pair, dict)
    }
    captured: set[str] = set()

    for index, step in enumerate(steps):
        name = step.get("id") if isinstance(step, dict) else None
        where = f"{at}.step {name or f'#{index + 1}'}"
        if not report.check(isinstance(step, dict), where, "must be a table"):
            continue
        call = step.get("call")
        if not report.check(isinstance(call, dict), f"{where}.call", "names the call it makes"):
            continue
        destination = call.get("to")
        validate_destination(destination, f"{where}.call.to", report)

        for reference in re.findall(r"\{\{\s*([a-z0-9_-]+)\s*\}\}", json.dumps(call)):
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

        for capture in step.get("capture", []):
            if not isinstance(capture, dict):
                continue
            report.check(
                capture.get("origin") in ("stack-service", "credential-store", "operator", "external"),
                f"{where}.capture",
                f"{capture.get('origin')!r} is not an origin a captured value may carry",
            )
            if isinstance(capture.get("name"), str):
                captured.add(capture["name"])

    for value, destination in sorted(pairs, key=lambda one: (str(one[0]), str(one[1]))):
        if destination == service_id:
            continue
        report.check(
            isinstance(destination, str) and bool(destination),
            f"{at}.pair",
            f"{value!r} is declared as carried to {destination!r}, which names nothing",
        )


def validate_destination(destination: object, where: str, report: Report) -> None:
    if not report.check(isinstance(destination, str) and destination, where,
                        "names a service in this stack or a host outside it"):
        return
    report.check(
        ":" not in destination,
        where,
        f"{destination!r} carries a port; a recipe names a service or a host and lemonfiber "
        "resolves the address",
    )
    report.check(
        IP_LITERAL.match(destination) is None,
        where,
        f"{destination!r} is an address; a recipe names and never addresses, because a declared "
        "address is a declared address wherever it points",
    )
    report.check(
        "/" not in destination,
        where,
        f"{destination!r} is not a name",
    )
    if "." in destination:
        report.check(
            DNS_NAME.match(destination) is not None,
            where,
            f"{destination!r} is not a DNS name",
        )


def validate_service(service: dict, published: Published, report: Report) -> None:
    where = "[[service]]"
    for field in SERVICE_REQUIRED:
        report.check(field in service, where, f"missing required field {field!r}")

    permitted = set(SERVICE_REQUIRED) | set(SERVICE_OPTIONAL)
    for field in sorted(set(service) - permitted):
        if field in FORBIDDEN_SERVICE_FIELDS:
            report.fail(
                f"{where}.{field}",
                f"{field!r} is a stack.toml field a plugin may not declare; "
                "lemonfiber fixes what a plugin's service may reach of the machine",
            )
        else:
            report.fail(
                f"{where}.{field}",
                f"{field!r} is outside the permitted set; permitted: {', '.join(sorted(permitted))}",
            )

    digest = service.get("digest")
    if digest is not None:
        report.check(
            isinstance(digest, str) and DIGEST.match(digest) is not None,
            f"{where}.digest",
            f"{digest!r} is not a well-formed sha256 digest",
        )

    image = service.get("image")
    if isinstance(image, str):
        report.check(
            "@" not in image and ":" not in image.rsplit("/", 1)[-1],
            f"{where}.image",
            f"{image!r} carries a tag or digest; the registry path is named on its own",
        )

    criticality = service.get("criticality")
    if criticality == FORBIDDEN_CRITICALITY:
        report.fail(
            f"{where}.criticality",
            f"a plugin may not declare {FORBIDDEN_CRITICALITY!r}; available: {', '.join(CRITICALITIES)}",
        )
    elif criticality is not None:
        report.check(
            criticality in CRITICALITIES,
            f"{where}.criticality",
            f"{criticality!r} is not one of {', '.join(CRITICALITIES)}",
        )

    if "port" in service:
        port = service["port"]
        report.check(isinstance(port, int) and 1 <= port <= 65535, f"{where}.port", f"invalid port {port!r}")
        report.check("bind" in service, f"{where}.bind",
                     "a declared port needs the tier it is published on")
    if "bind" in service:
        report.check(service["bind"] in BINDS, f"{where}.bind",
                     f"{service['bind']!r} is not one of {', '.join(BINDS)}")

    if "takes_data" in service:
        report.check(isinstance(service["takes_data"], bool), f"{where}.takes_data", "must be a boolean")

    for media_type in service.get("media_types", []):
        report.check(
            media_type in MEDIA_TYPES,
            f"{where}.media_types",
            f"{media_type!r} is not one of {', '.join(MEDIA_TYPES)}",
        )

    validate_config_path(service, report)
    validate_provides(service, published, report)

    health = service.get("health")
    if health is not None:
        validate_health(health, report)


def validate(manifest: dict, report: Report, published: Published | None = None) -> None:
    published = published or Published(None, None)

    version = manifest.get("schema_version")
    report.check(
        version in SUPPORTED_SCHEMA_VERSIONS,
        MANIFEST,
        f"schema_version {version!r} is not one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}",
    )

    for field in sorted(set(manifest) - set(TOP_LEVEL)):
        report.fail(f"{MANIFEST}.{field}", f"{field!r} is not a top-level table this contract defines")

    plugin = manifest.get("plugin")
    if report.check(isinstance(plugin, dict), MANIFEST, "no [plugin] table"):
        validate_plugin(plugin, report)
    plugin_id = plugin.get("id", "") if isinstance(plugin, dict) else ""

    services = manifest.get("service")
    first: dict = {}
    if report.check(isinstance(services, list) and services, MANIFEST, "no [[service]] entry"):
        report.check(len(services) == 1, MANIFEST,
                     f"{len(services)} services declared; this schema version permits exactly one")
        for service in services:
            validate_service(service, published, report)
        first = services[0]

    requires = manifest.get("requires")
    if requires is not None:
        report.check(isinstance(requires, dict), "[requires]", "must be a table")
        capabilities = requires.get("capabilities", [])
        report.check(
            isinstance(capabilities, list) and all(isinstance(c, str) and c for c in capabilities),
            "[requires].capabilities",
            "must be an array of capability names",
        )
        report.check(
            "min_lemonfiber_version" not in requires and "version" not in requires,
            "[requires]",
            "a manifest carries no minimum lemonfiber version; an unmet requirement "
            "is refused by naming the capability",
        )

    claims = manifest.get("claim")
    if claims is not None or core_claims(first):
        validate_claims(claims or [], first, published, report)

    wiring = manifest.get("wiring")
    if wiring is not None and report.check(isinstance(wiring, dict), "[wiring]", "must be a table"):
        validate_wiring(wiring, first, report)

    proofs = manifest.get("proof")
    if proofs is None:
        report.fail("[[proof]]", "no proof is declared, and a plugin whose proofs do not pass is not installed")
    else:
        validate_proofs(proofs, report)

    contributions = manifest.get("contribution")
    if contributions is not None:
        validate_contributions(contributions, plugin_id, requires or {}, published, report)

    recipes = manifest.get("recipe")
    if recipes is not None:
        validate_recipes(recipes, requires or {}, first.get("id", ""), report)


# Each case is a manifest broken one way, and the words its refusal must carry.
# A gate nobody has seen fail is a gate nobody knows the shape of.
BROKEN = (
    ("an image named by tag alone", "digest", None, "missing required field 'digest'"),
    ("a digest that is not one", "digest", "sha256:nope", "well-formed sha256 digest"),
    ("a criticality a plugin may not assign itself", "criticality", "critical", "may not declare"),
    ("a kernel capability", "grants", ["NET_ADMIN"], "a plugin may not declare"),
    ("an environment variable", "environment", {"ND_X": "1"}, "a plugin may not declare"),
    ("a port with no tier", "bind", None, "needs the tier"),
    ("a configuration directory inside the library", "config_path", "/data/x", "inside the data root"),
    ("a configuration directory that is the container root", "config_path", "/", "not a configuration directory"),
    ("a relative configuration directory", "config_path", "config", "not an absolute path"),
    ("a media type outside the vocabulary", "media_types", ["manga"], "is not one of"),
    ("a capability that is neither shape", "provides", ["Not A Name"], "neither a core name"),
)

# A vocabulary and a set of points, small enough to read and shaped exactly as
# the published ones are. Held here rather than fetched: a self-test that needs
# the network is one that reports nothing about the run that could not reach it.
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


def refuses(label: str, manifest: dict, expected: str, published: Published) -> bool:
    report = Report()
    validate(manifest, report, published)
    said = " ".join(report.faults)
    if expected not in said:
        print(f"::error::self-test: {label} was not refused by name — said: {said or '(nothing)'}")
        return False
    print(f"  ok   {label} refused")
    return True


def self_test() -> int:
    """Every rule above refuses the shape it exists to refuse."""
    sound = tomllib.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    published = Published(SAMPLE_VOCABULARY, SAMPLE_POINTS)

    report = Report()
    validate(sound, report)
    if report.faults:
        print("::error::self-test: the manifest in this repository was refused")
        for fault in report.faults:
            print(f"  {fault}")
        return 1
    print("  ok   the sound manifest is accepted")

    report = Report()
    validate(synthetic(), report, published)
    if report.faults:
        print("::error::self-test: the synthetic manifest was refused")
        for fault in report.faults:
            print(f"  {fault}")
        return 1
    print("  ok   the synthetic manifest is accepted against a published set")

    for label, field, value, expected in BROKEN:
        broken = tomllib.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        if value is None:
            broken["service"][0].pop(field, None)
        else:
            broken["service"][0][field] = value
        if not refuses(label, broken, expected, Published(None, None)):
            return 1

    # The blocks that are not the service, each broken its own way.
    shaped = (
        ("a hostname for a loopback service", lambda m: (
            m["service"][0].__setitem__("bind", "loopback"),
            m.setdefault("wiring", {}).__setitem__("hostname", "admin"),
        ), "only a lan service is proxied"),
        ("a hostname that is not a label", lambda m: m.setdefault("wiring", {}).__setitem__(
            "hostname", "http://x:80"), "not a single DNS label"),
        ("a dashboard group the dashboard has not got", lambda m: m.setdefault(
            "wiring", {}).__setitem__("dashboard_group", "Misc"), "is not one of"),
        ("a proxy stanza supplied by the plugin", lambda m: m.setdefault(
            "wiring", {}).__setitem__("reverse_proxy", "x:1"), "outside the permitted set"),
        ("a plugin declaring no proofs at all", lambda m: m.pop("proof"),
         "a plugin whose proofs do not pass is not installed"),
        ("a proof with nothing to decide", lambda m: m["proof"][0].__setitem__("expect", {}),
         "declares nothing"),
        ("a proof asserting something unknown", lambda m: m["proof"][0]["expect"].__setitem__(
            "vibes", "good"), "not something this can check"),
        ("a proof naming a recording that is not here", lambda m: m["proof"][0].__setitem__(
            "fixture", "fixtures/nowhere.json"), "is not in this source"),
        ("two proofs sharing an id", lambda m: m["proof"][1].__setitem__("id", m["proof"][0]["id"]),
         "declared twice"),
        ("proofs that only ever read a status", lambda m: [
            p.__setitem__("expect", {"status": 200}) for p in m["proof"]
        ], "constrains only a response status"),
    )
    for label, break_it, expected in shaped:
        broken = tomllib.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        break_it(broken)
        if not refuses(label, broken, expected, Published(None, None)):
            return 1

    # The blocks a real manifest here may not carry at all, against a published
    # set small enough to read.
    against_published = (
        ("a core capability with no claim behind it",
         lambda m: m.pop("claim"), "is demonstrated, not asserted"),
        ("a claim for something the service never said it could do",
         lambda m: m["service"][0]["provides"].remove("media.serve"), "has not said it can do it"),
        ("a claim leaving one of its capability's probes unbound",
         lambda m: m["claim"][0]["probe"].pop(), "binds no probe"),
        ("a probe the capability does not declare",
         lambda m: m["claim"][0]["probe"][0].__setitem__("id", "vibes"), "is not a probe"),
        ("a binding with a status the probe does not permit",
         lambda m: m["claim"][0]["probe"][0]["expect"].__setitem__("status", 200),
         "and the probe permits"),
        ("a probe asserting the operator has put something there",
         lambda m: m["claim"][0]["probe"][1]["expect"].__setitem__("json_array_min", 1),
         "asserts the operator has put something there"),
        ("a probe asserting a count of something the operator holds",
         lambda m: m["claim"][0]["probe"][1]["expect"].__setitem__("json_at_least", {"total": 1}),
         "asserts the operator has put something there"),
        ("a binding constraining no body where the probe requires one",
         lambda m: m["claim"][0]["probe"][1].__setitem__("expect", {"status": 200}),
         "constrains no body"),
        ("a capability the vocabulary no longer carries",
         lambda m: (m["service"][0]["provides"].__setitem__(0, "media.stream"),
                    m["claim"][0].__setitem__("capability", "media.stream")),
         "was removed in vocabulary generation"),
        ("a capability the vocabulary never carried",
         lambda m: (m["service"][0]["provides"].__setitem__(0, "media.beam"),
                    m["claim"][0].__setitem__("capability", "media.beam")),
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
        ("a contributed check missing what its point requires",
         lambda m: m["contribution"][0].pop("category"), "which 'doctor.check' requires"),
        ("a contributed check carrying a field the point does not declare",
         lambda m: m["contribution"][0].__setitem__("host", "example.invalid"),
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
        ("a remedy attached to a bundled check",
         lambda m: m["contribution"][1].__setitem__("for", "storage.space"),
         "the identity a bundled row already holds"),
        ("contributions on a manifest that never asked to make one",
         lambda m: m["requires"]["capabilities"].remove("doctor.contribute"),
         "asks for 'doctor.contribute' by name"),
        ("a recipe on a manifest that never asked to run one",
         lambda m: m.__setitem__("recipe", [{
             "id": "seed", "title": "Seed it", "why": "Because",
             "step": [{"id": "one", "call": {"method": "POST", "to": "sample", "path": "/x"}}],
         }]), "asks for 'recipe.run' by name"),
        ("a recipe addressing a machine rather than naming one",
         lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", [{
             "id": "seed", "title": "Seed it", "why": "Because",
             "step": [{"id": "one", "call": {"method": "POST", "to": "192.168.1.1", "path": "/x"}}],
         }])), "is an address"),
        ("a recipe reaching a bare host port",
         lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", [{
             "id": "seed", "title": "Seed it", "why": "Because",
             "step": [{"id": "one", "call": {"method": "POST", "to": "sample:8080", "path": "/x"}}],
         }])), "carries a port"),
        ("a recipe substituting something nothing captured",
         lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", [{
             "id": "seed", "title": "Seed it", "why": "Because",
             "step": [{"id": "one", "call": {"method": "POST", "to": "sample", "path": "/{{token}}"}}],
         }])), "which no earlier step captured"),
        ("a recipe carrying a value to a destination no pair permits",
         lambda m: (m["requires"]["capabilities"].append("recipe.run"), m.__setitem__("recipe", [{
             "id": "seed", "title": "Seed it", "why": "Because",
             "step": [
                 {"id": "one", "call": {"method": "POST", "to": "sample", "path": "/a"},
                  "capture": [{"name": "token", "from": "json.token", "origin": "stack-service"}]},
                 {"id": "two", "call": {"method": "POST", "to": "elsewhere.example",
                                        "path": "/b", "body": "{{token}}"}},
             ],
         }])), "no [[recipe.pair]] permits it"),
    )
    for label, break_it, expected in against_published:
        broken = synthetic()
        break_it(broken)
        if not refuses(label, broken, expected, published):
            return 1

    # An artefact in a shape this cannot read is a refusal naming the artefact,
    # never a stack trace: a gate that crashes is one nobody can tell apart from a
    # manifest that is wrong.
    listed = json.loads(json.dumps(SAMPLE_POINTS))
    listed["points"][0]["row"]["enums"] = [{"field": "category", "values": ["services"]}]
    if not refuses(
        "an extension point publishing its closed sets in a shape this cannot read",
        synthetic(), "in a shape this cannot read", Published(SAMPLE_VOCABULARY, listed),
    ):
        return 1

    if read_published("/nowhere-at-all").asked:
        print("::error::self-test: a directory that is not there read as published")
        return 1
    print("  ok   a directory that is not there is not a published set")

    # One pass, every violation: three faults at once, and all three named.
    broken = tomllib.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    broken["service"][0].pop("digest")
    broken["service"][0]["criticality"] = "critical"
    broken["plugin"]["forms"] = ["nonesuch"]
    report = Report()
    validate(broken, report)
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
                        help="a directory holding lemonfiber's published "
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
            name for name, found in ((VOCABULARY, published.vocabulary),
                                     (EXTENSION_POINTS, published.points))
            if found is None
        ]
        print(f"::error::{args.published} does not carry {' or '.join(missing)}")
        return 1

    validate(manifest, report, published)

    print(
        "Checked against 20-architecture/contracts/plugin-manifest.md, not against a\n"
        "published schema — none exists yet (ARCH-R92 is owed by 0.16.0, which is\n"
        "planned). This is a stand-in and the weaker answer of the two.\n"
    )

    if report.faults:
        for fault in report.faults:
            print(f"::error file={MANIFEST}::{fault}")
        print(f"\n{len(report.faults)} violation(s).", file=sys.stderr)
        return 1

    if report.unasked:
        print(f"{MANIFEST} conforms on every rule this run could decide. Not asked, for want of\n"
              "lemonfiber's published artefacts — run again with --published:")
        for one in report.unasked:
            print(f"    {one}")
        return 0

    print(f"{MANIFEST} conforms to the contract, on every rule this stand-in can check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

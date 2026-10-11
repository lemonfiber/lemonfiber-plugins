"""What a schema 2 bundle holds each pinned part's manifest to, and what holds across them.

Per part (ARCH-R266, ARCH-R96, ARCH-R97, ARCH-R222, ARCH-R270, ARCH-R272, F2-R5, OPS-R86,
REPO-R92): its stage, its services, its fills, its forms, its licence and its release.
Across the parts: the reserved register of ids, published ports and proxy hostnames
(ARCH-R269), and the services and asks the bundle's wiring names (ARCH-R268).
"""

from __future__ import annotations

import functools
import pathlib
import re

import tree

ASSEMBLED = "assembled"
OWN_ORIGINS = "https://github.com/lemonfiber/"
OWN_IMAGES = "ghcr.io/lemonfiber/"
OWN_LICENCE = "Hippocratic-3.0"
OSI = pathlib.Path(__file__).resolve().parent / "spdx_osi.txt"
CRITICAL = "critical"
EGRESS_GUARD = "egress-guard"
HOUSEHOLD = "lan"
PROXY = "proxy.front"
DOMAIN = ".{$DOMAIN"
LABEL = re.compile(r"\A[a-z0-9-]+\Z")

Register = dict[tuple[str, str], set[str]]


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


def built_of(services: list[dict]) -> list[dict]:
    """The services running an image lemonfiber builds: what makes a plugin one that builds an image."""
    return [one for one in services if str(one.get("image", "")).startswith(OWN_IMAGES)]


def filled_by(services: list[dict]) -> set[str]:
    """Every capability the services provide or speak."""
    filled = {name for one in services for name in listed(one, "provides") if isinstance(name, str)}
    return filled | {contract(name) for one in services for name in listed(one, "speaks") if isinstance(name, str)}


@functools.cache
def osi() -> frozenset[str]:
    """The OSI-approved SPDX identifiers a first-party plugin's licence may be."""
    lines = OSI.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def plugin_of(manifest: dict) -> dict:
    """A manifest's `[plugin]` table, or nothing where it has none."""
    plugin = manifest.get("plugin")
    return plugin if isinstance(plugin, dict) else {}


def assembled_problems(name: str, manifest: dict, services: list[dict]) -> list[str]:
    """An assembled part is one service of its id, speaking no contract, its claims recorded under
    `recordings/<id>/`."""
    said = []
    if len(services) != 1:
        said.append(f"it is assembled and declares {len(services)} services, not exactly one")
    said += [f"it is assembled and service {service.get('id')!r} speaks {listed(service, 'speaks')}"
             for service in adapters_of(services)]
    if services and services[0].get("id") != name:
        said.append(f"it is assembled and its one service is {services[0].get('id')!r}, not {name!r}")
    said += [f"it is assembled and its claim names the recording {recording}, outside recordings/{name}/"
             for recording in tree.recordings(manifest.get("claim"))
             if not recording.startswith(f"recordings/{name}/")]
    return said


def installed_problems(name: str, services: list[dict]) -> list[str]:
    """An installed part's service of its id replaces it, and no service names an in-process adapter."""
    taking = [service for service in services if service.get("id") == name]
    said = []
    if not taking:
        said.append(f"it is installed and declares no service {name!r} to take the part's place")
    elif taking[0].get("replaces") != name:
        said.append(f"it is installed and service {name}.replaces is {taking[0].get('replaces')!r}, not {name!r}")
    said += [f"it is installed and service {service.get('id')}.api names an in-process adapter"
             for service in services if "api" in service]
    return said


def service_problems(service: dict) -> list[str]:
    """One service of a first-party part: `replaces`, `reaches` and `asks_for`, and `critical`."""
    where = f"service {service.get('id')}"
    said = []
    if "replaces" in service and service["replaces"] != service.get("id"):
        said.append(f"{where}.replaces {service['replaces']!r} is not its own id")
    if "reaches" not in service or "asks_for" not in service:
        said.append(f"{where} does not declare both reaches and asks_for")
    elif not isinstance(service["asks_for"], str) or not service["asks_for"].strip():
        said.append(f"{where}.asks_for is blank")
    if service.get("criticality") == CRITICAL and service.get("shape") != EGRESS_GUARD:
        said.append(f"{where} is critical without shape = {EGRESS_GUARD!r}")
    return said


def forms_problems(pin: dict, plugin: dict, forms: list[dict]) -> list[str]:
    """`[plugin].forms` names exactly the forms whose closure holds the pin's profile."""
    holding = sorted(str(form.get("id")) for form in forms if pin["profile"] in listed(form, "profiles"))
    declared = listed(plugin, "forms")
    if sorted(map(str, declared)) == holding:
        return []
    profile = pin["profile"]
    return [f"[plugin].forms is {declared}, and the forms whose closure holds profile {profile!r} are {holding}"]


def licence_problems(plugin: dict, built: list[dict]) -> list[str]:
    """An OSI licence, or `Hippocratic-3.0` for lemonfiber's own code in an image it builds (F2-R5)."""
    licence = plugin.get("license")
    if str(plugin.get("upstream", "")).startswith(OWN_ORIGINS) and built:
        return [] if licence == OWN_LICENCE else [
            f"its licence is {licence!r}, and lemonfiber's own code with its own image carries {OWN_LICENCE}"
        ]
    return [] if licence in osi() else [f"its licence {licence!r} is not an OSI identifier"]


def release_problems(pin: dict, built: list[dict]) -> list[str]:
    """A release only on a part that builds an image, every image it builds tagged at it (OPS-R86)."""
    if "release" not in pin:
        return []
    said = [] if built else [f"it names release {pin['release']}, and it builds no image, so the train never tags it"]
    return said + [
        f"the image service {service.get('id')!r} is tagged {service.get('tag')!r}, not the pinned "
        f"release {pin['release']!r}"
        for service in built
        if service.get("tag") != pin["release"]
    ]


def part_problems(pin: dict, manifest: dict, forms: list[dict]) -> list[str]:
    """Everything a schema 2 pin's manifest has to say for it."""
    name = pin["id"]
    plugin = plugin_of(manifest)
    services = services_of(manifest)
    built = built_of(services)
    said = [] if plugin.get("id") == name else [f"the copy declares [plugin].id {plugin.get('id')!r}, not {name!r}"]
    said += (assembled_problems(name, manifest, services) if pin["stage"] == ASSEMBLED
             else installed_problems(name, services))
    said += [line for service in services for line in service_problems(service)]
    filled = filled_by(services)
    said += [f"fills {it!r}, which no service of the copy provides or speaks" for it in pin["fills"]
             if it not in filled]
    return [*said, *forms_problems(pin, plugin, forms), *licence_problems(plugin, built),
            *release_problems(pin, built)]


def proxied_to(text: str) -> str | None:
    """The service a `reverse_proxy <service>:<port>` in `text` names."""
    target = text.partition("reverse_proxy ")[2].split()
    return (target[0].split(":")[0] or None) if target else None


def answered(text: str) -> list[tuple[str, str | None]]:
    """Each label a proxy configuration answers on in front of the operator's domain, with the
    service its stanza's first `reverse_proxy` names. A commented-out stanza still names its label."""
    found: list[tuple[str, str | None]] = []
    opened: str | None = None
    for line in text.splitlines():
        said = line.lstrip().lstrip("#").lstrip()
        label, marker, rest = said.partition(DOMAIN)
        if marker and LABEL.match(label):
            if opened is not None:
                found.append((opened, None))
            opened, said = label, rest
        if opened is None:
            continue
        target = proxied_to(said)
        if target is not None or said.startswith("}"):
            found.append((opened, target))
            opened = None
    if opened is not None:
        found.append((opened, None))
    return found


def hostnames_of(manifest: dict) -> list[tuple[str, str]]:
    """Each label a plugin's household services are proxied at, with the service."""
    services = services_of(manifest)
    alone = str(services[0].get("id")) if len(services) == 1 else None
    wired = {str(row.get("service", alone)): row["hostname"] for row in listed(manifest, "wiring")
             if isinstance(row, dict) and "hostname" in row}
    return [
        (str(wired.get(str(service.get("id")), service.get("id"))), str(service.get("id")))
        for service in services
        if service.get("bind") == HOUSEHOLD and service.get("port") is not None
    ]


def ports_of(service: dict) -> list[object]:
    """Every port a service publishes on the host."""
    published = [row.get("port") for row in listed(service, "publish") if isinstance(row, dict)]
    return [port for port in (service.get("port"), *published) if port is not None]


def held(register: Register, kind: str, value: object, name: str) -> None:
    """Record that `name` holds `value` of `kind`."""
    register.setdefault((kind, str(value)), set()).add(name)


def proxy_labels(root: pathlib.Path, service: dict) -> list[tuple[str, str | None]]:
    """Every label the starting files of a proxy service answer on, with the service each routes to."""
    found = []
    for path in sorted((root / tree.CONFIG / str(service.get("id"))).rglob("*")):
        if path.is_file() and not path.is_symlink():
            found += answered(path.read_text(encoding="utf-8", errors="replace"))
    return found


def service_holdings(reserved: Register, name: str, part: dict) -> None:
    """Record every id, published port and household hostname `name`'s services hold."""
    for service in services_of(part):
        held(reserved, "id", service.get("id"), name)
        for port in ports_of(service):
            held(reserved, "port", port, name)
    for label, _ in hostnames_of(part):
        held(reserved, "hostname", label, name)


def proxy_holdings(reserved: Register, name: str, part: dict, root: pathlib.Path, owner: dict[str, str]) -> None:
    """Record every label `name`'s proxy configuration answers on, held by the plugin of the
    pinned service it routes to, or by `name` where it routes to none."""
    for service in services_of(part):
        if PROXY in listed(service, "provides"):
            for label, target in proxy_labels(root, service):
                held(reserved, "hostname", label, owner.get(str(target), name))


def register(parts: dict[str, dict], roots: dict[str, pathlib.Path]) -> Register:
    """The reserved register: each id, port and hostname, and the plugins holding it (ARCH-R269)."""
    reserved: Register = {}
    owner = {str(service.get("id")): name for name, part in parts.items() for service in services_of(part)}
    for name, part in parts.items():
        service_holdings(reserved, name, part)
        if name in roots:
            proxy_holdings(reserved, name, part, roots[name], owner)
    return reserved


def wiring_named(row: dict) -> str:
    """How a wiring is named in what is said about it."""
    said = f"asks {row['asks']!r}" if "asks" in row else f"to {row.get('to')!r}"
    return f"[[wiring]] {row.get('by')!r} {said}"


def asked_problems(row: dict, part: dict, services: dict[str, tuple[str, dict]]) -> list[str]:
    """A choice of filler: `by`'s plugin asks the capability, not of each, and `filled_by` fills it."""
    where = wiring_named(row)
    alone = len(services_of(part)) == 1
    asked = [ask for ask in listed(part, "ask") if isinstance(ask, dict)
             and ask.get("capability") == row["asks"]
             and ask.get("service", row["by"] if alone else None) == row["by"]]
    said = []
    if not asked:
        said.append(f"{where}: {row['by']}'s plugin asks no {row['asks']!r} in its [[ask]]")
    elif any(ask.get("each") is True for ask in asked):
        said.append(f"{where}: {row['by']} asks {row['asks']!r} of each filler, so there is none to choose")
    if row.get("filled_by") in services and row["asks"] not in filled_by([services[row["filled_by"]][1]]):
        said.append(f"{where}: {row['filled_by']} neither provides nor speaks {row['asks']!r}")
    return said


def across(wirings: list[dict], parts: dict[str, dict], roots: dict[str, pathlib.Path]) -> list[str]:
    """What holds across the pinned plugins: the reserved register, and the wiring's services and asks."""
    problems = [
        f"{kind} {value!r} is reserved by {' and '.join(sorted(holders))} (ARCH-R269)"
        for (kind, value), holders in sorted(register(parts, roots).items())
        if len(holders) > 1
    ]
    services = {str(service.get("id")): (name, service) for name, part in parts.items()
                for service in services_of(part)}
    for row in wirings:
        problems += [f"{wiring_named(row)}: {key} {row[key]!r} is no service of a pinned plugin"
                     for key in ("by", "to", "filled_by") if key in row and row[key] not in services]
        if "asks" in row and row.get("by") in services:
            problems += asked_problems(row, parts[services[row["by"]][0]], services)
    return problems

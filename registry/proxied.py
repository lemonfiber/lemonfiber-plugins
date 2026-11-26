"""What the proxy's configuration in a pinned plugin's copy answers on (ARCH-R269).

Every file a proxy plugin starts its services with is read in the format its name says:
Caddy's JSON configuration (`*.json`) or Traefik's (`*.toml`). Each host a route or a
router answers on is held by its first label, beside the service it forwards to. A file
in any other format, one that does not parse, a host no label can be read from and a
route or router that answers on hosts it does not name are refused rather than read as
answering on nothing.
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib
import urllib.parse

import tree

PROXY = "proxy.front"
CADDY = ".json"
TRAEFIK = ".toml"
LABEL = re.compile(r"\A[a-z0-9-]+\Z")
MATCHER = re.compile(r"\b(\w+)\(([^)]*)\)")
HOSTS = ("Host", "HostSNI")
QUOTED = re.compile(r"`([^`]*)`")
ROUTED = ("http", "tcp")
EITHER = "||"
NEGATION = "!"

Answered = list[tuple[str, str | None]]


class Unread(Exception):
    """Why a proxy configuration cannot be read for what it answers on."""


def label(host: object) -> str:
    """The first label of `host`, which the reserved register holds it by."""
    first = host.split(".", 1)[0] if isinstance(host, str) else ""
    if not LABEL.match(first):
        raise Unread(f"host {host!r} names no label of lower-case letters, digits and hyphens")
    return first


def dialled(value: object) -> str | None:
    """The service the first upstream under `value` dials, at any depth."""
    if isinstance(value, dict):
        for field, inner in value.items():
            if field == "dial" and isinstance(inner, str):
                return inner.rsplit(":", 1)[0] or None
            found = dialled(inner)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = dialled(item)
            if found is not None:
                return found
    return None


def matched_hosts(route: dict) -> list[str]:
    """Every host a Caddy route's matchers name."""
    matchers = route.get("match", [])
    if not isinstance(matchers, list) or not all(isinstance(one, dict) for one in matchers):
        raise Unread("a route's match is not a list of matchers")
    hosts: list[str] = []
    for matcher in matchers:
        named = matcher.get("host", [])
        if not isinstance(named, list):
            raise Unread("a route's host matcher is not a list")
        hosts += named
    return hosts


def caddy_routes(value: object, hosted: bool, found: Answered) -> None:
    """Each host the routes under `value` answer on; a route outside every host's answers on all."""
    if isinstance(value, list):
        for item in value:
            caddy_routes(item, hosted, found)
        return
    if not isinstance(value, dict):
        return
    for field, inner in value.items():
        if field == "routes" and isinstance(inner, list):
            for route in inner:
                if not isinstance(route, dict):
                    raise Unread("a route is not an object")
                hosts = matched_hosts(route)
                if not hosts and not hosted:
                    raise Unread("a route matching no host answers on every host")
                target = dialled(route.get("handle"))
                found += [(label(host), target) for host in hosts]
                caddy_routes(route, hosted or bool(hosts), found)
        elif field != "match":
            caddy_routes(inner, hosted, found)


def caddy(text: str) -> Answered:
    """Each label Caddy's JSON configuration answers on, with the service it forwards to."""
    try:
        read = json.loads(text)
    except ValueError as error:
        raise Unread(f"it is not JSON: {error}") from error
    found: Answered = []
    caddy_routes(read, False, found)
    return found


def rule_hosts(rule: object) -> list[str]:
    """Every host a Traefik rule matches on. A rule with an alternative matching no host, or
    negating a matcher, answers on hosts it does not name, and is refused."""
    if not isinstance(rule, str):
        raise Unread("a router's rule is not text")
    if NEGATION in rule:
        raise Unread(f"rule {rule!r} negates a matcher, so it answers on hosts it does not name")
    hosts: list[str] = []
    for alternative in rule.split(EITHER):
        named: list[str] = []
        for matcher, arguments in MATCHER.findall(alternative):
            if matcher.startswith("Host") and matcher not in HOSTS:
                raise Unread(f"rule {rule!r} matches hosts by {matcher}, which names no label")
            if matcher in HOSTS:
                named += QUOTED.findall(arguments)
        if not named:
            raise Unread(f"rule {rule!r} has an alternative matching no host, so it answers on every host")
        hosts += named
    return hosts


def upstream(services: dict, name: object) -> str | None:
    """The service a Traefik service of `name` forwards to first."""
    service = services.get(name) if isinstance(name, str) else None
    balanced = service.get("loadBalancer") if isinstance(service, dict) else None
    servers = balanced.get("servers") if isinstance(balanced, dict) else None
    first = servers[0] if isinstance(servers, list) and servers and isinstance(servers[0], dict) else {}
    if isinstance(first.get("url"), str):
        return urllib.parse.urlsplit(first["url"]).hostname
    if isinstance(first.get("address"), str):
        return first["address"].rsplit(":", 1)[0] or None
    return None


def traefik(text: str) -> Answered:
    """Each label Traefik's TOML configuration answers on, with the service it forwards to."""
    try:
        read = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise Unread(f"it is not TOML: {error}") from error
    found: Answered = []
    for kind in ROUTED:
        table = read.get(kind, {})
        routers = table.get("routers", {}) if isinstance(table, dict) else None
        services = table.get("services", {}) if isinstance(table, dict) else None
        if not isinstance(routers, dict) or not isinstance(services, dict):
            raise Unread(f"{kind} is not a table of routers and services")
        for router in routers.values():
            if not isinstance(router, dict):
                raise Unread(f"a {kind} router is not a table")
            target = upstream(services, router.get("service"))
            found += [(label(host), target) for host in rule_hosts(router.get("rule"))]
    return found


READERS = {CADDY: caddy, TRAEFIK: traefik}


def answered(root: pathlib.Path, services: list[str]) -> tuple[Answered, list[str]]:
    """Each label the starting files of `services` in `root` answer on, with the service each
    forwards to, and every file that cannot be read for it."""
    found: Answered = []
    refused: list[str] = []
    for service in services:
        starting, _ = tree.starting_files(root, service)
        for path in starting:
            suffix = pathlib.PurePosixPath(path).suffix
            if pathlib.PurePosixPath(path).name == tree.PLACEHOLDER:
                continue
            if suffix not in READERS:
                refused.append(f"the proxy configuration {path} is in no format read for the hosts it answers on, "
                               f"which are {sorted(READERS)}")
                continue
            try:
                found += READERS[suffix](tree.contained(root, path).read_text(encoding="utf-8"))
            except (Unread, tree.Unreadable, UnicodeDecodeError) as why:
                refused.append(f"the proxy configuration {path} cannot be read for the hosts it answers on: {why}")
    return found, refused

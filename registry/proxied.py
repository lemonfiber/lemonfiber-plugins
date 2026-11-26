"""What the proxy's configuration in a pinned plugin's copy answers on (ARCH-R269).

Every file a proxy plugin starts its services with is read in the format its name says:
Caddy's JSON configuration (`*.json`) or Traefik's (`*.toml`). Each host a route or a
router answers on is held by its first label, beside every service it forwards to. What
cannot be read with certainty is refused rather than read as answering on nothing: a
file in any other format or one that does not parse, a host no label can be read from,
a route or router that answers on hosts it does not name, and an upstream that cannot
be named.
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
DIAL = re.compile(r"\A([a-z0-9-]+(?:\.[a-z0-9-]+)*):\d+\Z")
FORWARDS = "reverse_proxy"
TEMPLATE = "{{"
ROUTED = ("http", "tcp")
BALANCER = "loadBalancer"
PROVIDER = "@"

#: Traefik's matchers this reads, each in every spelling its parser accepts: as declared,
#: lower case, upper case and capitalised.
HOSTS = ("Host", "HostSNI")
OTHERS = ("ALPN", "ClientIP", "Header", "HeaderRegexp", "Method", "Path", "PathPrefix", "PathRegexp",
          "Query", "QueryRegexp")
SPELLINGS = {spelled: name for name in (*HOSTS, *OTHERS)
             for spelled in (name, name.lower(), name.upper(), name.lower().capitalize())}

TOKEN = re.compile(r"""\s*(?:
    (?P<and>&&) | (?P<or>\|\|) | (?P<not>!) | (?P<open>\() | (?P<close>\)) | (?P<comma>,)
    | `(?P<raw>[^`]*)` | "(?P<quoted>[^"\\]*)" | (?P<name>[A-Za-z][A-Za-z0-9]*)
    )""", re.VERBOSE)

Answered = list[tuple[str, list[str]]]
Hosts = frozenset[str] | None


class Unread(Exception):
    """Why a proxy configuration cannot be read for what it answers on."""


def label(host: object) -> str:
    """The first label of `host`, which the reserved register holds it by."""
    first = host.split(".", 1)[0] if isinstance(host, str) else ""
    if not LABEL.match(first):
        raise Unread(f"host {host!r} names no label of lower-case letters, digits and hyphens")
    return first


def dial_of(upstream: object) -> str:
    """The service a Caddy upstream dials."""
    dial = upstream.get("dial") if isinstance(upstream, dict) else None
    matched = DIAL.match(dial) if isinstance(dial, str) else None
    if matched is None:
        raise Unread(f"upstream {upstream!r} dials no service named by host and port")
    return matched.group(1)


def forwarded(handler: dict) -> list[str]:
    """Every service a `reverse_proxy` handler forwards to, which has to be named."""
    upstreams = handler.get("upstreams")
    if not isinstance(upstreams, list) or not upstreams or "dynamic_upstreams" in handler:
        raise Unread("a reverse_proxy names no fixed upstreams")
    return [dial_of(upstream) for upstream in upstreams]


def dialled(value: object, found: list[str]) -> list[str]:
    """Every service each `reverse_proxy` handler under `value` forwards to, at any depth."""
    if isinstance(value, list):
        for item in value:
            dialled(item, found)
    elif isinstance(value, dict):
        if value.get("handler") == FORWARDS:
            found += forwarded(value)
        for inner in value.values():
            dialled(inner, found)
    return found


def matcher_sets(route: dict) -> list[list[str]]:
    """The hosts each of a Caddy route's matcher sets names; Caddy ORs the sets."""
    sets = route.get("match", [])
    if not isinstance(sets, list) or not all(isinstance(one, dict) for one in sets):
        raise Unread("a route's match is not a list of matcher sets")
    named: list[list[str]] = []
    for one in sets:
        hosts = one.get("host", [])
        if not isinstance(hosts, list):
            raise Unread("a route's host matcher is not a list")
        named.append(hosts)
    return named


def caddy_route(route: object, hosted: bool, found: Answered) -> None:
    """Each host one Caddy route answers on. A route outside every host's route with no
    matcher set, or one naming no host, answers on every host."""
    if not isinstance(route, dict):
        raise Unread("a route is not an object")
    sets = matcher_sets(route)
    limited = bool(sets) and all(sets)
    if not hosted and not limited:
        raise Unread("a route with no matcher set, or one naming no host, answers on every host")
    targets = dialled(route.get("handle", []), [])
    found += [(label(host), targets) for hosts in sets for host in hosts]
    caddy_routes(route, hosted or limited, found)


def caddy_routes(value: object, hosted: bool, found: Answered) -> None:
    """Each host the routes under `value` answer on, at any depth."""
    if isinstance(value, list):
        for item in value:
            caddy_routes(item, hosted, found)
        return
    if not isinstance(value, dict):
        return
    for field, inner in value.items():
        if field == "routes" and isinstance(inner, list):
            for route in inner:
                caddy_route(route, hosted, found)
        elif field != "match":
            caddy_routes(inner, hosted, found)


def caddy(text: str) -> Answered:
    """Each label Caddy's JSON configuration answers on, with every service it forwards to."""
    try:
        read = json.loads(text)
    except ValueError as error:
        raise Unread(f"it is not JSON: {error}") from error
    found: Answered = []
    caddy_routes(read, False, found)
    return found


def tokens(rule: str) -> list[tuple[str, str]]:
    """A Traefik rule as its tokens, each its kind and its text; refused where one is not."""
    read: list[tuple[str, str]] = []
    at = 0
    while rule[at:].strip():
        matched = TOKEN.match(rule, at)
        if matched is None:
            raise Unread(f"rule {rule!r} cannot be read past {rule[at:]!r}")
        kind = matched.lastgroup or ""
        read.append(("string" if kind in ("raw", "quoted") else kind, matched.group(kind)))
        at = matched.end()
    return read


class Rule:
    """A Traefik rule read whole, as the hosts it is limited to, or none where it is not."""

    def __init__(self, rule: str) -> None:
        self.written = rule
        self.read = tokens(rule)
        self.at = 0

    def peek(self) -> str | None:
        """The kind of the next token, if any is left."""
        return self.read[self.at][0] if self.at < len(self.read) else None

    def take(self, kind: str) -> str:
        """The next token's text, which has to be of `kind`."""
        if self.peek() != kind:
            raise Unread(f"rule {self.written!r} cannot be read: {kind} wanted at token {self.at + 1}")
        self.at += 1
        return self.read[self.at - 1][1]

    def whole(self) -> Hosts:
        """The rule, every token of it."""
        hosts = self.either()
        if self.peek() is not None:
            raise Unread(f"rule {self.written!r} cannot be read past token {self.at + 1}")
        return hosts

    def either(self) -> Hosts:
        """Alternatives joined by `||`: limited only where every one is."""
        hosts = self.both()
        while self.peek() == "or":
            self.take("or")
            other = self.both()
            hosts = None if hosts is None or other is None else hosts | other
        return hosts

    def both(self) -> Hosts:
        """Conditions joined by `&&`: limited where any one is."""
        hosts = self.one()
        while self.peek() == "and":
            self.take("and")
            other = self.one()
            if hosts is None:
                hosts = other
            elif other is not None:
                hosts = hosts & other
        return hosts

    def one(self) -> Hosts:
        """A negation, which limits nothing, a parenthesised rule, or a matcher."""
        if self.peek() == "not":
            self.take("not")
            self.one()
            return None
        if self.peek() == "open":
            self.take("open")
            hosts = self.either()
            self.take("close")
            return hosts
        return self.matcher()

    def matcher(self) -> Hosts:
        """A matcher this reads, and the hosts it names where it matches by host."""
        spelled = self.take("name")
        name = SPELLINGS.get(spelled)
        if name is None:
            raise Unread(f"rule {self.written!r} matches by {spelled}, which this does not read")
        self.take("open")
        arguments = [self.take("string")]
        while self.peek() == "comma":
            self.take("comma")
            arguments.append(self.take("string"))
        self.take("close")
        return frozenset(argument.lower() for argument in arguments) if name in HOSTS else None


def rule_hosts(rule: object) -> list[str]:
    """Every host a Traefik rule is limited to; a rule limited to none answers on every host."""
    if not isinstance(rule, str):
        raise Unread("a router's rule is not text")
    hosts = Rule(rule).whole()
    if hosts is None:
        raise Unread(f"rule {rule!r} is not limited to the hosts it names, so it answers on every host")
    return sorted(hosts)


def server_host(server: object, kind: str) -> str:
    """The service a server of a Traefik load balancer forwards to."""
    field = "url" if kind == "http" else "address"
    written = server.get(field) if isinstance(server, dict) else None
    host = None
    if isinstance(written, str):
        host = urllib.parse.urlsplit(written).hostname if kind == "http" else written.rsplit(":", 1)[0]
    if not host or not LABEL.match(host.split(".", 1)[0]):
        raise Unread(f"server {server!r} names no service by its {field}")
    return host


def upstreams(services: dict, name: object, kind: str) -> list[str]:
    """Every service a Traefik service of this file forwards to, from a plain load balancer."""
    if not isinstance(name, str) or PROVIDER in name:
        raise Unread(f"router service {name!r} is not one of this file's own")
    service = services.get(name)
    if not isinstance(service, dict) or set(service) != {BALANCER}:
        raise Unread(f"service {name!r} is not a plain load balancer of this file")
    servers = service[BALANCER].get("servers") if isinstance(service[BALANCER], dict) else None
    if not isinstance(servers, list) or not servers:
        raise Unread(f"service {name!r} names no servers")
    return [server_host(server, kind) for server in servers]


def routing(read: dict, kind: str) -> tuple[dict, dict]:
    """The routers and the services of one kind a Traefik configuration declares."""
    table = read.get(kind, {})
    routers = table.get("routers", {}) if isinstance(table, dict) else None
    services = table.get("services", {}) if isinstance(table, dict) else None
    if not isinstance(routers, dict) or not isinstance(services, dict):
        raise Unread(f"{kind} is not a table of routers and services")
    return routers, services


def traefik(text: str) -> Answered:
    """Each label Traefik's TOML configuration answers on, with every service it forwards to."""
    if TEMPLATE in text:
        raise Unread("it is a template, which Traefik expands before it reads it")
    try:
        read = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise Unread(f"it is not TOML: {error}") from error
    found: Answered = []
    for kind in ROUTED:
        routers, services = routing(read, kind)
        for router in routers.values():
            if not isinstance(router, dict):
                raise Unread(f"a {kind} router is not a table")
            targets = upstreams(services, router.get("service"), kind)
            found += [(label(host), targets) for host in rule_hosts(router.get("rule"))]
    return found


READERS = {CADDY: caddy, TRAEFIK: traefik}


def read_file(root: pathlib.Path, path: str) -> Answered:
    """Each label one starting file of a proxy answers on, with every service each forwards
    to. An empty placeholder is no configuration; one holding anything is read as any other."""
    try:
        content = tree.contained(root, path).read_bytes()
    except (tree.Unreadable, OSError) as why:
        raise Unread(f"it cannot be read: {why}") from why
    if pathlib.PurePosixPath(path).name == tree.PLACEHOLDER and not content:
        return []
    reader = READERS.get(pathlib.PurePosixPath(path).suffix)
    if reader is None:
        raise Unread(f"it is in no format read for the hosts it answers on, which are {sorted(READERS)}")
    try:
        return reader(content.decode("utf-8"))
    except UnicodeDecodeError as why:
        raise Unread(f"it is not UTF-8: {why}") from why


def answered(root: pathlib.Path, services: list[str]) -> tuple[Answered, list[str]]:
    """Each label the starting files of `services` in `root` answer on, with every service
    each forwards to, and every file that cannot be read for it."""
    found: Answered = []
    refused: list[str] = []
    for service in services:
        starting, _ = tree.starting_files(root, service)
        for path in starting:
            try:
                found += read_file(root, path)
            except Unread as why:
                refused.append(f"the proxy configuration {path} cannot be read for the hosts it answers on: {why}")
    return found, refused

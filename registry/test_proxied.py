"""What a proxy's configuration is read as answering on, each format against the shapes it
reads and the ones it refuses (ARCH-R269); run by `bundle.py --self-test` through `test_bundle`."""

from __future__ import annotations

import json

import proxied
from test_bundle import Case, caddy_config


def answers(reader, text: str) -> object:
    """What `reader` reads `text` as answering on, or None where it refuses it."""
    try:
        return reader(text)
    except proxied.Unread:
        return None


def unread(reader, text: str) -> bool:
    """Whether `reader` refuses `text` rather than reading what it answers on."""
    try:
        reader(text)
    except proxied.Unread:
        return True
    return False


TRAEFIK_CONFIG = """
[http.routers.watch]
rule = "Host(`watch.home.local`) || Host(`tv.home.local`) && PathPrefix(`/`)"
service = "door"

[http.services.door.loadBalancer]
servers = [{ url = "http://door:8096" }]

[tcp.routers.books]
rule = "HostSNI(`books.home.local`)"
service = "books"

[tcp.services.books.loadBalancer]
servers = [{ address = "calibre:8083" }]
"""


def routed(rule: str, servers: str = '{ url = "http://door:8096" }', service: str = "s") -> str:
    """Traefik's TOML configuration of one HTTP router of `rule` and the service it names."""
    return (f"[http.routers.r]\nrule = '{rule}'\nservice = '{service}'\n"
            f"[http.services.s.loadBalancer]\nservers = [{servers}]\n")


def caddy_route(match: list[dict], handle: list[dict] | None = None) -> str:
    """Caddy's JSON configuration of one route."""
    return json.dumps({"routes": [{"match": match, "handle": handle or []}]})


def cases() -> list[Case]:
    """What a proxy configuration answers on, as the reserved register reads it (ARCH-R269)."""
    caddy = caddy_config(("watch.home.local", "door:8096"), ("bare.home.local", "")).decode()
    unhosted = json.dumps({"apps": {"http": {"servers": {"s": {"routes": [{"handle": []}]}}}}})
    nested = json.dumps({"routes": [{"match": [{"host": ["watch.home.local"]}], "handle": [
        {"handler": "subroute", "routes": [{"match": [{"path": ["/x"]}], "handle": []}]}]}]})
    door = [("watch", ["door"])]
    return [
        ("each host Caddy's JSON answers on is read by its label with every service it forwards to", True,
         answers(proxied.caddy, caddy) == [("watch", ["door"]), ("bare", [])]),
        ("a route inside a host's route matching no host of its own is read", True,
         answers(proxied.caddy, nested) == [("watch", [])]),
        ("a Caddy route matching no host refused", True, unread(proxied.caddy, unhosted)),
        ("a Caddy route of two matcher sets, each naming a host, is read", True,
         answers(proxied.caddy, caddy_route([{"host": ["watch.home.local"]}, {"host": ["tv.home.local"]}]))
         == [("watch", []), ("tv", [])]),
        ("a Caddy route with a matcher set naming no host beside one naming a host refused", True,
         unread(proxied.caddy, caddy_route([{"host": ["watch.home.local"]}, {"path": ["/x"]}]))),
        ("a Caddy route forwarding to two services names both", True,
         answers(proxied.caddy, caddy_config(("watch.home.local", ("door:8096", "sonarr:8989"))).decode())
         == [("watch", ["door", "sonarr"])]),
        ("a Caddy reverse_proxy of dynamic upstreams refused", True,
         unread(proxied.caddy, caddy_route([{"host": ["watch.home.local"]}], [
             {"handler": "reverse_proxy", "dynamic_upstreams": {"source": "a", "name": "door"}}]))),
        ("a Caddy upstream dialling a placeholder refused", True,
         unread(proxied.caddy, caddy_config(("watch.home.local", "{http.request.host}:80")).decode())),
        ("a Caddy wildcard host refused", True,
         unread(proxied.caddy, caddy_config(("*.home.local", "door:8096")).decode())),
        ("a Caddy host matcher that is not a list refused", True,
         unread(proxied.caddy, nested.replace('{"path": ["/x"]}', '{"host": "tv.home.local"}'))),
        ("a Caddy configuration that is not JSON refused", True, unread(proxied.caddy, "watch.{$DOMAIN} {}")),
        ("each host Traefik's TOML answers on is read by its label with every service it forwards to", True,
         answers(proxied.traefik, TRAEFIK_CONFIG) == [("tv", ["door"]), ("watch", ["door"]), ("books", ["calibre"])]),
        ("a Traefik router of one host is read", True, answers(proxied.traefik, routed("Host(`watch.home.local`)")) == door),
        ("Traefik's static configuration answers on nothing", True,
         answers(proxied.traefik, '[entryPoints.web]\naddress = ":8080"\n[providers.file]\nfilename = "d.toml"\n') == []),
        ("an empty Traefik configuration answers on nothing", True, answers(proxied.traefik, "") == []),
        ("a Traefik configuration Traefik expands as a template refused", True,
         unread(proxied.traefik, routed('Host(`watch.{{ env "DOMAIN" }}`)'))),
        ("a Traefik rule's string holding a parenthesis is read whole", True,
         answers(proxied.traefik, routed("Host(`watch.home.local`) && PathPrefix(`/a)b`)")) == door),
        ("a Traefik matcher in a spelling Traefik's parser accepts is read", True,
         answers(proxied.traefik, routed("host(`watch.home.local`) && PATHPREFIX(`/`)")) == door),
        ("a Traefik host is read in lower case, as Traefik matches it", True,
         answers(proxied.traefik, routed("Host(`Watch.home.local`)")) == door),
        ("a Traefik host in double quotes is read", True, answers(proxied.traefik, routed('Host("watch.home.local")')) == door),
        ("a Traefik rule grouping alternatives under a host is read", True,
         answers(proxied.traefik, routed("(Host(`watch.home.local`) || Host(`tv.home.local`)) && Path(`/`)"))
         == [("tv", ["door"]), ("watch", ["door"])]),
        ("a Traefik matcher this does not read refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`) && Hots(`x`)"))),
        ("a Traefik rule not read to its end refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`) Host(`tv.home.local`)"))),
        ("a Traefik rule holding what no token reads refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`) $"))),
        ("a Traefik string with an escape refused", True,
         unread(proxied.traefik, routed('Host("watch.home\\x2elocal")'))),
        ("a Traefik router matching hosts by a pattern refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`) || HostRegexp(`^.+$`)"))),
        ("a Traefik router matching every host refused", True, unread(proxied.traefik, routed("Host(`*`)"))),
        ("a Traefik router matching no host refused", True, unread(proxied.traefik, routed("PathPrefix(`/`)"))),
        ("a Traefik rule with an alternative matching no host refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`) || PathPrefix(`/`)"))),
        ("a Traefik rule negating a matcher refused", True,
         unread(proxied.traefik, routed("!Host(`watch.home.local`)"))),
        ("a Traefik load balancer of two services names both", True,
         answers(proxied.traefik, routed("Host(`watch.home.local`)", '{ url = "http://door:8096" }, { url = "http://sonarr:8989" }'))
         == [("watch", ["door", "sonarr"])]),
        ("a Traefik router naming another provider's service refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`)", service="api@internal").replace(
             "[http.services.s.", '[http.services."api@internal".'))),
        ("a Traefik router naming a service this file does not declare refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`)", service="t"))),
        ("a Traefik service mirroring beside its load balancer refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`)") + "[http.services.s.mirroring]\nservice = 't'\n")),
        ("a Traefik server naming no service refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`)", '{ url = "http://:8096" }'))),
        ("a Traefik router whose rule is not text refused", True,
         unread(proxied.traefik, routed("Host(`watch.home.local`)").replace("rule = 'Host(`watch.home.local`)'", "rule = 1"))),
        ("Traefik routers that are not a table refused", True, unread(proxied.traefik, 'http = { routers = 1 }\n')),
        ("a Traefik configuration that is not TOML refused", True, unread(proxied.traefik, "[http")),
    ]

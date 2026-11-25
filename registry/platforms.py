#!/usr/bin/env python3
"""Hold every upstream image a bundled plugin pins to both platforms (F2-R6).

Every `[[service]]` of every plugin the bundle pins, as a part or offered, names an image
and the digest it runs. Where the image is not one lemonfiber builds under
`ghcr.io/lemonfiber/`, which is held to both platforms where it is built, that digest is
asked of its registry with an anonymous pull token and has to be an index, an OCI image
index or a Docker manifest list, carrying both `linux/amd64` and `linux/arm64`.

A pin is refused naming the image, the digest and why: a single-platform image, a
platform missing, a media type this does not know, a registry that cannot be reached,
answers an error or limits the rate, or content whose digest is not the one pinned. None
of these passes. Every request is bounded by TIMEOUT_S, and the whole check by BUDGET_S:
a pin not asked before the budget runs out is refused too.

Run:  python3 registry/platforms.py
      python3 registry/platforms.py --self-test
Needs: the network to the public registries the pins name, and no credentials.
Exit 0 = every upstream image carries both platforms, 1 = one does not or could not be
asked.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import parts  # noqa: E402
import tree  # noqa: E402

import bundle  # noqa: E402

REQUIRED = ("linux/amd64", "linux/arm64")
SCHEME = "https"
TIMEOUT_S = 15
BUDGET_S = 240
MAX_REPLY = 4 * 1024 * 1024
SAID = 120
OK = 200
UNAUTHORISED = 401
RATE_LIMITED = 429
DOCKER_HUB = "registry-1.docker.io"
INDEX_TYPES = (
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
)
IMAGE_TYPES = (
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
)
ACCEPT = ", ".join(INDEX_TYPES + IMAGE_TYPES)
USER_AGENT = "lemonfiber-plugins"
REPOSITORY = re.compile(r"\A[a-z0-9]+(?:[._/-][a-z0-9]+)*\Z")
HOST = re.compile(r"\A[a-z0-9.-]+(?::\d+)?\Z", re.ASCII)
UNPRINTABLE = re.compile(r"[^A-Za-z0-9 .,;:/+_()-]")


@dataclasses.dataclass(frozen=True)
class Reply:
    """A registry's answer: its status, its body and its headers by lower-cased name."""

    status: int
    body: bytes
    headers: dict[str, str]


#: One bounded GET: the address, the request's headers and its timeout in seconds. It
#: answers every status as a reply and raises OSError where nothing answered.
Fetch = Callable[[str, dict[str, str], float], Reply]


class Unanswered(Exception):
    """Why a registry gave no answer this can hold a pin to."""


def printable(text: object) -> str:
    """One line of a network reply, fit to print into a workflow log."""
    return UNPRINTABLE.sub("?", str(text).strip().replace("\n", " "))[:SAID]


def address(image: str) -> tuple[str, str] | None:
    """The registry host and repository an image name refers to, or None.

    A first segment with a dot or a colon in it, or `localhost`, is a host, and anything
    else is on Docker Hub, where a single-segment name is an official image under
    `library/`. `docker.io` is Docker Hub's name, not the host its registry answers on.
    """
    first, _, rest = image.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        host, repository = first.lower(), rest
    else:
        host, repository = DOCKER_HUB, image if rest else f"library/{image}"
    if host in ("docker.io", "index.docker.io"):
        host = DOCKER_HUB
        repository = repository if "/" in repository else f"library/{repository}"
    if not HOST.match(host) or not REPOSITORY.match(repository):
        return None
    return host, repository


class SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to the host the request went to, over https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        here, there = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if there.scheme != SCHEME or there.netloc.lower() != here.netloc.lower():
            raise urllib.error.HTTPError(req.full_url, code, "redirected off the registry", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetched(url: str, headers: dict[str, str], timeout: float,
            opener: urllib.request.OpenerDirector | None = None) -> Reply:
    """The network's Fetch, through `opener` where one is given."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        reply = (opener or urllib.request.build_opener(SameHostRedirects)).open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        reply = error
    with reply:
        body = reply.read(MAX_REPLY + 1)
        return Reply(reply.status, body, {key.lower(): value for key, value in reply.headers.items()})


def asked(fetch: Fetch, clock: Callable[[], float], deadline: float, url: str, headers: dict[str, str]) -> Reply:
    """One request, inside what is left of the budget, or why it went unanswered."""
    left = deadline - clock()
    if left <= 0:
        raise Unanswered(f"not asked: the check ran past its {BUDGET_S} s budget")
    try:
        reply = fetch(url, headers, min(TIMEOUT_S, left))
    except OSError as error:
        raise Unanswered(f"the registry is unreachable: {printable(getattr(error, 'reason', error))}") from error
    if len(reply.body) > MAX_REPLY:
        raise Unanswered(f"the registry answered with more than {MAX_REPLY // 1024} KiB")
    return reply


def answered(reply: Reply, who: str) -> Reply:
    """A reply that is an answer, or why it is not one."""
    if reply.status == RATE_LIMITED:
        raise Unanswered(f"{who} limited the rate ({RATE_LIMITED})")
    if reply.status != OK:
        raise Unanswered(f"{who} answered {reply.status}")
    return reply


def challenge_fields(challenge: str) -> dict[str, str]:
    """The `key="value"` pairs of a `WWW-Authenticate` challenge, after its scheme."""
    fields = {}
    for part in challenge.partition(" ")[2].split(","):
        key, _, value = part.strip().partition("=")
        if key and len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            fields[key] = value[1:-1]
    return fields


def anonymous_token(ask: Callable[[str, dict[str, str]], Reply], challenge: str) -> str:
    """The pull token a registry's `WWW-Authenticate: Bearer` challenge offers anyone."""
    if not challenge.lower().startswith("bearer "):
        raise Unanswered("the registry asked for credentials this does not hold")
    fields = challenge_fields(challenge)
    realm = urllib.parse.urlsplit(fields.get("realm", ""))
    if realm.scheme != SCHEME or not realm.netloc:
        raise Unanswered("the registry's token service is not an https address")
    query = urllib.parse.urlencode({key: value for key, value in fields.items() if key in ("service", "scope")})
    reply = answered(ask(urllib.parse.urlunsplit((SCHEME, realm.netloc, realm.path, query, "")), {}),
                     "the token service")
    try:
        document = json.loads(reply.body)
    except ValueError as error:
        raise Unanswered("the token service answered with something that is not JSON") from error
    token = (document.get("token") or document.get("access_token")) if isinstance(document, dict) else None
    if not isinstance(token, str) or not token:
        raise Unanswered("the token service answered without a token")
    return token


def manifest(ask: Callable[[str, dict[str, str]], Reply], host: str, repository: str, digest: str) -> Reply:
    """The manifest a digest names, asked anonymously."""
    url = f"{SCHEME}://{host}/v2/{repository}/manifests/{digest}"
    headers = {"Accept": ACCEPT}
    reply = ask(url, headers)
    if reply.status == UNAUTHORISED:
        token = anonymous_token(ask, reply.headers.get("www-authenticate", ""))
        reply = ask(url, {**headers, "Authorization": f"Bearer {token}"})
    return answered(reply, "the registry")


def platforms_of(document: dict) -> set[str]:
    """Every `os/architecture` an index lists."""
    entries = document.get("manifests")
    return {
        f"{entry['platform'].get('os')}/{entry['platform'].get('architecture')}"
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("platform"), dict)
    }


def refusal(fetch: Fetch, clock: Callable[[], float], deadline: float, image: str, digest: object) -> str:
    """Why a pinned digest is not an index carrying both platforms, or empty where it is."""
    where = address(image)
    if where is None:
        return "is not an image name this will address"
    if not isinstance(digest, str) or not bundle.IMAGE_DIGEST.match(digest):
        return "pins no sha256 digest to ask for"

    def ask(url: str, headers: dict[str, str]) -> Reply:
        return asked(fetch, clock, deadline, url, headers)

    try:
        reply = manifest(ask, *where, digest)
    except Unanswered as why:
        return str(why)
    served = f"sha256:{hashlib.sha256(reply.body).hexdigest()}"
    if served != digest:
        return f"was served content whose digest is {served}"
    try:
        document = json.loads(reply.body)
    except ValueError:
        return "was answered with something that is not JSON"
    if not isinstance(document, dict):
        return "was answered with a manifest that is not a JSON object"
    declared = document.get("mediaType") or reply.headers.get("content-type", "").partition(";")[0].strip()
    if declared in IMAGE_TYPES:
        return "is a single-platform image, not an index of platforms"
    if declared not in INDEX_TYPES:
        return f"has the media type {printable(declared) or 'none'}, which this does not know"
    missing = [platform for platform in REQUIRED if platform not in platforms_of(document)]
    if missing:
        return f"lacks {' and '.join(missing)}"
    return ""


def pinned(held: dict[str, pathlib.Path]) -> Iterator[tuple[str, str, object]]:
    """Each upstream image a copy's services name: where, the image and its digest."""
    for name, path in sorted(held.items()):
        text = path.read_bytes() if path.is_file() else tree.contained(path, tree.MANIFEST).read_bytes()
        for service in bundle.parsed(text).get("service", []):
            image = service.get("image") if isinstance(service, dict) else None
            if isinstance(image, str) and not image.startswith(parts.OWN_IMAGES):
                yield f"{name}/{service.get('id')}", image, service.get("digest")


def checked(fetch: Fetch = fetched, clock: Callable[[], float] = time.monotonic) -> int:
    """Every upstream image the bundle in this checkout pins, held to both platforms."""
    try:
        read = bundle.read(bundle.BUNDLE.read_text(encoding="utf-8"))
        held = bundle.copies(bundle.COPIES, read.schema)
        images = list(pinned({pin["id"]: held[pin["id"]] for pin in read.pins if pin["id"] in held}))
    except (bundle.Refusal, OSError) as refused:
        for line in str(refused).splitlines():
            print(f"::error::{line}")
        return 1
    deadline = clock() + BUDGET_S
    refused = 0
    for where, image, digest in images:
        why = refusal(fetch, clock, deadline, image, digest)
        if why:
            refused += 1
            print(f"::error::{where}: {image}@{digest} {why}")
        else:
            print(f"  {where}: {image}@{digest} carries {' and '.join(REQUIRED)}")
    print(f"\n{len(images) - refused} of {len(images)} upstream images carry {' and '.join(REQUIRED)}.")
    return 1 if refused else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true",
                        help="prove each refusal refuses, with no network")
    if parser.parse_args().self_test:
        import test_platforms

        return test_platforms.self_test()
    return checked()


if __name__ == "__main__":
    sys.exit(main())

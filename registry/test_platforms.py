"""`platforms.py --self-test`: each refusal of an upstream image's platforms, and the pass,
against a registry answered from memory, so nothing reaches the network."""

from __future__ import annotations

import contextlib
import email.message
import hashlib
import io
import json
import pathlib
import tempfile
import urllib.error
import urllib.request
import urllib.response

import platforms
from platforms import Reply

Case = tuple[str, bool, bool]

HOST = "registry.example"
IMAGE = f"{HOST}/upstream/app"
REALM = "https://auth.example/token"
CHALLENGE = f'Bearer realm="{REALM}",service="{HOST}",scope="repository:upstream/app:pull"'
TOKEN_URL = f"{REALM}?service={HOST}&scope=repository%3Aupstream%2Fapp%3Apull"
INDEX = platforms.INDEX_TYPES[0]
LIST = platforms.INDEX_TYPES[1]
SINGLE = platforms.IMAGE_TYPES[1]
BOTH = ("linux/amd64", "linux/arm64")


def document(media_type: str | None, *listed: str) -> bytes:
    held: dict = {"schemaVersion": 2}
    if media_type is not None:
        held["mediaType"] = media_type
    held["manifests"] = [
        {"platform": {"os": one.partition("/")[0], "architecture": one.partition("/")[2]}} for one in listed
    ]
    held["manifests"].append({"platform": {"os": "unknown", "architecture": "unknown"}})
    return json.dumps(held).encode()


def digest_of(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def url_of(digest: str, host: str = HOST, repository: str = "upstream/app") -> str:
    return f"https://{host}/v2/{repository}/manifests/{digest}"


class Registry:
    """A registry answered from memory: by address, a reply or an error to raise."""

    def __init__(self, answers: dict[str, list[Reply | OSError]]) -> None:
        self.answers = {url: list(replies) for url, replies in answers.items()}
        self.asked: list[tuple[str, dict[str, str], float]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> Reply:
        self.asked.append((url, headers, timeout))
        queued = self.answers.get(url)
        if not queued:
            return Reply(404, b"", {})
        answer = queued.pop(0) if len(queued) > 1 else queued[0]
        if isinstance(answer, OSError):
            raise answer
        return answer


def behind_token(body: bytes, content_type: str = "", token: Reply | None = None,
                 after: Reply | None = None) -> tuple[Registry, str]:
    digest = digest_of(body)
    served = after or Reply(200, body, {"content-type": content_type} if content_type else {})
    registry = Registry({
        url_of(digest): [Reply(401, b"", {"www-authenticate": CHALLENGE}), served],
        TOKEN_URL: [token or Reply(200, json.dumps({"token": "anonymous"}).encode(), {})],
    })
    return registry, digest


def said(fetch: platforms.Fetch, digest: object, image: str = IMAGE, clock=lambda: 0.0,
         deadline: float = platforms.BUDGET_S) -> str:
    return platforms.refusal(fetch, clock, deadline, image, digest)


def refusals() -> list[Case]:
    index, both = behind_token(document(LIST, *BOTH))
    oci, oci_digest = behind_token(document(None, *BOTH), content_type=f"{INDEX}; charset=utf-8")
    single, single_digest = behind_token(json.dumps({"schemaVersion": 2, "mediaType": SINGLE}).encode())
    one_missing, one_digest = behind_token(document(INDEX, "linux/amd64", "linux/arm/v7"))
    none_listed, none_digest = behind_token(json.dumps({"mediaType": INDEX, "manifests": "x"}).encode())
    unknown, unknown_digest = behind_token(document("application/vnd.example.list+json", *BOTH))
    untyped, untyped_digest = behind_token(document(None, *BOTH))
    unreachable = Registry({url_of(both): [urllib.error.URLError("no route to host")]})
    timed_out = Registry({url_of(both): [TimeoutError("timed out")]})
    limited, limited_digest = behind_token(document(LIST, *BOTH), after=Reply(429, b"", {}))
    token_limited, token_limited_digest = behind_token(document(LIST, *BOTH), token=Reply(429, b"", {}))
    erred = Registry({url_of(both): [Reply(500, b"", {})]})
    still_refused, still_digest = behind_token(document(LIST, *BOTH), after=Reply(401, b"", {}))
    basic = Registry({url_of(both): [Reply(401, b"", {"www-authenticate": 'Basic realm="x"'})]})
    plain = Registry({url_of(both): [Reply(401, b"", {"www-authenticate": 'Bearer realm="http://auth.example/t"'})]})
    tokenless, tokenless_digest = behind_token(document(LIST, *BOTH), token=Reply(200, b"{}", {}))
    numbered, numbered_digest = behind_token(document(LIST, *BOTH), token=Reply(200, b'{"token": 5}', {}))
    garbled_token, garbled_digest = behind_token(document(LIST, *BOTH), token=Reply(200, b"<html>", {}))
    swapped = Registry({url_of(both): [Reply(200, document(LIST, *BOTH) + b" ", {})]})
    not_json, not_json_digest = behind_token(b"<html>")
    listed, listed_digest = behind_token(b"[1]")
    big, big_digest = behind_token(document(LIST, *BOTH), after=Reply(200, b" " * (platforms.MAX_REPLY + 1), {}))
    late = Registry({})
    later = [0.0, 0.0, 10.0]
    budget_ran_out, budget_digest = behind_token(document(LIST, *BOTH))

    return [
        ("an index carrying both platforms, behind an anonymous token, passes",
         True, said(index, both) == "" and index.asked[1][0] == TOKEN_URL
         and index.asked[2][1].get("Authorization") == "Bearer anonymous"
         and "Authorization" not in index.asked[0][1]),
        ("an OCI index that names its type only in the reply's header passes",
         True, said(oci, oci_digest) == ""),
        ("a single-platform image is refused",
         True, said(single, single_digest) == "is a single-platform image, not an index of platforms"),
        ("an index missing linux/arm64 is refused, naming it",
         True, said(one_missing, one_digest) == "lacks linux/arm64"),
        ("an index listing no platforms is refused, naming both",
         True, said(none_listed, none_digest) == "lacks linux/amd64 and linux/arm64"),
        ("a media type this does not know is refused",
         True, said(unknown, unknown_digest).startswith("has the media type application/vnd.example.list+json")),
        ("a manifest naming no media type anywhere is refused",
         True, said(untyped, untyped_digest) == "has the media type none, which this does not know"),
        ("a registry that cannot be reached is refused",
         True, said(unreachable, both) == "the registry is unreachable: no route to host"),
        ("a registry that does not answer in time is refused",
         True, said(timed_out, both) == "the registry is unreachable: timed out"),
        ("a registry that limits the rate is refused",
         True, said(limited, limited_digest) == "the registry limited the rate (429)"),
        ("a token service that limits the rate is refused",
         True, said(token_limited, token_limited_digest) == "the token service limited the rate (429)"),
        ("a registry answering an error is refused",
         True, said(erred, both) == "the registry answered 500"),
        ("a registry refusing the anonymous token is refused",
         True, said(still_refused, still_digest) == "the registry answered 401"),
        ("a registry asking for credentials is refused",
         True, said(basic, both) == "the registry asked for credentials this does not hold"),
        ("a token service that is not https is refused",
         True, said(plain, both) == "the registry's token service is not an https address"),
        ("a token service answering without a token is refused",
         True, said(tokenless, tokenless_digest) == "the token service answered without a token"),
        ("a token that is not a string is refused",
         True, said(numbered, numbered_digest) == "the token service answered without a token"),
        ("a token service answering something that is not JSON is refused",
         True, said(garbled_token, garbled_digest) == "the token service answered with something that is not JSON"),
        ("content whose digest is not the pinned one is refused",
         True, said(swapped, both).startswith("was served content whose digest is sha256:")),
        ("a manifest that is not JSON is refused",
         True, said(not_json, not_json_digest) == "was answered with something that is not JSON"),
        ("a manifest that is not a JSON object is refused",
         True, said(listed, listed_digest) == "was answered with a manifest that is not a JSON object"),
        ("a reply past the size bound is refused",
         True, said(big, big_digest) == f"the registry answered with more than {platforms.MAX_REPLY // 1024} KiB"),
        ("a pin left when the budget has run out is refused, and not asked",
         True, said(late, both, deadline=0.0) == f"not asked: the check ran past its {platforms.BUDGET_S} s budget"
         and late.asked == []),
        ("a budget running out between requests refuses the pin",
         True, said(budget_ran_out, budget_digest, clock=lambda: later.pop(0), deadline=5.0)
         == f"not asked: the check ran past its {platforms.BUDGET_S} s budget"),
        ("every request is bounded by the timeout, or by less where less budget is left",
         True, said(index, both, deadline=3.0) == "" and index.asked[-1][2] == 3.0
         and max(asked[2] for asked in index.asked) == platforms.TIMEOUT_S),
        ("a digest that is not sha256 is refused without asking",
         True, said(late, "latest") == "pins no sha256 digest to ask for" and late.asked == []),
        ("a pin with no digest is refused",
         True, said(late, None) == "pins no sha256 digest to ask for"),
        ("an image name this cannot address is refused",
         True, said(late, both, image="Not/An Image") == "is not an image name this will address"),
    ]


class Opener:
    """An opener answering from memory, keeping what it was asked."""

    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.asked: list[tuple[urllib.request.Request, float]] = []

    def open(self, request: urllib.request.Request, timeout: float) -> object:
        self.asked.append((request, timeout))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def network() -> list[Case]:
    message = email.message.Message()
    message["Content-Type"] = LIST
    answered = Opener(urllib.response.addinfourl(io.BytesIO(b"{}"), message, "https://x", 200))
    reply = platforms.fetched("https://x", {"Accept": LIST}, 7.0, answered)
    request, timeout = answered.asked[0]
    error_headers = email.message.Message()
    error_headers["WWW-Authenticate"] = CHALLENGE
    challenged = Opener(urllib.error.HTTPError("https://x", 401, "no", error_headers, io.BytesIO(b"")))
    unreachable = Opener(urllib.error.URLError("down"))
    redirects = platforms.SameHostRedirects()
    asking = urllib.request.Request(f"https://{HOST}/v2/a")
    try:
        redirects.redirect_request(asking, io.BytesIO(b""), 307, "moved", message, "https://elsewhere.example/b")
        off_host = "followed"
    except urllib.error.HTTPError as error:
        off_host = str(error.code)
    try:
        redirects.redirect_request(asking, io.BytesIO(b""), 307, "moved", message, f"http://{HOST}/b")
        plain = "followed"
    except urllib.error.HTTPError as error:
        plain = str(error.code)
    same = redirects.redirect_request(asking, io.BytesIO(b""), 307, "moved", message, f"https://{HOST}/b")
    try:
        platforms.fetched("https://x", {}, 1.0, unreachable)
        down = "answered"
    except OSError:
        down = "raised"
    return [
        ("a request carries its headers, the user agent and its timeout",
         True, request.get_header("Accept") == LIST and request.get_header("User-agent") == platforms.USER_AGENT
         and timeout == 7.0),
        ("a reply carries its status, body and headers by lower-cased name",
         True, reply == Reply(200, b"{}", {"content-type": LIST})),
        ("an error status is a reply, not a raise",
         True, platforms.fetched("https://x", {}, 1.0, challenged)
         == Reply(401, b"", {"www-authenticate": CHALLENGE})),
        ("no answer raises", True, down == "raised"),
        ("a redirect off the registry's host is not followed", True, off_host == "307"),
        ("a redirect off https is not followed", True, plain == "307"),
        ("a redirect on the registry's host is followed", True, same is not None and same.full_url.endswith("/b")),
    ]


def addresses() -> list[Case]:
    return [
        ("a name on Docker Hub is addressed at its registry",
         True, platforms.address("qmcgaw/gluetun") == (platforms.DOCKER_HUB, "qmcgaw/gluetun")),
        ("an official image is addressed under library/",
         True, platforms.address("docker.io/traefik") == (platforms.DOCKER_HUB, "library/traefik")
         and platforms.address("traefik") == (platforms.DOCKER_HUB, "library/traefik")),
        ("docker.io is addressed at Docker Hub's registry",
         True, platforms.address("docker.io/jellyfin/jellyfin") == (platforms.DOCKER_HUB, "jellyfin/jellyfin")),
        ("another registry is addressed at its own host",
         True, platforms.address("lscr.io/linuxserver/sonarr") == ("lscr.io", "linuxserver/sonarr")),
        ("a platform listed twice, or beside attestations, counts once",
         True, platforms.platforms_of(json.loads(document(INDEX, *BOTH, "linux/amd64"))) == {
             *BOTH, "unknown/unknown"}),
    ]


MANIFEST = """[plugin]
id = "app"

[[service]]
id = "app"
image = "registry.example/upstream/app"
digest = "{digest}"

[[service]]
id = "app-adapter"
image = "ghcr.io/lemonfiber/app-adapter"
digest = "{digest}"
"""


def read_pins() -> list[Case]:
    digest = digest_of(b"x")
    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch)
        (root / "app").mkdir()
        (root / "app" / "plugin.toml").write_text(MANIFEST.format(digest=digest), encoding="utf-8")
        (root / "old.toml").write_text(MANIFEST.format(digest=digest).replace('"app', '"old'), encoding="utf-8")
        found = list(platforms.pinned({"app": root / "app", "old": root / "old.toml"}))
    return [
        ("every upstream image a copy pins is asked, and lemonfiber's own are not",
         True, found == [("app/app", IMAGE, digest), ("old/old", IMAGE, digest)]),
    ]


def whole_check() -> list[Case]:
    good, _ = behind_token(document(LIST, *BOTH))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        passed = platforms.checked(good, lambda: 0.0)
    every = platforms.pinned(platforms.bundle.copies(platforms.bundle.COPIES, 2))
    upstream = sum(1 for _ in every)
    held, platforms.refusal = platforms.refusal, lambda *_: ""
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            clean = platforms.checked(good, lambda: 0.0)
    finally:
        platforms.refusal = held
    return [
        ("the bundle in this checkout passes where every image carries both platforms",
         True, clean == 0),
        ("the bundle in this checkout is refused where its registry does not answer",
         True, passed == 1 and out.getvalue().count("::error::") == upstream > 0),
        ("the summary counts what was asked",
         True, f"0 of {upstream} upstream images carry linux/amd64 and linux/arm64." in out.getvalue()),
    ]


def self_test() -> int:
    """Each refusal, against the shape it exists to refuse."""
    failures = 0
    for what, expected, got in (*refusals(), *network(), *addresses(), *read_pins(), *whole_check()):
        print(f"  {'ok  ' if expected == got else 'FAIL'} {what}")
        failures += expected != got
    print("\nself-test passed." if not failures else f"\n{failures} rule(s) did not refuse.")
    return 1 if failures else 0

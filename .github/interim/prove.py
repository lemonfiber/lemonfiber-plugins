#!/usr/bin/env python3
"""Run what this plugin declares — until lemonfiber runs it.

**This is CI harness, not plugin content.** A plugin is `plugin.toml` and the
recordings in `fixtures/`. Nothing under `.github/` is installed, and lemonfiber
never runs any of it (`F3-R6`).

`F3-R3` says a plugin's declared proofs run in the existing verification engine,
the same way the bundled ones do, and `F10-R3` says proving works against a local
path with no catalogue and no network. That engine is in lemonfiber and nothing
reaches it from outside yet. This stands in, and is written to be thrown away:
the day lemonfiber proves a manifest on a path, `plugin.yml` calls it and this
file goes.

Three kinds of assertion, run the same way and reported apart, because they are
answerable at different moments and by different things:

    proof       what must hold before this plugin is installed (F3-R4)
    probe       what demonstrates a core capability this service claims (F4-R24)
    check       a row this plugin adds to the doctor's register (F3-R33)

Two modes, and the difference is reported rather than blurred (`F10-R6`):

    --against fixtures   the recorded responses in fixtures/, which is what lets
                         this run with no live instance anywhere (`F10-R4`)
    --against <base-url> a real instance

Three verdicts, never two (`F3-R5`, `F4-R7`): one that passed, one that failed,
and one that could not be run at all — which is reported as unproven and is never
counted as a pass. A probe the published vocabulary says needs the operator's
credential is the third of those against a live service, because a manifest holds
no credential until recipes arrive and a runner that could not ask has
established nothing about the service.

Exit 0 = everything passed, 1 = one failed or could not be run.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tomllib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = "plugin.toml"
TARGETS = "targets.toml"
VOCABULARY = "capability-vocabulary.json"
ATTEMPT_TIMEOUT_S = 10

PASS, FAIL, UNPROVEN = "pass", "fail", "unproven"

TYPES = {"bool": bool, "int": int, "str": str, "list": list, "dict": dict}


def declared() -> list[dict]:
    """Every assertion in the manifest, each carrying what kind it is.

    Flattened into one list because the runner does not care which block a
    request and an expectation came out of, and the report does — so the kind
    rides along rather than the runner being told three times.
    """
    manifest = tomllib.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    found: list[dict] = []
    for proof in manifest.get("proof", []):
        found.append({"kind": "proof", "id": proof.get("id"), **proof})
    for claim in manifest.get("claim", []):
        for probe in claim.get("probe", []):
            found.append({
                "kind": "probe",
                "capability": claim.get("capability"),
                "id": f"{claim.get('capability')}/{probe.get('id')}",
                "probe": probe.get("id"),
                **{key: value for key, value in probe.items() if key != "id"},
            })
    for entry in manifest.get("contribution", []):
        if entry.get("at") == "doctor.check":
            found.append({"kind": "check", "id": entry.get("id"), **entry})
    return found


def credentialled(published: str | None) -> set[tuple[str, str]]:
    """Which probes the published vocabulary says need the operator's credential.

    Empty where nothing was published, which makes every probe runnable against a
    live service and lets it fail honestly. Knowing less is not the same as
    assuming the answer.
    """
    if published is None:
        return set()
    path = pathlib.Path(published) / VOCABULARY
    if not path.is_file():
        return set()
    try:
        vocabulary = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return set()
    return {
        (capability.get("name"), probe.get("id"))
        for capability in vocabulary.get("capabilities", [])
        for probe in capability.get("probes", [])
        if probe.get("credential") == "operator"
    }


def answer_from_fixture(assertion: dict) -> tuple[dict, str | None]:
    """The recorded response this assertion names, and why it could not be read."""
    named = assertion.get("fixture")
    if not named:
        return {}, "declares no fixture, so there is nothing to run it against"
    path = ROOT / named
    if not path.is_file():
        return {}, f"names {named}, which is not in this source"
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as unreadable:
        return {}, f"{named} is not readable as JSON: {unreadable}"

    asked = assertion.get("request", {})
    recorded_request = recorded.get("request", {})
    if recorded_request != asked:
        return {}, (
            f"{named} records {recorded_request.get('method')} {recorded_request.get('path')}, "
            f"and this asks {asked.get('method')} {asked.get('path')}"
        )
    return recorded.get("response", {}), None


def answer_from_service(assertion: dict, base: str) -> tuple[dict, str | None]:
    """One request to a running instance, and what came back."""
    asked = assertion.get("request", {})
    if asked.get("method", "GET") != "GET":
        return {}, f"only GET is implemented here, and this asks {asked.get('method')}"
    url = base.rstrip("/") + asked.get("path", "/")
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=ATTEMPT_TIMEOUT_S) as reply:
            status, headers, body = reply.status, dict(reply.headers), reply.read()
    except urllib.error.HTTPError as answered:
        status, headers, body = answered.code, dict(answered.headers), answered.read()
    except OSError as unreachable:
        return {}, f"{url} could not be reached: {type(unreachable).__name__}: {unreachable}"
    try:
        parsed = json.loads(body) if body else None
    except ValueError:
        parsed = None
    answer = {
        "status": status,
        "headers": {"content-type": headers.get("Content-Type", "")},
        "json": parsed,
    }
    if parsed is None:
        answer["body_starts_with"] = body.decode("utf-8", "replace")[:200]
    return answer, None


def judge(assertion: dict, answer: dict) -> list[str]:
    """Every way this answer is not the one that was declared."""
    expect = assertion.get("expect", {})
    faults: list[str] = []

    if "status" in expect and answer.get("status") != expect["status"]:
        faults.append(f"status {answer.get('status')!r}, and it declares {expect['status']!r}")

    body = answer.get("json")

    if "json" in expect:
        wanted = expect["json"]
        if not isinstance(body, dict):
            faults.append(f"the body is not a JSON object: {body!r}")
        else:
            for key, value in wanted.items():
                if body.get(key) != value:
                    faults.append(f"{key} is {body.get(key)!r}, and it declares {value!r}")

    for key in expect.get("json_has_keys", []):
        if not isinstance(body, dict) or key not in body:
            faults.append(f"the body carries no {key!r}")

    if "content_type" in expect:
        got = answer.get("headers", {}).get("content-type", "")
        if expect["content_type"] not in got:
            faults.append(
                f"the content type is {got!r}, and it declares it carries "
                f"{expect['content_type']!r}"
            )

    if "body_starts_with" in expect:
        got = answer.get("body_starts_with", "")
        if not got.startswith(expect["body_starts_with"]):
            faults.append(
                f"the body starts {got[:40]!r}, and it declares it starts "
                f"{expect['body_starts_with']!r}"
            )

    if expect.get("json_is_absent") and body is not None:
        faults.append(f"the body parsed as JSON, and it declares it does not: {body!r}")

    if "json_array_min" in expect:
        wanted = expect["json_array_min"]
        if not isinstance(body, list):
            faults.append(f"the body is not a JSON array: {body!r}")
        elif len(body) < wanted:
            faults.append(f"the array holds {len(body)}, and it declares at least {wanted}")

    for key, least in expect.get("json_at_least", {}).items():
        if not isinstance(body, dict) or key not in body:
            faults.append(f"the body carries no {key!r}")
        elif not isinstance(body[key], (int, float)) or body[key] < least:
            faults.append(f"{key} is {body[key]!r}, and it declares at least {least!r}")

    for key, name in expect.get("json_types", {}).items():
        if not isinstance(body, dict) or key not in body:
            continue
        wanted = TYPES.get(name)
        if wanted is None:
            faults.append(f"it names a type this runner does not know: {name!r}")
        elif not isinstance(body[key], wanted):
            faults.append(f"{key} is {type(body[key]).__name__}, and it declares {name}")

    return faults


def run(assertion: dict, against: str, needs_credential: set) -> tuple[str, str]:
    if against == "fixtures":
        answer, unrunnable = answer_from_fixture(assertion)
    elif (assertion.get("capability"), assertion.get("probe")) in needs_credential:
        return UNPROVEN, (
            "the vocabulary declares this probe is asked with the operator's credential, and a "
            "manifest holds none until recipes arrive — unproven, not failed"
        )
    else:
        answer, unrunnable = answer_from_service(assertion, against)

    if unrunnable is not None:
        return UNPROVEN, unrunnable
    if not assertion.get("expect"):
        return UNPROVEN, "declares nothing it expects, so nothing about it can be decided"

    faults = judge(assertion, answer)
    if faults:
        return FAIL, "; ".join(faults)
    return PASS, f"HTTP {answer.get('status')}, and the body it declares"


def targeted() -> str | None:
    path = ROOT / TARGETS
    if not path.is_file():
        return None
    return tomllib.loads(path.read_text(encoding="utf-8")).get("lemonfiber")


def write_report(path: str, against: str, verdicts: list[tuple[dict, str, str]]) -> None:
    """The record a release train re-reads, rather than re-running.

    Held to the release this plugin targets rather than to whichever one is being
    cut: a report that named the version reading it would agree with every reader
    and describe none of them.
    """
    document = {
        "lemonfiber": targeted(),
        "against": against,
        "proofs": [
            {"id": assertion.get("id"), "kind": assertion.get("kind"),
             "outcome": "passed" if verdict == PASS else verdict, "detail": detail}
            for assertion, verdict, detail in verdicts
        ],
    }
    pathlib.Path(path).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--against",
        default="fixtures",
        help="'fixtures' for the recorded responses, or a base URL for a running instance",
    )
    parser.add_argument("--published", metavar="DIR",
                        help=f"a directory holding lemonfiber's published {VOCABULARY}")
    parser.add_argument("--report", metavar="FILE",
                        help="write the record a release train reads")
    args = parser.parse_args()

    path = ROOT / MANIFEST
    if not path.is_file():
        print(f"::error::{MANIFEST} is missing")
        return 1
    assertions = declared()
    if not assertions:
        print(f"::error::{MANIFEST} declares nothing to run, and a plugin whose proofs do not "
              "pass is not installed")
        return 1

    if args.against == "fixtures":
        print(
            "Run against recorded responses. These are proofs about what this plugin\n"
            "declares, not about a running service — which is a weaker claim, and is\n"
            "reported as the weaker one.\n"
        )
    else:
        print(f"Run against {args.against}.\n")

    needs_credential = credentialled(args.published)
    verdicts: list[tuple[dict, str, str]] = []
    for assertion in assertions:
        verdict, detail = run(assertion, args.against, needs_credential)
        verdicts.append((assertion, verdict, detail))
        mark = {PASS: "  ok  ", FAIL: "  FAIL", UNPROVEN: "  ????"}[verdict]
        print(f"{mark} {assertion['kind']:6} {assertion.get('id')!s:<34} {detail}")

    if args.report:
        write_report(args.report, args.against, verdicts)

    counted = [verdict for _, verdict, _ in verdicts]
    failed, unproven = counted.count(FAIL), counted.count(UNPROVEN)
    print(f"\n{counted.count(PASS)} passed, {failed} failed, {unproven} could not be run.")

    if unproven:
        print(
            "\nSomething could not be run, and is unproven rather than passed.",
            file=sys.stderr,
        )
    return 1 if failed or unproven else 0


if __name__ == "__main__":
    sys.exit(main())

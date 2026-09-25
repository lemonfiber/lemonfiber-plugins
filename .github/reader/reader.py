#!/usr/bin/env python3
"""Ask the lemonfiber release `targets.toml` names what this plugin comes to.

**This is CI harness, not plugin content.** Nothing under `.github/` is
installed, and lemonfiber never runs any of it (`F3-R6`).

Every verdict here is lemonfiber's own. `lemonfiber plugin claims` holds the
manifest to the schema, the capability vocabulary and the extension points its
build publishes, and runs every probe, proof and contributed check against the
recording it names (`F10-R3`, `F10-R4`). `lemonfiber plugin provenance` asks each
image's registry who vouched for it (`F3-R25`). This file fetches that release,
asks it, and writes down what it said; it decides nothing a manifest means.

    python3 .github/reader/reader.py reader     the release is out, verified, and reads this plugin
    python3 .github/reader/reader.py manifest   nothing about the manifest is refused
    python3 .github/reader/reader.py proofs     every assertion holds on its recording; writes proofs.json
    python3 .github/reader/reader.py image      every pinned digest resolves; what vouches for it

One refusal is reported and not failed on: a capability in `[requires]` that the
release does not offer a plugin. That is the release saying the plugin would not
be installed on it, which `targets.toml` does not claim; `F3-R21` is why the
refusal names the capability rather than a version, and `reader` prints it.

The release is fetched once into `.lemonfiber/` beside the manifest and checked
against the digest published with it. Exit 0 = the answer is the one asked for,
1 = it is not, or the release could not be asked.
"""

from __future__ import annotations

import hashlib
import io
import json
import pathlib
import platform
import stat
import subprocess
import sys
import tarfile
import tomllib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "plugin.toml"
TARGETS = ROOT / "targets.toml"
REPORT = ROOT / "proofs.json"
CACHE = ROOT / ".lemonfiber"
RELEASES = "https://github.com/lemonfiber/lemonfiber/releases/download"
FETCH_TIMEOUT_S = 120

# The one refusal that is about the release rather than the manifest.
UNOFFERED = "is not something this build offers a plugin"

# What this runs on, and the name the release gives the build for it.
BUILDS = {
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
}


class Unasked(RuntimeError):
    """The release could not be fetched or asked, so nothing was decided."""


def targeted() -> str:
    """The release `targets.toml` names (`REPO-R56`)."""
    version = tomllib.loads(TARGETS.read_text(encoding="utf-8")).get("lemonfiber")
    if not isinstance(version, str) or not version:
        raise Unasked(f"{TARGETS.name} names no lemonfiber release")
    return version


def build() -> str:
    named = BUILDS.get((platform.system(), platform.machine()))
    if named is None:
        raise Unasked(f"no lemonfiber build is published for {platform.system()} {platform.machine()}")
    return named


def fetched(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_S) as answer:
        return answer.read()


def binary() -> pathlib.Path:
    """The release's `lemonfiber`, fetched and verified the first time it is asked for."""
    version, named = targeted(), build()
    held = CACHE / version / named / "lemonfiber"
    if held.is_file():
        return held
    archive = f"lemonfiber-{named}.tar.xz"
    base = f"{RELEASES}/v{version}/{archive}"
    body = fetched(base)
    published = fetched(f"{base}.sha256").decode("utf-8").split()[0]
    if hashlib.sha256(body).hexdigest() != published:
        raise Unasked(f"{archive} from v{version} is not the file its published digest names")
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:xz") as unpacked:
        member = unpacked.extractfile(f"lemonfiber-{named}/lemonfiber")
        if member is None:
            raise Unasked(f"{archive} from v{version} holds no lemonfiber")
        held.parent.mkdir(parents=True, exist_ok=True)
        held.write_bytes(member.read())
    held.chmod(held.stat().st_mode | stat.S_IXUSR)
    return held


def plugin(*asked: str) -> subprocess.CompletedProcess:
    """One question to `lemonfiber plugin`, about this directory."""
    return subprocess.run(
        [str(binary()), "plugin", *asked, str(ROOT)],
        capture_output=True, text=True, check=False,
    )


def claimed() -> dict:
    """What `lemonfiber plugin claims --json` says, or why it said nothing."""
    answer = plugin("claims", "--json")
    try:
        return json.loads(answer.stdout)
    except ValueError:
        raise Unasked(f"lemonfiber read nothing here: {answer.stderr.strip()}") from None


def reader() -> int:
    """The release is out, it is the one downloaded, and it reads this plugin."""
    version = targeted()
    said = subprocess.run([str(binary()), "--version"], capture_output=True, text=True, check=False)
    if said.stdout.strip() != f"lemonfiber {version}":
        print(f"::error::targets.toml names {version}, and the binary says {said.stdout.strip()!r}")
        return 1
    read = claimed()
    print(plugin("claims").stdout)
    for refusal in read["refusals"]:
        if UNOFFERED in refusal["message"]:
            print(f"::notice::{version} would not install this: {refusal['message']}")
    return 0


def manifest() -> int:
    """Every refusal the release makes of the manifest, bar what it does not offer."""
    read = claimed()
    held = [one for one in read["refusals"] if UNOFFERED not in one["message"]]
    for refusal in held:
        print(f"::error file=plugin.toml::{refusal['location']}: {refusal['message']}")
    print(
        f"{len(held)} refusal(s) of the manifest, held to capability vocabulary generation "
        f"{read['vocabulary_version']} and extension points generation {read['extension_points_version']}."
    )
    return 1 if held else 0


def said(verdict: dict) -> str:
    """A verdict's reasons, as one line."""
    reasons = [value for key, value in verdict.items() if key != "outcome"]
    flat = [str(each) for value in reasons for each in (value if isinstance(value, list) else [value])]
    return "; ".join(flat)


def verdicts(read: dict) -> list[dict]:
    """Every assertion and what the release said of it, in the order the report keeps."""
    found = [{"id": one["id"], "kind": "proof", "verdict": one["verdict"]} for one in read["proofs"]]
    for capability in read["capabilities"]:
        found.extend(
            {"id": f"{capability['name']}/{probe['probe']}", "kind": "probe", "verdict": probe["verdict"]}
            for probe in capability["probes"]
        )
    found.extend({"id": one["id"], "kind": "check", "verdict": one["verdict"]} for one in read["checks"])
    return found


def proofs() -> int:
    """Every probe, proof and check on its recording, written down as `proofs.json`.

    The report is the record the release train reads (`OPS-R67`): which release
    decided it, and whether each assertion passed. Anything but passed fails,
    and a report naming nothing fails too (`F3-R5`).
    """
    read = claimed()
    found = verdicts(read)
    report = {
        "lemonfiber": targeted(),
        "against": read["against"],
        "proofs": [
            {"id": one["id"], "kind": one["kind"], "outcome": one["verdict"]["outcome"],
             "detail": said(one["verdict"])}
            for one in found
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for entry in report["proofs"]:
        mark = "  ok  " if entry["outcome"] == "passed" else "  " + entry["outcome"].upper()[:4]
        print(f"{mark} {entry['kind']:6} {entry['id']:<36} {entry['detail']}")
    failing = [entry for entry in report["proofs"] if entry["outcome"] != "passed"]
    print(f"\n{len(found) - len(failing)} passed, {len(failing)} not, against the {read['against']}.")
    return 1 if failing or not found else 0


def resolves(reference: str) -> str:
    """The digest a reference names in its registry now, or nothing."""
    asked = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", reference, "--format", "{{.Manifest.Digest}}"],
        capture_output=True, text=True, check=False,
    )
    return asked.stdout.strip() if asked.returncode == 0 else ""


def image() -> int:
    """Every pinned digest resolves and its tag still names it (`F3-R8`), then who vouches (`F3-R25`)."""
    services = tomllib.loads(MANIFEST.read_text(encoding="utf-8")).get("service", [])
    faults = 0
    for service in services:
        pinned = f"{service['image']}@{service['digest']}"
        if resolves(pinned) != service["digest"]:
            print(f"::error::{pinned} is not in its registry")
            faults += 1
            continue
        tagged = resolves(f"{service['image']}:{service['tag']}")
        if tagged and tagged != service["digest"]:
            print(f"::error::{service['image']}:{service['tag']} names {tagged}, not the pinned digest")
            faults += 1
        else:
            print(f"  ok   {pinned}, which {service['tag']} names" if tagged else f"  ok   {pinned}")
    vouched = plugin("provenance")
    print(vouched.stdout + vouched.stderr)
    return 1 if faults or vouched.returncode != 0 else 0


ASKED = {"reader": reader, "manifest": manifest, "proofs": proofs, "image": image}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ASKED:
        print(f"usage: reader.py {{{','.join(ASKED)}}}", file=sys.stderr)
        return 2
    try:
        return ASKED[sys.argv[1]]()
    except (Unasked, OSError) as why:
        print(f"::error::{why}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

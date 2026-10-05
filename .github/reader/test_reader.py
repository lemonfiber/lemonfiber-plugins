#!/usr/bin/env python3
"""What `reader.py proofs` writes down and fails on, given what the release said.

The release is not asked here. Every verdict is the release's own, so what these
hold the reader to is the part that is not: that each verdict is written to
`proofs.json` as it was given, that failing as declared is kept apart from passed
and failed with the declaration it failed as, and that the run fails on
everything but passed and failing as declared.

Stdlib unittest, no network. Run:  python3 -m unittest discover -s .github/reader
"""

from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import reader

CLAIMED = {
    "fixture": "fixtures/identity-anonymous.json",
    "constraint": "json",
    "place": "/MediaContainer/claimed",
    "held": "false",
    "reason": "Recorded from a server nobody has claimed; claiming one needs a plex.tv account.",
}


def answer(*checks: dict, proofs: tuple[dict, ...] = ()) -> dict:
    """What `lemonfiber plugin claims --json` says, cut to what the reader reads."""
    return {
        "against": "recordings",
        "proofs": list(proofs),
        "capabilities": [],
        "checks": list(checks),
        "refusals": [],
    }


def check(name: str, verdict: dict) -> dict:
    return {"id": name, "verdict": verdict}


def declared(**over) -> dict:
    return {"outcome": reader.AS_DECLARED, "declared": [{**CLAIMED, **over}]}


class Proofs(unittest.TestCase):
    def setUp(self) -> None:
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.report = pathlib.Path(box.name) / "proofs.json"

    def proved(self, said: dict) -> tuple[int, str]:
        """`reader.py proofs` against an answer, as CI would print it."""
        out = io.StringIO()
        with (
            mock.patch.object(reader, "claimed", return_value=said),
            mock.patch.object(reader, "targeted", return_value="0.17.0"),
            mock.patch.object(reader, "REPORT", self.report),
            mock.patch.object(sys, "argv", ["reader.py", "proofs"]),
            contextlib.redirect_stdout(out),
        ):
            code = reader.main()
        return code, out.getvalue()

    def written(self) -> list[dict]:
        return json.loads(self.report.read_text(encoding="utf-8"))["proofs"]

    def test_failing_as_declared_is_written_apart_and_fails_nothing(self):
        code, said = self.proved(answer(
            check("plex:claimed", declared()),
            check("plex:not-published", {"outcome": "passed"}),
        ))
        self.assertEqual(code, 0, said)
        claimed, published = self.written()
        self.assertEqual(claimed["outcome"], "failing-as-declared")
        self.assertEqual(claimed["declared"], [CLAIMED])
        self.assertEqual(
            claimed["detail"],
            "fails as declared on fixtures/identity-anonymous.json: json at /MediaContainer/claimed "
            "held false. Recorded from a server nobody has claimed; claiming one needs a plex.tv account.",
        )
        self.assertNotIn("declared", published)
        self.assertIn("  decl check  plex:claimed", said)
        self.assertIn("::notice::check plex:claimed fails as declared on fixtures/identity-anonymous.json", said)
        self.assertIn("1 passed, 1 failing as declared, 0 not, against the recordings.", said)

    def test_failing_as_declared_is_never_counted_as_passed(self):
        code, said = self.proved(answer(check("plex:claimed", declared())))
        self.assertEqual(code, 0, said)
        self.assertIn("0 passed, 1 failing as declared, 0 not", said)

    def test_a_declaration_about_the_answer_as_a_whole_names_no_place(self):
        whole = {"outcome": reader.AS_DECLARED, "declared": [{**CLAIMED, "constraint": "status", "held": "500"}]}
        del whole["declared"][0]["place"]
        code, said = self.proved(answer(check("plex:claimed", whole)))
        self.assertEqual(code, 0, said)
        self.assertIn("identity-anonymous.json: status held 500. Recorded", self.written()[0]["detail"])

    def test_every_declaration_an_assertion_failed_as_is_named(self):
        other = {**CLAIMED, "fixture": "fixtures/identity-other.json", "held": "null"}
        code, said = self.proved(answer(
            check("plex:claimed", {"outcome": reader.AS_DECLARED, "declared": [CLAIMED, other]}),
        ))
        self.assertEqual(code, 0, said)
        self.assertEqual(said.count("::notice::"), 2)
        self.assertEqual(self.written()[0]["declared"], [CLAIMED, other])

    def test_a_failure_beside_one_failing_as_declared_fails_the_run(self):
        code, said = self.proved(answer(
            check("plex:claimed", declared()),
            check("plex:no-anonymous-lan", {"outcome": "failed", "faults": ["status is 200, and it declares 401"]}),
        ))
        self.assertEqual(code, 1)
        self.assertIn("  FAIL check  plex:no-anonymous-lan", said)
        self.assertIn("0 passed, 1 failing as declared, 1 not", said)
        self.assertIn("::notice::check plex:claimed", said)

    def test_a_stale_declaration_is_a_failure_the_release_names(self):
        stale = {"outcome": "failed", "faults": ["passes on fixtures/identity-anonymous.json, which it declares it fails on"]}
        code, said = self.proved(answer(check("plex:claimed", stale)))
        self.assertEqual(code, 1)
        self.assertIn("  FAIL check  plex:claimed", said)
        self.assertEqual(self.written()[0]["outcome"], "failed")
        self.assertNotIn("declared", self.written()[0])

    def test_an_unproven_assertion_is_not_excused_by_a_declaration(self):
        unrun = {"outcome": "unproven", "why": "fixtures/identity-anonymous.json is not in the plugin"}
        code, said = self.proved(answer(check("plex:claimed", unrun)))
        self.assertEqual(code, 1)
        self.assertIn("  UNPR check  plex:claimed", said)
        self.assertIn("0 passed, 0 failing as declared, 1 not", said)

    def test_failing_as_declared_naming_no_declaration_writes_nothing(self):
        code, said = self.proved(answer(check("plex:claimed", {"outcome": reader.AS_DECLARED})))
        self.assertEqual(code, 1)
        self.assertIn("::error::the release said failing-as-declared and named no declaration", said)
        self.assertFalse(self.report.exists())

    def test_a_declaration_without_its_reason_writes_nothing(self):
        code, said = self.proved(answer(check("plex:claimed", declared(reason=""))))
        self.assertEqual(code, 1)
        self.assertIn("its declaration names no reason", said)
        self.assertFalse(self.report.exists())

    def test_a_declaration_that_is_not_a_table_names_everything_it_lacks(self):
        bare = {"outcome": reader.AS_DECLARED, "declared": ["fixtures/identity-anonymous.json"]}
        code, said = self.proved(answer(check("plex:claimed", bare)))
        self.assertEqual(code, 1)
        self.assertIn("names no fixture, constraint, held, reason", said)

    def test_a_report_naming_nothing_fails(self):
        code, said = self.proved(answer())
        self.assertEqual(code, 1)
        self.assertIn("0 passed, 0 failing as declared, 0 not", said)

    def test_every_kind_is_written_in_the_order_the_report_keeps(self):
        said = answer(check("c", {"outcome": "passed"}), proofs=({"id": "p", "verdict": {"outcome": "passed"}},))
        said["capabilities"] = [{"name": "media.serve", "probes": [{"probe": "guarded", "verdict": {"outcome": "passed"}}]}]
        code, out = self.proved(said)
        self.assertEqual(code, 0, out)
        self.assertEqual(
            [(one["kind"], one["id"]) for one in self.written()],
            [("proof", "p"), ("probe", "media.serve/guarded"), ("check", "c")],
        )


class Schema(unittest.TestCase):
    """`reader.py manifest` holds the manifest's schema line to `targets.toml` (`F10-R17`)."""

    WANTED = "https://github.com/lemonfiber/lemonfiber/releases/download/v0.17.0/plugin-manifest.schema.json"

    def setUp(self) -> None:
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.manifest = pathlib.Path(box.name) / "plugin.toml"

    def read(self, first_line: str | None) -> tuple[int, str]:
        """`reader.py manifest` on a manifest opening with `first_line`, the release refusing nothing."""
        body = "schema_version = 1\n"
        self.manifest.write_text(body if first_line is None else f"{first_line}\n{body}", encoding="utf-8")
        said = answer()
        said["vocabulary_version"], said["extension_points_version"] = 1, 1
        out = io.StringIO()
        with (
            mock.patch.object(reader, "claimed", return_value=said),
            mock.patch.object(reader, "targeted", return_value="0.17.0"),
            mock.patch.object(reader, "MANIFEST", self.manifest),
            mock.patch.object(sys, "argv", ["reader.py", "manifest"]),
            contextlib.redirect_stdout(out),
        ):
            code = reader.main()
        return code, out.getvalue()

    def test_the_schema_of_the_targeted_release_passes(self):
        code, out = self.read(f"#:schema {self.WANTED}")
        self.assertEqual(code, 0, out)
        self.assertNotIn("::error", out)

    def test_the_schema_of_another_release_is_refused_naming_both(self):
        other = self.WANTED.replace("v0.17.0", "v0.16.0")
        code, out = self.read(f"#:schema {other}")
        self.assertEqual(code, 1, out)
        self.assertIn("::error file=plugin.toml,line=1::", out)
        self.assertIn(other, out)
        self.assertIn(self.WANTED, out)
        self.assertIn("1 refusal(s)", out)

    def test_a_schema_on_main_is_refused(self):
        code, out = self.read("#:schema https://raw.githubusercontent.com/lemonfiber/lemonfiber/main/contract/plugin-manifest.schema.json")
        self.assertEqual(code, 1, out)

    def test_a_schema_line_below_the_first_is_not_one_an_editor_reads(self):
        code, out = self.read(f"# a comment\n#:schema {self.WANTED}")
        self.assertEqual(code, 0, out)
        self.assertIn("::notice file=plugin.toml::", out)

    def test_naming_no_schema_says_which_line_would_and_refuses_nothing(self):
        code, out = self.read(None)
        self.assertEqual(code, 0, out)
        self.assertIn(f"::notice file=plugin.toml::an editor checks this manifest as it is typed once its first line is `#:schema {self.WANTED}`", out)
        self.assertIn("0 refusal(s)", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)

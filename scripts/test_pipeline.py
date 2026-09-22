"""Offline checks; no API credentials or network requests are needed."""
import argparse
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pymupdf
from jsonschema import ValidationError, validate as validate_schema

from biography_schema import SYSTEM_PROMPT, RESPONSE_FORMAT
import book_settings as book
from extract_biographies import build_records, extract_records, get_lines, parse_entry, split_entries
import pipeline

SAMPLE_PDF = pipeline.ROOT / "examples/searchable.pdf"
METADATA = {"pdf_viewer_pages": [8], "printed_pages": [23], "source_id": "test", "last_entry_incomplete": False}


def empty_biography():
    data = {key: [] if rule.get("type") == "array" else None
            for key, rule in RESPONSE_FORMAT["schema"]["properties"].items()}
    data["quality"] = {"multiple_people_detected": False, "needs_review": False, "needs_review_reason": None}
    return data


def lines_from_page(positions):
    """Lines the parser reads from a one-page A4 PDF with text at the given (x, y, text) positions."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "page.pdf"
        with pymupdf.open() as document:
            page = document.new_page(width=595, height=842)
            for x, y, text in positions:
                page.insert_text((x, y), text)
            document.save(path)
        return [text for text, _ in get_lines(path, {"pdf_viewer_pages": [4]})]


class LineTests(unittest.TestCase):
    def test_column_divider_does_not_pull_right_column_into_left(self):
        lines = lines_from_page([(55, 120, "LEFT FIRST"), (55, 150, "LEFT SECOND"),
                                 (297.2, 120, "RIGHT FIRST"), (297.2, 150, "RIGHT SECOND")])
        self.assertEqual(lines, ["LEFT FIRST", "LEFT SECOND", "RIGHT FIRST", "RIGHT SECOND"])

    def test_running_head_and_page_number_are_dropped_only_in_the_margins(self):
        lines = lines_from_page([(400, 40, "© ABD"), (300, 820, "19"),
                                 (55, 120, "ABAZA, OSMAN, author"), (55, 140, "ABD"), (55, 160, "1921")])
        self.assertEqual(lines, ["ABAZA, OSMAN, author", "ABD", "1921"])

    def test_wrapped_heading_with_a_title_word_is_one_line(self):
        lines = lines_from_page([(55, 120, "EL-BAKOURI, Sheikh AHMED"), (55, 132, "HASSAN, Ex-Minister of Wakfs :"),
                                 (55, 144, "& Mrs. Kawkab El-Bakouri")])
        self.assertEqual(lines[0], "EL-BAKOURI, Sheikh AHMED HASSAN, Ex-Minister of Wakfs :")

    def test_stray_hyphen_before_a_heading_does_not_glue_two_people(self):
        lines = lines_from_page([(55, 120, "Tel. 61991. ALEXANDRIA (Eg).-"), (55, 132, "AL KALAAOUI, MOHAMED FAH-"),
                                 (55, 144, "MY, avocat a la cour de Cassation")])
        self.assertEqual(lines, ["Tel. 61991. ALEXANDRIA (Eg).-",
                                 "AL KALAAOUI, MOHAMED FAHMY, avocat a la cour de Cassation"])


class EntryTests(unittest.TestCase):
    def test_biography_crossing_page_is_not_split(self):
        lines = [("ABAZA, OSMAN, author", 4), ("continued biography text", 5), ("ABAZA, SHOUKRY, engineer", 5)]
        entries = split_entries(lines)
        self.assertEqual(len(entries), 2)
        self.assertEqual([page for _, page in entries[0]], [4, 5])

    def test_club_initials_are_not_a_person(self):
        entries = split_entries([("ABAZA, MAHMOUD, adviser", 4), ("CAIRO. Clubs :", 4),
                                 ("HSE, SPC.", 4), ("ABAZA, OSMAN, author", 4)])
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][-1][0], "HSE, SPC.")

    def test_short_surname_after_a_club_line_is_a_person(self):
        entries = split_entries([("ALY ABDEL-ALIM, Lewa (General), officer", 8), ("Club: Officers Club, Cairo.", 8),
                                 ("AMER, Mouchir (Field Marshal)", 8), ("ABDUL HAKIM ALY, Minister of War", 8)])
        self.assertEqual([entry[0][0] for entry in entries],
                         ["ALY ABDEL-ALIM, Lewa (General), officer", "AMER, Mouchir (Field Marshal)",
                          "ABDUL HAKIM ALY, Minister of War"])

    def test_heading_only_entry_is_attached_to_its_continuation(self):
        records, _ = build_records([("AMER, Mouchir (Field Marshal)", 8),
                                    ("ABDUL HAKIM ALY, Minister of War and Marine; born 1919.", 8),
                                    ("AMIN, ALY, journalist, born 1914.", 8)], METADATA)
        self.assertEqual([r["header"] for r in records], ["AMER, Mouchir (Field Marshal) ABDUL HAKIM ALY,", "AMIN, ALY,"])
        self.assertTrue(records[0]["body"].startswith("Minister of War"))
        self.assertEqual([r["id"] for r in records], ["test_001", "test_002"])

    def test_degree_lines_are_not_headings_and_never_leave_an_empty_heading(self):
        self.assertFalse(book.looks_like_heading("MD, 00; Oculist Cairo; Eg."))
        self.assertFalse(book.looks_like_heading("M.B., Ch.B., Prof. of Surgery"))
        self.assertTrue(book.looks_like_heading("ABBASSY, Dr. AHMED SHAFIK,"))
        fields = parse_entry([("M.B., Ch.B., Prof. of Surgery, Faculty of Medicine", 13)])
        self.assertEqual(fields["header"], "M.B., Ch.B.,")

    def test_country_profile_is_set_aside_instead_of_sent(self):
        profile = " ".join(["area 444,442 sq. km. POPULATION 5 million. CAPITAL Damascus. CURRENCY pound. HISTORY long."] * 30)
        records, skipped = build_records([("RURITANIA, Kingdom of,", 8), (profile, 8), ("ABAZA, OSMAN, author", 8)], METADATA)
        self.assertEqual([r["header"] for r in records], ["ABAZA, OSMAN,"])
        self.assertEqual(len(skipped), 1)
        self.assertIn("RURITANIA", skipped[0]["header"])

    def test_verified_sample_matches_manual_entry_inventory(self):
        if not SAMPLE_PDF.exists():
            self.skipTest("examples/searchable.pdf is not distributed with the code")
        metadata = pipeline.read_json(pipeline.SOURCE)
        records, _, skipped = extract_records(SAMPLE_PDF, metadata)
        reference = pipeline.read_json(pipeline.ROOT / "docs/reference_entries.json")
        self.assertEqual(len(records), len(reference))
        self.assertEqual(skipped, [])
        for record, expected in zip(records, reference):
            self.assertIn(expected["header_contains"], record["header"])
            self.assertEqual(record["pdf_page_start"], expected["pdf_page_start"])
            self.assertEqual(record["pdf_page_end"], expected["pdf_page_end"])
        self.assertEqual(sum(r["source_incomplete"] for r in records), 1)
        self.assertTrue(records[-1]["source_incomplete"])
        self.assertIn("NAZMY", records[14]["header"])
        self.assertIn("KAMAL-EL-DiN MAHMOUD", records[17]["header"])
        self.assertIn("Deir Mowas, Mallawi", records[0]["body"])
        self.assertIn("Faculté Polytech.", records[0]["body"])
        self.assertNotIn("Deir MoFawas", records[0]["body"])
        self.assertNotIn("ABD Abdel Nabi", records[16]["body"])  # the running head no longer leaks into the text
        self.assertEqual([r["header"] for r in records if not r["body"]], [])


class ResultTests(unittest.TestCase):
    def test_schema_rejects_missing_fields(self):
        value = empty_biography()
        validate_schema(value, RESPONSE_FORMAT["schema"])
        del value["birthdate"]
        with self.assertRaises(ValidationError):
            validate_schema(value, RESPONSE_FORMAT["schema"])

    def test_evidence_is_checked_against_the_actual_input(self):
        data = {"notes": [{"evidence": "born in Cairo"}, {"evidence": "born in Lyon"}]}
        issues = pipeline.evidence_issues(data, "He was born in Cairo in 1905.")
        self.assertEqual(len(issues), 1)
        self.assertIn("notes[2]", issues[0])

    def test_wide_export_preserves_each_item_and_evidence(self):
        record = {"data": {"education": [{"degree": "MD", "evidence": "MD, Cairo"},
                                          {"degree": "PhD", "evidence": "PhD, Leeds"}]},
                  "validation": {"evidence_issues": ["review this"]}}
        result = pipeline.flatten(record)
        self.assertEqual(result["data_education_1_degree"], "MD")
        self.assertEqual(result["data_education_2_evidence"], "PhD, Leeds")
        self.assertEqual(result["validation_evidence_issues_1"], "review this")

    def make_run(self, directory):
        output = Path(directory)
        entry = {"id": "sample_001", "header": "ABAZA, OSMAN,", "body": "author", "source_incomplete": True}
        config = {"model": "gpt-5-mini", "reasoning": "high", "max_output_tokens": 16000,
                  "prompt": SYSTEM_PROMPT, "format": RESPONSE_FORMAT}
        saved = {"id": entry["id"], "fingerprint": pipeline.digest({"config": config, "record": entry}),
                 "input_sha256": pipeline.digest(entry), "status": "complete", "data": empty_biography(),
                 "model": "gpt-5-mini", "reasoning": "high"}
        pipeline.write_json(output / "entries.json", [entry])
        pipeline.write_json(output / "responses/sample_001.json", saved)
        args = argparse.Namespace(output=output, model="gpt-5-mini", reasoning="high", max_output_tokens=16000,
                                  limit=None, dry_run=False, env_file=output / "absent.env", workers=1, max_retries=0)
        return args, entry, saved

    def test_matching_cache_resumes_without_a_key_or_api_call(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _, _ = self.make_run(directory)
            with patch.dict("os.environ", {}, clear=True), patch("openai.OpenAI", side_effect=AssertionError("API called")):
                pipeline.structure(args)

    def test_changed_input_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            args, entry, _ = self.make_run(directory)
            entry["body"] = "changed input"
            pipeline.write_json(args.output / "entries.json", [entry])
            with self.assertRaisesRegex(ValueError, "different input/settings"):
                pipeline.structure(args)
            with self.assertRaisesRegex(ValueError, "input has changed"):
                pipeline.export(args)

    def test_missing_response_cannot_be_exported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _, saved = self.make_run(directory)
            saved["status"] = "failed"
            pipeline.write_json(args.output / "responses/sample_001.json", saved)
            with self.assertRaisesRegex(ValueError, "Incomplete run"):
                pipeline.export(args)
            self.assertEqual(pipeline.read_json(args.output / "failures.json")[0]["status"], "failed")

    def test_incomplete_api_response_is_not_accepted_even_if_json_parses(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _, saved = self.make_run(directory)
            saved["status"] = "failed"
            pipeline.write_json(args.output / "responses/sample_001.json", saved)
            response = SimpleNamespace(status="incomplete", output_text=json.dumps(empty_biography()),
                                       usage=None, model="test-model", model_dump=lambda: {"status": "incomplete"})
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch("openai.OpenAI") as client:
                client.return_value.responses.create.return_value = response
                with self.assertRaisesRegex(ValueError, "requests need review"):
                    pipeline.structure(args)
            result = pipeline.read_json(args.output / "responses/sample_001.json")
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("data", result)

    def test_reasoning_is_omitted_for_models_without_it(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _, _ = self.make_run(directory)
            (args.output / "responses/sample_001.json").unlink()
            args.model, args.reasoning = "gpt-4.1-mini", "none"
            response = SimpleNamespace(status="completed", output_text=json.dumps(empty_biography()),
                                       usage=None, model="gpt-4.1-mini", model_dump=lambda: {})
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch("openai.OpenAI") as client:
                client.return_value.responses.create.return_value = response
                pipeline.structure(args)
                request = client.return_value.responses.create.call_args.kwargs
            self.assertNotIn("reasoning", request)
            self.assertEqual(request["temperature"], 0)
            self.assertEqual(pipeline.read_json(args.output / "responses/sample_001.json")["status"], "complete")

    def test_cut_off_record_is_reviewable_and_source_flags_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            args, _, _ = self.make_run(directory)
            pipeline.export(args)
            pipeline.validate(args)
            records = pipeline.read_json(args.output / "biographies.json")
            self.assertTrue(records[0]["validation"]["needs_review"])
            records[0]["validation"]["needs_review"] = False
            pipeline.write_json(args.output / "biographies.json", records)
            with self.assertRaisesRegex(ValueError, "Review flags"):
                pipeline.validate(args)


if __name__ == "__main__":
    unittest.main()

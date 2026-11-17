import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from labledger.errors import ContractError
from labledger.ingest.contracts import parse_bundle
from labledger.ingest.loaders import decode_json, encode_canonical
from labledger.ingest.migrations import schema_description
from labledger.ingest.manifests import manifest_template, read_manifest
from tests.helpers import bundle


class BundleContractTests(unittest.TestCase):
    def test_valid_bundle_normalizes_timestamps_and_digest(self):
        payload = bundle()
        payload["measurements"][0]["measured_at"] = "2026-11-01T12:00:00+02:00"
        parsed = parse_bundle(payload, "a" * 64)
        self.assertEqual(parsed.measurements[0].measured_at, "2026-11-01T10:00:00Z")
        self.assertEqual(parsed.source_digest, "a" * 64)
        self.assertEqual(parsed.reference_cohort, "baseline")

    def test_supported_protocol_versions_are_retained(self):
        for version in (1, 2):
            with self.subTest(version=version):
                payload = bundle(protocol=version)
                parsed = parse_bundle(payload, "digest")
                self.assertEqual(parsed.protocol_version, version)

    def test_protocol_one_value_field_is_migrated_without_mutating_input(self):
        payload = bundle(protocol=1)
        before = payload["measurements"][0]["reading"]
        parsed = parse_bundle(payload, "digest")
        self.assertEqual(parsed.measurements[0].value, before)
        self.assertIn("reading", payload["measurements"][0])
        self.assertNotIn("value", payload["measurements"][0])

    def test_protocol_one_rejects_mixed_old_and_new_value_fields(self):
        payload = bundle(protocol=1)
        payload["measurements"][0]["value"] = payload["measurements"][0]["reading"]
        with self.assertRaisesRegex(ContractError, "reading, not value"):
            parse_bundle(payload, "digest")

    def test_protocol_two_rejects_legacy_reading_field(self):
        payload = bundle(protocol=2)
        row = payload["measurements"][0]
        row["reading"] = row.pop("value")
        with self.assertRaisesRegex(ContractError, "value, not reading"):
            parse_bundle(payload, "digest")

    def test_protocol_descriptions_make_value_field_migration_explicit(self):
        self.assertEqual(schema_description(1)["measurement_value_field"], "reading")
        self.assertEqual(schema_description(2)["measurement_value_field"], "value")

    def test_protocol_description_rejects_unknown_version(self):
        with self.assertRaisesRegex(ContractError, "unsupported"):
            schema_description(99)

    def test_rejects_unknown_protocol_version(self):
        payload = bundle(protocol=3)
        with self.assertRaisesRegex(ContractError, "protocol_version"):
            parse_bundle(payload, "digest")

    def test_rejects_boolean_version_and_replicate_count(self):
        for field, value in (("protocol_version", True), ("min_replicates", True)):
            payload = bundle()
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                parse_bundle(payload, "digest")

    def test_rejects_missing_required_top_level_field(self):
        payload = bundle()
        del payload["reference_cohort"]
        with self.assertRaisesRegex(ContractError, "missing fields"):
            parse_bundle(payload, "digest")

    def test_rejects_non_object_root(self):
        with self.assertRaises(ContractError):
            parse_bundle([], "digest")

    def test_rejects_invalid_control_bounds(self):
        payload = bundle()
        payload["control_range"] = {"min": 1.2, "max": 0.8}
        with self.assertRaisesRegex(ContractError, "below"):
            parse_bundle(payload, "digest")

    def test_rejects_malformed_control_shape(self):
        payload = bundle()
        payload["control_range"]["median"] = 1.0
        with self.assertRaisesRegex(ContractError, "control_range"):
            parse_bundle(payload, "digest")

    def test_rejects_unbounded_replicate_policy(self):
        for count in (1, 101, 2.5):
            payload = bundle()
            payload["min_replicates"] = count
            with self.subTest(count=count), self.assertRaises(ContractError):
                parse_bundle(payload, "digest")

    def test_rejects_duplicate_measurement_identifier(self):
        payload = bundle()
        payload["measurements"][1]["id"] = payload["measurements"][0]["id"]
        with self.assertRaisesRegex(ContractError, "duplicate measurement"):
            parse_bundle(payload, "digest")

    def test_rejects_unexpected_measurement_fields(self):
        payload = bundle()
        payload["measurements"][0]["unreviewed"] = "value"
        with self.assertRaisesRegex(ContractError, "exactly"):
            parse_bundle(payload, "digest")

    def test_rejects_missing_measurement_fields(self):
        payload = bundle()
        del payload["measurements"][0]["unit"]
        with self.assertRaises(ContractError):
            parse_bundle(payload, "digest")

    def test_rejects_invalid_roles(self):
        payload = bundle()
        payload["measurements"][2]["role"] = "unknown"
        with self.assertRaisesRegex(ContractError, "role"):
            parse_bundle(payload, "digest")

    def test_rejects_boolean_and_non_finite_values(self):
        for value in (True, float("nan"), float("inf"), "bad"):
            payload = bundle()
            payload["measurements"][0]["value"] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                parse_bundle(payload, "digest")

    def test_rejects_naive_timestamp(self):
        payload = bundle()
        payload["measurements"][0]["measured_at"] = "2026-11-01T10:00:00"
        with self.assertRaisesRegex(ContractError, "timezone"):
            parse_bundle(payload, "digest")

    def test_rejects_invalid_timestamp_text(self):
        payload = bundle()
        payload["measurements"][0]["measured_at"] = "yesterday"
        with self.assertRaisesRegex(ContractError, "ISO-8601"):
            parse_bundle(payload, "digest")

    def test_requires_at_least_one_control(self):
        payload = bundle()
        payload["measurements"] = [row for row in payload["measurements"] if row["role"] != "control"]
        with self.assertRaisesRegex(ContractError, "control"):
            parse_bundle(payload, "digest")

    def test_digest_is_over_original_bytes(self):
        body = json.dumps(bundle(), ensure_ascii=False).encode()
        decoded, digest = decode_json(body)
        self.assertEqual(decoded["study_id"], "study-1")
        self.assertEqual(len(digest), 64)
        self.assertEqual(encode_canonical(parse_bundle(decoded, digest))[:1], "{")

    def test_rejects_invalid_utf8_and_json(self):
        for body in (b"\xff", b"{broken"):
            with self.subTest(body=body), self.assertRaises(ContractError):
                decode_json(body)

    def test_rejects_duplicate_json_keys_instead_of_using_last_value(self):
        with self.assertRaisesRegex(ContractError, "duplicate JSON key"):
            decode_json(b'{"study_id":"first","study_id":"second"}')

    def test_rejects_unknown_bundle_fields_to_catch_misspellings(self):
        payload = bundle()
        payload["protocol_verison"] = 2
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            parse_bundle(payload, "digest")

    def test_manifest_checks_exact_file_digest_before_returning_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = root / "run.json"
            payload.write_bytes(b'{"one":1}')
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"bundles": [{"path": "run.json", "sha256": digest}]}),
                                encoding="utf-8")
            self.assertEqual(read_manifest(manifest), [payload])

    def test_manifest_template_is_sorted_and_reusable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "z.json"
            second = root / "a.json"
            first.write_text("z", encoding="utf-8")
            second.write_text("a", encoding="utf-8")
            template = manifest_template([first, second], root=root)
            self.assertEqual([item["path"] for item in template["bundles"]], ["a.json", "z.json"])
            destination = root / "manifest.json"
            destination.write_text(json.dumps(template), encoding="utf-8")
            self.assertEqual(read_manifest(destination), [second, first])

    def test_manifest_rejects_modified_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = root / "run.json"
            payload.write_text("original", encoding="utf-8")
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            payload.write_text("changed", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"bundles": [{"path": "run.json", "sha256": digest}]}),
                                encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "digest mismatch"):
                read_manifest(manifest)

    def test_manifest_rejects_parent_path_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root.parent / "outside.json"
            outside.write_text("outside", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"bundles": [{"path": "../outside.json",
                                  "sha256": hashlib.sha256(outside.read_bytes()).hexdigest()}]}), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "escapes"):
                read_manifest(manifest)

    def test_manifest_rejects_duplicate_resolved_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = root / "run.json"
            payload.write_text("same", encoding="utf-8")
            item = {"path": "run.json", "sha256": hashlib.sha256(payload.read_bytes()).hexdigest()}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"bundles": [item, item]}), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "duplicate path"):
                read_manifest(manifest)

    def test_rejects_empty_measurement_array(self):
        payload = bundle()
        payload["measurements"] = []
        with self.assertRaisesRegex(ContractError, "non-empty"):
            parse_bundle(payload, "digest")


if __name__ == "__main__":
    unittest.main()

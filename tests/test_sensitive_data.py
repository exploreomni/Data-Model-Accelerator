"""Synthetic disclosure regressions; no real customer data or host qualification."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import sensitive_data as scanner


def archive(items):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as out:
        for name, body in items:
            out.writestr(name, body)
    return stream.getvalue()


class SensitiveDataTests(unittest.TestCase):
    def test_embedded_text_is_not_misclassified_as_json(self):
        for value in ('[Guide](guide.md)', '[sqlfluff]\ndialect = snowflake',
                      '{% macro example() %}{{ ref("x") }}{% endmacro %}', '{color:red}'):
            content = json.dumps({'base64': base64.b64encode(value.encode()).decode()}).encode()
            self.assertEqual(scanner.scan_bytes(content, 'artifact.json')['status'], 'clear')
            changed = json.dumps({'base64': base64.b64encode((value+' SYNTHETIC_PII_CANARY').encode()).decode()}).encode()
            self.assertEqual(scanner.scan_bytes(changed, 'artifact.json')['status'], 'blocked')

    def test_clean_metadata_is_not_claimed_certified(self):
        report = scanner.scan_bytes(b'order_id,order_date\n', 'schema.csv')
        self.assertEqual(report['status'], 'clear')
        self.assertTrue(report['coverage']['complete'])
        self.assertTrue(any('not absence' in line for line in report['limitations']))

    def test_value_and_sensitive_filename_never_appear_in_findings(self):
        value = 'fictional-person@example.invalid'
        report = scanner.scan_bytes(('Owner: ' + value).encode(), value + '.txt')
        self.assertEqual(report['status'], 'blocked')
        self.assertNotIn(value, json.dumps(report))
        self.assertNotIn('Owner:', json.dumps(report))
        self.assertEqual(report['findings'][0]['rule_id'], 'pii.email')
        self.assertEqual(report['findings'][0]['location'], {'member_indices': [], 'line': 1})

    def test_secret_ssn_card_and_health_signals_are_candidates(self):
        cases = [(b'password = SYNTHETIC_CREDENTIAL_ONLY', 'CREDENTIAL'),
                 (b'-----BEGIN PRIVATE KEY-----', 'CREDENTIAL'),
                 (b'123-45-6789', 'PII'),  # standard fictional test pattern
                 (b'4111 1111 1111 1111', 'PCI'),  # standard payment test number
                 (b'cvv: 999', 'PCI'),
                 (b'diagnosis: SYNTHETIC_ONLY', 'PHI')]
        for payload, category in cases:
            with self.subTest(category=category):
                report = scanner.scan_bytes(payload, 'fixture.txt')
                self.assertEqual(report['status'], 'blocked')
                self.assertIn(category, [row['category'] for row in report['findings']])
                self.assertNotIn(payload.decode(), json.dumps(report))

    def test_arbitrary_numeric_identifier_is_not_pan_without_luhn(self):
        self.assertEqual(scanner.scan_bytes(b'1234567890123456', 'fixture.txt')['status'], 'clear')

    def test_card_pattern_does_not_match_substrings_of_integrity_hashes(self):
        digest = 'abcdef' + '4111111111111111' + 'b' * 42
        self.assertEqual(len(digest), 64)
        self.assertEqual(scanner.scan_bytes(json.dumps({'sha256': digest}).encode(), 'evidence.json')['status'], 'clear')
        self.assertEqual(scanner.scan_bytes(b'"sha256":"4111111111111111"', 'evidence.txt')['status'], 'blocked')

    def test_numeric_uuid_is_not_pan_but_adjacent_card_still_blocks(self):
        value = '10000000-0000-4000-8000-000000000001'
        self.assertEqual(scanner.scan_bytes(value.encode(), 'identity.txt')['status'], 'clear')
        for card in ('4111-1111-1111-1111', '4111111111111111', '-4111111111111111'):
            self.assertEqual(scanner.scan_bytes((value + ' ' + card).encode(), 'identity.txt')['status'], 'blocked')
        self.assertEqual(scanner.scan_bytes((value+' SYNTHETIC_PII_CANARY').encode(), 'identity.txt')['status'], 'blocked')

    def test_health_field_declarations_are_not_treated_as_patient_values(self):
        for payload in (b'dimensions:\n  patient_id:\n    sql: patient_id\n',
                        b'columns:\n  diagnosis:\r\n    description: Clinical code field\r\n'):
            self.assertEqual(scanner.scan_bytes(payload, 'patients.view')['status'], 'clear')
        self.assertEqual(scanner.scan_bytes(b'patient_id: FICTIONAL_RECORD_ONLY\n',
                                           'fixture.txt')['status'], 'blocked')

    def test_escaped_json_and_html_entities_are_scanned_decoded(self):
        for body, name in [(b'{"owner":"fictional\\u0040example.invalid"}', 'fixture.json'),
                           (b'<p>fictional&#64;example.invalid</p>', 'fixture.html')]:
            self.assertEqual(scanner.scan_bytes(body, name)['status'], 'blocked')

    def test_portal_base64_is_scanned_even_when_visible_text_is_clean(self):
        raw = b'SYNTHETIC_PHI_CANARY'
        payload = json.dumps({'files': [{'base64': base64.b64encode(raw).decode()}]})
        body = ('<script type="application/json">' + payload + '</script>').encode()
        report = scanner.scan_bytes(body, 'START_HERE.html')
        self.assertEqual(report['status'], 'blocked')
        self.assertNotIn(raw.decode(), json.dumps(report))
        self.assertNotIn(base64.b64encode(raw).decode(), json.dumps(report))

    def test_nested_archive_and_decoded_json_preserve_detection(self):
        body = archive([('inner.zip', archive([('data.json', b'{"owner":"fictional\\u0040example.invalid"}')]))])
        report = scanner.scan_bytes(body, 'handoff.zip')
        self.assertEqual(report['status'], 'blocked')
        self.assertTrue(any(f['location']['member_indices'][:2] == [0, 0] for f in report['findings']))

    def test_unsafe_archive_filename_and_symlink_never_leak(self):
        malicious = '../fictional@example.invalid.txt'
        report = scanner.scan_bytes(archive([(malicious, b'plain')]), 'fixture.zip')
        self.assertEqual(report['status'], 'blocked')
        self.assertNotIn(malicious, json.dumps(report))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as out:
            entry = zipfile.ZipInfo('link'); entry.external_attr = 0o120777 << 16
            out.writestr(entry, '../outside')
        self.assertEqual(scanner.scan_bytes(stream.getvalue(), 'fixture.zip')['status'], 'unsupported')

    def test_invalid_encoding_binary_and_unqualified_formats_block_coverage(self):
        for body, name in [(b'\xff', 'a.txt'), (b'\0', 'a.txt'), (b'plain', 'a.parquet'),
                           (b'PKbad', 'a.txt'), (b'{broken', 'a.json'),
                           (b'{"k":"one","k":"two"}', 'a.json')]:
            with self.subTest(name=name):
                report = scanner.scan_bytes(body, name)
                self.assertEqual(report['status'], 'unsupported')
                self.assertFalse(report['coverage']['complete'])

    def test_archives_and_base64_share_depth_and_expansion_bounds(self):
        body = b'plain'
        for _ in range(scanner.MAX_DEPTH + 2):
            body = archive([('nested.zip' if body.startswith(b'PK') else 'plain.txt', body)])
        self.assertEqual(scanner.scan_bytes(body, 'fixture.zip')['status'], 'unsupported')
        body = b'{}'
        for _ in range(scanner.MAX_DEPTH + 2):
            body = json.dumps({'base64': base64.b64encode(body).decode()}).encode()
        self.assertEqual(scanner.scan_bytes(body, 'fixture.json')['status'], 'unsupported')
        self.assertEqual(scanner.scan_bytes(archive([('large.txt', b'x' * 100000)]), 'a.zip')['status'], 'unsupported')

    def test_limits_and_invalid_base64_never_pass(self):
        with patch.object(scanner, 'MAX_BYTES', 8):
            self.assertEqual(scanner.scan_bytes(b'x' * 9, 'a.txt')['status'], 'unsupported')
        with patch.object(scanner, 'MAX_MEMBERS', 1):
            self.assertEqual(scanner.scan_bytes(archive([('a.txt', b'a'), ('b.txt', b'b')]), 'a.zip')['status'], 'unsupported')
        self.assertEqual(scanner.scan_bytes(b'{"base64":"not valid"}', 'a.json')['status'], 'unsupported')

    def test_archive_names_comments_extras_prefix_and_tail_cannot_bypass(self):
        canary = b'SYNTHETIC_PII_CANARY'
        named = archive([(canary.decode() + '.txt', b'plain')])
        self.assertEqual(scanner.scan_bytes(named, 'a.zip')['status'], 'blocked')
        for member_comment, archive_comment, extra in [(canary, b'', b''), (b'', canary, b''),
                                                       (b'', b'', b'\xfe\xca\x02\x00xx')]:
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as out:
                entry = zipfile.ZipInfo('safe.txt'); entry.comment = member_comment; entry.extra = extra
                out.writestr(entry, b'plain'); out.comment = archive_comment
            report = scanner.scan_bytes(stream.getvalue(), 'a.zip')
            self.assertNotEqual(report['status'], 'clear')
            self.assertNotIn(canary.decode(), json.dumps(report))
        plain = archive([('safe.txt', b'plain')])
        for data in (canary + plain, plain + canary):
            self.assertEqual(scanner.scan_bytes(data, 'a.zip')['status'], 'unsupported')
        self.assertEqual(scanner.scan_bytes(archive([('empty/', canary)]), 'a.zip')['status'], 'unsupported')

    def test_duplicate_html_attribute_cannot_hide_an_embedded_payload(self):
        encoded = base64.b64encode(b'SYNTHETIC_PII_CANARY').decode()
        for attrs in ('src="data:text/plain;base64,' + encoded + '" src="about:blank"',
                      'src="about:blank" src="data:text/plain;base64,' + encoded + '"'):
            result = scanner.scan_bytes(('<iframe ' + attrs + '></iframe>').encode(), 'a.html')
            self.assertEqual(result['status'], 'blocked')
            self.assertFalse(result['coverage']['complete'])
        self.assertEqual(scanner.scan_bytes(b'<script type="application/json" type="text/plain">{}</script>',
                                           'a.html')['status'], 'unsupported')
        self.assertEqual(scanner.scan_bytes(b'<script type>plain</script>', 'a.html')['status'], 'clear')

    def test_agent_input_staging_rejects_archive_and_html_bypasses_without_output(self):
        from prepare_agent_input import prepare
        from test_privacy_contract import approved_classification, approved_policy
        canary = b'SYNTHETIC_PII_CANARY'
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as out:
            item = zipfile.ZipInfo('safe.txt'); item.comment = canary
            out.writestr(item, b'plain')
        encoded = base64.b64encode(canary).decode()
        bodies = [(archive([(canary.decode() + '.txt', b'plain')]), 'safe.zip'),
                  (stream.getvalue(), 'safe.zip'),
                  (archive([('safe.txt', b'plain')]) + canary, 'safe.zip'),
                  (archive([('folder/', canary)]), 'safe.zip'),
                  (('<iframe src="data:text/plain;base64,' + encoded + '" src="about:blank"></iframe>').encode(), 'safe.html')]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root / 'source'; source.mkdir()
            for index, (body, filename) in enumerate(bodies):
                with self.subTest(index=index):
                    (source / filename).write_bytes(body)
                    request = {'schema_version': 1, 'kind': 'agent_input_request', 'policy': approved_policy(),
                               'files': [{'path': filename, 'sha256': hashlib.sha256(body).hexdigest(),
                                          'classification': approved_classification()}]}
                    output = root / ('projection-' + str(index))
                    with self.assertRaises(ValueError):
                        prepare(source, request, output)
                    self.assertFalse(output.exists())
                    self.assertEqual((source / filename).read_bytes(), body)

    def test_cli_is_value_free_and_does_not_follow_links(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root).resolve(); path = root / 'fixture.txt'
            path.write_text('fictional-person@example.invalid')
            result = subprocess.run([sys.executable, '-B', scanner.__file__, str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('fictional-person', result.stdout + result.stderr)
            link = root / 'link.txt'; link.symlink_to(path)
            with self.assertRaises(ValueError):
                scanner.scan_file(link)


if __name__ == '__main__':
    unittest.main()

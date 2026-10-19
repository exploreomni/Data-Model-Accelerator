"""Cheap syntax checks must include draft filenames, not just native names."""
from pathlib import Path
import sys
import tempfile
import unittest
import importlib.util

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
from artifact_syntax import check_structured_artifacts


@unittest.skipUnless(importlib.util.find_spec('yaml'), 'Optional YAML parser unavailable')
class ArtifactSyntaxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def check(self, name, text):
        path = self.root / name; path.write_text(text)
        before = path.read_bytes()
        result = check_structured_artifacts(self.root, [name])
        self.assertEqual(path.read_bytes(), before)
        return result

    def test_invalid_omni_draft_cannot_pass_basic_yaml(self):
        result = self.check('sales.topic.draft.yaml', 'base_view: sales\nowners: [@team-data]\n')
        self.assertIn('failed', [f['status'] for f in result])

    def test_valid_yaml_is_syntax_only(self):
        result = self.check('sales.topic.draft.yaml', 'base_view: sales\nowners: ["@team-data"]\n')
        self.assertEqual([(f['code'], f['status']) for f in result], [('yaml_syntax_checked', 'passed')])

    def test_native_omni_filenames_receive_the_same_syntax_checks(self):
        for name in ('sales.view', 'sales.query.view', 'sales.topic', 'model', 'relationships'):
            with self.subTest(name=name):
                self.assertEqual(self.check(name, 'label: Synthetic\n')[0]['status'], 'passed')
                result = self.check(name, 'owners: [@team-data]\n')
                self.assertEqual((result[0]['code'], result[0]['status']), ('yaml_syntax_invalid', 'failed'))

    def test_duplicate_json_and_yaml_keys_cannot_hide_values(self):
        for name, text in [('a.json', '{"filter":1,"filter":2}'), ('a.yaml', 'filter: 1\nfilter: 2')]:
            with self.subTest(name=name):
                self.assertEqual(self.check(name, text)[0]['status'], 'failed')

    def test_safe_unknowns_and_unrelated_files_are_retained(self):
        self.assertEqual(self.check('design.json', '{"type":null}')[0]['status'], 'passed')
        self.assertEqual(self.check('notes.md', 'unfinished definition'), [])
        self.assertEqual(self.check('templated.yml', 'root: &x {a: 1}\nother: *x')[0]['status'], 'unsupported')

    def test_valid_timestamps_and_read_limits_are_not_syntax_failures(self):
        self.assertEqual(self.check('dated.yml', 'created_at: 2026-10-19\n')[0]['status'], 'unsupported')
        self.assertEqual(self.check('large.json', ' ' * (1024 * 1024 + 1))[0]['code'], 'json_syntax_unreadable')
        self.assertEqual(check_structured_artifacts(self.root, ['missing.json'])[0]['status'], 'unsupported')

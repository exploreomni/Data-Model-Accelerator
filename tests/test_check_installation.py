"""Read-only installed content comparison includes prompts, parsers and assets."""
import shutil
import tempfile
from pathlib import Path
import unittest

import test_engagement_stages
from check_installation import compare


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.expected = root / 'expected'; self.expected.mkdir()
        (self.expected / 'SKILL.md').write_text('Synthetic skill')
        for folder in ('scripts', 'references', 'agents', 'assets'):
            (self.expected / folder).mkdir()
            (self.expected / folder / 'sample.txt').write_text('Synthetic pinned content')
        self.installed = root / 'installed'
        shutil.copytree(self.expected, self.installed)

    def test_equal_content_and_ignored_bytecode_are_read_only(self):
        cache = self.installed / 'scripts/__pycache__'; cache.mkdir()
        (cache / 'test.pyc').write_bytes(b'not a runtime source')
        before = {str(p): p.read_bytes() for p in self.installed.rglob('*') if p.is_file()}
        self.assertEqual(compare(self.expected, self.installed)['status'], 'match')
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.installed.rglob('*') if p.is_file()})

    def test_changed_instructions_missing_parser_and_extra_asset_are_reported(self):
        (self.installed / 'agents/sample.txt').write_text('Changed model instructions')
        (self.installed / 'scripts/sample.txt').unlink()
        (self.installed / 'assets/extra.svg').write_text('<svg/>')
        result = compare(self.expected, self.installed)
        self.assertEqual(result['status'], 'different')
        self.assertEqual(result['changed'], ['agents/sample.txt'])
        self.assertEqual(result['missing'], ['scripts/sample.txt'])
        self.assertEqual(result['extra'], ['assets/extra.svg'])

    def test_symlinks_and_missing_skill_are_not_equal_empty_installations(self):
        (self.installed / 'assets/link.txt').symlink_to(self.expected / 'SKILL.md')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            compare(self.expected, self.installed)
        with self.assertRaises(ValueError):
            compare(self.expected, self.installed / 'absent')

    def test_top_level_content_folders_cannot_redirect_identity_reads(self):
        shutil.rmtree(self.installed / 'scripts')
        (self.installed / 'scripts').symlink_to(self.expected / 'scripts', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            compare(self.expected, self.installed)

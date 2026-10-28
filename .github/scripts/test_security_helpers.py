"""Small adversarial checks for the dependency-audit boundary; no network."""
import unittest

from audit_locks import audit_inventory

HASH = 'a' * 64
SUFFIX = ' --hash=sha256:' + HASH
URL = 'https://github.com/dbt-labs/dbt/releases/download/v2.0.8/dbt_oss-2.0.8-py3-none-manylinux_2_28_x86_64.whl'


class AuditInventoryTests(unittest.TestCase):
    def test_hash_locked_direct_wheel_is_included(self):
        self.assertEqual(audit_inventory('dbt-oss @ ' + URL + '#sha256=' + HASH + SUFFIX), ['dbt-oss==2.0.8'])

    def test_url_cannot_disguise_another_package(self):
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            audit_inventory('dbt @ ' + URL + SUFFIX)

    def test_url_cannot_override_the_reviewed_hash(self):
        with self.assertRaisesRegex(ValueError, 'fragment/hash mismatch'):
            audit_inventory('dbt-oss @ ' + URL + '#sha256=' + 'b' * 64 + SUFFIX)

    def test_ambiguous_or_unhashed_requirements_fail(self):
        for requirement in ['pip==26.2.2', 'pip>=26.2.2' + SUFFIX, 'pip==26.*' + SUFFIX,
                            'pip==26.2.2; python_version < "3.10"' + SUFFIX, '']:
            with self.subTest(requirement=requirement), self.assertRaises(ValueError):
                audit_inventory(requirement)

    def test_unreviewed_wheel_origins_fail(self):
        for url in [URL.replace('github.com', 'example.com'), URL.replace('https:', 'http:'), URL + '?redirect=other']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                audit_inventory('dbt-oss @ ' + url + SUFFIX)

    def test_conflicting_versions_fail_but_identical_entries_deduplicate(self):
        pin = 'pip==26.2.2' + SUFFIX
        self.assertEqual(audit_inventory(pin + '\n' + pin), ['pip==26.2.2'])
        with self.assertRaisesRegex(ValueError, 'Conflicting versions'):
            audit_inventory(pin + '\npip==26.0.1' + SUFFIX)


if __name__ == '__main__':
    unittest.main()

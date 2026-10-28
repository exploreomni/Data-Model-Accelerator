"""Small adversarial checks for the dependency-audit boundary; no network."""
import unittest
import subprocess
from pathlib import Path

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


class RunnerPackageTests(unittest.TestCase):
    def check_source_package(self, record, comparison_result):
        script = Path(__file__).with_name('prepare_runner.sh').resolve()
        # Stub only dpkg's exit status; exercise the real source-package filter.
        result = subprocess.run(
            ['bash', '-c', 'source "$1"; stub_result="$2"; dpkg() { return "$stub_result"; }; verify_php_packages',
             'runner-test', str(script), str(comparison_result)],
            input=record, text=True, capture_output=True)
        return result

    def test_extension_version_is_not_compared_to_php_release(self):
        result = self.check_source_package('php8.3-amqp\tphp-amqp\t1.11.0-5ubuntu1\n', 1)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unpatched_php_source_fails(self):
        result = self.check_source_package('php8.3-cli\tphp8.3\t8.3.6-0ubuntu0.24.04.11\n', 1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unpatched PHP', result.stderr)

    def test_patched_php_source_passes(self):
        result = self.check_source_package('php8.3-cli\tphp8.3\t8.3.6-0ubuntu0.24.04.13\n', 0)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

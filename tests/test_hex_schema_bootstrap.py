import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import bootstrap_hex_schema as bootstrap
import hex_source


class HexSchemaBootstrapTests(unittest.TestCase):
    def test_bootstrap_and_reader_pins_match(self):
        self.assertEqual(bootstrap.SHA256, hex_source.SCHEMA_SHA256)
        self.assertEqual(bootstrap.DESTINATION, hex_source.SCHEMA_PATH)

    def test_mutable_publisher_content_cannot_silently_change_contract(self):
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            bootstrap.verify(b'{"changed": true}')

    def test_verified_json_only(self):
        content = b'{"synthetic": true}'
        with patch.object(bootstrap, 'SHA256', hashlib.sha256(content).hexdigest()):
            self.assertEqual(bootstrap.verify(content), content)

    def test_redirect_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'redirect'):
            bootstrap.NoRedirect().redirect_request(None, None, 302, None, None, 'https://other.example/schema')

    def test_missing_schema_does_not_trigger_network(self):
        with patch.object(hex_source, 'SCHEMA_PATH', Path('/nonexistent/dma-hex-schema.json')):
            with self.assertRaisesRegex(ValueError, 'bootstrap_hex_schema.py'):
                hex_source._schema_validator()


if __name__ == '__main__':
    unittest.main()

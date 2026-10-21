"""OOXML relationship parts retain ordinary bounded disclosure scanning."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import sensitive_data as scanner
import migration_plan_exports
from test_migration_plan_exports import fixture


def archive(items):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as result:
        for name, value in items: result.writestr(name, value)
    return out.getvalue()


def replace_member(content, name, value):
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        items = [(info.filename, value if info.filename == name else package.read(info)) for info in package.infolist()]
        if name not in package.namelist(): items.append((name, value))
    return archive(items)


def relationship(target):
    return ('<?xml version="1.0" encoding="UTF-8"?><Relationships '
            'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="r1" Type="https://example.invalid/type" Target="' + target +
            '" TargetMode="External"/></Relationships>').encode()


class SensitiveOOXMLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {Path(row['path']).suffix: row['content'] for row in migration_plan_exports.export_files(fixture())
                     if Path(row['path']).suffix in {'.xlsx', '.docx'}}

    def test_actual_generated_workbook_and_document_in_outer_delivery_are_scanned(self):
        self.assertEqual(set(self.files), {'.xlsx', '.docx'})
        for extension, content in self.files.items():
            with self.subTest(extension=extension):
                report = scanner.scan_bytes(content, 'plan' + extension)
                self.assertEqual(report['status'], 'clear', report['findings'])
                self.assertTrue(report['coverage']['complete'])
                self.assertGreater(report['coverage']['objects_inspected'], 3)
        report = scanner.scan_bytes(archive([('plan' + ext, body) for ext, body in self.files.items()]), 'delivery.zip')
        self.assertEqual(report['status'], 'clear', report['findings'])

    def test_root_and_document_relationship_targets_cannot_hide_sensitive_values(self):
        for extension, member in (('.xlsx', '_rels/.rels'), ('.xlsx', 'xl/_rels/workbook.xml.rels'),
                                  ('.docx', 'word/_rels/document.xml.rels')):
            for target, rule in (('mailto:fictional&#64;example.org', 'pii.email'),
                                 ('Bearer synthetic-token-123', 'credential.bearer')):
                with self.subTest(member=member, rule=rule):
                    content = replace_member(self.files[extension], member, relationship(target))
                    report = scanner.scan_bytes(archive([('plan' + extension, content)]), 'delivery.zip')
                    self.assertEqual(report['status'], 'blocked')
                    self.assertIn(rule, {r['rule_id'] for r in report['findings']})
                    self.assertNotIn(target, str(report))

    def test_malformed_relationship_and_unsupported_or_binary_members_remain_blocked(self):
        mutations = [('_rels/.rels', b'<Relationships><Relationship>'),
                     ('_rels/.rels', b'<Relationships>\0</Relationships>'),
                     ('_rels/.rels', b'<!DOCTYPE x [<!ENTITY payload "hidden">]><x>&payload;</x>'),
                     ('word/opaque.dat', b'Unrecognized embedded payload'),
                     ('word/embedding.bin', b'\0\xff\0')]
        for name, value in mutations:
            with self.subTest(member=name, value=value):
                content = replace_member(self.files['.docx'], name, value)
                report = scanner.scan_bytes(content, 'plan.docx')
                self.assertEqual(report['status'], 'unsupported')
                self.assertFalse(report['coverage']['complete'])
        with patch.object(scanner, 'MAX_MEMBERS', 2):
            self.assertEqual(scanner.scan_bytes(self.files['.xlsx'], 'plan.xlsx')['status'], 'unsupported')


if __name__ == '__main__': unittest.main()

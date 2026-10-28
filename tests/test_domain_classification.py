"""Optional classification evidence preserves source IDs and human domain scope."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'))
import domain_classification as classification
from ae_common import hash_json


def row(identifier='source:Orders', domain='sales', shared=None):
    return {'id': identifier, 'table_id': 'Raw."Order.Table"', 'domain_id': domain,
            'confidence': 0.8, 'rationale': 'Supplied metadata describes this business use.',
            'required_columns': ['Order.ID', 'Customer ID'], 'shared_domain_ids': shared or [],
            'evidence_refs': ['metadata://review/1']}


def document(entries=None, version='1', fingerprint='a' * 64):
    return {'schema_version': 1, 'kind': 'domain_classification', 'version': version,
            'source_reference': 'metadata://classification/export', 'source_sha256': fingerprint,
            'entries': entries if entries is not None else [row()]}


def state():
    return {'inputs': {'source': {'fingerprint': {'algorithm': 'sha256', 'value': 'a' * 64}}},
            'workflow': {'domain_journey': {'active_domain_id': 'accepted-sales',
                         'domains': [{'id': 'accepted-sales', 'name': 'Approved customer label'}],
                         'completions': ['completed-before-import']},
                         'design': {'revision': 3, 'entities': [{'id': 'accepted-model'}]},
                         'naming_governance': {'selected': 'AcceptedName'}}}


class DomainClassificationTests(unittest.TestCase):
    def test_csv_preserves_qualified_ids_and_provenance_and_cli_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = root / 'metadata.csv'
            with source.open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=sorted(classification.ENTRY_FIELDS))
                writer.writeheader()
                entry = row()
                for field in ('required_columns', 'shared_domain_ids', 'evidence_refs'): entry[field] = json.dumps(entry[field])
                writer.writerow(entry)
            imported = classification.from_csv(source, 'metadata://original', 'a' * 64, 'export-1')
            self.assertEqual(imported['entries'][0], row())
            self.assertEqual(imported['import_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            output = root / 'new.json'
            args = ['--csv', str(source), '--source-reference', 'metadata://original', '--source-sha256', 'a' * 64,
                    '--version', 'export-1', '--output', str(output)]
            self.assertEqual(classification.main(args), 0)
            self.assertEqual(json.loads(output.read_text()), imported)
            with self.assertRaises(FileExistsError): classification.main(args)
            link = root / 'link.csv'; link.symlink_to(source)
            with self.assertRaisesRegex(ValueError, 'Symlink'): classification.from_csv(link, 'metadata://original', 'a' * 64)

    def test_register_preserves_accepted_scope_and_rejects_invalid_or_same_version_drift(self):
        engagement = state(); original = copy.deepcopy(engagement)
        classification.register(engagement, document())
        accepted = copy.deepcopy(engagement)
        classification.register(engagement, document())
        self.assertEqual(engagement, accepted)
        stored = engagement['workflow'].pop('domain_classification')
        self.assertEqual(engagement, original)
        engagement['workflow']['domain_classification'] = stored
        changed = document(); changed['entries'][0]['domain_id'] = 'another-proposal'
        with self.assertRaisesRegex(ValueError, 'new version'): classification.register(engagement, changed)
        for invalid in (dict(document(), schema_version=2), dict(document(), kind='approved_domains')):
            with self.assertRaises(ValueError): classification.normalize(invalid)
        for confidence in (True, -0.1, 1.1, float('nan'), 'high'):
            invalid = document(); invalid['entries'][0]['confidence'] = confidence
            with self.assertRaises(ValueError): classification.normalize(invalid)

    def test_source_change_is_stale_until_explicit_versioned_reimport(self):
        engagement = state(); classification.register(engagement, document())
        self.assertEqual(classification.summary(engagement)['status'], 'current')
        engagement['inputs']['source']['fingerprint']['value'] = 'b' * 64
        self.assertEqual(classification.summary(engagement)['status'], 'stale')
        stale = classification.packet(engagement, 'sales')
        self.assertEqual(stale['status'], 'stale'); self.assertEqual(stale['entries'], [])
        self.assertFalse(stale['scope_complete'])
        with self.assertRaisesRegex(ValueError, 'fingerprint'): classification.register(engagement, document())
        classification.register(engagement, document(version='2', fingerprint='b' * 64))
        self.assertEqual(classification.summary(engagement)['status'], 'current')
        self.assertEqual(classification.summary(engagement)['history_count'], 1)
        self.assertEqual(engagement['workflow']['domain_classification']['history'][0]['document'], document())
        self.assertNotIn('entries', classification.summary(engagement))

    def test_packet_contains_selected_and_explicit_shared_only_with_partial_bounds(self):
        engagement = state()
        self.assertEqual(classification.summary(engagement)['status'], 'not_imported')
        self.assertIsNone(classification.packet(engagement, 'sales'))
        self.assertIsNone(classification.validate_packet({'bindings': {}}))
        rows = [row(), row('shared:Customer', 'shared', ['sales']), row('other:Inventory', 'inventory')]
        classification.register(engagement, document(rows))
        body = classification.packet(engagement, 'sales')
        self.assertEqual([e['id'] for e in body['entries']], ['source:Orders', 'shared:Customer'])
        request = {'domain_classification': body, 'bindings': {'domain_classification': body['sha256']}}
        self.assertEqual(classification.validate_packet(request), body)
        bad = copy.deepcopy(body); bad['entries'].append(rows[-1])
        bad['sha256'] = hash_json({k: v for k, v in bad.items() if k != 'sha256'})
        with self.assertRaisesRegex(ValueError, 'unrelated'): classification.validate_packet({'domain_classification': bad, 'bindings': {'domain_classification': bad['sha256']}})
        altered = copy.deepcopy(request); altered['domain_classification']['entries'][0]['rationale'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'pin mismatch'): classification.validate_packet(altered)
        classification.register(engagement, document([row('entry:' + str(i)) for i in range(100)], version='2'))
        bounded = classification.packet(engagement, 'sales')
        self.assertLessEqual(len(json.dumps(bounded, separators=(',', ':'), sort_keys=True).encode()), classification.MAX_PACKET_BYTES)
        self.assertFalse(bounded['scope_complete']); self.assertGreater(bounded['omitted_entry_count'], 0)
        self.assertEqual(classification.validate_packet({'domain_classification': bounded, 'bindings': {'domain_classification': bounded['sha256']}}), bounded)

    def test_packet_binds_architect_and_entity_briefs_to_explicit_workflow_scope(self):
        engagement = state()
        engagement['workflow']['domain_journey']['domains'].append(
            {'id': 'sales', 'name': 'Sales', 'shared_dependency_ids': ['shared-customers']})
        engagement['workflow']['design']['entities'] += [
            {'id': 'orders', 'domain': 'Sales'}, {'id': 'sales-lines', 'domain': 'sales'},
            {'id': 'inventory', 'domain': 'inventory'}, {'id': 'shared-customers', 'domain': 'shared'}]
        # Imported domain suggestions cannot add entity IDs to accepted scope.
        classification.register(engagement, document([row(), row('inventory', 'sales')]))
        body = classification.packet(engagement, 'sales')
        self.assertEqual(body['scope_ids'], ['orders', 'sales', 'sales-lines', 'shared-customers'])
        request = {'domain_classification': body, 'bindings': {'domain_classification': body['sha256']}}
        for scope in (['sales'], ['orders'], ['sales-lines', 'shared-customers']):
            self.assertEqual(classification.validate_packet({**request, 'brief': {'scope_ids': scope}}), body)
        with self.assertRaisesRegex(ValueError, 'specialist task scope'):
            classification.validate_packet({**request, 'brief': {'scope_ids': ['inventory']}})
        engagement['inputs']['source']['fingerprint']['value'] = 'b' * 64
        stale = classification.packet(engagement, 'sales')
        self.assertEqual(stale['entries'], [])
        self.assertEqual(stale['scope_ids'], body['scope_ids'])


if __name__ == '__main__': unittest.main()

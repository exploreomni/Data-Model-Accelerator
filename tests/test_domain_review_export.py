"""Synthetic domain packaging: complete accounting without larger safety limits."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from test_guided_workflow import BASE, collector, workflow
from test_design_builder import request
import design_builder
import domain_review_export as exporter
import delivery_portal as portal


class DomainReviewExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        (self.source / 'source.sql').write_text('select 1 as order_id')
        self.run = self.root / 'run'
        with patch.object(workflow, '_assess_repository', collector):
            workflow.start_engagement(self.source, self.run, BASE)
            value = request()
            value['nodes'] += [{'id': 'returns', 'name': 'returns', 'domain': 'returns', 'layer': 'gold',
                                'depends_on': ['raw_orders'], 'disposition': 'create'},
                               {'id': 'isolated', 'name': 'isolated', 'domain': 'returns', 'layer': 'gold'}]
            edge = {'from': 'orders', 'to': 'returns', 'kind': 'relationship', 'cardinality': 'unknown', 'status': 'proposed'}
            value['edges'] += [edge, copy.deepcopy(edge)]
            self.state = workflow.stage_action(self.run, 'import-design', document=design_builder.assemble(value))

    def test_each_entity_has_one_owner_and_every_edge_occurrence_survives(self):
        before = copy.deepcopy(self.state)
        plan = exporter.plan_partitions(self.state)
        index = plan['index']
        self.assertEqual(self.state, before)
        self.assertEqual(len(index['entities']), 5)
        self.assertEqual(len(index['relationships']), 4)
        owned = [key for part in plan['partitions'] for key in part['owned_model_ids']]
        self.assertEqual(sorted(owned), ['customers', 'isolated', 'orders', 'raw_orders', 'returns'])
        self.assertEqual(len(set(owned)), len(owned))
        self.assertTrue(all(row['partitions'] for row in index['relationships']))
        self.assertEqual(len({row['id'] for row in index['relationships']}), 4)
        returns = next(p for p in plan['partitions'] if p['domain'] == 'returns')
        self.assertEqual(returns['shared_dependency_ids'], ['raw_orders'])
        self.assertEqual(returns['reference_ids'], ['orders'])
        self.assertEqual(len(returns['review']['domain_proposals'][0]['relationships']), 3)
        self.assertEqual({row['from'] for row in index['dependencies']}, {'raw_orders', 'customers'})
        self.assertNotIn('source_paths', json.dumps(plan))
        altered = copy.deepcopy(returns['review']); altered['models'] = [m for m in altered['models'] if m['id'] != 'isolated']
        with self.assertRaisesRegex(ValueError, 'every owned entity'):
            portal.validate_review(self.state, altered)

    def test_actual_packages_reopen_hashes_match_and_repeated_bytes_are_stable(self):
        before = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for directory in (self.source, self.run) for p in directory.rglob('*') if p.is_file()}
        with patch.object(portal, '_check_disclosure_bytes', wraps=portal._check_disclosure_bytes) as scanner:
            result = exporter.export_domains(self.state, self.root / 'first', run_dir=self.run)
        scanned = [call.args[1] for call in scanner.call_args_list]
        self.assertIn('delivery.zip', scanned)
        self.assertTrue(any(path.endswith('/review.json') for path in scanned))
        self.assertIn('PARTITION_INDEX.json', scanned)
        index = json.loads(Path(result['index']).read_text())
        for record in index['files']:
            content = (self.root / 'first' / record['path']).read_bytes()
            self.assertEqual(len(content), record['bytes'])
            self.assertEqual(hashlib.sha256(content).hexdigest(), record['sha256'])
        for item in index['partitions']:
            package = self.root / 'first' / item['zip']
            self.assertEqual(portal.verify_delivery(package)['status'], 'integrity_verified')
            with zipfile.ZipFile(package) as archive:
                page = archive.read('START_HERE.html')
                for name in archive.namelist():
                    extracted = self.root / 'first' / item['id'] / name
                    self.assertTrue(extracted.is_file(), name)
                    self.assertEqual(extracted.read_bytes(), archive.read(name))
            self.assertEqual(page, (self.root / 'first' / item['entrypoint']).read_bytes())
            data = json.loads(page.decode().split('<script id="delivery-data" type="application/json">')[1].split('</script>')[0])
            self.assertEqual({m['id'] for m in data['review']['models']}, set(item['owned_model_ids'] + item['shared_dependency_ids']))
            self.assertEqual(data['workflow']['design_checks']['status'], 'consistent')
            self.assertNotIn('review_model_missing', json.dumps(data['workflow']['design_checks']))
            self.assertNotIn('review_assurance', data['workflow'])
            self.assertEqual(data['workflow']['design_readiness']['native_validation']['status'], 'unassessed')
            self.assertEqual(data['files'], [])
        repeated = exporter.export_domains(self.state, self.root / 'second', run_dir=self.run)
        self.assertEqual(Path(result['index']).read_bytes(), Path(repeated['index']).read_bytes())
        after = {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for directory in (self.source, self.run) for p in directory.rglob('*') if p.is_file()}
        self.assertEqual(after, before)
        with self.assertRaisesRegex(ValueError, 'new output directory'):
            exporter.export_domains(self.state, self.root / 'first', run_dir=self.run)

    def test_explicit_batches_keep_domain_identity_full_closure_and_exact_accounting(self):
        plan = exporter.plan_partitions(self.state, max_owned_models=1)
        self.assertEqual(len(plan['partitions']), 5)
        self.assertEqual({row['domain'] for row in plan['partitions']}, {'sales', 'returns', 'shared'})
        self.assertEqual(sorted(key for row in plan['partitions'] for key in row['owned_model_ids']),
                         ['customers', 'isolated', 'orders', 'raw_orders', 'returns'])
        orders = next(row for row in plan['partitions'] if row['owned_model_ids'] == ['orders'])
        self.assertEqual(orders['shared_dependency_ids'], ['customers', 'raw_orders'])
        self.assertEqual(orders['batch_index'], 1)
        self.assertTrue(all(row['partitions'] for row in plan['index']['relationships']))
        changed = copy.deepcopy(orders['review']); changed['partition']['batch_index'] = 2
        with self.assertRaisesRegex(ValueError, 'every owned entity'):
            portal.validate_review(self.state, changed)
        for value in (0, -1, True, 1.5):
            with self.assertRaisesRegex(ValueError, 'max_owned_models'):
                exporter.plan_partitions(self.state, value)

    def test_limits_fail_without_published_partial_or_truncation(self):
        destination = self.root / 'blocked'
        with patch.object(portal, 'MAX_ARTIFACT_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'unchanged safety bounds.*No partial delivery'):
                exporter.export_domains(self.state, destination, run_dir=self.run)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.root.glob('.domain-review-*')))
        self.assertEqual(len(exporter.plan_partitions(self.state)['index']['entities']), 5)

    def test_large_review_batches_fit_but_one_huge_closure_fails_atomically(self):
        from ae_common import _json_bytes, hash_json, MAX_JSON_BYTES
        from design_consistency import project_review
        import sensitive_data
        state = copy.deepcopy(self.state)
        doc = state['workflow']['design']
        template = copy.deepcopy(doc['entities'][0])
        entities = []
        for number in range(32):
            row = copy.deepcopy(template)
            row.update(id='model_' + str(number).zfill(2), name='model_' + str(number).zfill(2),
                       domain='domain_' + str(number // 8), depends_on=[], asset_ids=[], keys=['id'])
            row['columns'] = [{'name': 'id', 'type': 'integer', 'key': 'PK', 'description': 'Synthetic key'}] + [
                {'name': 'column_' + str(column), 'type': 'string',
                 'description': ('Synthetic bounded definition. ' * 250)[:6800]} for column in range(50)]
            entities.append(row)
        doc.update(entities=entities, assets=[], decisions=[], existing_models=[], relationships=[
            {'from': row['id'], 'to': entities[(number + 9) % 32]['id'], 'kind': 'relationship',
             'cardinality': 'unknown', 'status': 'proposed'} for number, row in enumerate(entities)])
        doc.pop('sha256', None); doc['sha256'] = hash_json(doc)
        self.assertGreater(len(_json_bytes(project_review(doc))), MAX_JSON_BYTES)
        self.assertLess(len(_json_bytes(state)), workflow.MAX_JSON_BYTES)
        plan = exporter.plan_partitions(state, max_owned_models=2)
        self.assertEqual(len(plan['partitions']), 16)
        self.assertEqual(len(plan['index']['entities']), 32)
        self.assertEqual(len(plan['index']['relationships']), 32)
        self.assertTrue(all(row['partitions'] for row in plan['index']['relationships']))
        originals = {row['id']: row for row in project_review(doc)['models']}
        for partition in plan['partitions']:
            self.assertLess(len(_json_bytes(partition['review'])), sensitive_data.MAX_BYTES)
            for row in partition['review']['models']:
                self.assertEqual(row, originals[row['id']])
        doc['entities'][0]['depends_on'] = [row['id'] for row in entities[1:]]
        doc.pop('sha256'); doc['sha256'] = hash_json(doc)
        destination = self.root / 'huge-closure'
        with self.assertRaisesRegex(ValueError, 'review JSON exceeds'):
            exporter.export_domains(state, destination, run_dir=self.run, max_owned_models=2)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.root.glob('.domain-review-*')))

    def test_source_output_overlap_and_missing_disclosure_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'separate'):
            exporter.export_domains(self.state, self.source / 'delivery', run_dir=self.run)
        governed = copy.deepcopy(self.state); governed['answers']['migration_scope'] = 'model_only'
        with self.assertRaisesRegex(ValueError, 'disclosure contract'):
            exporter.export_domains(governed, self.root / 'no-permission', run_dir=self.run)
        self.assertFalse((self.root / 'no-permission').exists())
        with self.assertRaisesRegex(ValueError, 'retained run'):
            exporter.export_domains(self.state, self.run / 'delivery', run_dir=self.run)
        candidate = self.root / 'candidate'; candidate.mkdir()
        scoped = copy.deepcopy(self.state); scoped['workflow']['artifact_root'] = str(candidate)
        with self.assertRaisesRegex(ValueError, 'candidate artifact'):
            exporter.export_domains(scoped, candidate / 'delivery', run_dir=self.run)

    def test_exact_projection_and_governed_metadata_disclosure(self):
        from test_privacy_contract import approved_classification, approved_policy
        governed = copy.deepcopy(self.state); governed['answers']['migration_scope'] = 'model_only'
        disclosure = {'audience': 'reviewer', 'artifacts': {}, 'presentation': approved_classification(), 'policy': approved_policy()}
        part = exporter.plan_partitions(governed)['partitions'][0]
        review = {**part['review'], 'disclosure': disclosure}
        for field in ('models', 'relationships', 'domain_proposals', 'assets'):
            payload = {'review': copy.deepcopy(review)}
            payload['review'][field] = [{'hidden': 'projection differs'}]
            with self.assertRaisesRegex(ValueError, 'Disclosure projection differs'):
                exporter._published_review(governed, review, payload, 'reviewer')
        with patch.object(portal, '_check_share_policy', wraps=portal._check_share_policy) as policy:
            result = exporter.export_domains(governed, self.root / 'governed', run_dir=self.run, disclosure=disclosure)
        self.assertTrue(any(call.args[3].get('kind') == 'domain_design_review_index' for call in policy.call_args_list))
        self.assertTrue(any('partition' in call.args[3] for call in policy.call_args_list))
        for path in (self.root / 'governed').glob('*/review.json'):
            self.assertNotIn('disclosure', json.loads(path.read_text()))
        self.assertTrue(Path(result['entrypoint']).is_file())

    def test_concurrent_destination_is_never_overwritten_or_deleted(self):
        target = self.root / 'raced'
        original = Path.mkdir
        def race(path, *args, **kwargs):
            if path == target:
                original(path)
                (path / 'other-owner.txt').write_text('preserve')
                raise FileExistsError('Concurrent destination')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', race):
            with self.assertRaises(FileExistsError):
                exporter.export_domains(self.state, target, run_dir=self.run)
        self.assertEqual((target / 'other-owner.txt').read_text(), 'preserve')

    def test_cli_uses_retained_state_without_repository_assessment(self):
        with patch.object(workflow, '_assess_repository', side_effect=AssertionError('No new source scan')):
            output = io.StringIO()
            with redirect_stdout(output):
                status = exporter.main(['--state', str(self.run / 'state.json'), '--output', str(self.root / 'cli'), '--max-owned-models', '1'])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())['entity_count'], 5)
        self.assertEqual(len(json.loads(output.getvalue())['packages']), 5)


if __name__ == '__main__':
    unittest.main()

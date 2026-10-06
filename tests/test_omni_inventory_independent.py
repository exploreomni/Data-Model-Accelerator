"""Independent inventory and authored-patch checks against the frozen corpus.

Local inspection is not native compilation, source authority or deployment.
No generated baseline, production edits, live system or corpus mutation.
"""
import base64
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / 'tests/fixtures/omni_modeler'
sys.path.insert(0, str(REPO / 'skills/data-model-accelerator/scripts'))
import omni_inventory as inventory


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest_json(value):
    return digest_bytes(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                  ensure_ascii=True, allow_nan=False).encode())


class IndependentInventoryTests(unittest.TestCase):
    def setUp(self):
        self.cases = {case['id']: case for case in json.loads((CORPUS / 'cases.json').read_text())['cases']}
        self.expected = json.loads((CORPUS / 'expected/source_semantics.json').read_text())
        self.frozen = json.loads((CORPUS / 'FROZEN_SHA256.json').read_text())['files']
        self.scope = {'model_id': 'synthetic-orders-model', 'layer': 'branch',
                      'branch_id': 'synthetic-review-branch', 'workbook_id': None}
        self.context = {'scope': copy.deepcopy(self.scope), 'capture_reference': 'synthetic-capture-A'}

    def files(self, case):
        return {name: (CORPUS / path).read_bytes() for name, path in self.cases[case]['files'].items()}

    def expected_inventory(self, case='authorization_noops'):
        return {'schema_version': 1, 'kind': 'omni_expected_inventory',
                'scope_sha256': digest_json(self.scope), 'provenance': 'synthetic',
                'reference': 'independent-frozen-corpus', 'complete': True,
                'pagination_complete': True,
                'files': {name: self.frozen[path] for name, path in self.cases[case]['files'].items()}}

    def scope_files(self, name):
        return {'orders.view': (CORPUS / ('source/scopes/' + name + '/orders.view')).read_bytes()}

    def assert_runtime_or_parsed(self, report, source):
        """Core CI still checks exact preservation when optional YAML is absent."""
        self.assertEqual(inventory.decode_files(report['authored_files']), source)
        for key in ('native_verified', 'semantics_validated', 'deployment_authorized'):
            self.assertIs(report[key], False)
        if inventory.yaml is None:
            self.assertEqual(report['status'], 'partial')
            self.assertIn('runtime.yaml_unavailable', {f['code'] for f in report['findings']})
            self.assertEqual(report['objects'], [])
            return False
        return True

    def propose_or_runtime_error(self, authored, effective, edits, **kwargs):
        if inventory.yaml is None and edits:
            with self.assertRaises(inventory.InventoryError) as caught:
                inventory.propose_patch(authored, effective, edits, **kwargs)
            self.assertEqual(str(caught.exception), 'patch.yaml_unavailable')
            return None
        return inventory.propose_patch(authored, effective, edits, **kwargs)

    def edit(self, authored, pointer, value, path='orders.view'):
        return {'path': path, 'pointer': pointer, 'value': value,
                'expected_sha256': digest_bytes(authored[path]) if path in authored else None}

    def test_entire_frozen_corpus_remains_byte_identical(self):
        for path, expected in self.frozen.items():
            with self.subTest(path=path):
                self.assertEqual(digest_bytes((CORPUS / path).read_bytes()), expected)

    def test_encode_decode_preserves_crlf_unicode_opaque_bytes_and_hashes(self):
        files = {'folder/opaque.bin': b'\x00\xff\x80\n',
                 'orders.view': b'# comment\r\nlabel: "Shipping"\r\n',
                 'notes.txt': 'A synthetic caf\u00e9 note'.encode()}
        records = inventory.encode_files(files)
        self.assertEqual(inventory.decode_files(records), files)
        for path, data in files.items():
            self.assertEqual(records[path]['sha256'], digest_bytes(data))
            self.assertEqual(records[path]['byte_length'], len(data))
            self.assertEqual(base64.b64decode(records[path]['base64']), data)
        self.assertEqual(records, inventory.encode_files(dict(reversed(list(files.items())))))

    def test_byte_records_refuse_tampered_content_hash_length_and_invalid_shapes(self):
        original = inventory.encode_files(self.files('authorization_noops'))
        for mutation in ('hash', 'length', 'base64', 'boolean_length', 'unhashable_record', 'path'):
            records = copy.deepcopy(original)
            record = records['orders.view']
            if mutation == 'hash': record['sha256'] = '0' * 64
            elif mutation == 'length': record['byte_length'] += 1
            elif mutation == 'base64': record['base64'] = '*invalid*'
            elif mutation == 'boolean_length': record['byte_length'] = True
            elif mutation == 'unhashable_record': records['orders.view'] = []
            else: records['../escape.view'] = records.pop('orders.view')
            with self.subTest(mutation=mutation), self.assertRaises(inventory.InventoryError):
                inventory.decode_files(records)

    def test_encoder_rejects_malformed_text_through_stable_error_boundary(self):
        with self.assertRaises(inventory.InventoryError) as caught:
            inventory.encode_files({'orders.view': '\ud800'})
        self.assertNotIn('ud800', str(caught.exception))

    def test_file_path_and_input_boundaries_are_value_free(self):
        for files in ({'../bad.view': b'x'}, {'/absolute.view': b'x'},
                      {'a//orders.view': b'x'}, {'a\\orders.view': b'x'},
                      {'orders.view': {}}, [], {4: b'x'}):
            with self.subTest(files=files), self.assertRaises(inventory.InventoryError):
                inventory.inspect_model(files)
        with self.assertRaises(inventory.InventoryError):
            inventory.inspect_model({})

    def test_frozen_inventory_matches_declared_scope_without_authenticating_provenance(self):
        files = self.files('authorization_noops')
        expected = self.expected_inventory()
        before = copy.deepcopy((files, self.context, expected))
        report = inventory.inspect_model(files, self.context, expected)
        self.assert_runtime_or_parsed(report, files)
        self.assertEqual(report['coverage']['status'], 'matched_declared_inventory')
        self.assertFalse(report['coverage']['independence_authenticated'])
        self.assertFalse(report['coverage']['native_verified'])
        self.assertEqual(before, (files, self.context, expected))

    def test_inventory_detects_missing_unexpected_changed_and_wrong_scope(self):
        files = self.files('authorization_noops'); expected = self.expected_inventory()
        changed = dict(files); changed['orders.view'] += b'\n# changed after freeze\n'
        changed.pop('orders.topic'); changed['extra.txt'] = b'opaque source'
        report = inventory.inspect_model(changed, self.context, expected)
        self.assertEqual(report['coverage']['status'], 'mismatch')
        self.assertEqual(report['coverage']['missing'], ['orders.topic'])
        self.assertEqual(report['coverage']['unexpected'], ['extra.txt'])
        self.assertEqual(report['coverage']['changed'], ['orders.view'])
        expected['scope_sha256'] = 'f' * 64
        with self.assertRaises(inventory.InventoryError):
            inventory.inspect_model(files, self.context, expected)

    def test_partial_and_same_capture_inventory_do_not_claim_independent_completion(self):
        files = self.files('authorization_noops')
        for mutation, status in (('complete', 'partial_capture'),
                                 ('pagination_complete', 'partial_capture'),
                                 ('same-capture', 'same_capture_not_independent')):
            expected = self.expected_inventory()
            if mutation == 'same-capture': expected['reference'] = self.context['capture_reference']
            else: expected[mutation] = False
            with self.subTest(mutation=mutation):
                report = inventory.inspect_model(files, self.context, expected)
                self.assertEqual(report['coverage']['status'], status)
                self.assertFalse(report['coverage']['independence_authenticated'])
                self.assertNotEqual(report['status'], 'inspected')
        report = inventory.inspect_model(files, self.context)
        self.assertEqual(report['coverage']['status'], 'unverified')

    def test_authored_and_effective_snapshots_stay_separate_and_lossless(self):
        authored, effective = self.scope_files('authored'), self.scope_files('effective')
        report = inventory.inspect_model(authored, self.context, effective_files=effective)
        self.assertEqual(inventory.decode_files(report['authored_files']), authored)
        self.assertEqual(inventory.decode_files(report['effective_files']), effective)
        if not self.assert_runtime_or_parsed(report, authored): return
        objects = {o['id']: o for o in report['objects']}
        self.assertEqual(set(objects), {'authored:view:orders', 'effective:view:orders'})
        self.assertEqual(set(objects['authored:view:orders']['definition']), {'label'})
        self.assertIn('dimensions', objects['effective:view:orders']['definition'])

    def test_opaque_unknown_and_invalid_yaml_preserve_every_input_byte(self):
        for variant in self.cases['unknown_constructs']['isolated_variants']:
            files = {name: (CORPUS / path).read_bytes() for name, path in variant['files'].items()}
            with self.subTest(expected=variant['expected']):
                report = inventory.inspect_model(files)
                if not self.assert_runtime_or_parsed(report, files): continue
                if variant['expected'] == 'invalid_rejected':
                    self.assertEqual(report['status'], 'invalid')
                    self.assertIn('yaml.duplicate_or_non_string_key', {f['code'] for f in report['findings']})
                else:
                    self.assertEqual(report['status'], 'partial')
                    self.assertTrue(report['objects'])
                    self.assertTrue(any('preserved' in f['code'] for f in report['findings']))

    def test_modeled_query_view_uses_frozen_identity_mapping_and_dependencies(self):
        files = self.files('modeled_query_view'); report = inventory.inspect_model(files)
        if not self.assert_runtime_or_parsed(report, files): return
        wanted = self.expected['query_views']['orders_by_customer']
        obj = next(o for o in report['objects'] if o['name'] == wanted['identity'])
        self.assertEqual(obj['kind'], 'query_view')
        self.assertEqual(obj['subtype'], wanted['kind'])
        self.assertEqual(obj['path'], wanted['native_file'])
        self.assertEqual({o['source_field']: o['name'] for o in obj['outputs']}, wanted['output_mappings'])
        refs = {e['reference']: e['status'] for e in report['dependencies'] if e['from'] == obj['id']}
        for field in wanted['output_mappings']:
            self.assertEqual(refs[field], 'resolved')
        self.assertNotIn('table_name', obj['definition'])

    def test_sql_query_view_keeps_source_sql_and_unqualified_output_shape(self):
        files = self.files('sql_query_view'); report = inventory.inspect_model(files)
        if not self.assert_runtime_or_parsed(report, files): return
        wanted = self.expected['query_views']['returns_by_order']
        obj = next(o for o in report['objects'] if o['name'] == wanted['identity'])
        self.assertEqual(obj['kind'], 'query_view')
        self.assertEqual(obj['path'], wanted['native_file'])
        refs = {e['reference'] for e in report['dependencies']
                if e['from'] == obj['id'] and e['kind'] == 'sql_reference'}
        self.assertEqual(refs, set(wanted['view_dependencies']))
        self.assertIn('sql.output_shape_unqualified', {f['code'] for f in report['findings']})
        self.assertNotIn('table_name', obj['definition'])

    def test_query_output_schema_drift_is_not_silently_inspected(self):
        files = self.files('modeled_query_view')
        name = 'orders_by_customer.query.view'
        files[name] = files[name].replace(b'    orders.paid_shipping_cents: paid_shipping_cents\n', b'')
        report = inventory.inspect_model(files)
        if not self.assert_runtime_or_parsed(report, files): return
        self.assertNotEqual(report['status'], 'inspected',
                            'A declared dimension now has no projected query output.')
        self.assertTrue(report['findings'])

    def test_role_aliases_remain_two_topic_scoped_objects(self):
        files = self.files('role_aliases'); report = inventory.inspect_model(files)
        if not self.assert_runtime_or_parsed(report, files): return
        scoped = {o['name']: o for o in report['objects'] if o['parent_id']}
        self.assertEqual(set(scoped), {'buyers', 'sellers'})
        self.assertNotEqual(scoped['buyers']['id'], scoped['sellers']['id'])
        for role, expected in self.expected['role_views'].items():
            self.assertEqual(scoped[role]['definition']['extends'], [expected['extends']])
            self.assertEqual(scoped[role]['parent_id'], 'authored:topic:roles')
        for ref in ('buyers.party_id', 'sellers.party_id', 'buyers.label', 'sellers.label'):
            self.assertTrue(any(e['reference'] == ref and e['status'] == 'resolved'
                                for e in report['dependencies']), ref)

    def test_measure_local_filter_keys_are_dependencies_including_missing_joined_fields(self):
        files = {'order_lines.view': (CORPUS / 'source/physical/order_lines.view').read_bytes()}
        report = inventory.inspect_model(files)
        if not self.assert_runtime_or_parsed(report, files): return
        edges = [e for e in report['dependencies'] if e['reference'] == 'orders.status']
        self.assertTrue(edges, 'A qualified filter field must not disappear from the dependency graph.')
        self.assertTrue(all(e['status'] == 'unresolved' for e in edges))
        self.assertNotEqual(report['status'], 'inspected')

    def test_missing_sql_and_query_references_remain_explicit_gaps(self):
        files = self.files('modeled_query_view')
        files['orders_by_customer.query.view'] = files['orders_by_customer.query.view'].replace(
            b'orders.shipping_cents: shipping_cents', b'orders.absent_value: shipping_cents')
        files['orders.view'] += b'\nfuture_extension: "${missing_view.missing_field}"\n'
        report = inventory.inspect_model(files)
        if not self.assert_runtime_or_parsed(report, files): return
        self.assertTrue(any(e['reference'] == 'orders.absent_value' and e['status'] == 'unresolved'
                            for e in report['dependencies']))
        self.assertNotEqual(report['status'], 'inspected')

    def test_duplicate_view_identity_and_field_identity_are_invalid(self):
        variants = [
            {'orders.view': b'dimensions:\n  id: {}\n',
             'subdir/orders.query.view': b'query:\n  base_view: missing\n  fields:\n    missing.id: id\n'},
            {'orders.view': b'dimensions:\n  shared_name: {}\nmeasures:\n  shared_name:\n    aggregate_type: count\n'}]
        for files in variants:
            with self.subTest(files=list(files)):
                report = inventory.inspect_model(files)
                if not self.assert_runtime_or_parsed(report, files): continue
                self.assertEqual(report['status'], 'invalid')
                self.assertTrue(any('duplicate_identity' in f['code'] for f in report['findings']))

    def test_query_output_alias_collisions_are_invalid(self):
        files = self.files('modeled_query_view')
        files['orders_by_customer.query.view'] = files['orders_by_customer.query.view'].replace(
            b'orders.paid_order_count: paid_order_count', b'orders.paid_order_count: order_count')
        report = inventory.inspect_model(files)
        if not self.assert_runtime_or_parsed(report, files): return
        self.assertEqual(report['status'], 'invalid')
        self.assertIn('query.output_collision', {f['code'] for f in report['findings']})

    def test_extends_query_and_self_field_cycles_are_invalid(self):
        variants = [
            {'a.view': b'extends: [b]\n', 'b.view': b'extends: [a]\n'},
            {'a.query.view': b'query:\n  base_view: b\n  fields:\n    b.id: id\ndimensions:\n  id: {}\n',
             'b.query.view': b'query:\n  base_view: a\n  fields:\n    a.id: id\ndimensions:\n  id: {}\n'},
            {'a.view': b'dimensions:\n  loop:\n    sql: ${loop}\n'}]
        for files in variants:
            with self.subTest(files=list(files)):
                report = inventory.inspect_model(files)
                if not self.assert_runtime_or_parsed(report, files): continue
                self.assertEqual(report['status'], 'invalid')
                self.assertTrue(report['cycles'])
                self.assertIn('dependency.cycle', {f['code'] for f in report['findings']})

    def test_noop_patch_preserves_opaque_and_authored_bytes_with_no_runtime_requirement(self):
        authored = self.scope_files('authored')
        authored['future.view'] = (CORPUS / 'source/opaque/future.view').read_bytes()
        effective = self.scope_files('effective')
        before = copy.deepcopy((authored, effective))
        proposal = inventory.propose_patch(authored, effective, [])
        self.assertEqual(proposal['status'], 'no_op')
        self.assertEqual(proposal['diff'], [])
        self.assertEqual(proposal['explicit_deletions'], [])
        self.assertEqual(inventory.decode_files(proposal['candidate_files']), authored)
        self.assertEqual(before, (authored, effective))

    def test_label_patch_changes_only_authored_value_without_materializing_inheritance(self):
        authored, effective = self.scope_files('authored'), self.scope_files('effective')
        target = self.expected['scope']['patch_request']
        proposal = self.propose_or_runtime_error(authored, effective,
            [self.edit(authored, target['path'], target['value'])])
        if proposal is None: return
        candidate = inventory.decode_files(proposal['candidate_files'])
        expected = inventory.yaml.safe_load((CORPUS / self.expected['scope']['expected_authored_patch_file']).read_text())
        self.assertEqual(inventory.yaml.safe_load(candidate['orders.view']), expected)
        self.assertTrue(candidate['orders.view'].startswith(b'# This branch owns only a presentation override.\n'))
        self.assertEqual(set(candidate), {'orders.view'})
        self.assertEqual(proposal['diff'][0]['origin'], 'authored')
        self.assertFalse(proposal['applied'])
        self.assertFalse(proposal['deployment_authorized'])
        self.assertFalse(proposal['deletion_authorized'])

    def test_effective_only_equal_value_is_noop_and_changed_value_creates_minimal_override(self):
        effective = self.scope_files('effective')
        same = self.propose_or_runtime_error({}, effective, [self.edit({}, '/label', 'Order review')])
        if same is None: return
        self.assertEqual(same['status'], 'no_op')
        self.assertEqual(inventory.decode_files(same['candidate_files']), {})
        changed = inventory.propose_patch({}, effective, [self.edit({}, '/label', 'New presentation')])
        candidate = inventory.decode_files(changed['candidate_files'])
        self.assertEqual(inventory.yaml.safe_load(candidate['orders.view']), {'label': 'New presentation'})
        self.assertEqual(changed['diff'][0]['origin'], 'new_authored_override')

    def test_explicit_file_deletion_is_only_a_hash_bound_proposal(self):
        authored, effective = self.scope_files('authored'), self.scope_files('effective')
        proposal = inventory.propose_patch(authored, effective, [], explicit_deletions=[{
            'path': 'orders.view', 'expected_sha256': self.frozen['source/scopes/authored/orders.view']}])
        self.assertEqual(inventory.decode_files(proposal['candidate_files']), {})
        self.assertEqual(proposal['explicit_deletions'], self.expected['scope']['explicit_deletion_case']['expected_plan_deletions'])
        self.assertTrue(proposal['diff'][0]['effective_definition_may_remain'])
        self.assertFalse(proposal['applied'])
        self.assertFalse(proposal['deletion_authorized'])
        self.assertEqual(authored, self.scope_files('authored'))
        with self.assertRaises(inventory.InventoryError):
            inventory.propose_patch({}, effective, [], explicit_deletions=[{'path': 'orders.view', 'expected_sha256': None}])

    def test_changed_authored_bytes_stale_hash_and_overlapping_edits_are_refused(self):
        authored = self.scope_files('authored')
        stale = self.edit(authored, '/label', 'new label'); stale['expected_sha256'] = '0' * 64
        with self.assertRaises(inventory.InventoryError):
            inventory.propose_patch(authored, {}, [stale])
        edits = [self.edit(authored, '/label', 'first change'), self.edit(authored, '/label', 'second change')]
        if inventory.yaml is None:
            self.propose_or_runtime_error(authored, {}, edits)
        else:
            with self.assertRaises(inventory.InventoryError) as caught:
                inventory.propose_patch(authored, {}, edits)
            self.assertEqual(str(caught.exception), 'patch.overlapping_edits')

    def test_pointer_escape_and_nonmapping_path_boundaries(self):
        authored = {'orders.view': b'label: Original\ntags: [one, two]\n'}
        for pointer in ('/', '', '/tags/0', '/label/child', '/bad~2key'):
            with self.subTest(pointer=pointer), self.assertRaises(inventory.InventoryError):
                inventory.propose_patch(authored, {}, [self.edit(authored, pointer, 'new')])

    def test_replacing_value_keeps_unrelated_comments_and_crlf(self):
        authored = {'orders.view': b'# before\r\nlabel: Old\r\n# after\r\ndescription: Keep exactly\r\n'}
        proposal = self.propose_or_runtime_error(authored, {}, [self.edit(authored, '/label', 'Changed')])
        if proposal is None: return
        output = inventory.decode_files(proposal['candidate_files'])['orders.view']
        self.assertTrue(output.startswith(b'# before\r\n'))
        self.assertTrue(output.endswith(b'\r\n# after\r\ndescription: Keep exactly\r\n'))
        self.assertEqual(output.count(b'\r\n'), authored['orders.view'].count(b'\r\n'))

    def test_malformed_context_expectation_and_patch_values_have_stable_errors(self):
        files = self.files('authorization_noops')
        for context in ([], {'scope': []}, {'scope': {'model_id': [], 'layer': {}, 'branch_id': None, 'workbook_id': None}}):
            with self.subTest(context=context), self.assertRaises(inventory.InventoryError):
                inventory.inspect_model(files, context)
        for edits in ({}, None, [{'path': [], 'pointer': '/label', 'value': {}, 'expected_sha256': None}]):
            with self.subTest(edits=edits), self.assertRaises(inventory.InventoryError):
                inventory.propose_patch(files, {}, edits)

    def test_cli_refuses_symlinked_request_ancestor_without_writing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); inputs = root / 'inputs'; inputs.mkdir()
            request = inputs / 'request.json'
            request.write_text(json.dumps({'files': {'orders.view': 'dimensions:\n  id: {}\n'}}))
            linked = root / 'alias'; linked.symlink_to(inputs, target_is_directory=True)
            output = root / 'inventory.json'; captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                result = inventory.main(['inspect', '--request', str(linked / 'request.json'), '--output', str(output)])
            self.assertEqual(result, 2, captured.getvalue())
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Export bounded, design-only domain reviews from one retained canonical state.

No repository scan, source execution, approval, or implementation registration.
Existing JSON, package, disclosure and archive limits remain unchanged.
"""
import argparse
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

from ae_common import _json_bytes, hash_json, load_json, require, MAX_JSON_BYTES
import delivery_portal as portal

QUALIFICATION = ('Design-only partition of a retained canonical snapshot. Shared dependencies may repeat; '
    'boundary references have no included definition. Registered implementation artifacts remain in their '
    'original delivery. Inventory accounting and file integrity do not establish source completeness, '
    'native validation, business acceptance or refactor completion.')


def plan_partitions(state, max_owned_models=None):
    """Pure projection: one owner partition per entity; no object/edge truncation."""
    from engagement_stages import closure, validate_design
    from design_consistency import project_review
    doc = state.get('workflow', {}).get('design')
    require(isinstance(doc, dict), 'Import a canonical design before partition export')
    require(max_owned_models is None or type(max_owned_models) is int and 1 <= max_owned_models <= portal.MAX_REVIEW_ITEMS,
            'max_owned_models must be an integer from 1 to the existing review item bound')
    validate_design(copy.deepcopy({k: v for k, v in doc.items() if k != 'sha256'}))
    require(doc.get('sha256') == hash_json({k: v for k, v in doc.items() if k != 'sha256'}), 'Canonical design hash differs')
    projected = project_review(doc)
    models = {row['id']: row for row in projected['models']}
    graph = {key: row.get('depends_on', []) for key, row in models.items()}
    groups = {}
    for row in models.values():
        groups.setdefault(row['domain'], []).append(row['id'])
    require(len(groups) <= 256, 'Domain count exceeds export bound; select a reviewed design scope')
    edges = [{'id': 'relationship-' + str(i + 1).zfill(6), 'source_sha256': hash_json(edge),
              'relationship': copy.deepcopy(edge), 'partitions': []}
             for i, edge in enumerate(projected['relationships'])]
    partitions, owners, scopes = [], {}, []
    for number, domain in enumerate(sorted(groups)):
        ordered = sorted(groups[domain]); size = max_owned_models or len(ordered)
        scopes.extend((number, domain, offset // size + 1, ordered[offset:offset + size]) for offset in range(0, len(ordered), size))
    require(len(scopes) <= 256, 'Partition count exceeds export bound; select a reviewed canonical scope')
    for number, domain, batch_index, owned_ids in scopes:
        key = 'domain-' + str(number + 1).zfill(3) + '-' + hashlib.sha256(domain.encode()).hexdigest()[:10]
        batch = {'batch_index': batch_index, 'batch_size': max_owned_models} if max_owned_models else {}
        if batch:
            key += '-batch-' + str(batch_index).zfill(3)
        owned = set(owned_ids); included = set(closure(graph, owned))
        for identifier in owned:
            require(identifier not in owners, 'Entity has more than one owning partition')
            owners[identifier] = key
        internal, boundary, internal_ids, boundary_ids = [], [], [], []
        for record in edges:
            endpoints = {record['relationship']['from'], record['relationship']['to']}
            if not endpoints & included:
                continue
            category = 'internal' if endpoints <= included else 'boundary'
            (internal if category == 'internal' else boundary).append(copy.deepcopy(record['relationship']))
            (internal_ids if category == 'internal' else boundary_ids).append(record['id'])
            record['partitions'].append({'id': key, 'role': category})
        references = sorted({edge[end] for edge in boundary for end in ('from', 'to')} - included)
        selected = [copy.deepcopy(models[key]) for key in sorted(included)]
        asset_ids = {key for row in selected for key in row.get('asset_ids', [])}
        review = {'schema_version': 1, 'title': domain + ' · design review', 'description': QUALIFICATION,
                  'source_fingerprint': portal.source_fingerprint(state), 'context_sha256': portal.context_fingerprint(state),
                  'target': {key: state.get('answers', {}).get(key) for key in ('framework', 'warehouse')},
                  'design_binding': projected['design_binding'], 'models': selected, 'relationships': internal,
                  'assets': [{k: row[k] for k in ('id', 'name', 'kind', 'mapping_status') if k in row}
                             for row in projected['assets'] if row['id'] in asset_ids],
                  'artifacts': [], 'validation': [], 'changes': [], 'decisions': [],
                  'partition': {'kind': 'domain_design_review', 'domain': domain, **batch,
                                'owned_model_ids': sorted(owned), 'shared_dependency_ids': sorted(included - owned)}}
        if boundary:
            review['domain_proposals'] = [{'id': key + '-boundary', 'domain': domain,
                'model_ids': sorted(owned), 'relationships': boundary,
                'reference_endpoints': [{'id': identifier, 'name': models[identifier]['name']} for identifier in references]}]
        portal.validate_review(state, review)
        require(len(_json_bytes(review)) <= MAX_JSON_BYTES,
                'Domain review JSON exceeds the existing limit; select a reviewed smaller domain or batch without dropping dependencies')
        partitions.append({'id': key, 'domain': domain, **batch, 'owned_model_ids': sorted(owned),
            'shared_dependency_ids': sorted(included - owned), 'reference_ids': references,
            'internal_relationship_ids': internal_ids, 'boundary_relationship_ids': boundary_ids, 'review': review})
    require(set(owners) == set(models) and all(row['partitions'] for row in edges), 'Partition inventory accounting failed')
    index = {'schema_version': 1, 'kind': 'domain_design_review_index', 'qualification': QUALIFICATION,
             'partitioning': {'method': 'domain_sorted_entity_ids', 'max_owned_models': max_owned_models},
             'source_fingerprint': portal.source_fingerprint(state), 'context_sha256': portal.context_fingerprint(state),
             'design_binding': projected['design_binding'], 'state_sha256': state.get('state_sha256'),
             'entities': [{'id': key, 'owner_partition': owners[key], 'source_sha256': hash_json(row),
                           'included_partitions': [p['id'] for p in partitions if key in p['owned_model_ids'] + p['shared_dependency_ids']]}
                          for key, row in sorted(models.items())],
             'relationships': edges,
             'dependencies': [{'from': parent, 'to': key} for key in sorted(graph) for parent in sorted(graph[key])],
             'partitions': [], 'files': []}
    return {'index': index, 'partitions': partitions}


def _write(root, relative, content):
    """The same content scanner checks each standalone output before publication."""
    portal._check_disclosure_bytes(content, relative)
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {'path': relative, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}


def _published_review(state, review, payload, audience):
    for field in ('models', 'relationships', 'domain_proposals', 'assets'):
        require(payload['review'].get(field, []) == review.get(field, []),
                'Disclosure projection differs from complete partition accounting; use an explicitly reviewed smaller canonical scope')
    result = {k: v for k, v in review.items() if k != 'disclosure'}
    portal._check_share_policy(state, review, [], result, audience)
    return result


def export_domains(state, output, *, run_dir, audience='reviewer', disclosure=None, max_owned_models=None):
    """Publish into an exclusively created directory; failure preserves other outputs."""
    require(audience in {'reviewer', 'engineer'}, 'Domain design reviews support reviewer or engineer audiences')
    output = portal._path(output)
    require(output.parent.is_dir() and not output.exists(), 'Choose a new output directory with an existing parent')
    protected = [portal._path(run_dir)]
    if state.get('workflow', {}).get('artifact_root'):
        protected.append(portal._path(state['workflow']['artifact_root']))
    for attempt in state.get('operations', {}).get('attempts', []):
        if attempt.get('artifact_root'):
            protected.append(portal._path(attempt['artifact_root']))
    require(all(output != root and output not in root.parents and root not in output.parents for root in protected),
            'Domain delivery must be separate from retained run and candidate artifact directories')
    if state.get('inputs', {}).get('source', {}).get('path'):
        from source_roots import ensure_output
        ensure_output(state, output)
    planned = plan_partitions(state, max_owned_models)
    index = planned['index']
    from finalize_delivery import _directory_identity, _remove_owned_directory
    parent_identity = _directory_identity(output.parent)
    # Generate fully before exclusive publication. No state is changed.
    with tempfile.TemporaryDirectory(prefix='.domain-review-', dir=output.parent) as folder:
        staging = Path(folder).resolve()
        for partition in planned['partitions']:
            key, review = partition['id'], partition['review']
            if disclosure is not None:
                review['disclosure'] = copy.deepcopy(disclosure)
            directory = staging / key; directory.mkdir()
            archive_path = directory / 'delivery.zip'
            try:
                portal.package_delivery(state, review, directory, archive_path, audience,
                                        ['documentation', 'dictionary', 'diagrams'])
                portal.verify_delivery(archive_path)
                with zipfile.ZipFile(archive_path) as archive:
                    page = archive.read('START_HERE.html')
                    from portal_checks import parse_page
                    _, payload = parse_page(page.decode())
                    published_review = _published_review(state, review, payload, audience)
                    files = [_write(staging, key + '/review.json', _json_bytes(published_review))]
                    # The ZIP has been verified; retain every safe member so
                    # HTML navigation and relative document/image links work.
                    for name in sorted(archive.namelist()):
                        relative = portal._relative(name).as_posix()
                        require(relative not in {'review.json', 'delivery.zip'}, 'Partition output name collides')
                        files.append(_write(staging, key + '/' + relative, archive.read(name)))
                body = archive_path.read_bytes()
                files.append({'path': key + '/delivery.zip', 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
            except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
                raise ValueError('Domain partition ' + key + ' could not be exported under unchanged safety bounds: ' + str(error) +
                    '. Retain this canonical design; select a smaller reviewed domain/batch with its complete shared dependencies. No partial delivery was published.') from error
            index['partitions'].append({k: v for k, v in partition.items() if k != 'review'} | {
                'review_sha256': hash_json(published_review), 'entrypoint': key + '/START_HERE.html', 'zip': key + '/delivery.zip'})
            index['files'].extend(files)
        rows = ''.join('<li><a href="' + html.escape(p['entrypoint'], quote=True) + '">' + html.escape(p['domain']) +
            (' · review batch ' + str(p['batch_index']) if 'batch_index' in p else '') +
            '</a> — ' + str(len(p['owned_model_ids'])) + ' owned objects; ' + str(len(p['shared_dependency_ids'])) +
            ' shared dependencies; <a href="' + html.escape(p['zip'], quote=True) + '">portable ZIP</a></li>' for p in index['partitions'])
        page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>Domain design review index</title><style>body{font:18px/1.6 system-ui,sans-serif;margin:40px;color:#18324a;background:#f4f7fb}main{max-width:1100px;margin:auto}li{margin:16px 0}a{color:#185b72}</style><body><main><h1>Domain design reviews</h1><p>' + html.escape(QUALIFICATION) +
                '</p><p>' + str(len(index['entities'])) + ' owned objects and ' + str(len(index['relationships'])) +
                ' declared relationship occurrences are accounted for in <a href="PARTITION_INDEX.json">the index</a>.</p><ul>' + rows + '</ul></main></body></html>').encode()
        index['files'].append(_write(staging, 'START_HERE.html', page))
        manifest = _json_bytes(index)
        require(len(manifest) <= MAX_JSON_BYTES, 'Partition index exceeds the existing JSON limit; retain a smaller reviewed canonical scope')
        # Index metadata is a disclosure surface too. Scan-only is insufficient
        # when the saved engagement requires a governed share policy.
        portal._check_share_policy(state, {'disclosure': disclosure or {}}, [], index, audience)
        _write(staging, 'PARTITION_INDEX.json', manifest)
        require(_directory_identity(output.parent) == parent_identity, 'Output parent changed during generation')
        require(not output.exists(), 'Output appeared during export; choose a new output directory')
        output.mkdir(mode=0o700)
        output_identity = _directory_identity(output)
        try:
            for path in sorted(staging.iterdir()):
                require(_directory_identity(output) == output_identity, 'Output directory changed during publication')
                os.rename(path, output / path.name)
        except (OSError, ValueError):
            _remove_owned_directory(output, output_identity)
            raise
    return {'entrypoint': str(output / 'START_HERE.html'), 'index': str(output / 'PARTITION_INDEX.json'),
            'packages': [str(output / row['zip']) for row in index['partitions']],
            'entity_count': len(index['entities']), 'relationship_count': len(index['relationships']), 'qualification': QUALIFICATION}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, help='Retained engagement state.json; no new repository assessment')
    parser.add_argument('--output', required=True, help='New directory for the index and separate domain packages')
    parser.add_argument('--audience', choices=['reviewer', 'engineer'], default='reviewer')
    parser.add_argument('--disclosure', help='Existing reviewed disclosure contract; required by governed scope')
    parser.add_argument('--max-owned-models', type=int, help='Explicit presentation batch size per domain; sorted entity IDs and full dependency closure are retained')
    args = parser.parse_args(argv)
    try:
        from guided_workflow import load_engagement
        state_path = portal._path(args.state)
        require(state_path.name == 'state.json', 'Supply the retained engagement state.json')
        result = export_domains(load_engagement(state_path.parent), args.output, run_dir=state_path.parent, audience=args.audience,
                                disclosure=load_json(args.disclosure) if args.disclosure else None,
                                max_owned_models=args.max_owned_models)
        print(json.dumps(result, indent=2)); return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('Domain review export blocked: ' + str(error), file=sys.stderr); return 2


if __name__ == '__main__':
    raise SystemExit(main())

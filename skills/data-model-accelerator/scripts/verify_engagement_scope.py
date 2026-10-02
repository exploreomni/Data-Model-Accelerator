"""Verify declared engagement coverage without parsing or executing source code.

Source revisions are ae_common.snapshot byte-inventory hashes, not Git refs.
Node paths and dependency edges are host/specialist declarations: complete file
accounting does not prove complete semantic discovery or correct exclusions.
"""
import argparse
from collections import deque
from pathlib import Path
import sys

from ae_common import hash_file, hash_json, require, safe_relative, snapshot, write_json
from freeze_benchmark import _bound_json, _fields, _sha, _text
from verify_dbt_evidence import IGNORED_DIRS

NODE_KINDS = {'model', 'source', 'semantic', 'report', 'support'}
CONSUMER_KINDS = {'semantic', 'report'}
DISPOSITIONS = {'migrate', 'retire', 'defer'}


def _unique_list(value, label, validator, nonempty=False):
    require(type(value) is list and (value or not nonempty), label + ' must be a list' + (' with at least one item' if nonempty else ''))
    items = [validator(item) for item in value]
    require(len(items) == len(set(items)), 'Duplicate ' + label)
    return sorted(items)


def _closure(start, edges):
    found, pending = set(start), list(start)
    while pending:
        for node_id in edges[pending.pop()]:
            if node_id not in found:
                found.add(node_id)
                pending.append(node_id)
    return found


def _acyclic(parents, children):
    counts = {node_id: len(dependencies) for node_id, dependencies in parents.items()}
    pending = deque(node_id for node_id, count in counts.items() if count == 0)
    visited = 0
    while pending:
        visited += 1
        for node_id in children[pending.popleft()]:
            counts[node_id] -= 1
            if counts[node_id] == 0:
                pending.append(node_id)
    require(visited == len(parents), 'Dependency graph contains a cycle')


def verify(contract_path, source_project):
    """Return a deterministic coverage report for a byte-bound source snapshot.

    Malformed contracts, unresolved references, invalid paths, cycles and drift
    raise ValueError. Valid declarations with incomplete coverage or unresolved
    consumer dispositions return passed=False and actionable errors.
    """
    contract, contract_sha256 = _bound_json(contract_path)
    _fields(contract, ('schema_version', 'kind', 'source_revision', 'nodes',
                       'selected_nodes', 'exclusions', 'consumers'))
    require(type(contract['schema_version']) is int and contract['schema_version'] == 1,
            'Unsupported engagement scope version')
    require(contract['kind'] == 'engagement_scope', 'Invalid engagement scope kind')
    source_revision = _sha(contract['source_revision'])
    source = snapshot(source_project)
    require(source['sha256'] == source_revision, 'Source revision drift: scope contract does not match source snapshot')
    source_paths = {entry['path'] for entry in source['files']}

    require(type(contract['nodes']) is list and contract['nodes'], 'nodes must be a nonempty list')
    nodes, covered_paths = {}, set()
    for entry in contract['nodes']:
        _fields(entry, ('id', 'kind', 'paths', 'depends_on'))
        node_id = _text(entry['id'], 'node ID')
        require(node_id not in nodes, 'Duplicate node ID: ' + node_id)
        require(type(entry['kind']) is str and entry['kind'] in NODE_KINDS, 'Invalid node kind: ' + node_id)
        paths = _unique_list(entry['paths'], 'node paths', safe_relative, nonempty=True)
        require(set(paths) <= source_paths, 'Node paths missing from source snapshot: ' + ', '.join(sorted(set(paths) - source_paths)))
        dependencies = _unique_list(entry['depends_on'], 'dependency IDs', lambda value: _text(value, 'dependency ID'))
        nodes[node_id] = {'id': node_id, 'kind': entry['kind'], 'paths': paths, 'depends_on': dependencies}
        covered_paths.update(paths)

    parents = {node_id: set(entry['depends_on']) for node_id, entry in nodes.items()}
    children = {node_id: set() for node_id in nodes}
    for node_id, dependencies in parents.items():
        require(dependencies <= set(nodes), 'Unresolved dependency IDs for ' + node_id + ': ' + ', '.join(sorted(dependencies - set(nodes))))
        for dependency in dependencies:
            children[dependency].add(node_id)
    _acyclic(parents, children)
    selected = _unique_list(contract['selected_nodes'], 'selected node IDs', lambda value: _text(value, 'selected node ID'), nonempty=True)
    require(set(selected) <= set(nodes), 'Unresolved selected node IDs: ' + ', '.join(sorted(set(selected) - set(nodes))))

    require(type(contract['exclusions']) is list, 'exclusions must be a list')
    exclusions = {}
    for entry in contract['exclusions']:
        _fields(entry, ('path', 'reason'))
        path = safe_relative(entry['path'])
        require(path not in exclusions, 'Duplicate exclusion path: ' + path)
        require(path in source_paths, 'Excluded path missing from source snapshot: ' + path)
        require(path not in covered_paths, 'Exclusion overlaps a node path: ' + path)
        exclusions[path] = _text(entry['reason'], 'exclusion reason')

    affected = _closure(selected, children)
    affected_consumers = {node_id for node_id in affected if nodes[node_id]['kind'] in CONSUMER_KINDS}
    required_nodes = _closure(affected, parents)
    require(type(contract['consumers']) is list, 'consumers must be a list')
    consumers = {}
    for entry in contract['consumers']:
        _fields(entry, ('node_id', 'disposition', 'reason'))
        node_id = _text(entry['node_id'], 'consumer node ID')
        require(node_id not in consumers, 'Duplicate consumer disposition: ' + node_id)
        require(node_id in nodes, 'Unresolved consumer node ID: ' + node_id)
        require(nodes[node_id]['kind'] in CONSUMER_KINDS, 'Consumer must be a semantic or report node: ' + node_id)
        require(type(entry['disposition']) is str and entry['disposition'] in DISPOSITIONS, 'Invalid consumer disposition: ' + node_id)
        consumers[node_id] = dict(entry, reason=_text(entry['reason'], 'consumer reason'))

    errors = []
    omitted = source_paths - covered_paths - set(exclusions)
    if omitted:
        errors.append('Account for source files with node paths or explicit exclusions: ' + ', '.join(sorted(omitted)))
    missing = affected_consumers - set(consumers)
    if missing:
        errors.append('Declare a disposition for every affected semantic/report consumer: ' + ', '.join(sorted(missing)))
    extra = set(consumers) - affected_consumers
    if extra:
        errors.append('Remove dispositions for unaffected consumers or correct the declared graph/selection: ' + ', '.join(sorted(extra)))
    for node_id in sorted(affected_consumers & set(consumers)):
        if consumers[node_id]['disposition'] == 'defer':
            errors.append('Resolve deferred consumer ' + node_id + ' before proceeding (declare migrate or retire with reviewed rationale): ' + consumers[node_id]['reason'])

    normalized = dict(contract, nodes=[nodes[node_id] for node_id in sorted(nodes)],
                      selected_nodes=selected,
                      exclusions=[{'path': path, 'reason': exclusions[path]} for path in sorted(exclusions)],
                      consumers=[consumers[node_id] for node_id in sorted(consumers)])
    require(snapshot(source_project) == source, 'Source snapshot changed during scope verification')
    require(hash_file(contract_path) == contract_sha256, 'Scope contract changed during verification')
    return {
        'schema_version': 1, 'kind': 'engagement_scope_verification',
        'passed': not errors, 'source_revision': source_revision,
        'contract_sha256': contract_sha256, 'normalized_scope_sha256': hash_json(normalized),
        'selected_nodes': selected, 'required_nodes': sorted(required_nodes),
        'affected_nodes': sorted(affected), 'affected_consumers': sorted(affected_consumers),
        'consumer_dispositions': normalized['consumers'],
        'required_paths': sorted({path for node_id in required_nodes for path in nodes[node_id]['paths']}),
        'source_file_count': len(source_paths), 'accounted_file_count': len(source_paths - omitted),
        'exclusions': normalized['exclusions'], 'errors': errors,
        'limitations': [
            'Paths, dependency edges, node classifications and exclusions are host/specialist declarations; file accounting is not parser proof of semantic or graph completeness.',
            'Coverage uses ae_common.snapshot; generated/environment directories excluded by that helper: ' + ', '.join(sorted(IGNORED_DIRS)) + '.',
            'Migrate/retire dispositions record declared decisions only; typed authority and final approval require the separate authority stage.',
            'No source code, SQL, hooks or credentials are executed or connected; this report does not establish warehouse, Omni or production acceptance.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', required=True)
    parser.add_argument('--source-project', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        project = Path(args.source_project).absolute()
        output = Path(args.output).absolute()
        require(not output.is_relative_to(project), 'Scope report output must remain outside the source project')
        report = verify(args.contract, project)
        write_json(output, report)
        print('PASS' if report['passed'] else 'FAIL')
        return 0 if report['passed'] else 1
    except (ValueError, OSError, TypeError, KeyError) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

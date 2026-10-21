"""Inspect or export scoped migration planning; no network calls or ticket writes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from ae_common import hash_json, require, safe_relative


def inspect(state, action, domain_id=None, max_bytes=32768, budget_reason=None, record_ids=None):
    import migration_planning as planning
    require(action in {'summary', 'context'}, 'Unknown planning inspection')
    if action == 'context':
        require(type(domain_id) is str and domain_id.strip(), 'Select one planning domain')
        require(type(max_bytes) is int and 1024 <= max_bytes <= 65536, 'Packet limit must be 1024..65536 bytes')
        require(max_bytes <= 32768 or type(budget_reason) is str and budget_reason.strip(),
                'A larger packet needs an explicit budget reason')
        return planning.context_packet(state, domain_id, max_bytes=max_bytes, record_ids=record_ids)
    require(record_ids is None, 'Record partitions apply only to context')
    result = planning.public_summary(state)
    if result is not None and domain_id:
        result['domains'] = [d for d in result['domains'] if d['domain_id'] == domain_id]
        require(result['domains'], 'Planning domain is not configured')
    return result


def export(state, output, domain_id=None):
    from guided_workflow import _path, _outside
    from migration_plan_exports import export_files
    summary = inspect(state, 'summary', domain_id)
    require(summary and summary['domains'], 'Configure and record a migration plan before exporting')
    require(all(d.get('plan_sha256') for d in summary['domains']),
            'Some selected domains have no plan; select a recorded domain or record the missing drafts')
    destination = _path(output)
    _outside(destination, _path(state['inputs']['source']['path']))
    require(not destination.exists() and destination.parent.is_dir(), 'Use a new export directory with an existing parent')
    files = export_files(summary)
    require(files, 'No planning artifacts were produced')
    seen = set()
    records = []
    with tempfile.TemporaryDirectory(prefix='.migration-plan-', dir=destination.parent) as temporary:
        root = Path(temporary)
        for row in files:
            relative = safe_relative(row['path'])
            require(row['path'].startswith('05_Migration/') and row['path'].casefold() not in seen,
                    'Planning export path is unsafe or duplicated')
            seen.add(row['path'].casefold())
            require(type(row['content']) is bytes and len(row['content']) <= 5 * 1024 * 1024,
                    'Planning file must be bounded bytes; partition the selected domain')
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(row['content']); path.chmod(0o600)
            records.append({'path': row['path'], 'sha256': hashlib.sha256(row['content']).hexdigest(),
                            'bytes': len(row['content']), 'domain_id': row['domain_id']})
        require(sum(r['bytes'] for r in records) <= 50 * 1024 * 1024, 'Planning export exceeds total size limit')
        # Exclusive directory creation prevents overwriting a prior or human-edited export.
        destination.mkdir(mode=0o700)
        try:
            for entry in root.iterdir():
                shutil.move(str(entry), str(destination / entry.name))
        except Exception:
            shutil.rmtree(destination)
            raise
    return {'kind': 'migration_planning_export', 'schema_version': 1, 'files': records,
            'snapshot_sha256': hash_json(summary), 'external_writes': False,
            'qualification': 'Local planning artifacts only. Google payloads are pending host creation; '
                             'ticket imports, native validation, business acceptance and deployment were not performed.'}


def main(argv=None):
    from guided_workflow import load_engagement, _path, _outside
    from omni_native import _private_file
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('summary', 'context', 'export'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--domain')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-bytes', type=int, default=32768)
    parser.add_argument('--budget-reason')
    parser.add_argument('--record', action='append', dest='record_ids')
    args = parser.parse_args(argv)
    state = load_engagement(args.run)
    destination, run = _path(args.output), _path(args.run)
    _outside(destination, _path(state['inputs']['source']['path']))
    _outside(destination, run)
    if args.action == 'export':
        require(args.record_ids is None, 'Export the selected complete domain; context partitions are not exports')
        result = export(state, destination, args.domain)
        print(json.dumps(result, indent=2))
    else:
        result = inspect(state, args.action, args.domain, args.max_bytes, args.budget_reason, args.record_ids)
        _private_file(destination, {'schema_version': 1, 'kind': 'migration_planning_inspection',
                      'engagement_id': state['engagement_id'], 'action': args.action,
                      'domain_id': args.domain, 'result_sha256': hash_json(result), 'result': result,
                      'qualification': 'Local retained evidence only; route through agent-input disclosure before dispatch.'})
        print('Planning inspection saved. No source scan or external write performed.')
    return 0


if __name__ == '__main__':
    main()

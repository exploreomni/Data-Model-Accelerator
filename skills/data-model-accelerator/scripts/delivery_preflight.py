"""Early delivery diagnostics. Missing evidence never grants or removes draft authority."""
import argparse
import json
from pathlib import Path


def assess(state, review=None, artifact_root=None, audience=None, include=None):
    from delivery_portal import AUDIENCES, SUFFIXES, _native_omni_artifact, resolve_selection
    from sensitive_data import MAX_BYTES
    from ae_common import require
    audience = audience or state.get('answers', {}).get('audience') or 'engineer'
    require(audience in AUDIENCES, 'Unknown delivery audience')
    selected = resolve_selection(state, audience, include)
    review = review or {}
    rows = [r for r in review.get('artifacts', []) if r.get('category') in selected
            and audience in r.get('audiences', [])]
    issues, sizes = [], []
    for row in rows:
        path = Path(row['path'])
        if path.suffix.lower() not in SUFFIXES and not _native_omni_artifact(path):
            issues.append({'code': 'unsupported_format', 'artifact_id': row['id'],
                           'action': 'Choose a supported export before authoring the delivery.'})
        if artifact_root:
            from delivery_portal import _relative, _path
            source = _path(Path(artifact_root) / str(_relative(row['path'])), _path(artifact_root))
            size = source.stat().st_size if source.is_file() else None
            sizes.append({'artifact_id': row['id'], 'bytes': size})
            if size is None or size > MAX_BYTES:
                issues.append({'code': 'missing_file' if size is None else 'partition_document',
                               'artifact_id': row['id'],
                               'action': 'Register the file or partition this document within the scanner limit.'})
    disclosure = review.get('disclosure', {})
    if state.get('answers', {}).get('migration_scope'):
        missing = [row['id'] for row in rows if row['id'] not in disclosure.get('artifacts', {})]
        if (disclosure.get('audience') != audience or not disclosure.get('policy')
                or not disclosure.get('presentation') or missing):
            issues.append({'code': 'disclosure_context_required', 'artifact_ids': missing,
                'action': 'Supply the audience policy and classifications before final export. A clean scan does not establish sharing approval.'})
    catalogue = state.get('inputs', {}).get('catalogue') or {}
    from run_efficiency import summarize
    return {'schema_version': 1, 'kind': 'delivery_preflight',
        'status': 'needs_delivery_context' if issues else 'ready_for_final_checks',
        'audience': audience, 'selected_categories': sorted(selected),
        'target': state.get('inputs', {}).get('target', {}),
        'source_roles': state.get('answers', {}).get('source_roles',
                        state.get('workflow', {}).get('migration_intents', {})),
        'formats': sorted({Path(r['path']).suffix.lower() for r in rows}),
        'artifact_count': len(rows), 'artifact_sizes': sizes,
        'selected_bytes': sum(r['bytes'] or 0 for r in sizes),
        'model_count': len(review.get('models', [])),
        'partition_recommended': len(review.get('models', [])) > 100 or len(rows) > 200,
        'physical_catalogue': 'captured_not_verified' if catalogue.get('available') else 'not_supplied',
        'run_efficiency': summarize(state),
        'issues': issues,
        'qualification': 'Early planning only. Draft generation remains available through its existing request workflow. Final export checks exact bytes; validation and approval remain separate.'}


def completion(state, checkpoint=False):
    return {'artifact_delivery': 'incomplete_checkpoint' if checkpoint else
            'provisional_delivery_complete' if not state.get('readiness', {}).get('generation_ready') else 'selected_files_complete',
            'native_validation': 'not_established_by_packaging',
            'business_approval': 'not_established_by_packaging', 'deployment_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--review')
    parser.add_argument('--artifacts')
    parser.add_argument('--audience')
    args = parser.parse_args()
    from guided_workflow import load_engagement
    from ae_common import load_json
    report = assess(load_engagement(args.run_dir), load_json(args.review) if args.review else None,
                    args.artifacts, args.audience)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Read-only, scoped readiness projection; never an approval or execution gate."""
import copy

from ae_common import hash_json
from design_builder import counts
from design_consistency import assess_design
from design_coverage import summarize as coverage_summary
from design_evidence import summarize as evidence_summary, review_summary


def summarize(state, selected=None):
    doc = state.get('workflow', {}).get('design') or {}
    models = doc.get('entities', [])
    scope = set(selected) if selected is not None else {e['id'] for e in models}
    # Assess only disclosed objects and internal edges; count boundary interfaces
    # as objects if and only if the package actually includes them.
    integrity_mismatch = 'sha256' in doc and doc['sha256'] != hash_json({k: v for k, v in doc.items() if k != 'sha256'})
    scoped = copy.deepcopy(doc)
    scoped.pop('sha256', None)  # A derived subset is not the original hashed document.
    scoped['entities'] = [copy.deepcopy(e) for e in models if e['id'] in scope]
    for entity in scoped['entities']:
        entity['depends_on'] = [p for p in entity['depends_on'] if p in scope]
    scoped['relationships'] = [r for r in doc.get('relationships', []) if {r['from'], r['to']} <= scope]
    scoped['decisions'] = [d for d in doc.get('decisions', []) if set(d['model_ids']) <= scope]
    checks = assess_design(scoped)
    if integrity_mismatch:
        checks['status'] = 'findings'
        checks['findings'].append({'code': 'design_hash_mismatch'})
    from engagement_stages import approved_entities
    approved = approved_entities(state) if models else set()
    return {'schema_version': 1, 'counts': counts(scoped['entities']),
            'structural': {'status': checks['status'], 'findings': len(checks['findings']), 'unknowns': len(checks['unknowns'])},
            'coverage': coverage_summary(state, sorted(scope)),
            'evidence': evidence_summary(state, sorted(scope)),
            'independent_review': review_summary(state, sorted(scope)),
            'human_review': {'status': 'recorded' if scope and scope <= approved else 'partial' if scope & approved else 'unassessed'},
            'native_validation': {'status': 'unassessed', 'qualification': 'This design view does not establish native warehouse or semantic validation; inspect separately recorded execution evidence.'},
            'qualification': 'Structural validity, source completeness, provenance, independent review, human review and native validation are separate. Missing evidence does not prevent explicitly requested provisional code.'}

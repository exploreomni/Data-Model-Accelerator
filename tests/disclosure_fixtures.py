"""Declared approvals for synthetic tests only; never native/human evidence."""
import copy
from privacy_contract import default_policy, new_classification


def synthetic_disclosure(artifact_ids, audience='engineer'):
    evidence = [{'reference': 'synthetic-test-only', 'sha256': 'a' * 64}]
    policy = default_policy()
    policy.update(review_status='approved', review_reference='synthetic-test-only', evidence=evidence)
    policy['destinations']['share'] = {'allowed_sensitivities': ['PUBLIC'], 'allowed_categories': []}
    classification = new_classification('PUBLIC')
    classification.update(categories_known=True, review_status='approved', review_reference='synthetic-test-only', evidence=evidence,
                          lineage={'status': 'complete', 'upstream_ids': [], 'transformation': 'source'})
    classification['handling']['share'] = 'allow'
    return {'audience': audience, 'policy': policy, 'presentation': copy.deepcopy(classification),
            'artifacts': {name: copy.deepcopy(classification) for name in artifact_ids}}

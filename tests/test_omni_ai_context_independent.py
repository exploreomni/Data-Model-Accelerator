"""Independent context contract attacks; synthetic definitions only, no model calls."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/data-model-accelerator/scripts'))
import omni_ai_context as ai
import omni_contract as omni
from test_omni_ai_context import fixture, reviewed, evaluation_fixture
from test_privacy_contract import approved_classification


def rehash(context):
    context['context_sha256']=ai.digest({k:v for k,v in context.items() if k!='context_sha256'})


@unittest.skipUnless(omni.yaml is not None and omni.sqlglot is not None,'Pinned semantic runtime required')
class IndependentContextTests(unittest.TestCase):
    def setUp(self):self.spec,self.inputs=fixture()
    def context(self):return ai.build_context(self.spec,**self.inputs)['context']
    def renew(self):self.spec['pins']=ai.input_pins(**self.inputs);reviewed(self.spec)
    def evaluate(self,change):
        context=self.context();suite,obs=evaluation_fixture(context);change(suite,obs,context)
        return ai.evaluate_answers(suite,obs,context)

    def test_secondary_physical_dependency_cannot_be_omitted(self):
        self.inputs['model_files']['shipments.view']=self.inputs['model_files']['shipments.view'].replace('sql: ${amount}','sql: ${amount} + ${id}')
        self.spec['bindings']['shipments.net_total']['field_sha256']=ai.digest({'sql':'${amount} + ${id}','aggregate_type':'sum'})
        self.renew()
        with self.assertRaises(ai.ContextError):ai.build_context(self.spec,**self.inputs)

    def test_private_dependency_cannot_be_hidden_by_public_measure_declaration(self):
        self.inputs['model_files']['shipments.view']=self.inputs['model_files']['shipments.view'].replace('sql: ${amount}','sql: ${amount} + ${id}')
        binding=self.spec['bindings']['shipments.net_total']
        binding['field_sha256']=ai.digest({'sql':'${amount} + ${id}','aggregate_type':'sum'})
        binding['columns'].append(dict(binding['columns'][0],column='ID',column_id='mart_shipments.ID'))
        column=self.inputs['dictionary']['models'][0]['columns'][0]
        column.update(sensitivity='RESTRICTED',privacy=approved_classification('RESTRICTED',['PHI']))
        self.renew();result=ai.build_context(self.spec,**self.inputs)
        self.assertEqual(result['context']['approved_definitions'],[])
        self.assertEqual(result['context']['fields'],[])
        self.assertNotIn('Net shipment amount',json.dumps(result))

    def test_full_catalogue_namespace_cannot_be_changed_in_mapping(self):
        self.spec['bindings']['shipments.net_total']['columns'][0]['namespace']=dict(
            self.spec['bindings']['shipments.net_total']['columns'][0]['namespace'],database='OTHER')
        reviewed(self.spec)
        with self.assertRaises(ai.ContextError):ai.build_context(self.spec,**self.inputs)

    def test_duplicate_dependency_does_not_replace_missing_dependency(self):
        binding=self.spec['bindings']['shipments.net_total'];binding['columns'].append(copy.deepcopy(binding['columns'][0]))
        reviewed(self.spec)
        with self.assertRaises(ai.ContextError):ai.build_context(self.spec,**self.inputs)

    def test_unresolved_meaning_remains_question_and_cannot_be_a_claim(self):
        context=self.context()
        self.assertEqual([x['id'] for x in context['approved_definitions']],['net_amount'])
        self.assertEqual([x['id'] for x in context['unresolved_questions']],['refunds'])
        def change(suite,obs,context):
            obs['answers'][0]['claims']=[{'definition_id':'refunds','statement_sha256':ai.digest('Assumed refund meaning')}]
        self.assertEqual(self.evaluate(change)['status'],'failed')

    def test_rehashed_missing_pins_or_lineage_is_not_a_valid_context(self):
        for mutation in ('pins','field','source_hash','count','spec_hash'):
            context=self.context()
            if mutation=='pins':context['pins']={}
            elif mutation=='field':context['fields']=[{'field':context['fields'][0]['field']}]
            elif mutation=='source_hash':context['approved_definitions'][0]['source_evidence_sha256']='invalid'
            elif mutation=='count':context['withheld_definition_count']=-1
            else:context['spec_sha256']='invalid'
            rehash(context)
            with self.subTest(mutation=mutation),self.assertRaises(ai.ContextError):ai.verify_context(context)

    def test_fabricated_approval_and_native_claims_cannot_survive_rehash(self):
        for key in ('native_verified','review_authority_authenticated','access_enforcement_verified'):
            context=self.context();context[key]=True;rehash(context)
            with self.subTest(key=key),self.assertRaises(ai.ContextError):ai.verify_context(context)

    def test_unexpected_persona_and_missing_attributes_fail(self):
        for mutate in (lambda a:a.update(persona_id='unapproved'),lambda a:a.update(attributes_used=[]),
                       lambda a:a.update(attributes_used=['secret_group'])):
            with self.subTest(mutate=mutate):
                self.assertEqual(self.evaluate(lambda s,o,c:mutate(o['answers'][0]))['status'],'failed')

    def test_refusal_cannot_leak_fields_or_approved_claims(self):
        for mutate in (lambda a:a.update(fields=['shipments.net_total']),
                       lambda a:a.update(claims=[{'definition_id':'net_amount','statement_sha256':'a'*64}]),
                       lambda a:a.update(decision='answer')):
            with self.subTest(mutate=mutate):
                self.assertEqual(self.evaluate(lambda s,o,c:mutate(o['answers'][2]))['status'],'failed')

    def test_changed_question_or_context_binding_fails(self):
        for key in ('question_sha256','context_sha256'):
            with self.subTest(key=key):
                self.assertEqual(self.evaluate(lambda s,o,c:o['answers'][0].update({key:'f'*64}))['status'],'failed')

    def test_duplicate_or_omitted_answer_is_not_full_coverage(self):
        self.assertEqual(self.evaluate(lambda s,o,c:o['answers'].pop())['status'],'failed')
        self.assertEqual(self.evaluate(lambda s,o,c:o['answers'].__setitem__(2,copy.deepcopy(o['answers'][0])))['status'],'failed')

    def test_wrong_statement_hash_and_extra_prose_never_pass(self):
        self.assertEqual(self.evaluate(lambda s,o,c:o['answers'][0]['claims'][0].update(statement_sha256='f'*64))['status'],'failed')
        marker='unapproved narrative marker'
        result=self.evaluate(lambda s,o,c:o['answers'][0].update(prose=marker))
        self.assertEqual(result['status'],'failed');self.assertNotIn(marker,json.dumps(result))

    def test_sensitive_observation_diagnostics_are_value_free(self):
        marker='SYNTHETIC_PHI_CANARY'
        result=self.evaluate(lambda s,o,c:o['answers'][0].update(prose=marker))
        self.assertEqual(result['status'],'failed');self.assertNotIn(marker,json.dumps(result))

    def test_local_answer_pass_does_not_claim_natural_language_or_access_truth(self):
        result=self.evaluate(lambda s,o,c:None)
        self.assertEqual(result['status'],'passed')
        for key in ('live_ai_authenticated','natural_language_answer_verified','access_enforcement_verified'):
            self.assertFalse(result[key])


if __name__=='__main__':unittest.main()

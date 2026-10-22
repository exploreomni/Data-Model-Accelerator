"""Operator discovery uses current validators and does not change an engagement."""
import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest

import test_engagement_stages
from ae_common import hash_json
import engagement_stages as stages
import guided_workflow as guided
import operator_contracts as contracts


class OperatorContractTests(unittest.TestCase):
    def test_discoverable_examples_roundtrip_actual_answer_and_design_validators(self):
        catalog=contracts.examples();examples={r['id']:r for r in catalog['contracts']}
        self.assertEqual(set(examples),set(contracts.NAMES))
        import migration_intent
        migration_intent._validate_intent(examples['migration-intent']['example'])
        intake=examples['intake']['example']
        self.assertEqual(guided._answers(intake),intake)
        self.assertEqual(contracts.validate_answers(intake)['missing_answers'],[])
        design=examples['import-design']['example']
        self.assertEqual(stages.validate_design(design),design)
        state={'engagement_id':'example.engagement','workflow':stages.empty_workflow()}
        imported=stages.import_design(state,copy.deepcopy(design))
        self.assertEqual(imported['sha256'],hash_json(design))
        stages.record_responses(state,examples['decision-responses']['example'])
        self.assertEqual(state['workflow']['responses'][0]['decision_id'],'order.population')
        self.assertEqual(state['workflow']['approvals'],[])
        self.assertTrue(examples['decision-responses']['example']['request_only'])
        from source_adapters.registry import SOURCES
        source=examples['source-registration']
        self.assertEqual(source['supported_adapter_names'],list(SOURCES))
        stages.fields(source['example'],{'schema_version'},{'source_profiles','source_identity','verified_connection_dialects'})
        self.assertEqual(source['example']['schema_version'],1)
        self.assertEqual(source['coverage_required_keys'],['schema_version','expected_files','reports','requirements','targets','mappings'])

    def test_unknown_keys_have_suggestions_and_preferences_are_not_dropped(self):
        answers={'warehous':'snowflake','framework':'dbt','model':'configured-model','reasoning_effort':'high'}
        before=copy.deepcopy(answers);result=contracts.validate_answers(answers)
        self.assertFalse(result['valid']);self.assertIsNone(result['normalized_answers'])
        self.assertEqual(result['submitted_answers'],answers);self.assertEqual(answers,before)
        issue=next(x for x in result['errors'] if x['path']=='warehous')
        self.assertIn('warehouse',issue['suggested_keys'])
        self.assertIn('Preserve',next(x for x in result['errors'] if x['path']=='model')['message'])
        result['submitted_answers']['framework']='changed'
        self.assertEqual(answers['framework'],'dbt')

    def test_new_design_examples_validate_without_inventing_inputs(self):
        import design_builder
        import design_coverage
        examples={r['id']:r['example'] for r in contracts.examples()['contracts']}
        design_coverage._validate(examples['design-coverage'])
        draft=design_builder.assemble(examples['design-assembly'])
        self.assertEqual(draft['entities'][0]['columns'][0]['type'],'unknown')
        self.assertEqual(draft['entities'][0]['keys'],[])
        self.assertTrue(all(s['status']=='missing' for s in examples['design-coverage']['sources']))
        self.assertEqual(examples['design-evidence']['claims'][0]['basis'],'proposal')

    def test_domain_choice_populates_missing_priority_without_overwriting_preferences(self):
        import test_domain_workflow as fixtures
        h=fixtures.DomainTests('test_discovery_never_selects_or_opens_design')
        h.setUp();self.addCleanup(h.doCleanups)
        h.state['answers']['priority_domain']=None
        h.state['answers']['naming_policy']={'mode':'preserve','domain':None,'decision_reference':None}
        guided._save(h.h.run,h.state,'synthetic-choice-setup')
        first=guided.stage_action(h.h.run,'select-domain',document=h.request(select=True))
        self.assertEqual(first['answers']['priority_domain'],'Sales')
        self.assertEqual(first['answers']['naming_policy']['mode'],'preserve')
        self.assertNotIn('priority_domain',first['readiness']['missing_answers'])
        resumed=guided.resume_engagement(h.h.run)
        self.assertEqual(resumed['answers'],first['answers'])

    def test_preserve_naming_shape_valid_and_bare_preference_repair_is_explicit(self):
        valid={'naming_policy':{'mode':'preserve','domain':None,'decision_reference':None}}
        self.assertEqual(contracts.validate_answers(valid)['normalized_answers'],valid)
        invalid={'naming_policy':'preserve'};result=contracts.validate_answers(invalid)
        self.assertFalse(result['valid']);self.assertEqual(result['submitted_answers'],invalid)
        self.assertEqual(result['errors'][0]['suggested_shape'],valid['naming_policy'])
        self.assertEqual(invalid['naming_policy'],'preserve')
        rename=contracts.validate_answers({'naming_policy':'type_domain'})
        suggestion=rename['errors'][0]['suggested_shape']
        self.assertEqual(suggestion['mode'],'type_domain')
        self.assertFalse(contracts.validate_answers({'naming_policy':suggestion})['valid'])

    def test_invalid_types_enums_and_incomplete_answers_remain_visible(self):
        result=contracts.validate_answers({'deliverables':'documentation','framework':'unavailable-framework'})
        self.assertEqual({x['path'] for x in result['errors']},{'deliverables','framework'})
        expected=next(x for x in result['errors'] if x['path']=='deliverables')['expected']
        self.assertEqual(expected['type'],'array_of_strings')
        self.assertIn('documentation',expected['allowed_items'])
        self.assertFalse(contracts.validate_answers([])['valid'])
        self.assertFalse(contracts.validate_answers({7:'bad'})['valid'])
        incomplete=contracts.validate_answers({'warehouse':'gcp'})
        self.assertTrue(incomplete['valid']);self.assertIn('warehouse',incomplete['missing_answers'])
        self.assertEqual(incomplete['normalized_answers']['warehouse'],'gcp')

    def test_secrets_and_invalid_json_values_are_not_echoed(self):
        for value in ({'password':'DO_NOT_ECHO'}, {'environment':'password=DO_NOT_ECHO'},
                      {'priority_domain':float('nan')}, {'priority_domain':set()}):
            result=contracts.validate_answers(value)
            self.assertFalse(result['valid']);self.assertIsNone(result['submitted_answers'])
            self.assertNotIn('DO_NOT_ECHO',json.dumps(result))

    def test_examples_are_fresh_and_model_host_authority_is_explicit(self):
        first=contracts.examples('intake');original=copy.deepcopy(first)
        first['contracts'][0]['example']['naming_policy']['mode']='changed'
        self.assertEqual(contracts.examples('intake'),original)
        text=json.dumps(original)
        self.assertIn('model and reasoning effort',text);self.assertIn('Do not choose cheaper',text)
        self.assertEqual(original['host_qualification']['plugin_integration'],'not_tested')
        with self.assertRaises(ValueError):contracts.examples('unknown')
        self.assertEqual(set(contracts.answer_fields()),guided.ANSWER_KEYS)

    def test_cli_validation_is_read_only_and_examples_discoverable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();source=root/'answers.json';source.write_text(json.dumps({'naming_policy':'preserve'}))
            state=root/'engagement.json';state.write_text('{"unchanged":true}')
            before={p.name:p.read_bytes() for p in root.iterdir()}
            out=io.StringIO()
            with redirect_stdout(out):self.assertEqual(contracts.main(['validate-answers','--answers',str(source)]),1)
            self.assertEqual(json.loads(out.getvalue())['errors'][0]['path'],'naming_policy')
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
            with redirect_stdout(io.StringIO()):self.assertEqual(contracts.main(['examples','decision-responses']),0)
            source.write_text('{"password":"DO_NOT_ECHO"}')
            out=io.StringIO();err=io.StringIO()
            with redirect_stdout(out),redirect_stderr(err):
                self.assertEqual(contracts.main(['validate-answers','--answers',str(source)]),2)
            self.assertNotIn('DO_NOT_ECHO',out.getvalue()+err.getvalue())

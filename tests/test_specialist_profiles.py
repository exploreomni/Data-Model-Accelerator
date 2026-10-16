"""Portable profile routing, freshness and backwards-compatible contract checks."""
import hashlib
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/data-model-accelerator/scripts'
sys.path.insert(0, str(SCRIPTS))
import specialist_profiles as profiles
from source_adapters.registry import SOURCES
from plan_specialists import plan_repository


class SpecialistProfileTests(unittest.TestCase):
    def test_every_adapter_has_exactly_one_bounded_profile_and_resolvable_local_links(self):
        self.assertEqual(set(SOURCES), profiles.SOURCES)
        self.assertEqual({p.stem for p in profiles.PROFILE_ROOT.glob('*.md')}, profiles.SOURCES)
        for source in sorted(SOURCES):
            with self.subTest(source=source):
                p = profiles.load_profile(source)
                self.assertEqual(p['sha256'], hashlib.sha256(p['text'].encode()).hexdigest())
                self.assertEqual(p['bytes'], len(p['text'].encode()))
                self.assertEqual(p['role'], 'source_specialist')
                for heading in ('Purpose', 'Required inputs', 'Interpretation and placement',
                                'Required handoff', 'Escalation and boundaries', 'Acceptance checks'):
                    self.assertEqual(p['text'].count('## ' + heading + '\n'), 1)
                for link in re.findall(r'\]\(([^)]+)\)', p['text']):
                    if '://' not in link and not link.startswith('#'):
                        self.assertTrue((profiles.PROFILE_ROOT / link.split('#')[0]).resolve().is_file(), link)

    def test_planner_binds_all_profiles_without_expanding_runtime_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = root / 'repo'; repo.mkdir()
            for source in SOURCES:
                folder = repo / source; folder.mkdir()
                (folder / 'example.sql').write_text('select order_id from orders;\n')
            plan = plan_repository(repo, root / 'run', inspect_git=False,
                                   source_profiles=[s + ':' + s for s in sorted(SOURCES)], semantic_target='omni')
            tasks = {t['source_type']: t for t in plan['tasks']}
            self.assertTrue(set(SOURCES) <= tasks.keys())
            for source in SOURCES:
                task = tasks[source]
                self.assertEqual(task['context_role'], 'source_specialist')
                self.assertEqual(task['specialist_profile'], profiles.profile_binding(source))
                self.assertNotIn('text', task['specialist_profile'])
            self.assertEqual(plan['review_roles'], ['warehouse_architect', 'omni_modeler', 'independent_qa'])
            self.assertEqual(plan['review_context_roles'], {'warehouse_architect': 'warehouse_architect',
                             'omni_modeler': 'semantic_modeler', 'independent_qa': 'independent_reviewer'})
            self.assertEqual(plan['target_tasks'][0]['role'], 'omni_modeler')
            self.assertEqual(plan['coverage']['specialists_executed'], 0)

    def test_legacy_raw_csv_and_unknown_routing_stay_outside_the_17_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); repo = root / 'repo'; repo.mkdir()
            (repo / 'orders.csv').write_text('order_id,amount\n1,4\n')
            (repo / 'note.md').write_text('Unclassified project evidence.\n')
            plan = plan_repository(repo, root / 'run', inspect_git=False)
            self.assertEqual({t['source_type'] for t in plan['tasks']}, {'raw_csv', 'unknown'})
            self.assertTrue(all('specialist_profile' not in t for t in plan['tasks']))
            self.assertEqual(plan['review_roles'], ['warehouse_architect', 'semantic_architect', 'independent_qa'])

    def test_path_injection_oversize_and_redirected_profiles_rejected(self):
        for value in ('../dbt', '/tmp/dbt', 'omni', None, [], 'DBT'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                profiles.load_profile(value)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / 'dbt.md'
            target.write_text('x' * (profiles.MAX_PROFILE_BYTES + 1))
            with patch.object(profiles, 'PROFILE_ROOT', root):
                with self.assertRaises(ValueError): profiles.load_profile('dbt')
                target.unlink(); (root / 'real.md').write_text('profile')
                target.symlink_to(root / 'real.md')
                with self.assertRaises(ValueError): profiles.load_profile('dbt')

    def test_disposition_mapping_does_not_rename_legacy_destinations(self):
        for disposition, destination in [('move_upstream', 'warehouse'), ('retain_semantic', 'semantic'),
                                         ('retain_presentation', 'presentation'), ('split', 'split'),
                                         ('unresolved', 'unresolved'), ('reuse_existing', 'warehouse'),
                                         ('consolidate_candidate', 'unresolved'), ('retire_candidate', 'unresolved')]:
            self.assertTrue(profiles.disposition_matches(disposition, destination))
        for disposition, destination in [('move_upstream', 'semantic'), ('retire_candidate', 'warehouse'),
                                         ('invented', 'warehouse'), ([], 'semantic'), ('split', [])]:
            self.assertFalse(profiles.disposition_matches(disposition, destination))


if __name__ == '__main__':
    unittest.main()

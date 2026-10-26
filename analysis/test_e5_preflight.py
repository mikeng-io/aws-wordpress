"""Preflight eligibility and mutation refusal; no live calls."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('preflight',Path(__file__).resolve().parents[1]/'experiments/E5-attribute-cache/scripts/preflight.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.report={'baseline':[{'region':p.REGION,'checks':{'filesystems':{'e5_count':0}},'errors':{}}],
          'retained_buckets':{'e5':0},'permissions':{'error':None,'actions':[{'action':x,'decision':'allowed','missing_context':[]} for x in p.ACTIONS]},
          'host_tools':{'docker':True},'local_guard':{'resolved':True},
          'budget':{'pricing_fresh_today':True,'projected_total_with_reserve_usd':4.55,'hard_ceiling_usd':10}}
    def test_good_read_only_evidence_is_conditional_not_unqualified_ready(self):
        self.assertEqual(p.readiness(self.report),'CONDITIONAL_PILOT_READY')
    def test_errors_active_resources_missing_region_and_retained_buckets_refuse(self):
        changes=[lambda r:r['baseline'][0]['errors'].update(api='AccessDenied'),
                 lambda r:r['baseline'][0]['checks']['filesystems'].update(e5_count=1),
                 lambda r:r.update(baseline=[]),lambda r:r['retained_buckets'].update(e5=1)]
        for change in changes:
            r=copy.deepcopy(self.report);change(r);self.assertEqual(p.readiness(r),'NOT_READY')
    def test_missing_or_duplicate_permission_actions_refuse(self):
        for actions in (self.report['permissions']['actions'][:-1],self.report['permissions']['actions'][:-1]+self.report['permissions']['actions'][:1]):
            r=copy.deepcopy(self.report);r['permissions']['actions']=actions;self.assertEqual(p.readiness(r),'NOT_READY')
    def test_missing_context_is_not_allowed_proof(self):
        self.report['permissions']['actions'][0]['missing_context']=['aws:ResourceTag/example']
        self.assertEqual(p.readiness(self.report),'NOT_READY')
    def test_stale_pricing_missing_tool_unresolved_guard_or_budget_exhaustion_refuse(self):
        for change in (lambda r:r['budget'].update(pricing_fresh_today=False),lambda r:r['host_tools'].update(docker=False),
                       lambda r:r['local_guard'].update(resolved=False),lambda r:r['budget'].update(projected_total_with_reserve_usd=10)):
            r=copy.deepcopy(self.report);change(r);self.assertEqual(p.readiness(r),'NOT_READY')
    def test_delete_or_tag_activation_cannot_be_queried(self):
        obj=p.Preflight.__new__(p.Preflight)
        with patch.object(p.subprocess,'run') as run:
            for args in (('cloudformation','delete-stack'),('fsx','delete-backup'),('ce','update-cost-allocation-tags-status')):
                with self.assertRaises(ValueError):obj.query('forbidden',*args)
            run.assert_not_called()
if __name__=='__main__':unittest.main()

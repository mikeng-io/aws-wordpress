#!/usr/bin/env python3
"""Read-only E5 pilot preflight. Raw account evidence stays in ignored private state."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[3]
REGION = 'ap-southeast-1'
ACTIONS = ['cloudformation:DescribeStacks','cloudformation:ListStacks','cloudformation:ListStackResources',
           'cloudformation:DescribeStackEvents','cloudformation:DeleteStack','fsx:DescribeBackups',
           'fsx:DeleteBackup','s3:GetBucketTagging','s3:ListBucket','s3:GetObject','s3:DeleteObject','s3:DeleteBucket']
READ_ONLY = {('sts','get-caller-identity'),('iam','simulate-principal-policy'),('ec2','describe-regions'),
 ('cloudformation','list-stacks'),('cloudformation','describe-stack-events'),('fsx','describe-file-systems'),
 ('fsx','describe-volumes'),('fsx','describe-storage-virtual-machines'),('fsx','describe-backups'),
 ('efs','describe-file-systems'),('ec2','describe-instances'),('ec2','describe-volumes'),
 ('ec2','describe-nat-gateways'),('ec2','describe-vpc-endpoints'),('ecs','list-clusters'),
 ('s3api','list-buckets'),('logs','describe-log-groups'),('ce','get-tags'),('ce','get-cost-and-usage'),
 ('ce','list-cost-allocation-tags')}


def ours(obj):
    tags = {x['Key']:x['Value'] for x in obj.get('Tags', [])}
    return tags.get('Study') == 'aws-wordpress' and tags.get('Experiment') == 'E5'


def readiness(report):
    baseline = report['baseline']
    baseline_ok = (any(r['region'] == REGION for r in baseline)
        and all(not r['errors'] and all(x['e5_count'] == 0 for x in r['checks'].values()) for r in baseline)
        and report['retained_buckets']['e5'] == 0)
    actions = report['permissions']['actions']
    permissions_ok = (not report['permissions']['error'] and len(actions) == len(ACTIONS)
        and {x['action'] for x in actions} == set(ACTIONS)
        and all(x['decision'] == 'allowed' and not x['missing_context'] for x in actions))
    tools_ok = all(report['host_tools'].values())
    guard_ok = report['local_guard']['resolved']
    price_ok = report['budget']['pricing_fresh_today']
    budget_ok = report['budget']['projected_total_with_reserve_usd'] < report['budget']['hard_ceiling_usd']
    return 'CONDITIONAL_PILOT_READY' if all((baseline_ok,permissions_ok,tools_ok,guard_ok,price_ok,budget_ok)) else 'NOT_READY'


class Preflight:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.utc = now.isoformat()
        self.stamp = now.strftime('%Y%m%dT%H%M%SZ')
        self.sha = subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
        self.private = REPO/'.e5-watchdog'/'preflight'/self.stamp
        self.private.mkdir(mode=0o700, parents=True)
        os.chmod(REPO/'.e5-watchdog',0o700)

    def query(self, label, *args, region=REGION):
        if args[:2] not in READ_ONLY:
            raise ValueError('preflight prohibits non-read-only actions')
        try:
            p = subprocess.run(['aws',*args,'--region',region,'--no-cli-pager','--output','json',
                                '--cli-connect-timeout','10','--cli-read-timeout','20'],
                               capture_output=True,text=True,timeout=60)
            if p.returncode:
                m = re.search(r'An error occurred \(([^)]+)\)',p.stderr)
                error = m.group(1) if m else 'CLI_ERROR'
                self.store(label, {'error':error, 'detail':p.stderr})
                return None, error
            data = json.loads(p.stdout)
            self.store(label,data)
            return data,None
        except (OSError,subprocess.TimeoutExpired,ValueError):
            self.store(label, {'error':'UNAVAILABLE'})
            return None,'UNAVAILABLE'

    def store(self,label,data):
        path=self.private/(label+'.json')
        path.write_text(json.dumps(data,indent=2)+'\n');path.chmod(0o600)

    def scan(self,region):
        out={'region':region,'checks':{},'errors':{}}
        specs=[('cloudformation','list-stacks','StackSummaries'),('fsx','describe-file-systems','FileSystems'),
               ('fsx','describe-volumes','Volumes'),('fsx','describe-storage-virtual-machines','StorageVirtualMachines'),
               ('fsx','describe-backups','Backups'),('efs','describe-file-systems','FileSystems'),
               ('ec2','describe-instances','Reservations'),('ec2','describe-volumes','Volumes'),
               ('ec2','describe-nat-gateways','NatGateways'),('ec2','describe-vpc-endpoints','VpcEndpoints'),
               ('ecs','list-clusters','clusterArns')]
        for service,op,key in specs:
            name=f'{service}-{op}'
            data,error=self.query(region+'-'+name,service,op,region=region)
            if error:out['errors'][name]=error;continue
            items=data[key]
            if service=='cloudformation':
                count=sum(x['StackName']=='E5-AttributeCache-dev' and x['StackStatus']!='DELETE_COMPLETE' for x in items)
            elif key=='clusterArns':count=sum('E5-AttributeCache' in x.rsplit('/',1)[-1] for x in items)
            else:
                if key=='Reservations':items=[i for r in items for i in r['Instances'] if i['State']['Name']!='terminated']
                if op=='describe-nat-gateways':items=[i for i in items if i['State']!='deleted']
                count=sum(ours(x) for x in items)
            out['checks'][name]={'e5_count':count,'all_count':len(items)}
        return out

    def run(self):
        report={'utc':self.utc,'source_commit':self.sha,'region':REGION,'live_mutations':False,
                'source_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'source_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True).strip())}
        def available(argv, starts=None):
            try:
                p=subprocess.run(argv,capture_output=True,text=True,timeout=20)
                return p.returncode == 0 and (starts is None or p.stdout.startswith(starts))
            except (OSError,subprocess.TimeoutExpired):return False
        report['host_tools']={'aws_cli_v2':available(['aws','--version'],'aws-cli/2'),
            'docker_daemon':available(['docker','info','--format','{{.ServerVersion}}']),
            'pinned_runner_present':available(['docker','image','inspect','aws-wordpress-runner','--format','{{.Id}}']),
            'region_matches':os.environ.get('AWS_DEFAULT_REGION',REGION)==REGION and os.environ.get('AWS_REGION',REGION)==REGION}
        latest=REPO/'.e5-watchdog/latest.json'
        report['local_guard']={'resolved':True,'phase':'NO_PREVIOUS_RUN'}
        if latest.exists():
            try:
                state=json.loads((Path(json.loads(latest.read_text())['directory'])/'state.json').read_text())
                report['local_guard']={'phase':state['phase'],'resolved':state['phase']=='complete' and bool(state.get('cleanup_verified'))}
            except (OSError,ValueError,KeyError):report['local_guard']={'phase':'UNREADABLE','resolved':False}
        identity,error=self.query('identity','sts','get-caller-identity')
        if error:raise RuntimeError('AWS identity unavailable; no pilot readiness verdict')
        report['identity']={'authenticated':True,'principal_type':'IAM_USER' if ':user/' in identity['Arn'] else 'OTHER'}
        simulation,error=(self.query('permission-simulation','iam','simulate-principal-policy',
                           '--policy-source-arn',identity['Arn'],'--action-names',*ACTIONS,'--resource-arns','*')
                          if ':user/' in identity['Arn'] else (None,'UNSUPPORTED_PRINCIPAL'))
        report['permissions']={'error':error,'scope':'identity-policy simulation on *, not live deletion proof',
             'actions':[] if error else [{'action':x['EvalActionName'],'decision':x['EvalDecision'],
                 'missing_context':x.get('MissingContextValues',[])} for x in simulation['EvaluationResults']]}
        regions,error=self.query('regions','ec2','describe-regions')
        if error:raise RuntimeError('Region inventory unavailable')
        names=sorted(x['RegionName'] for x in regions['Regions'])
        with ThreadPoolExecutor(max_workers=6) as pool:
            report['baseline']=list(pool.map(self.scan,names))
        buckets,error=self.query('buckets','s3api','list-buckets')
        report['retained_buckets']={'error':error,'e5':None if error else sum(b['Name'].startswith('e5-attributecache-dev-') for b in buckets['Buckets']),
            'e2_diagnostics':None if error else sum(b['Name'].startswith('e2-storagematrix-dev-diagnosticsbucket') for b in buckets['Buckets'])}
        logs,error=self.query('e5-logs','logs','describe-log-groups','--log-group-name-prefix','/aws/lambda/E5-AttributeCache-dev')
        report['retained_lambda_log_groups']=None if error else len(logs['logGroups'])
        history,error=self.query('stack-history','cloudformation','list-stacks')
        report['attempt_history']=[]
        if not error:
            for n,stack in enumerate(s for s in history['StackSummaries'] if s['StackName']=='E5-AttributeCache-dev'):
                events,err=self.query(f'attempt-{n}-events','cloudformation','describe-stack-events','--stack-name',stack['StackId'])
                ends=[] if err else [e['Timestamp'] for e in events['StackEvents'] if e.get('ResourceType')=='AWS::CloudFormation::Stack' and e.get('ResourceStatus')=='DELETE_COMPLETE']
                end=max(ends) if ends else None
                span=None if not end else (datetime.fromisoformat(end)-datetime.fromisoformat(stack['CreationTime'])).total_seconds()/60
                report['attempt_history'].append({'created':stack['CreationTime'],'delete_complete':end,'stack_minutes':span,'status':stack['StackStatus']})
        end=(datetime.now(timezone.utc).date()+timedelta(days=1)).isoformat()
        period=f'Start=2026-10-15,End={end}'
        ct,err=self.query('ce-tags','ce','get-tags','--time-period',period,'--tag-key','Experiment',region='us-east-1')
        allocation,ae=self.query('ce-allocation-tags','ce','list-cost-allocation-tags','--tag-keys','Study','Experiment',region='us-east-1')
        cost,ce=self.query('ce-cost','ce','get-cost-and-usage','--time-period',period,'--granularity','DAILY','--metrics','UnblendedCost',
            '--filter',json.dumps({'And':[{'Tags':{'Key':'Study','Values':['aws-wordpress']}},{'Tags':{'Key':'Experiment','Values':['E5']}}]}),region='us-east-1')
        report['billing']={'e5_tag_visible':False if err else 'E5' in ct.get('Tags',[]),
             'allocation_tags':[] if ae else [{k:x[k] for k in ('TagKey','Status')} for x in allocation['CostAllocationTags']],
             'observed_tag_filtered_usd':None if ce else sum(float(x['Total']['UnblendedCost']['Amount']) for x in cost['ResultsByTime']),
             'estimated_periods':None if ce else any(x.get('Estimated') for x in cost['ResultsByTime']),
             'errors':{k:v for k,v in [('tag_values',err),('allocation_tags',ae),('cost',ce)] if v},
             'actual_historical_cost_verified':False}
        price_path=sorted((REPO/'results/pricing').glob('*/pricing.json'))[-1]
        prices=json.loads(price_path.read_text())
        interface=next(x['usd'] for x in prices['vpc_endpoint'] if x['endpoint_type']=='PrivateLink' and x['unit']=='Hrs')
        fsx=sum(prices['fsx_minimum_configs'][k]['usd_per_hour'] for k in ['OpenZFS Single-AZ 1','Lustre Scratch (SSD)','ONTAP Single-AZ gen-1'])
        subtotal=prices['ec2_instances']['c7gd.large']['usd_per_hour']+12*interface+fsx
        report['budget']={'pricing_snapshot':str(price_path.parent.relative_to(REPO)),
            'pricing_utc':prices['snapshot_utc'],'pricing_fresh_today':datetime.fromisoformat(prices['snapshot_utc']).date()==datetime.now(timezone.utc).date() and prices['region']==REGION,'standing_subtotal_usd_per_hour':round(subtotal,5),
            'excludes':'EBS root, small EFS/S3/log usage, request/data-transfer charges and billing minimum effects',
            'hard_ceiling_usd':30,'historical_estimate_usd':16.996,'historical_basis':'conservative post-run planning proxy through formal v3; not an invoice',
            'estimated_remaining_before_pilot_usd':13.004,
            'pilot_planning_target_usd':2.6,'additional_planning_reserve_usd':0.4,
            'projected_total_with_reserve_usd':19.996,
            'actual_remaining_verified':False,
            'pilot_80_to_100_minutes_plus_75s_subtotal_usd':[round(subtotal*m/60,4) for m in (81.25,101.25)]}
        report['readiness']=readiness(report)
        report['conditions']=['Billing attribution/actual remaining budget unverified; planning uses the recorded $16.996 proxy.',
          'Simulator is not live resource-policy, service-role or deletion-timing proof.',
          'Recheck transient baseline/credentials immediately before the single pilot; no deployment performed.']
        output=REPO/'experiments/E5-attribute-cache/preflight'/f'{self.stamp}-{self.sha[:7]}'
        output.mkdir(parents=True)
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(str(output.relative_to(REPO)))
        print(report['readiness'])
        return report


if __name__=='__main__':
    Preflight().run()

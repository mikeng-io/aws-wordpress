#!/usr/bin/env node
/**
 * CDK app for the study's apparatus.
 *
 * There is deliberately no "platform" stack here. Stacks are added per experiment,
 * built to answer one question, and are allowed to be thrown away afterwards.
 * Resist generalising across experiments until at least three of them exist and
 * the shared shape is observed rather than guessed.
 */
import { App, Tags } from 'aws-cdk-lib';
import { E1MountTopologyStack } from '../lib/stacks/e1-mount-topology.js';
import { E3FargateEphemeralLatencyStack } from '../lib/stacks/e3-fargate-ephemeral-latency.js';
import { NatStrategy, natPlanningHourlyUsd } from '../lib/nat-strategy.js';

const app = new App();

// Region is fixed for the study - see docs/region-decision.md. Every latency and
// cost figure is region-specific, so this is provenance rather than preference.
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'ap-southeast-1',
};

// Stack naming: <ExperimentId>-<PascalSlug>-<topology>. A CDK stack ID is
// load-bearing - renaming one orphans the CloudFormation stack rather than renaming
// it - so the topology suffix is present from the first deploy, not retrofitted
// when a prod variant is eventually needed.
// E1 asks a question about mount topology, not about egress. The instance sits in a
// private isolated subnet with no public IP and no internet route, reaching AWS
// services through interface endpoints. No NAT because nothing needs the public
// internet - the choice is declared rather than assumed.
const e1Nat: NatStrategy = { kind: 'none' };

new E1MountTopologyStack(app, 'E1-MountTopology-dev', {
  env,
  experimentId: 'E1',
  topology: 'dev',
  nat: e1Nat,
  // 1x t4g.small (~0.019) + 10 interface endpoints (~0.13) + EFS at near-zero usage,
  // plus whatever the egress strategy costs. Planning estimate, not a measurement -
  // see H7. Endpoints cost more than the public-subnet shortcut they replace; that
  // shortcut was the wrong trade.
  estimatedHourlyUsd: 0.15 + natPlanningHourlyUsd(e1Nat),
  description: 'E1 - does ECS on EC2 mount EFS per host or per task?',
});

new E3FargateEphemeralLatencyStack(app, 'E3-FargateEphemeralLatency-dev', {
  env,
  experimentId: 'E3',
  topology: 'dev',
  // No NAT, no ASG, no EC2-agent endpoints - a one-shot Fargate RunTask is
  // structurally cheaper than E1's persistent EC2 service. 3 interface endpoints
  // (~0.04) + EFS at near-zero usage + Fargate vCPU/memory-seconds for a run
  // measured in minutes, not hours.
  estimatedHourlyUsd: 0.04,
  description: 'E3 - is Fargate ephemeral storage actually fast, or just not EFS?',
});

// E2 - placement differential (N tasks on 1 host vs N hosts, identical EFS)
// Not specced yet. Its original design assumed the shared-NFS-client mechanism
// E1 refuted; needs redesigning around what E1 actually found before it's worth
// building.

Tags.of(app).add('Study', 'aws-wordpress');

app.synth();

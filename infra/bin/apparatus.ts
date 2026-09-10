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
// E1 asks about mount topology, not egress: the workload sits in a private
// isolated subnet with no public IP and no internet route, reaching AWS services
// through interface endpoints. Five compute arms (t4g / m7g / c7g / r7g /
// Fargate) share one EFS and one VPC in a single deployment, so no arm's result
// can be explained by a different filesystem or network.
const e1Nat: NatStrategy = { kind: 'none' };

new E1MountTopologyStack(app, 'E1-MountTopology-dev', {
  env,
  experimentId: 'E1',
  topology: 'dev',
  nat: e1Nat,
  tasksPerArm: 2,
  // 4 EC2 instances (t4g.small ~0.019, m7g.large ~0.095, c7g.large ~0.085,
  // r7g.large ~0.125) + 10 interface endpoints (~0.13) + 2 Fargate tasks (~0.02)
  // + EFS at near-zero usage. Planning estimate, not a measurement - see H7.
  estimatedHourlyUsd: 0.48 + natPlanningHourlyUsd(e1Nat),
  description: 'E1 - does EFS mount per host or per task, across t/m/c/r and Fargate?',
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

// E2 - storage matrix. Retired from its original "placement differential" design,
// which assumed the shared-NFS-client mechanism E1 refuted, and redefined in place
// as the per-tier metadata-cost matrix: local ephemeral, EFS, FSx (OpenZFS /
// Lustre / ONTAP), JuiceFS, SeaweedFS, Mountpoint-S3. Specced in
// experiments/E2-storage-matrix/README.md; no stack yet, because the tier list has
// to survive a correctness gate before any of it is worth deploying.
//
// E4 - cache adapter. Specced and deliberately unbuilt: gated on E2, since there is
// no point building a cache tier if an off-the-shelf one already delivers it.

Tags.of(app).add('Study', 'aws-wordpress');

app.synth();

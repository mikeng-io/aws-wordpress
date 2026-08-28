import { Stack, StackProps, Tags } from 'aws-cdk-lib';
import { Construct } from 'constructs';

/**
 * Single-AZ and multi-AZ are not the same measurement - cross-AZ adds real RTT to
 * every metadata op, and at ~4,300 ops per request (E0) that compounds. Topology is
 * therefore recorded as provenance, not treated as a deployment convenience.
 */
export type Topology = 'dev' | 'prod';

export interface ExperimentStackProps extends StackProps {
  /** Stable experiment ID, e.g. "E2". Results reference it, so it never changes. */
  readonly experimentId: string;
  /**
   * Rough hourly cost while this stack is up, in USD. Recorded so a forgotten
   * stack has a known burn rate rather than an unknown one, and so the teardown
   * decision in the experiment README can be checked against reality.
   */
  readonly estimatedHourlyUsd: number;
  /** `dev` = 1 AZ, no NAT. `prod` = 3 AZ, CloudFront VPC origin. */
  readonly topology: Topology;
}

/**
 * Base for every experiment stack.
 *
 * Enforces the two things CLAUDE.md requires of billable apparatus: every resource
 * is attributable to an experiment, and every stack declares what it costs to leave
 * running.
 */
export abstract class ExperimentStack extends Stack {
  public readonly experimentId: string;
  public readonly topology: Topology;

  protected constructor(scope: Construct, id: string, props: ExperimentStackProps) {
    super(scope, id, props);

    this.experimentId = props.experimentId;
    this.topology = props.topology;

    Tags.of(this).add('Study', 'aws-wordpress');
    Tags.of(this).add('Experiment', props.experimentId);
    Tags.of(this).add('Topology', props.topology);
    Tags.of(this).add('EstimatedHourlyUsd', props.estimatedHourlyUsd.toFixed(2));
  }
}

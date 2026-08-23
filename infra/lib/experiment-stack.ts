import { Stack, StackProps, Tags } from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface ExperimentStackProps extends StackProps {
  /** Stable experiment ID, e.g. "E2". Results reference it, so it never changes. */
  readonly experimentId: string;
  /**
   * Rough hourly cost while this stack is up, in USD. Recorded so a forgotten
   * stack has a known burn rate rather than an unknown one, and so the teardown
   * decision in the experiment README can be checked against reality.
   */
  readonly estimatedHourlyUsd: number;
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

  protected constructor(scope: Construct, id: string, props: ExperimentStackProps) {
    super(scope, id, props);

    this.experimentId = props.experimentId;

    Tags.of(this).add('Study', 'aws-wordpress');
    Tags.of(this).add('Experiment', props.experimentId);
    Tags.of(this).add('EstimatedHourlyUsd', props.estimatedHourlyUsd.toFixed(2));
  }
}

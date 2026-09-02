import * as ec2 from 'aws-cdk-lib/aws-ec2';

/**
 * How a VPC gets egress, as an explicit choice rather than a hardcoded number.
 *
 * This is a study variable, not a deployment detail. The 2020 stack used
 * `natGateways: 3` — one per AZ, roughly $98/month sitting idle — and never
 * measured what that bought. H7 pre-registers NAT data processing as one of the
 * cost traps that decides outcomes, so the strategy has to be swappable and its
 * cost has to be attributable.
 */
export type NatStrategy =
  /**
   * No NAT. Workloads sit in public subnets with egress-only security groups, or in
   * isolated subnets reaching AWS services through VPC endpoints.
   *
   * Free. Correct for short-lived experiments and for any fleet that does not need
   * to reach the public internet — which, notably, a WordPress fleet *serving*
   * traffic does not. Only wp-admin needs egress, to reach wordpress.org for
   * plugin and core updates.
   */
  | { readonly kind: 'none' }
  /**
   * Managed NAT Gateways. `count: 1` is the usual cost-saving choice; it introduces
   * a single point of failure and cross-AZ data charges for traffic originating in
   * other AZs. `count: azs` removes both and multiplies the idle cost.
   */
  | { readonly kind: 'gateway'; readonly count: number }
  /**
   * NAT instances via NatInstanceProviderV2. Roughly a tenth of a NAT Gateway's
   * idle cost, at the price of owning patching, bandwidth limits, and HA yourself.
   *
   * Note this is `instanceV2`. `NatProvider.instance()` is deprecated — its AMI
   * reached end of life on 2023-12-31.
   */
  | {
      readonly kind: 'instance';
      readonly instanceType: ec2.InstanceType;
      readonly count?: number;
    };

/** What a strategy resolves to in CDK VPC terms. */
export interface ResolvedNat {
  readonly natGateways: number;
  readonly natGatewayProvider?: ec2.NatProvider;
  readonly description: string;
}

export function resolveNat(strategy: NatStrategy): ResolvedNat {
  switch (strategy.kind) {
    case 'none':
      return { natGateways: 0, description: 'no NAT (public subnets or VPC endpoints)' };

    case 'gateway':
      return {
        natGateways: strategy.count,
        natGatewayProvider: ec2.NatProvider.gateway(),
        description: `${strategy.count}x NAT Gateway`,
      };

    case 'instance': {
      const count = strategy.count ?? 1;
      return {
        natGateways: count,
        natGatewayProvider: ec2.NatProvider.instanceV2({
          instanceType: strategy.instanceType,
          // CDK's default is INBOUND_AND_OUTBOUND, which makes the instance an open
          // relay for anything that can route to it. Egress is all a NAT owes us.
          defaultAllowedTraffic: ec2.NatTrafficDirection.OUTBOUND_ONLY,
        }),
        description: `${count}x NAT instance (${strategy.instanceType.toString()})`,
      };
    }
  }
}

/**
 * PLANNING ESTIMATE ONLY — ap-southeast-1 list prices, idle, excluding data
 * processing and cross-AZ transfer.
 *
 * These are not results and must never be quoted as measurements. Real cost figures
 * come from the Price List Query API multiplied by measured utilisation, per H7.
 * They exist here so a stack can declare a burn rate before it is deployed.
 */
export function natPlanningHourlyUsd(strategy: NatStrategy): number {
  switch (strategy.kind) {
    case 'none':
      return 0;
    case 'gateway':
      return strategy.count * 0.059;
    case 'instance':
      return (strategy.count ?? 1) * 0.0212; // t4g.nano class, plus its public IPv4
  }
}

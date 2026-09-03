import { CfnOutput, RemovalPolicy } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import * as path from 'node:path';
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';

/**
 * E3 - is Fargate's local ephemeral storage actually fast, or just "not EFS"?
 *
 * H2 assumes hydrate-onto-ephemeral is a viable Fargate design. That assumption
 * has never been checked - nobody has published small-file metadata latency for
 * Fargate ephemeral storage. This stack answers it directly: one Fargate task,
 * two mounts (its own ephemeral storage, and EFS - the same filesystem shape E1
 * used), one benchmark run against both in sequence within the same task, so nothing
 * but the mount differs between the two result sets.
 *
 * Deliberately a one-shot RunTask, not a Service: this produces one comparison,
 * not a fleet. No ASG, no capacity provider, none of E1's EC2-bootstrap machinery
 * - Fargate needs none of it. `dev` topology (1 AZ, no NAT): nothing here is a
 * fleet-scale measurement, so single-AZ costs no validity, same reasoning as E1.
 */
export class E3FargateEphemeralLatencyStack extends ExperimentStack {
  constructor(scope: Construct, id: string, props: ExperimentStackProps) {
    super(scope, id, props);

    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.43.0.0/16'),
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });

    const taskSecurityGroup = new ec2.SecurityGroup(this, 'TaskSecurityGroup', {
      vpc,
      description: 'E3 benchmark task. No inbound - it runs once and exits.',
      allowAllOutbound: true,
    });

    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3 });

    const endpointSecurityGroup = new ec2.SecurityGroup(this, 'EndpointSecurityGroup', {
      vpc,
      description: 'E3 interface endpoints',
      allowAllOutbound: false,
    });
    endpointSecurityGroup.addIngressRule(
      taskSecurityGroup,
      ec2.Port.tcp(443),
      'HTTPS from the benchmark task only',
    );

    // Fargate needs none of E1's EC2-agent endpoints (ecs-agent, ecs-telemetry,
    // ssm*) - there is no self-registering host agent here, AWS's control plane
    // talks to the task directly. Only image pull and log delivery are needed.
    const interfaceEndpoints: Record<string, ec2.InterfaceVpcEndpointAwsService> = {
      Ecr: ec2.InterfaceVpcEndpointAwsService.ECR,
      EcrDocker: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
      Logs: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
    };
    for (const [id2, service] of Object.entries(interfaceEndpoints)) {
      vpc.addInterfaceEndpoint(`${id2}Endpoint`, {
        service,
        securityGroups: [endpointSecurityGroup],
        subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
        privateDnsEnabled: true,
      });
    }

    const fileSystemSecurityGroup = new ec2.SecurityGroup(this, 'FileSystemSecurityGroup', {
      vpc,
      description: 'E3 EFS mount target',
      allowAllOutbound: false,
    });
    fileSystemSecurityGroup.addIngressRule(
      taskSecurityGroup,
      ec2.Port.tcp(2049),
      'NFS from the benchmark task only',
    );

    const fileSystem = new efs.FileSystem(this, 'FileSystem', {
      vpc,
      oneZone: true,
      securityGroup: fileSystemSecurityGroup,
      encrypted: true,
      throughputMode: efs.ThroughputMode.ELASTIC,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    // No grantRootAccess() - same lesson as E1. This task mounts over plain
    // NFS/TLS, not IAM-authorized access, so a resource policy is not just
    // unnecessary but actively harmful: any custom policy replaces EFS's
    // permissive default, and a policy that omits ClientMount denies the mount
    // outright.

    const cluster = new ecs.Cluster(this, 'Cluster', { vpc, containerInsightsV2: ecs.ContainerInsights.DISABLED });

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'TaskDefinition', {
      cpu: 512,
      memoryLimitMiB: 1024,
      // Default Fargate ephemeral storage is 20 GiB - plenty for a benchmark tree
      // of 20 dirs x 50 files x <=50KB.
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    taskDefinition.addVolume({
      name: 'efs',
      efsVolumeConfiguration: {
        fileSystemId: fileSystem.fileSystemId,
        transitEncryption: 'ENABLED',
      },
    });

    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      retention: logs.RetentionDays.ONE_DAY,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const container = taskDefinition.addContainer('bench', {
      image: ecs.ContainerImage.fromAsset(path.join(__dirname, 'e3-bench'), {
        platform: Platform.LINUX_ARM64,
      }),
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e3', logGroup }),
    });
    container.addMountPoints({
      containerPath: '/efs-bench',
      sourceVolume: 'efs',
      readOnly: false,
    });
    // /local-bench needs no mount point at all - it's ordinary Fargate ephemeral
    // storage, which is simply the task's writable filesystem. That absence IS
    // the "local" arm of the comparison.

    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'TaskDefinitionArn', { value: taskDefinition.taskDefinitionArn });
    new CfnOutput(this, 'LogGroupName', { value: logGroup.logGroupName });
    new CfnOutput(this, 'SubnetId', { value: vpc.isolatedSubnets[0].subnetId });
    new CfnOutput(this, 'SecurityGroupId', { value: taskSecurityGroup.securityGroupId });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
  }
}

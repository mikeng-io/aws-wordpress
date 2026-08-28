import { CfnOutput, RemovalPolicy } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';

/**
 * E1 - does the ECS agent mount EFS once per host, or once per task?
 *
 * H1 claims co-located tasks share an NFS attribute cache, so task 2's stat() is
 * served from what task 1 warmed. That is only true if they share one NFS client.
 * This stack puts two tasks on one instance against one filesystem so the question
 * can be answered by inspection.
 *
 * Deliberately minimal, and deliberately `dev` topology: a single AZ, a public
 * subnet, and no NAT Gateway. The instance reaches SSM and ECR through the internet
 * gateway with an egress-only security group, which costs the price of one public
 * IPv4 address rather than $0.045/hr for NAT or $0.06/hr for six interface
 * endpoints. Nothing here is a performance measurement, so single-AZ costs us
 * nothing in validity.
 */
export interface E1StackProps extends ExperimentStackProps {
  /** Both tasks must land here, so the instance has to fit them both. */
  readonly instanceType?: ec2.InstanceType;
}

export class E1MountTopologyStack extends ExperimentStack {
  constructor(scope: Construct, id: string, props: E1StackProps) {
    super(scope, id, props);

    const instanceType =
      props.instanceType ?? ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.SMALL);

    // --- network ------------------------------------------------------------
    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.42.0.0/16'),
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
      ],
    });

    // Free, and it keeps ECR layer pulls off any metered path. Cheap insurance
    // against the NAT-data-processing trap recorded in H7.
    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3 });

    const instanceSecurityGroup = new ec2.SecurityGroup(this, 'InstanceSecurityGroup', {
      vpc,
      description: 'E1 container instance. Egress only - access is via SSM, not SSH.',
      allowAllOutbound: true,
    });

    const fileSystemSecurityGroup = new ec2.SecurityGroup(this, 'FileSystemSecurityGroup', {
      vpc,
      description: 'E1 EFS mount target',
      allowAllOutbound: false,
    });
    fileSystemSecurityGroup.addIngressRule(
      instanceSecurityGroup,
      ec2.Port.tcp(2049),
      'NFS from the container instance only',
    );

    // --- storage ------------------------------------------------------------
    const fileSystem = new efs.FileSystem(this, 'FileSystem', {
      vpc,
      oneZone: true,
      securityGroup: fileSystemSecurityGroup,
      encrypted: true,
      throughputMode: efs.ThroughputMode.ELASTIC,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // --- compute ------------------------------------------------------------
    const cluster = new ecs.Cluster(this, 'Cluster', { vpc, containerInsightsV2: ecs.ContainerInsights.DISABLED });

    const autoScalingGroup = new autoscaling.AutoScalingGroup(this, 'Asg', {
      vpc,
      instanceType,
      // arm64 AMI, to match t4g. A mismatch here fails at container start, not deploy.
      machineImage: ecs.EcsOptimizedImage.amazonLinux2023(ecs.AmiHardwareType.ARM),
      minCapacity: 1,
      maxCapacity: 1,
      desiredCapacity: 1,
      securityGroup: instanceSecurityGroup,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      associatePublicIpAddress: true,
      requireImdsv2: true,
    });
    autoScalingGroup.role.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
    );

    cluster.addAsgCapacityProvider(
      new ecs.AsgCapacityProvider(this, 'CapacityProvider', {
        autoScalingGroup,
        enableManagedTerminationProtection: false,
      }),
    );

    // --- task ---------------------------------------------------------------
    const taskDefinition = new ecs.Ec2TaskDefinition(this, 'TaskDefinition', {
      networkMode: ecs.NetworkMode.AWS_VPC,
    });

    taskDefinition.addVolume({
      name: 'efs',
      efsVolumeConfiguration: {
        fileSystemId: fileSystem.fileSystemId,
        transitEncryption: 'ENABLED',
      },
    });

    const container = taskDefinition.addContainer('probe', {
      // Multi-arch, and ships the coreutils the probe needs.
      image: ecs.ContainerImage.fromRegistry('public.ecr.aws/amazonlinux/amazonlinux:2023'),
      // Idle. The experiment drives it with ECS Exec rather than an entrypoint, so
      // the same task can be probed repeatedly without redeploying.
      command: ['sleep', 'infinity'],
      memoryReservationMiB: 256,
      cpu: 256,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'e1',
        logGroup: new logs.LogGroup(this, 'LogGroup', {
          retention: logs.RetentionDays.ONE_DAY,
          removalPolicy: RemovalPolicy.DESTROY,
        }),
      }),
    });
    container.addMountPoints({
      containerPath: '/mnt/efs',
      sourceVolume: 'efs',
      readOnly: false,
    });

    fileSystem.grantRootAccess(taskDefinition.taskRole);

    const service = new ecs.Ec2Service(this, 'Service', {
      cluster,
      taskDefinition,
      desiredCount: 2, // both land on the single instance - that is the whole point
      securityGroups: [instanceSecurityGroup],
      enableExecuteCommand: true,
      minHealthyPercent: 0,
      circuitBreaker: { rollback: false },
    });

    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'ServiceName', { value: service.serviceName });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
    new CfnOutput(this, 'AsgName', { value: autoScalingGroup.autoScalingGroupName });
  }
}

import { CfnOutput, RemovalPolicy } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';
import { NatStrategy, resolveNat } from '../nat-strategy.js';

/**
 * E1 - does the ECS agent mount EFS once per host, or once per task?
 *
 * H1 claims co-located tasks share an NFS attribute cache, so task 2's stat() is
 * served from what task 1 warmed. That is only true if they share one NFS client.
 * This stack puts two tasks on one instance against one filesystem so the question
 * can be answered by inspection.
 *
 * `dev` topology - a single AZ, because nothing here is a performance measurement
 * and single-AZ costs no validity.
 *
 * The container instance sits in a PRIVATE_ISOLATED subnet with no public IP and no
 * route to an internet gateway. Egress reaches exactly the AWS services the ECS
 * agent, SSM and ECR require, through interface endpoints, plus the free S3 gateway
 * endpoint for image layers. There is no NAT because nothing here needs the public
 * internet - not because NAT is expensive.
 */
export interface E1StackProps extends ExperimentStackProps {
  /** Both tasks must land here, so the instance has to fit them both. */
  readonly instanceType?: ec2.InstanceType;
  /** Egress strategy. E1 needs none; the prop exists so it is never hardcoded. */
  readonly nat: NatStrategy;
}

export class E1MountTopologyStack extends ExperimentStack {
  constructor(scope: Construct, id: string, props: E1StackProps) {
    super(scope, id, props);

    const instanceType =
      props.instanceType ?? ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.SMALL);

    // --- network ------------------------------------------------------------
    const nat = resolveNat(props.nat);

    // A NAT strategy of 'none' needs no public subnet at all. Any other strategy
    // does, since that is where the gateway or instance has to live.
    const subnetConfiguration: ec2.SubnetConfiguration[] =
      props.nat.kind === 'none'
        ? [{ name: 'Isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 }]
        : [
            { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
            { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
          ];

    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.42.0.0/16'),
      maxAzs: 1,
      natGateways: nat.natGateways,
      natGatewayProvider: nat.natGatewayProvider,
      subnetConfiguration,
    });

    /** Where the workload runs. Never public. */
    const workloadSubnets: ec2.SubnetSelection =
      props.nat.kind === 'none'
        ? { subnetType: ec2.SubnetType.PRIVATE_ISOLATED }
        : { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS };

    const instanceSecurityGroup = new ec2.SecurityGroup(this, 'InstanceSecurityGroup', {
      vpc,
      description: 'E1 container instance. No inbound; access is via SSM, not SSH.',
      allowAllOutbound: true,
    });

    // --- egress via endpoints, not the internet -----------------------------
    // Free, no per-AZ charge, and it carries ECR image layers - which is also the
    // NAT data-processing trap recorded in H7.
    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3 });

    const endpointSecurityGroup = new ec2.SecurityGroup(this, 'EndpointSecurityGroup', {
      vpc,
      description: 'E1 interface endpoints',
      allowAllOutbound: false,
    });
    endpointSecurityGroup.addIngressRule(
      instanceSecurityGroup,
      ec2.Port.tcp(443),
      'HTTPS from the container instance only',
    );

    // An ECS container instance with no internet route needs every one of these.
    // Omitting ECS_AGENT or ECS_TELEMETRY leaves the instance unable to register
    // with the cluster, which presents as a silent failure to place tasks.
    const interfaceEndpoints: Record<string, ec2.InterfaceVpcEndpointAwsService> = {
      Ecr: ec2.InterfaceVpcEndpointAwsService.ECR,
      EcrDocker: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
      Logs: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      Ssm: ec2.InterfaceVpcEndpointAwsService.SSM,
      SsmMessages: ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES,
      Ec2Messages: ec2.InterfaceVpcEndpointAwsService.EC2_MESSAGES,
      Ecs: ec2.InterfaceVpcEndpointAwsService.ECS,
      EcsAgent: ec2.InterfaceVpcEndpointAwsService.ECS_AGENT,
      EcsTelemetry: ec2.InterfaceVpcEndpointAwsService.ECS_TELEMETRY,
    };
    for (const [id, service] of Object.entries(interfaceEndpoints)) {
      vpc.addInterfaceEndpoint(`${id}Endpoint`, {
        service,
        securityGroups: [endpointSecurityGroup],
        subnets: workloadSubnets,
        privateDnsEnabled: true,
      });
    }

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
      vpcSubnets: workloadSubnets,
      associatePublicIpAddress: false,
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
      vpcSubnets: workloadSubnets,
      enableExecuteCommand: true,
      minHealthyPercent: 0,
      circuitBreaker: { rollback: false },
    });

    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'ServiceName', { value: service.serviceName });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
    new CfnOutput(this, 'AsgName', { value: autoScalingGroup.autoScalingGroupName });
    // Recorded so a result can state the egress topology it was measured under.
    new CfnOutput(this, 'NatStrategy', { value: nat.description });
  }
}

import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import * as path from 'node:path';
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';

export interface E2StorageMatrixProps extends ExperimentStackProps {
  /** Instance type for the EC2 arm. Must carry NVMe instance store (a `*d` type). */
  readonly instanceType?: ec2.InstanceType;
}

/**
 * E2 - what does each storage tier charge per metadata operation?
 *
 * This stack builds the BLOCK-BACKED group of the matrix: the three tiers where
 * the kernel owns the filesystem. The server-backed group (EFS is here as the
 * reference; FSx and the FUSE tiers are not) is added to this same stack later
 * rather than to a sibling - one number per experiment, replaced in place.
 *
 * The question this group answers is narrow and sharp. E3 measured a mount it
 * called "local ephemeral" at 3.1 us and reported ~271x over EFS, but Fargate
 * ephemeral is itself a network-backed volume - so that ratio might be a property
 * of the metadata path (the kernel's dentry cache answering without a round trip)
 * or a property of the device. Those two explanations predict different things,
 * and EC2 instance store separates them because it genuinely is attached NVMe.
 *
 * Pre-registered in experiments/E2-storage-matrix/README.md as prediction 5:
 * instance store and Fargate ephemeral TIE on stat p50 and SEPARATE on the
 * device-touching ops. A uniform win either way refutes it.
 *
 * Both arms mount the SAME EFS filesystem, which is what makes them comparable:
 * EFS is the common ruler carried across the EC2/Fargate boundary, exactly as E3
 * used it to compare two mounts inside one task.
 */
export class E2StorageMatrixStack extends ExperimentStack {
  constructor(scope: Construct, id: string, props: E2StorageMatrixProps) {
    super(scope, id, props);

    // c7gd.large: 2 vCPU, 4 GiB, 1 x 118 GB NVMe instance store. Compute-optimised
    // rather than general purpose because the benchmark is syscall-bound and the
    // extra memory of an m7gd would only enlarge the page cache - which is a
    // variable this experiment wants held down, not helped.
    const instanceType = props.instanceType ?? ec2.InstanceType.of(
      ec2.InstanceClass.C7GD,
      ec2.InstanceSize.LARGE,
    );

    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.44.0.0/16'),
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });
    const workloadSubnets: ec2.SubnetSelection = { subnetType: ec2.SubnetType.PRIVATE_ISOLATED };

    const workloadSecurityGroup = new ec2.SecurityGroup(this, 'WorkloadSecurityGroup', {
      vpc,
      description: 'E2 benchmark instances and tasks. No inbound.',
      allowAllOutbound: true,
    });

    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3 });

    const endpointSecurityGroup = new ec2.SecurityGroup(this, 'EndpointSecurityGroup', {
      vpc,
      description: 'E2 interface endpoints',
      allowAllOutbound: false,
    });
    endpointSecurityGroup.addIngressRule(
      workloadSecurityGroup,
      ec2.Port.tcp(443),
      'HTTPS from the benchmark workloads only',
    );

    // The EC2 arm needs the ECS agent endpoints that Fargate does not: a
    // self-registering host agent, plus SSM for reading the instance directly when
    // a mount needs to be confirmed on the host rather than inferred from inside a
    // container - the lesson E1 paid for.
    const interfaceEndpoints: Record<string, ec2.InterfaceVpcEndpointAwsService> = {
      Ecr: ec2.InterfaceVpcEndpointAwsService.ECR,
      EcrDocker: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
      Logs: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      Ecs: ec2.InterfaceVpcEndpointAwsService.ECS,
      EcsAgent: ec2.InterfaceVpcEndpointAwsService.ECS_AGENT,
      EcsTelemetry: ec2.InterfaceVpcEndpointAwsService.ECS_TELEMETRY,
      Ssm: ec2.InterfaceVpcEndpointAwsService.SSM,
      SsmMessages: ec2.InterfaceVpcEndpointAwsService.SSM_MESSAGES,
      Ec2Messages: ec2.InterfaceVpcEndpointAwsService.EC2_MESSAGES,
      CloudFormation: ec2.InterfaceVpcEndpointAwsService.CLOUDFORMATION,
    };
    for (const [endpointId, service] of Object.entries(interfaceEndpoints)) {
      vpc.addInterfaceEndpoint(`${endpointId}Endpoint`, {
        service,
        securityGroups: [endpointSecurityGroup],
        subnets: workloadSubnets,
        privateDnsEnabled: true,
      });
    }

    // --- the common ruler: one EFS, mounted by both arms ---------------------
    const fileSystemSecurityGroup = new ec2.SecurityGroup(this, 'FileSystemSecurityGroup', {
      vpc,
      description: 'E2 EFS mount target',
      allowAllOutbound: false,
    });
    fileSystemSecurityGroup.addIngressRule(
      workloadSecurityGroup,
      ec2.Port.tcp(2049),
      'NFS from the benchmark workloads only',
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
    // No grantRootAccess() - E1's lesson. Any custom file-system policy replaces
    // EFS's permissive default, and one that omits ClientMount denies the mount.

    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc,
      containerInsightsV2: ecs.ContainerInsights.DISABLED,
    });

    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      retention: logs.RetentionDays.ONE_DAY,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const benchImage = ecs.ContainerImage.fromAsset(path.join(__dirname, 'bench'), {
      platform: Platform.LINUX_ARM64,
    });

    // --- EC2 arm: instance store + EBS root + EFS ----------------------------
    const asg = new autoscaling.AutoScalingGroup(this, 'BlockBackedAsg', {
      vpc,
      instanceType,
      machineImage: ecs.EcsOptimizedImage.amazonLinux2023(ecs.AmiHardwareType.ARM),
      minCapacity: 1,
      maxCapacity: 1,
      securityGroup: workloadSecurityGroup,
      vpcSubnets: workloadSubnets,
      associatePublicIpAddress: false,
      requireImdsv2: true,
      // CloudFormation reports ASG CREATE_COMPLETE as soon as the API call
      // succeeds, not when an instance exists. E1 paid for this one.
      signals: autoscaling.Signals.waitForMinCapacity({ timeout: Duration.minutes(10) }),
    });
    asg.role.addManagedPolicy(iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'));

    const capacityProvider = new ecs.AsgCapacityProvider(this, 'BlockBackedCapacityProvider', {
      autoScalingGroup: asg,
      enableManagedTerminationProtection: false,
    });
    cluster.addAsgCapacityProvider(capacityProvider);

    // Instance store arrives RAW. Unlike EBS, AL2023 does not partition, format or
    // mount it - so without this the bind mount below would silently create an
    // ordinary directory on the root EBS volume and the "instance store" arm would
    // report EBS latency under an NVMe name. The container's entrypoint checks
    // st_dev for exactly this reason; this is the half that makes the check pass.
    //
    // The device is found by its stable by-id symlink rather than /dev/nvme1n1,
    // because NVMe enumeration order is not guaranteed and picking the wrong
    // device here would reformat the root volume.
    asg.addUserData(
      'set -euxo pipefail',
      'INSTANCE_STORE_DEV=$(find /dev/disk/by-id -name "nvme-Amazon_EC2_NVMe_Instance_Storage_*" ! -name "*-part*" | sort | head -1)',
      'if [ -z "$INSTANCE_STORE_DEV" ]; then echo "no instance store device found" >&2; exit 1; fi',
      'mkfs.xfs -f "$INSTANCE_STORE_DEV"',
      'mkdir -p /mnt/instance-store /mnt/ebs-bench',
      'mount -o noatime "$INSTANCE_STORE_DEV" /mnt/instance-store',
      // Prove the mount took before anything downstream depends on it.
      'test "$(stat -c %d /mnt/instance-store)" != "$(stat -c %d /)"',
      'chmod 777 /mnt/instance-store /mnt/ebs-bench',
    );

    // cfn-signal must be the LAST user-data line: addAsgCapacityProvider appends
    // the ECS_CLUSTER config, and signalling earlier would report success before
    // the instance knows which cluster to join. aws-cfn-bootstrap is not
    // preinstalled on this AMI; AL2023's dnf repos are S3-backed, so the install
    // works through the S3 gateway endpoint with no NAT.
    const cfnAsg = asg.node.defaultChild as autoscaling.CfnAutoScalingGroup;
    asg.addUserData(
      'dnf install -y aws-cfn-bootstrap',
      `/opt/aws/bin/cfn-signal --exit-code $? --stack ${Stack.of(this).stackName} ` +
        `--resource ${cfnAsg.logicalId} --region ${Stack.of(this).region}`,
    );

    const ec2TaskDefinition = new ecs.Ec2TaskDefinition(this, 'BlockBackedTaskDefinition', {
      networkMode: ecs.NetworkMode.AWS_VPC,
    });
    ec2TaskDefinition.addVolume({
      name: 'instance-store',
      host: { sourcePath: '/mnt/instance-store' },
    });
    ec2TaskDefinition.addVolume({
      name: 'ebs',
      host: { sourcePath: '/mnt/ebs-bench' },
    });
    ec2TaskDefinition.addVolume({
      name: 'efs',
      efsVolumeConfiguration: {
        fileSystemId: fileSystem.fileSystemId,
        transitEncryption: 'ENABLED',
      },
    });

    const ec2Container = ec2TaskDefinition.addContainer('bench', {
      image: benchImage,
      memoryReservationMiB: 512,
      cpu: 1024,
      environment: {
        BENCH_MOUNTS: 'instance_store=/bench/instance-store ebs=/bench/ebs efs=/bench/efs',
      },
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e2-ec2', logGroup }),
    });
    for (const [containerPath, sourceVolume] of [
      ['/bench/instance-store', 'instance-store'],
      ['/bench/ebs', 'ebs'],
      ['/bench/efs', 'efs'],
    ] as const) {
      ec2Container.addMountPoints({ containerPath, sourceVolume, readOnly: false });
    }

    // --- Fargate arm: task ephemeral + the same EFS --------------------------
    const fargateTaskDefinition = new ecs.FargateTaskDefinition(this, 'FargateTaskDefinition', {
      cpu: 1024,
      memoryLimitMiB: 2048,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });
    fargateTaskDefinition.addVolume({
      name: 'efs',
      efsVolumeConfiguration: {
        fileSystemId: fileSystem.fileSystemId,
        transitEncryption: 'ENABLED',
      },
    });
    const fargateContainer = fargateTaskDefinition.addContainer('bench', {
      image: benchImage,
      environment: {
        // 'ephemeral' is exempt from the entrypoint's root-filesystem check by
        // design: on Fargate the task's own writable layer IS the tier measured.
        BENCH_MOUNTS: 'ephemeral=/bench/ephemeral efs=/bench/efs',
      },
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e2-fargate', logGroup }),
    });
    fargateContainer.addMountPoints({
      containerPath: '/bench/efs',
      sourceVolume: 'efs',
      readOnly: false,
    });

    // Both arms are one-shot RunTasks, not services: this produces a comparison,
    // not a fleet. Nothing here restarts, so nothing here needs a circuit breaker
    // or a desired count.
    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'Ec2TaskDefinitionArn', { value: ec2TaskDefinition.taskDefinitionArn });
    new CfnOutput(this, 'FargateTaskDefinitionArn', { value: fargateTaskDefinition.taskDefinitionArn });
    new CfnOutput(this, 'CapacityProviderName', { value: capacityProvider.capacityProviderName });
    new CfnOutput(this, 'LogGroupName', { value: logGroup.logGroupName });
    new CfnOutput(this, 'SubnetId', { value: vpc.isolatedSubnets[0].subnetId });
    new CfnOutput(this, 'SecurityGroupId', { value: workloadSecurityGroup.securityGroupId });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
    new CfnOutput(this, 'AsgName', { value: asg.autoScalingGroupName });
    new CfnOutput(this, 'InstanceType', { value: instanceType.toString() });
  }
}

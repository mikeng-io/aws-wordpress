import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import * as path from 'node:path';
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';
import { NatStrategy, resolveNat } from '../nat-strategy.js';

/**
 * E1 - EFS mount topology across compute platforms.
 *
 * An earlier revision answered "per host or per task?" on one instance type (t4g.small), from one
 * deployment, by reading SSM output by eye. The answer was per task. That is a
 * discovery, not a replicated result, and it says nothing about whether the
 * behaviour is a property of ECS or of that one burstable instance family.
 *
 * This tests the question across FIVE compute arms in a single deployment -
 * burstable, general purpose, compute optimised, memory optimised, and Fargate -
 * sharing one VPC, one EFS filesystem and one endpoint set, so an arm's result
 * cannot be explained by a different filesystem or a different network.
 *
 * Fargate is the arm that matters most and is measured differently by necessity:
 * there is no host to inspect. No SSM, no SSH, nothing underneath the task is
 * reachable. Every EC2 arm therefore ALSO runs the in-task collector, so the two
 * platforms are compared on identical evidence rather than on whatever each
 * happens to expose.
 */
export interface E1StackProps extends ExperimentStackProps {
  readonly nat: NatStrategy;
  /** Tasks per EC2 arm. Capped by ENI limits: awsvpc consumes one ENI per task,
   *  and every instance type used here allows 3 total (primary + 2 tasks). */
  readonly tasksPerArm?: number;
}

interface Arm {
  readonly id: string;
  readonly instanceType: ec2.InstanceType;
  readonly family: string;
}

export class E1MountTopologyStack extends ExperimentStack {
  constructor(scope: Construct, id: string, props: E1StackProps) {
    super(scope, id, props);

    const tasksPerArm = props.tasksPerArm ?? 2;

    // One arm per EC2 family. Graviton throughout so the CPU architecture is held
    // constant and only the family varies - a mixed-architecture comparison would
    // confound family with instruction set.
    const arms: Arm[] = [
      { id: 'T4g', family: 'burstable',        instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.SMALL) },
      { id: 'M7g', family: 'general-purpose',  instanceType: ec2.InstanceType.of(ec2.InstanceClass.M7G, ec2.InstanceSize.LARGE) },
      { id: 'C7g', family: 'compute-optimised',instanceType: ec2.InstanceType.of(ec2.InstanceClass.C7G, ec2.InstanceSize.LARGE) },
      { id: 'R7g', family: 'memory-optimised', instanceType: ec2.InstanceType.of(ec2.InstanceClass.R7G, ec2.InstanceSize.LARGE) },
    ];

    // --- network ------------------------------------------------------------
    const nat = resolveNat(props.nat);
    const subnetConfiguration: ec2.SubnetConfiguration[] =
      props.nat.kind === 'none'
        ? [{ name: 'Isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 }]
        : [
            { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
            { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
          ];

    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.44.0.0/16'),
      maxAzs: 1,
      natGateways: nat.natGateways,
      natGatewayProvider: nat.natGatewayProvider,
      subnetConfiguration,
    });

    const workloadSubnets: ec2.SubnetSelection =
      props.nat.kind === 'none'
        ? { subnetType: ec2.SubnetType.PRIVATE_ISOLATED }
        : { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS };

    const instanceSecurityGroup = new ec2.SecurityGroup(this, 'InstanceSecurityGroup', {
      vpc,
      description: 'E1 workload. No inbound; access is via SSM, not SSH.',
      allowAllOutbound: true,
    });

    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3 });

    const endpointSecurityGroup = new ec2.SecurityGroup(this, 'EndpointSecurityGroup', {
      vpc,
      description: 'E1 interface endpoints',
      allowAllOutbound: false,
    });
    endpointSecurityGroup.addIngressRule(instanceSecurityGroup, ec2.Port.tcp(443), 'HTTPS from workload only');

    const interfaceEndpoints: Record<string, ec2.InterfaceVpcEndpointAwsService> = {
      CloudFormation: ec2.InterfaceVpcEndpointAwsService.CLOUDFORMATION,
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
    for (const [epId, service] of Object.entries(interfaceEndpoints)) {
      vpc.addInterfaceEndpoint(`${epId}Endpoint`, {
        service,
        securityGroups: [endpointSecurityGroup],
        subnets: workloadSubnets,
        privateDnsEnabled: true,
      });
    }

    // --- storage: ONE filesystem, shared by every arm -----------------------
    const fileSystemSecurityGroup = new ec2.SecurityGroup(this, 'FileSystemSecurityGroup', {
      vpc,
      description: 'E1 EFS mount target',
      allowAllOutbound: false,
    });
    fileSystemSecurityGroup.addIngressRule(instanceSecurityGroup, ec2.Port.tcp(2049), 'NFS from workload only');

    const fileSystem = new efs.FileSystem(this, 'FileSystem', {
      vpc,
      oneZone: true,
      securityGroup: fileSystemSecurityGroup,
      encrypted: true,
      throughputMode: efs.ThroughputMode.ELASTIC,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    // No grantRootAccess(): a FileSystemPolicy omitting ClientMount denies the
    // mount outright, and these tasks use plain NFS/TLS, not IAM-authorized access.

    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc,
      containerInsightsV2: ecs.ContainerInsights.DISABLED,
    });

    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      retention: logs.RetentionDays.ONE_DAY,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const probeImage = ecs.ContainerImage.fromAsset(
      path.join(__dirname, 'e1-probe'), { platform: Platform.LINUX_ARM64 });

    const addVolume = (td: ecs.TaskDefinition) => {
      td.addVolume({
        name: 'efs',
        efsVolumeConfiguration: { fileSystemId: fileSystem.fileSystemId, transitEncryption: 'ENABLED' },
      });
    };

    // --- EC2 arms -----------------------------------------------------------
    for (const arm of arms) {
      const asg = new autoscaling.AutoScalingGroup(this, `${arm.id}Asg`, {
        vpc,
        instanceType: arm.instanceType,
        machineImage: ecs.EcsOptimizedImage.amazonLinux2023(ecs.AmiHardwareType.ARM),
        minCapacity: 1,
        maxCapacity: 1,
        securityGroup: instanceSecurityGroup,
        vpcSubnets: workloadSubnets,
        associatePublicIpAddress: false,
        requireImdsv2: true,
        // CloudFormation reports an ASG CREATE_COMPLETE as soon as the API call
        // succeeds - it does NOT wait for an instance. Without this, services
        // race ahead of the capacity they need.
        signals: autoscaling.Signals.waitForMinCapacity({ timeout: Duration.minutes(8) }),
      });
      asg.role.addManagedPolicy(iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'));

      const capacityProvider = new ecs.AsgCapacityProvider(this, `${arm.id}CapacityProvider`, {
        autoScalingGroup: asg,
        enableManagedTerminationProtection: false,
      });
      cluster.addAsgCapacityProvider(capacityProvider);

      // cfn-signal must be the LAST user-data line: addAsgCapacityProvider above
      // appends the ECS_CLUSTER config, and signalling before that would report
      // success before the instance knows which cluster to join. aws-cfn-bootstrap
      // is not preinstalled on this AMI; AL2023's dnf repos are S3-backed so this
      // install works through the S3 gateway endpoint with no NAT.
      const cfnAsg = asg.node.defaultChild as autoscaling.CfnAutoScalingGroup;
      asg.addUserData(
        'dnf install -y aws-cfn-bootstrap',
        `/opt/aws/bin/cfn-signal --exit-code $? --stack ${Stack.of(this).stackName} ` +
          `--resource ${cfnAsg.logicalId} --region ${Stack.of(this).region}`,
      );

      const taskDefinition = new ecs.Ec2TaskDefinition(this, `${arm.id}TaskDefinition`, {
        networkMode: ecs.NetworkMode.AWS_VPC,
      });
      addVolume(taskDefinition);
      const container = taskDefinition.addContainer('probe', {
        image: probeImage,
        command: ['sleep', 'infinity'],
        memoryReservationMiB: 256,
        cpu: 256,
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: `e1-${arm.id.toLowerCase()}`, logGroup }),
      });
      container.addMountPoints({ containerPath: '/mnt/efs', sourceVolume: 'efs', readOnly: false });

      const service = new ecs.Ec2Service(this, `${arm.id}Service`, {
        cluster,
        taskDefinition,
        desiredCount: tasksPerArm,
        securityGroups: [instanceSecurityGroup],
        vpcSubnets: workloadSubnets,
        enableExecuteCommand: true,
        minHealthyPercent: 0,
        // Pin each service to its own family's capacity, so an arm's tasks cannot
        // silently land on another arm's instance and confound the comparison.
        capacityProviderStrategies: [{ capacityProvider: capacityProvider.capacityProviderName, weight: 1 }],
      });
      service.node.addDependency(asg);

      new CfnOutput(this, `${arm.id}AsgName`, { value: asg.autoScalingGroupName });
      new CfnOutput(this, `${arm.id}ServiceName`, { value: service.serviceName });
    }

    // --- Fargate arm --------------------------------------------------------
    // No ASG, no capacity provider, no host. The only observer available is the
    // task itself, which is the point.
    const fargateTaskDefinition = new ecs.FargateTaskDefinition(this, 'FargateTaskDefinition', {
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });
    addVolume(fargateTaskDefinition);
    const fargateContainer = fargateTaskDefinition.addContainer('probe', {
      image: probeImage,
      command: ['sleep', 'infinity'],
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e1-fargate', logGroup }),
    });
    fargateContainer.addMountPoints({ containerPath: '/mnt/efs', sourceVolume: 'efs', readOnly: false });

    const fargateService = new ecs.FargateService(this, 'FargateService', {
      cluster,
      taskDefinition: fargateTaskDefinition,
      desiredCount: tasksPerArm,
      securityGroups: [instanceSecurityGroup],
      vpcSubnets: workloadSubnets,
      enableExecuteCommand: true,
      minHealthyPercent: 0,
    });

    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
    new CfnOutput(this, 'FargateServiceName', { value: fargateService.serviceName });
    new CfnOutput(this, 'LogGroupName', { value: logGroup.logGroupName });
    new CfnOutput(this, 'TasksPerArm', { value: String(tasksPerArm) });
    new CfnOutput(this, 'Arms', { value: arms.map((a) => `${a.id}:${a.family}`).join(',') + ',Fargate:serverless' });
  }
}

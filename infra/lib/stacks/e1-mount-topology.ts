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
      // Required for cfn-signal (see the ASG's `signals` config below) to reach the
      // CloudFormation control plane. Confirmed missing by direct evidence: the
      // ASG's CreationPolicy waited its full 5-minute timeout and received zero
      // signals, with no other explanation - ECS_CLUSTER config and cfn-signal's
      // presence on the AMI were both otherwise verified. Historically this call
      // required the public internet; CloudFormation added PrivateLink support
      // specifically so it works from an isolated subnet like this one.
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
      // min == max pins the fleet at one instance without setting desiredCapacity,
      // which CDK warns resets the group's size on every deployment.
      minCapacity: 1,
      maxCapacity: 1,
      securityGroup: instanceSecurityGroup,
      vpcSubnets: workloadSubnets,
      associatePublicIpAddress: false,
      requireImdsv2: true,
      // Without this, CloudFormation marks the ASG resource CREATE_COMPLETE as
      // soon as the CreateAutoScalingGroup API call succeeds - it does NOT wait for
      // an instance to actually launch. Confirmed directly on the first deploy: the
      // ECS Service failed at 04:50:17 and the instance's EC2 LaunchTime was
      // 04:50:20, three seconds later - the Service was already trying (and
      // failing) to place tasks before the instance existed. waitForMinCapacity
      // makes CloudFormation hold the ASG resource open until an instance actually
      // signals success via cfn-signal, so the Service resource that depends on it
      // does not start until an instance is really there.
      signals: autoscaling.Signals.waitForMinCapacity({ timeout: Duration.minutes(5) }),
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

    // cfn-signal is what `signals` above is waiting for, and it is not part of the
    // ECS-optimized AMI's default boot behaviour - it has to be invoked explicitly.
    // aws-cfn-bootstrap (providing /opt/aws/bin/cfn-signal) is NOT preinstalled on
    // this AMI. Confirmed by direct evidence, not assumption, after two failed
    // deploys: SSM into the instance showed cloud-init finishing successfully with
    // ECS_CLUSTER written correctly, and the sole failure was
    // "/opt/aws/bin/cfn-signal: No such file or directory" on line 3 of user data.
    // AL2023's dnf repos are themselves hosted in S3 (al2023-repos-<region>-...),
    // specifically so package installs work through the S3 gateway endpoint this
    // stack already has for ECR layers - no NAT, no extra endpoint required.
    //
    // This MUST be the last line added to user data. addAsgCapacityProvider (above)
    // appends the ECS_CLUSTER config that tells the agent which cluster to join; an
    // earlier attempt called addUserData for cfn-signal before this point, and the
    // instance would have reported boot success before it was even configured to
    // join the right cluster - signalling "success" while telling CloudFormation
    // nothing true about ECS readiness. Signalling on boot completion rather than
    // after confirmed agent registration is still deliberate: it answers "did the
    // instance launch," the actual gap that broke the first deploy, and leaves the
    // ECS circuit breaker's own retries to absorb the much shorter remaining
    // agent-registration lag.
    const cfnAsg = autoScalingGroup.node.defaultChild as autoscaling.CfnAutoScalingGroup;
    autoScalingGroup.addUserData(
      'dnf install -y aws-cfn-bootstrap',
      `/opt/aws/bin/cfn-signal --exit-code $? --stack ${Stack.of(this).stackName} ` +
        `--resource ${cfnAsg.logicalId} --region ${Stack.of(this).region}`,
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
      // Built locally and pushed to the private CDK assets repository. A
      // public.ecr.aws reference would be unpullable here: the ECR interface
      // endpoints serve private repositories only, and this subnet has no internet
      // route. Platform is pinned rather than inherited from the build host, so an
      // x86 laptop does not silently produce an image the arm64 instance cannot run.
      image: ecs.ContainerImage.fromAsset(path.join(__dirname, 'e1-probe'), {
        platform: Platform.LINUX_ARM64,
      }),
      // Idle. The experiment drives it with ECS Exec rather than an entrypoint, so
      // the same task can be probed repeatedly without redeploying.
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

    // Deliberately no grantRootAccess() and no authorizationConfig on the volume:
    // this task mounts over plain NFS/TLS, not IAM-authorized EFS access, so no
    // task-role permission is needed for the mount to succeed - it is governed
    // purely by network path and the file system's resource policy.
    //
    // grantRootAccess() was tried here and is exactly what broke the mount.
    // Confirmed directly: `aws efs describe-file-system-policy` showed CDK had
    // written a policy granting ClientWrite and ClientRootAccess but NOT
    // ClientMount, and AWS's own EFS IAM docs list ClientMount as the action that
    // "provides read-only access to a file system" - i.e. the one every mount
    // needs first. With no policy at all, EFS defaults to open (equivalent to
    // Principal "*" on all three actions); the moment any custom policy exists,
    // that implicit default is replaced by exactly what the policy states, and the
    // narrower policy never granted the one action that lets a client mount at all.
    // grantRootAccess() is for IAM-authorized mounts (authorizationConfig with
    // iam: 'ENABLED' and an access point), which this task does not use.

    const service = new ecs.Ec2Service(this, 'Service', {
      cluster,
      taskDefinition,
      desiredCount: 2, // both land on the single instance - that is the whole point
      securityGroups: [instanceSecurityGroup],
      vpcSubnets: workloadSubnets,
      enableExecuteCommand: true,
      minHealthyPercent: 0,
      // This service uses the EC2 launch type directly, not a capacity-provider
      // strategy, so nothing in its properties references the ASG by Ref/GetAtt -
      // CloudFormation has no path to infer a dependency from. Without the explicit
      // one added below, Service creation starts as soon as Cluster and
      // TaskDefinition exist, in parallel with (and in the first deploy, well
      // before) the ASG's instance ever launching.
      // Kept enabled deliberately. The first deploy's failure timeline (Service
      // failed at 04:50:17, EC2 LaunchTime 04:50:20 - three seconds later) is
      // consistent with a boot-time placement race, but that timeline alone does
      // not rule out the probe container itself being broken - removing the
      // breaker would have papered over either cause with silent infinite retries.
      // The container is verified locally (see e1-probe/README) before this flag
      // is revisited.
      circuitBreaker: { rollback: false },
    });
    service.node.addDependency(autoScalingGroup);

    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'ServiceName', { value: service.serviceName });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
    new CfnOutput(this, 'AsgName', { value: autoScalingGroup.autoScalingGroupName });
    // Recorded so a result can state the egress topology it was measured under.
    new CfnOutput(this, 'NatStrategy', { value: nat.description });
  }
}

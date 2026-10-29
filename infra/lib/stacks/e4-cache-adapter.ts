import { CfnOutput, RemovalPolicy } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import * as path from 'node:path';
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';

/**
 * E4 - read-only task-start hydration on Fargate.
 *
 * The original cache-adapter design was gated by E2: FUSE tiers need
 * CAP_SYS_ADMIN and are EC2-only, and on EC2 the existing tiers are prior art.
 * What remains on Fargate is hydration: copy a read-only code tree onto the task's
 * ephemeral storage at start, serve reads there, never sync back.
 *
 * Three one-shot tasks share one EFS origin and one bench image:
 *   seed     - builds the tree on EFS and tars it; timing is not a result
 *   efs      - fresh task, reads the seeded tree over EFS
 *   hydrated - fresh task, downloads+extracts the tar locally, reads the copy
 *
 * Deliberately no Service, ALB, NAT or FSx. One fresh task per arm per replication
 * keeps the EFS arm from inheriting the seed task's client cache.
 */
export class E4CacheAdapterStack extends ExperimentStack {
  constructor(scope: Construct, id: string, props: ExperimentStackProps) {
    super(scope, id, props);

    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.46.0.0/16'),
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });

    const taskSecurityGroup = new ec2.SecurityGroup(this, 'TaskSecurityGroup', {
      vpc,
      description: 'E4 hydration tasks. No inbound - each runs once and exits.',
      allowAllOutbound: true,
    });

    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3 });

    const endpointSecurityGroup = new ec2.SecurityGroup(this, 'EndpointSecurityGroup', {
      vpc,
      description: 'E4 interface endpoints',
      allowAllOutbound: false,
    });
    endpointSecurityGroup.addIngressRule(
      taskSecurityGroup,
      ec2.Port.tcp(443),
      'HTTPS from the hydration tasks only',
    );

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
      description: 'E4 EFS mount target',
      allowAllOutbound: false,
    });
    fileSystemSecurityGroup.addIngressRule(
      taskSecurityGroup,
      ec2.Port.tcp(2049),
      'NFS from the hydration tasks only',
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

    const resultsBucket = new s3.Bucket(this, 'ResultsBucket', {
      removalPolicy: RemovalPolicy.DESTROY,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
    });

    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc,
      containerInsightsV2: ecs.ContainerInsights.DISABLED,
    });

    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      retention: logs.RetentionDays.ONE_DAY,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const image = ecs.ContainerImage.fromAsset(path.join(__dirname, 'bench'), {
      platform: Platform.LINUX_ARM64,
    });

    const makeTask = (
      id2: string,
      arm: string,
      environment: Record<string, string>,
      mountPath: string,
      readOnly: boolean,
    ): ecs.FargateTaskDefinition => {
      const taskDefinition = new ecs.FargateTaskDefinition(this, `${id2}TaskDefinition`, {
        cpu: 512,
        memoryLimitMiB: 1024,
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
      const container = taskDefinition.addContainer(id2, {
        image,
        environment: {
          BENCH_S3_BUCKET: resultsBucket.bucketName,
          BENCH_ARM: arm,
          ...environment,
        },
        logging: ecs.LogDrivers.awsLogs({ streamPrefix: arm, logGroup }),
      });
      container.addMountPoints({ containerPath: mountPath, sourceVolume: 'efs', readOnly });
      resultsBucket.grantReadWrite(taskDefinition.taskRole);
      return taskDefinition;
    };

    const seedTask = makeTask(
      'Seed',
      'seed',
      {
        BENCH_MOUNTS: 'efs=/efs',
        BENCH_KEEP: '1',
        BENCH_SEED_ONLY: '1',
        BENCH_SEED_TAR: '/efs/tree.tar',
        BENCH_SHUFFLE: '0',
      },
      '/efs',
      false,
    );

    const efsTask = makeTask(
      'Efs',
      'efs',
      {
        BENCH_MOUNTS: 'efs=/efs',
        BENCH_EXISTING: '1',
        BENCH_SHUFFLE: '0',
      },
      '/efs',
      false,
    );

    const hydratedTask = makeTask(
      'Hydrated',
      'hydrated',
      {
        BENCH_MOUNTS: 'ephemeral=/local-bench',
        BENCH_EXISTING: '1',
        BENCH_HYDRATE_FROM: '/efs-origin/tree.tar',
        BENCH_HYDRATE_TO: '/local-bench/tree',
        BENCH_SHUFFLE: '0',
      },
      '/efs-origin',
      true,
    );

    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'SeedTaskDefinitionArn', { value: seedTask.taskDefinitionArn });
    new CfnOutput(this, 'EfsTaskDefinitionArn', { value: efsTask.taskDefinitionArn });
    new CfnOutput(this, 'HydratedTaskDefinitionArn', { value: hydratedTask.taskDefinitionArn });
    new CfnOutput(this, 'LogGroupName', { value: logGroup.logGroupName });
    new CfnOutput(this, 'SubnetId', { value: vpc.isolatedSubnets[0].subnetId });
    new CfnOutput(this, 'SecurityGroupId', { value: taskSecurityGroup.securityGroupId });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
    new CfnOutput(this, 'ResultsBucketName', { value: resultsBucket.bucketName });
  }
}

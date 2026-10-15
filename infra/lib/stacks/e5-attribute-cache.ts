import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import * as autoscaling from 'aws-cdk-lib/aws-autoscaling';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as efs from 'aws-cdk-lib/aws-efs';
import * as fsx from 'aws-cdk-lib/aws-fsx';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as zlib from 'node:zlib';
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';

export interface E5AttributeCacheProps extends ExperimentStackProps {
  /** EC2 arm. c7gd.large by default: the client E2's miss costs were measured on. */
  readonly instanceType?: ec2.InstanceType;
}

/** Cohort mounts per NFS tier. `forced` alone zeroes the FILE attribute timers. */
const NFS_COHORTS = ['default', 'forced', 'ss-0.1', 'ss-1', 'ss-10'] as const;
/** Lustre and EBS have no attribute timers to force; they get subdirectories. */
const DIR_COHORTS = ['default', 'ss-0.1', 'ss-1', 'ss-10'] as const;
const TIERS = ['ebs', 'efs_host_plain', 'efs_host_tls', 'fsx_openzfs', 'fsx_ontap', 'fsx_lustre'];

/**
 * E5 - what an NFS stat costs on a tree this client did not just create.
 * Design, predictions and the reason for every choice below:
 * experiments/E5-attribute-cache/README.md.
 *
 * The FSx, EFS, VPC and endpoint construction is COPIED from E2's stack
 * (e2-storage-matrix.ts), not shared with it. Factoring it into a module would have
 * been acceptable only with E2's synthesized template byte-identical afterwards;
 * copying makes that trivially true and leaves E2's completed apparatus untouched.
 * The rationale comments for every FSx setting live in E2's file and are not
 * repeated here: every setting is E2's, unchanged, so the tiers are the tiers E2's
 * miss costs came from. What differs is the HOST: how the tree gets onto each tier,
 * and how each cohort is mounted.
 *
 * The host does, in order, before the ECS task can start:
 *   1. mounts each tier ONCE through a `seed` mount and writes the trees;
 *   2. unmounts every seed mount, cancels Lustre's DLM locks, drops caches;
 *   3. records seed-epoch (the age gate in the task reads it);
 *   4. mounts every cohort of every NFS tier as its OWN superblock (nosharecache),
 *      so each has its own attribute cache and its own mountstats counters.
 * So every measurement mount meets every file as a client that has never seen it.
 */
export class E5AttributeCacheStack extends ExperimentStack {
  constructor(scope: Construct, id: string, props: E5AttributeCacheProps) {
    super(scope, id, props);

    const instanceType = props.instanceType ?? ec2.InstanceType.of(
      ec2.InstanceClass.C7GD,
      ec2.InstanceSize.LARGE,
    );
    const region = Stack.of(this).region;

    // --- network: E2's, with its own CIDR --------------------------------------
    const vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr('10.45.0.0/16'),
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Isolated', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });
    const workloadSubnets: ec2.SubnetSelection = { subnetType: ec2.SubnetType.PRIVATE_ISOLATED };
    const workloadSecurityGroup = new ec2.SecurityGroup(this, 'WorkloadSecurityGroup', {
      vpc,
      description: 'E5 benchmark instance and task. No inbound.',
      allowAllOutbound: true,
    });
    vpc.addGatewayEndpoint('S3Endpoint', { service: ec2.GatewayVpcEndpointAwsService.S3 });
    const endpointSecurityGroup = new ec2.SecurityGroup(this, 'EndpointSecurityGroup', {
      vpc,
      description: 'E5 interface endpoints',
      allowAllOutbound: false,
    });
    endpointSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcp(443), 'HTTPS from the benchmark only');

    // E2's twelve, every one still used: ECR/ECS/Logs for the task, SSM for host
    // provenance, CloudFormation for cfn-signal, FSx for the ONTAP endpoint lookup,
    // EFS for the mount helper. Dropping Fargate removed no endpoint.
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
      Efs: ec2.InterfaceVpcEndpointAwsService.ELASTIC_FILESYSTEM,
      Fsx: ec2.InterfaceVpcEndpointAwsService.FSX,
    };
    for (const [endpointId, service] of Object.entries(interfaceEndpoints)) {
      vpc.addInterfaceEndpoint(`${endpointId}Endpoint`, {
        service,
        securityGroups: [endpointSecurityGroup],
        subnets: workloadSubnets,
        privateDnsEnabled: true,
      });
    }

    // --- EFS --------------------------------------------------------------------
    const fileSystemSecurityGroup = new ec2.SecurityGroup(this, 'FileSystemSecurityGroup', {
      vpc,
      description: 'E5 EFS mount target',
      allowAllOutbound: false,
    });
    fileSystemSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcp(2049), 'NFS from the benchmark only');
    const fileSystem = new efs.FileSystem(this, 'FileSystem', {
      vpc,
      oneZone: true,
      securityGroup: fileSystemSecurityGroup,
      encrypted: true,
      throughputMode: efs.ThroughputMode.ELASTIC,
      performanceMode: efs.PerformanceMode.GENERAL_PURPOSE,
      removalPolicy: RemovalPolicy.DESTROY,
    });

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
    const resultsBucket = new s3.Bucket(this, 'ResultsBucket', {
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
    });
    // RETAINed, with expiry: boot evidence must survive a rollback (see E2).
    const diagnosticsBucket = new s3.Bucket(this, 'DiagnosticsBucket', {
      removalPolicy: RemovalPolicy.RETAIN,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      lifecycleRules: [{ expiration: Duration.days(14) }],
    });

    // --- FSx: E2's three arms, every setting unchanged --------------------------
    const fsxSecurityGroup = new ec2.SecurityGroup(this, 'FsxSecurityGroup', {
      vpc,
      description: 'E5 FSx file systems',
      allowAllOutbound: false,
    });
    fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcp(2049), 'NFS (OpenZFS, ONTAP)');
    fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcp(988), 'Lustre LNet');
    fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcpRange(1018, 1023), 'Lustre management');
    fsxSecurityGroup.addIngressRule(fsxSecurityGroup, ec2.Port.allTraffic(), 'FSx internal');
    workloadSecurityGroup.addIngressRule(fsxSecurityGroup, ec2.Port.tcp(988), 'Lustre LNet back to client');
    workloadSecurityGroup.addIngressRule(fsxSecurityGroup, ec2.Port.tcpRange(1018, 1023), 'Lustre management back to client');
    fsxSecurityGroup.addEgressRule(workloadSecurityGroup, ec2.Port.tcp(988), 'Lustre LNet to client');
    fsxSecurityGroup.addEgressRule(workloadSecurityGroup, ec2.Port.tcpRange(1018, 1023), 'Lustre mgmt to client');
    fsxSecurityGroup.addEgressRule(workloadSecurityGroup, ec2.Port.tcp(2049), 'NFS to client (OpenZFS, ONTAP)');
    fsxSecurityGroup.addEgressRule(fsxSecurityGroup, ec2.Port.allTraffic(), 'FSx internal');

    const subnetId = vpc.isolatedSubnets[0].subnetId;
    const openzfs = new fsx.CfnFileSystem(this, 'FsxOpenZfs', {
      fileSystemType: 'OPENZFS',
      subnetIds: [subnetId],
      securityGroupIds: [fsxSecurityGroup.securityGroupId],
      storageCapacity: 64,
      storageType: 'SSD',
      openZfsConfiguration: {
        deploymentType: 'SINGLE_AZ_1',
        throughputCapacity: 128,
        copyTagsToBackups: true,
        automaticBackupRetentionDays: 0,
        rootVolumeConfiguration: {
          nfsExports: [{
            clientConfigurations: [{ clients: '*', options: ['rw', 'crossmnt', 'no_root_squash'] }],
          }],
          dataCompressionType: 'NONE',
        },
      },
    });
    const lustre = new fsx.LustreFileSystem(this, 'FsxLustre', {
      vpc,
      vpcSubnet: vpc.isolatedSubnets[0],
      securityGroup: fsxSecurityGroup,
      storageCapacityGiB: 1200,
      lustreConfiguration: { deploymentType: fsx.LustreDeploymentType.SCRATCH_2 },
      fileSystemTypeVersion: fsx.FileSystemTypeVersion.V_2_15,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const ontap = new fsx.CfnFileSystem(this, 'FsxOntap', {
      fileSystemType: 'ONTAP',
      subnetIds: [subnetId],
      securityGroupIds: [fsxSecurityGroup.securityGroupId],
      storageCapacity: 1024,
      storageType: 'SSD',
      ontapConfiguration: {
        deploymentType: 'SINGLE_AZ_1',
        throughputCapacity: 128,
        preferredSubnetId: subnetId,
        automaticBackupRetentionDays: 0,
      },
    });
    const svm = new fsx.CfnStorageVirtualMachine(this, 'FsxOntapSvm', {
      fileSystemId: ontap.ref,
      name: 'e5svm',
      rootVolumeSecurityStyle: 'UNIX',
    });
    const ontapVolume = new fsx.CfnVolume(this, 'FsxOntapVolume', {
      name: 'e5vol',
      volumeType: 'ONTAP',
      ontapConfiguration: {
        storageVirtualMachineId: svm.attrStorageVirtualMachineId,
        junctionPath: '/vol1',
        sizeInBytes: String(64 * 1024 * 1024 * 1024),
        securityStyle: 'UNIX',
        tieringPolicy: { name: 'NONE' },
        snapshotPolicy: 'none',
        storageEfficiencyEnabled: 'false',
        copyTagsToBackups: 'true',
      },
    });
    ontapVolume.node.addDependency(svm);
    for (const f of [openzfs, lustre, ontap]) {
      f.node.addDependency(fsxSecurityGroup);
    }

    // --- EC2 host ----------------------------------------------------------------
    const asg = new autoscaling.AutoScalingGroup(this, 'HostAsg', {
      vpc,
      instanceType,
      machineImage: ecs.EcsOptimizedImage.amazonLinux2023(ecs.AmiHardwareType.ARM),
      minCapacity: 1,
      maxCapacity: 1,
      securityGroup: workloadSecurityGroup,
      vpcSubnets: workloadSubnets,
      associatePublicIpAddress: false,
      requireImdsv2: true,
      // Longer than E2's 10 min: seeding six tiers x up to five trees happens
      // before the signal. ~30k small files; EFS creates are ~6.5 ms each.
      signals: autoscaling.Signals.waitForMinCapacity({ timeout: Duration.minutes(25) }),
    });
    asg.role.addManagedPolicy(iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'));
    asg.node.addDependency(fileSystem.mountTargetsAvailable);
    asg.node.addDependency(ontapVolume);
    diagnosticsBucket.grantPut(asg.role);
    asg.role.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['fsx:DescribeStorageVirtualMachines', 'fsx:DescribeFileSystems'],
      resources: ['*'],
    }));
    const capacityProvider = new ecs.AsgCapacityProvider(this, 'HostCapacityProvider', {
      autoScalingGroup: asg,
      enableManagedTerminationProtection: false,
    });
    cluster.addAsgCapacityProvider(capacityProvider);

    // Host scripts travel gzipped and base64-encoded: user data never has to escape
    // them, and EC2 caps user data at 16 KB.
    const hostFile = (name: string) =>
      zlib.gzipSync(fs.readFileSync(path.join(__dirname, 'e5-host', name)), { level: 9 }).toString('base64');

    const nfsOpts = 'nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2';
    const nfsCohorts = NFS_COHORTS.join(' ');
    const dirCohorts = DIR_COHORTS.join(' ');
    const nfsTiers = ['efs_host_plain', 'efs_host_tls', 'fsx_openzfs', 'fsx_ontap'];

    asg.addUserData(
      'set -euxo pipefail',
      `DIAG_S3=s3://${diagnosticsBucket.bucketName}/e5-diagnostics`,
      'dump_diagnostics() {',
      '  local stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)-$(hostname)',
      '  { findmnt -t nfs,nfs4,lustre -o TARGET,SOURCE,FSTYPE,OPTIONS; cat /mnt/host-facts/seed-manifest;',
      '    dmesg | grep -i -E "nfs|lustre|lnet" | tail -60; } > /tmp/diag.txt 2>&1 || true',
      '  aws s3 cp /var/log/cloud-init-output.log "$DIAG_S3/$stamp-cloud-init.log" --only-show-errors || true',
      '  aws s3 cp /tmp/diag.txt "$DIAG_S3/$stamp-diag.txt" --only-show-errors || true',
      '}',
      'trap dump_diagnostics ERR EXIT',
      // Retry: a mount target or file server can report available before it answers.
      'r() { for i in $(seq 1 24); do "$@" && return 0; sleep 10; done; return 1; }',
      'notroot() { test "$(stat -c %d "$1")" != "$(stat -c %d /)"; }',

      'mkdir -p /mnt/host-facts /mnt/e5 /mnt/e5-ctl /mnt/e5-seed/efs /mnt/e5-seed/openzfs /mnt/e5-seed/ontap /mnt/fsx-lustre',
      'stat -c %d / > /mnt/host-facts/root-dev',
      'dnf install -y amazon-efs-utils lustre-client',
      `echo ${hostFile('seed.py')} | base64 -d | gunzip > /usr/local/bin/e5-seed`,
      `echo ${hostFile('hostctl.sh')} | base64 -d | gunzip > /usr/local/bin/e5-hostctl`,
      'chmod +x /usr/local/bin/e5-seed /usr/local/bin/e5-hostctl',

      `NFS=${nfsOpts}`,
      `EFS_ID=${fileSystem.fileSystemId}`,
      `EFS_DNS=${fileSystem.fileSystemId}.efs.${region}.amazonaws.com`,
      `OZ_DNS=${openzfs.attrDnsName}`,
      `LUSTRE_HOST=${lustre.dnsName}`,
      'for i in $(seq 1 30); do getent hosts "$EFS_DNS" && break || sleep 5; done',
      `ONTAP_DNS=$(aws fsx describe-storage-virtual-machines --region ${region} --storage-virtual-machine-ids ${svm.attrStorageVirtualMachineId} --query 'StorageVirtualMachines[0].Endpoints.Nfs.DNSName' --output text)`,
      'test -n "$ONTAP_DNS" && test "$ONTAP_DNS" != None',

      // --- 1. seed, through mounts that will never be measured --------------------
      'r mount -t nfs4 -o $NFS,noresvport "$EFS_DNS":/ /mnt/e5-seed/efs',
      'r mount -t nfs -o $NFS "$OZ_DNS":/fsx /mnt/e5-seed/openzfs',
      'r mount -t nfs -o $NFS "$ONTAP_DNS":/vol1 /mnt/e5-seed/ontap',
      `r mount -t lustre -o noatime,flock ${lustre.dnsName}@tcp:/${lustre.mountName} /mnt/fsx-lustre`,
      'for m in /mnt/e5-seed/efs /mnt/e5-seed/openzfs /mnt/e5-seed/ontap /mnt/fsx-lustre; do notroot $m; done',
      // One seeder per tree root, in parallel; `wait <pid>` under set -e fails the
      // boot if any seeder fails. default/ also gets an empty conf/, where the
      // conformance gate runs without touching the measured tree.
      'seed() { local base=$1 tier=$2; shift 2; for c in "$@"; do',
      '  e5-seed $([ $c = default ] && echo --conf) "$base/$c" | sed "s/^/$tier,/"; done > /tmp/seed-$tier.txt; }',
      'P=()',
      `seed /mnt/e5-seed/efs/e5-plain efs_host_plain ${nfsCohorts} & P+=($!)`,
      `seed /mnt/e5-seed/efs/e5-tls efs_host_tls ${nfsCohorts} & P+=($!)`,
      `seed /mnt/e5-seed/openzfs/e5 fsx_openzfs ${nfsCohorts} & P+=($!)`,
      `seed /mnt/e5-seed/ontap/e5 fsx_ontap ${nfsCohorts} & P+=($!)`,
      `seed /mnt/fsx-lustre/e5 fsx_lustre ${dirCohorts} & P+=($!)`,
      `seed /mnt/e5/ebs ebs ${dirCohorts} & P+=($!)`,
      'for p in "${P[@]}"; do wait "$p"; done',
      `cat ${TIERS.map((t) => `/tmp/seed-${t}.txt`).join(' ')} > /mnt/host-facts/seed-manifest`,
      // Every tree complete, and all of them there. A short seed would fail a stat
      // mid-cohort, which agebench treats as fatal: better to fail the boot.
      `test "$(awk -F, '$4 != 1000' /mnt/host-facts/seed-manifest | wc -l)" -eq 0`,
      `test "$(wc -l < /mnt/host-facts/seed-manifest)" -eq ${nfsTiers.length * NFS_COHORTS.length + 2 * DIR_COHORTS.length}`,

      // --- 2. forget it all --------------------------------------------------------
      'umount /mnt/e5-seed/efs /mnt/e5-seed/openzfs /mnt/e5-seed/ontap',
      // Cancels the client's DLM locks, and the pages and attributes they cover:
      // Lustre's equivalent of unmounting the seed mount.
      'lctl set_param ldlm.namespaces.*.lru_size=clear',
      'lctl get_param ldlm.namespaces.*.lru_max_age ldlm.namespaces.*.lru_size llite.*.statahead_max > /mnt/host-facts/lustre-params 2>&1 || true',
      'sync; echo 3 > /proc/sys/vm/drop_caches',
      // --- 3. the age gate's reference ---------------------------------------------
      'date +%s > /mnt/host-facts/seed-epoch',

      // --- 4. one superblock per cohort ---------------------------------------------
      // forced, and only forced, zeroes the FILE attribute timers; directory timers
      // stay at their defaults everywhere (actimeo=0 is rejected in the README).
      `for c in ${nfsCohorts}; do`,
      '  o=nosharecache; [ $c = forced ] && o=$o,acregmin=0,acregmax=0',
      `  for t in ${nfsTiers.join(' ')}; do mkdir -p /mnt/e5/$t/$c; done`,
      '  r mount -t nfs4 -o $NFS,noresvport,$o "$EFS_DNS":/e5-plain/$c /mnt/e5/efs_host_plain/$c',
      // Through the EFS mount helper's TLS proxy: what production ECS+EFS runs.
      '  r mount -t efs -o tls,$o "$EFS_ID":/e5-tls/$c /mnt/e5/efs_host_tls/$c',
      '  r mount -t nfs -o $NFS,$o "$OZ_DNS":/fsx/e5/$c /mnt/e5/fsx_openzfs/$c',
      '  r mount -t nfs -o $NFS,$o "$ONTAP_DNS":/vol1/e5/$c /mnt/e5/fsx_ontap/$c',
      'done',
      // Lustre: one client per file system, so a bind of the seeded subtree.
      'mkdir -p /mnt/e5/fsx_lustre && mount --bind /mnt/fsx-lustre/e5 /mnt/e5/fsx_lustre',
      // Fail closed on the host too: every NFS cohort is a mount, none shares a
      // superblock. The task repeats this and also checks the options.
      `D=$(for t in ${nfsTiers.join(' ')}; do for c in ${nfsCohorts}; do notroot /mnt/e5/$t/$c; stat -c %d /mnt/e5/$t/$c; done; done)`,
      `test "$(echo "$D" | sort -u | wc -l)" -eq ${nfsTiers.length * NFS_COHORTS.length}`,
      'findmnt -t nfs,nfs4,lustre -o TARGET,SOURCE,FSTYPE,OPTIONS > /mnt/host-facts/mounts.txt',
      'chmod -R 755 /mnt/host-facts && chmod 777 /mnt/e5-ctl',
      'systemd-run --unit=e5-hostctl /usr/local/bin/e5-hostctl /mnt/e5-ctl',
    );

    // cfn-signal must be last (see E2).
    const cfnAsg = asg.node.defaultChild as autoscaling.CfnAutoScalingGroup;
    asg.addUserData(
      'dnf install -y aws-cfn-bootstrap',
      `/opt/aws/bin/cfn-signal --exit-code $? --stack ${Stack.of(this).stackName} ` +
        `--resource ${cfnAsg.logicalId} --region ${region}`,
    );

    // --- the task -----------------------------------------------------------------
    const taskDefinition = new ecs.Ec2TaskDefinition(this, 'TaskDefinition', {
      networkMode: ecs.NetworkMode.AWS_VPC,
    });
    taskDefinition.addVolume({ name: 'e5', host: { sourcePath: '/mnt/e5' } });
    taskDefinition.addVolume({ name: 'host-facts', host: { sourcePath: '/mnt/host-facts' } });
    taskDefinition.addVolume({ name: 'e5-ctl', host: { sourcePath: '/mnt/e5-ctl' } });
    const container = taskDefinition.addContainer('bench', {
      image: benchImage,
      memoryReservationMiB: 512,
      cpu: 1024,
      environment: {
        BENCH_MODE: 'e5',
        E5_TIERS: TIERS.join(' '),
        E5_INTERVALS: '0.1 1 10',
        BENCH_S3_BUCKET: resultsBucket.bucketName,
        BENCH_ARM: 'ec2',
      },
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e5-ec2', logGroup }),
    });
    // /mnt/e5 holds ~20 NFS mounts made at boot. A host volume is a Docker bind,
    // which is recursive, so they appear under /e5. Not taken on trust: the task's
    // mount check fails if any cohort is not its own NFS superblock.
    container.addMountPoints(
      { containerPath: '/e5', sourceVolume: 'e5', readOnly: false },
      { containerPath: '/bench/host-facts', sourceVolume: 'host-facts', readOnly: true },
      { containerPath: '/e5-ctl', sourceVolume: 'e5-ctl', readOnly: false },
    );
    resultsBucket.grantWrite(taskDefinition.taskRole);

    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'Ec2TaskDefinitionArn', { value: taskDefinition.taskDefinitionArn });
    new CfnOutput(this, 'CapacityProviderName', { value: capacityProvider.capacityProviderName });
    new CfnOutput(this, 'LogGroupName', { value: logGroup.logGroupName });
    new CfnOutput(this, 'SubnetId', { value: subnetId });
    new CfnOutput(this, 'SecurityGroupId', { value: workloadSecurityGroup.securityGroupId });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
    new CfnOutput(this, 'AsgName', { value: asg.autoScalingGroupName });
    new CfnOutput(this, 'InstanceType', { value: instanceType.toString() });
    new CfnOutput(this, 'ResultsBucketName', { value: resultsBucket.bucketName });
    new CfnOutput(this, 'FsxOntapSvmId', { value: svm.attrStorageVirtualMachineId });
  }
}

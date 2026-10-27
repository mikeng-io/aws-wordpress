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
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';

export interface E5AttributeCacheProps extends ExperimentStackProps {
  /** E2's instance, so prediction 1 compares an identical client. */
  readonly instanceType?: ec2.InstanceType;
}

/** NFS tiers: five mounts each, one superblock per cohort family. */
const NFS_TIERS = ['efs_host_plain', 'efs_host_tls', 'fsx_openzfs', 'fsx_ontap'] as const;
/** Mount families. `default` serves cohort A1-A7, `forced` A8, `ss-<delta>` cohort B. */
const FAMILIES = ['default', 'forced', 'ss-0.1', 'ss-1', 'ss-10'] as const;
const SUBTREE: Record<(typeof FAMILIES)[number], string> = {
  default: 'a', forced: 'forced', 'ss-0.1': 'ss-0.1', 'ss-1': 'ss-1', 'ss-10': 'ss-10',
};
/** Lustre and EBS have one mount each, so their families are subtrees of it. No `forced`: it is an NFS option. */
const SINGLE_MOUNT_SUBTREES = ['a', 'ss-0.1', 'ss-1', 'ss-10'];

/**
 * E5 - what does an NFS stat() cost once the file is old?
 *
 * See experiments/E5-attribute-cache/README.md. E2 found that bench.c's NFS stat
 * numbers were the client attribute cache: it stats files seconds after creating
 * them. E5 measures files the client did not create, on mounts that have never seen
 * them, with the RPC counters checked around every cohort.
 *
 * COPIED from e2-storage-matrix.ts, not factored out of it. The README allowed a
 * shared module only if `cdk synth E2-StorageMatrix-dev` stayed byte-identical; a
 * copy carries no risk of moving E2's template, and E2 is complete. What is carried
 * over unchanged: the VPC and endpoint set, the EFS file system, all three FSx file
 * systems with their security-group dependency, backup and snapshot settings, the
 * diagnostics trap, and the host-facts root-dev record. What differs: no Fargate arm,
 * no instance store, no ECS-managed EFS volumes, and the mount layout below.
 */
export class E5AttributeCacheStack extends ExperimentStack {
  constructor(scope: Construct, id: string, props: E5AttributeCacheProps) {
    super(scope, id, props);
    const diagnostic = this.node.tryGetContext('e5Diagnostic') === '1';

    const instanceType = props.instanceType ?? ec2.InstanceType.of(
      ec2.InstanceClass.C7GD,
      ec2.InstanceSize.LARGE,
    );

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
    endpointSecurityGroup.addIngressRule(
      workloadSecurityGroup,
      ec2.Port.tcp(443),
      'HTTPS from the benchmark workloads only',
    );

    // E2's twelve, unchanged. None of them was there only for Fargate: the ECS agent
    // and telemetry endpoints are the EC2 arm's, SSM reads the host, CloudFormation
    // carries cfn-signal, EFS and FSx serve the boot-time mount and describe calls.
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

    // --- EFS, as E2 -----------------------------------------------------------
    const fileSystemSecurityGroup = new ec2.SecurityGroup(this, 'FileSystemSecurityGroup', {
      vpc,
      description: 'E5 EFS mount target',
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
    // RETAINed so boot evidence survives a rollback, as in E2. Unlike E2, collect.sh
    // copies it into the replication and then deletes the bucket once the stack is
    // gone: E2's seven retained buckets were never removed by anything.
    const diagnosticsBucket = new s3.Bucket(this, 'DiagnosticsBucket', {
      removalPolicy: RemovalPolicy.RETAIN,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      lifecycleRules: [{ expiration: Duration.days(14) }],
    });

    // --- FSx, E2's three arms unchanged -----------------------------------------
    const fsxSecurityGroup = new ec2.SecurityGroup(this, 'FsxSecurityGroup', {
      vpc,
      description: 'E5 FSx file systems',
      allowAllOutbound: false,
    });
    fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcp(2049), 'NFS (OpenZFS, ONTAP)');
    fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcp(988), 'Lustre LNet');
    fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcpRange(1018, 1023), 'Lustre management');
    fsxSecurityGroup.addIngressRule(fsxSecurityGroup, ec2.Port.allTraffic(), 'FSx internal');
    // LNet is bidirectional; see e2-storage-matrix.ts for what each rule cost to learn.
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

    // --- the host --------------------------------------------------------------
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
      // E2's 10 minutes plus seeding: ~10,000 EFS creates at several ms each, which
      // runs in parallel with the FSx seeds but is the long pole.
      signals: autoscaling.Signals.waitForMinCapacity({ timeout: Duration.minutes(25) }),
    });
    asg.role.addManagedPolicy(iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'));
    asg.node.addDependency(fileSystem.mountTargetsAvailable);
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

    const region = Stack.of(this).region;
    // E2's production NFS options, unchanged. noresvport only on EFS, as in E2.
    const nfsOpts = 'nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2';
    const familyOpts = (family: string) =>
      family === 'forced' ? ',nosharecache,acregmin=0,acregmax=0' : ',nosharecache';
    // How each NFS tier mounts. `$1` is the extra options, `$2` the mount point.
    const mountCmd: Record<(typeof NFS_TIERS)[number], (extra: string, at: string) => string> = {
      efs_host_plain: (x, at) => `mount -t nfs4 -o ${nfsOpts},noresvport${x} "$EFS_DNS":/ ${at}`,
      efs_host_tls: (x, at) => `mount -t efs -o tls${x} "$EFS_ID":/ ${at}`,
      fsx_openzfs: (x, at) => `mount -t nfs -o ${nfsOpts}${x} ${openzfs.attrDnsName}:/fsx ${at}`,
      fsx_ontap: (x, at) => `mount -t nfs -o ${nfsOpts}${x} "$ONTAP_DNS":/vol1 ${at}`,
    };
    const retry = (cmd: string) => `for i in $(seq 1 24); do ${cmd} && break || sleep 10; done`;
    const isMount = (at: string) => `test "$(stat -c %d ${at})" != "$(stat -c %d /)"`;
    const seeder = fs.readFileSync(path.join(__dirname, 'bench', 'e5-seed.py'), 'utf8');
    if (seeder.includes('E5SEED_EOF')) throw new Error('e5-seed.py contains the heredoc terminator');

    const diagnosticSubtrees = (base: string, tier: string) => diagnostic ? [
      ...['2','3'].flatMap((r) => ['0.1','1','10'].map((d) => `${base}/ss-${d}/diag-round-${r}`)),
      ...(tier === 'fsx_lustre' ? ['1','4'].map((r) => `${base}/ss-0.1/diag-round-${r}`) : []),
      ...(tier === 'efs_host_tls' ? ['on','off'].flatMap((m) => ['0.1','1','10'].map((d) => `${base}/ss-${d}/diag-tls-${m}`)) : []),
    ] : [];
    const nfsSubtrees = (tier: string, root: string) => [
      ...FAMILIES.map((f) => `${root}/e5/${tier}/${SUBTREE[f]}`),
      ...diagnosticSubtrees(`${root}/e5/${tier}`, tier),
    ].join(' ');
    const singleSubtrees = (base: string, tier: string) => [
      ...SINGLE_MOUNT_SUBTREES.map((s) => `${base}/${s}`), ...diagnosticSubtrees(base,tier),
    ].join(' ');

    asg.addUserData(
      'set -euxo pipefail',
      `DIAG_S3=s3://${diagnosticsBucket.bucketName}/e5-diagnostics`,
      'dump_diagnostics() {',
      '  local stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)-$(hostname)',
      '  { echo "--- mounts ---"; findmnt -t nfs,nfs4,lustre,xfs,ext4 -o TARGET,SOURCE,FSTYPE,OPTIONS 2>&1;',
      '    echo "--- dmesg lustre/lnet/nfs ---"; dmesg 2>&1 | grep -i -E "lustre|lnet|nfs" | tail -60;',
      '    echo "--- seed log ---"; cat /var/log/e5-seed.log 2>&1;',
      '  } > /tmp/diag.txt 2>&1 || true',
      '  aws s3 cp /var/log/cloud-init-output.log "$DIAG_S3/$stamp-cloud-init.log" --only-show-errors || true',
      '  aws s3 cp /tmp/diag.txt "$DIAG_S3/$stamp-diag.txt" --only-show-errors || true',
      ...(diagnostic ? ['  aws s3 cp "$(command -v amazon-efs-mount-watchdog)" "$DIAG_S3/$stamp-watchdog-source.py" --only-show-errors || true'] : []),
      '}',
      'trap dump_diagnostics ERR EXIT',

      'mkdir -p /mnt/host-facts',
      'stat -c %d / > /mnt/host-facts/root-dev',
      'cat > /usr/local/bin/e5-seed <<\'E5SEED_EOF\'',
      seeder.trimEnd(),
      'E5SEED_EOF',
      'chmod +x /usr/local/bin/e5-seed',

      'dnf install -y amazon-efs-utils lustre-client',
      `EFS_ID=${fileSystem.fileSystemId}`,
      `EFS_DNS=${fileSystem.fileSystemId}.efs.${region}.amazonaws.com`,
      'for i in $(seq 1 30); do getent hosts "$EFS_DNS" && break || sleep 5; done',
      `ONTAP_DNS=$(aws fsx describe-storage-virtual-machines --region ${region} --storage-virtual-machine-ids ${svm.attrStorageVirtualMachineId} --query 'StorageVirtualMachines[0].Endpoints.Nfs.DNSName' --output text)`,
      'test -n "$ONTAP_DNS" && test "$ONTAP_DNS" != "None"',
      `LUSTRE_HOST=${lustre.dnsName}`,

      // --- seed: through mounts that are unmounted before anything is measured ----
      // EFS is seeded once for both EFS tiers (one file system, two subtrees).
      'mkdir -p /mnt/e5-seed/efs /mnt/e5-seed/fsx_openzfs /mnt/e5-seed/fsx_ontap /mnt/e5/fsx_lustre /mnt/e5-ebs',
      retry(`mount -t nfs4 -o ${nfsOpts},noresvport "$EFS_DNS":/ /mnt/e5-seed/efs`),
      retry(`mount -t nfs -o ${nfsOpts} ${openzfs.attrDnsName}:/fsx /mnt/e5-seed/fsx_openzfs`),
      retry(`mount -t nfs -o ${nfsOpts} "$ONTAP_DNS":/vol1 /mnt/e5-seed/fsx_ontap`),
      // Lustre has one client per file system, so its one mount is also its
      // measurement mount; its seeding cache is cleared below instead.
      retry(`mount -t lustre -o noatime,flock ${lustre.dnsName}@tcp:/${lustre.mountName} /mnt/e5/fsx_lustre`),
      ...['/mnt/e5-seed/efs', '/mnt/e5-seed/fsx_openzfs', '/mnt/e5-seed/fsx_ontap', '/mnt/e5/fsx_lustre'].map(isMount),
      // Four seeders in parallel, one per file system; every exit status is checked.
      '{',
      `  e5-seed ${nfsSubtrees('efs_host_plain', '/mnt/e5-seed/efs')} ${nfsSubtrees('efs_host_tls', '/mnt/e5-seed/efs')} & p1=$!`,
      `  e5-seed ${nfsSubtrees('fsx_openzfs', '/mnt/e5-seed/fsx_openzfs')} & p2=$!`,
      `  e5-seed ${nfsSubtrees('fsx_ontap', '/mnt/e5-seed/fsx_ontap')} & p3=$!`,
      `  e5-seed ${singleSubtrees('/mnt/e5/fsx_lustre/e5/fsx_lustre','fsx_lustre')} & p4=$!`,
      `  e5-seed ${singleSubtrees('/mnt/e5-ebs','ebs')}`,
      '  wait $p1 && wait $p2 && wait $p3 && wait $p4',
      '} > /var/log/e5-seed.log 2>&1',
      'mkdir -p /mnt/e5/fsx_lustre/e5/fsx_lustre/conf /mnt/e5-ebs/conf',
      // Only the conformance directories are opened up. A recursive chmod over the
      // trees would be ~10,000 SETATTRs on EFS for nothing: the task runs as root.
      'chmod 777 /mnt/e5-seed/*/e5/*/a/conf /mnt/e5/fsx_lustre/e5/fsx_lustre/conf /mnt/e5-ebs/conf',
      'sync',
      // The age gate reads this; it is written by the host, not through a mount.
      'date +%s > /mnt/host-facts/seed-utc',
      'umount /mnt/e5-seed/efs /mnt/e5-seed/fsx_openzfs /mnt/e5-seed/fsx_ontap',
      // Lustre: cancel every DLM lock, which drops the pages and attributes they
      // cover. EBS and anything else: drop clean caches host-wide.
      'lctl set_param ldlm.namespaces.*.lru_size=clear',
      'sync && echo 3 > /proc/sys/vm/drop_caches',

      // --- measurement mounts: five per NFS tier, each its own superblock ----------
      ...NFS_TIERS.flatMap((tier) => FAMILIES.flatMap((family) => {
        const at = `/mnt/e5/${tier}/${family}`;
        return [`mkdir -p ${at}`, retry(mountCmd[tier](familyOpts(family), at)), isMount(at)];
      })),
      'chmod -R 755 /mnt/host-facts',
    );

    const cfnAsg = asg.node.defaultChild as autoscaling.CfnAutoScalingGroup;
    asg.addUserData(
      'dnf install -y aws-cfn-bootstrap',
      `/opt/aws/bin/cfn-signal --exit-code $? --stack ${Stack.of(this).stackName} ` +
        `--resource ${cfnAsg.logicalId} --region ${region}`,
    );

    // --- the task ----------------------------------------------------------------
    const taskDefinition = new ecs.Ec2TaskDefinition(this, 'TaskDefinition', {
      networkMode: ecs.NetworkMode.AWS_VPC,
      ...(diagnostic ? { pidMode: ecs.PidMode.HOST } : {}),
    });
    const binds: Array<[name: string, hostPath: string]> = [
      ['ebs', '/mnt/e5-ebs'],
      ['fsx_lustre', '/mnt/e5/fsx_lustre/e5/fsx_lustre'],
      ...NFS_TIERS.flatMap((tier) => FAMILIES.map((family): [string, string] =>
        [`${tier}.${family}`, `/mnt/e5/${tier}/${family}/e5/${tier}/${SUBTREE[family]}`])),
    ];
    const volName = (name: string) => `e5-${name.replace(/[^a-zA-Z0-9]/g, '-')}`;
    for (const [name, hostPath] of binds) {
      taskDefinition.addVolume({ name: volName(name), host: { sourcePath: hostPath } });
    }
    taskDefinition.addVolume({ name: 'host-facts', host: { sourcePath: '/mnt/host-facts' } });
    taskDefinition.addVolume({ name: 'cache-ctl' });

    const container = taskDefinition.addContainer('bench', {
      image: benchImage,
      memoryReservationMiB: 512,
      cpu: 1024,
      environment: {
        BENCH_MODE: diagnostic ? 'e5-diagnostic' : 'e5',
        // e5-run shuffles at tier level and records it; entrypoint's per-mount
        // shuffle would only scramble the mount-facts list.
        BENCH_SHUFFLE: '0',
        BENCH_MOUNTS: binds.map(([name]) => `${name}=/bench/${name}`).join(' '),
        E5_TIERS: ['ebs', ...NFS_TIERS, 'fsx_lustre'].join(' '),
        E5_NFS_TIERS: NFS_TIERS.join(' '),
        BENCH_S3_BUCKET: resultsBucket.bucketName,
        BENCH_ARM: 'ec2',
      },
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e5-ec2', logGroup }),
    });
    for (const [name] of binds) {
      container.addMountPoints({ containerPath: `/bench/${name}`, sourceVolume: volName(name), readOnly: false });
    }
    container.addMountPoints({ containerPath: '/bench/host-facts', sourceVolume: 'host-facts', readOnly: true });

    // E2's privileged sidecar, here for one job: reading the Lustre client's counters,
    // which an unprivileged container is not assumed to be able to. The benchmark
    // stays unprivileged so its seccomp filter, and so its per-syscall cost, is E2's.
    const sidecar = taskDefinition.addContainer('cache-dropper', {
      image: benchImage,
      entryPoint: ['/usr/local/bin/cache-dropper'],
      privileged: true,
      essential: false,
      ...(diagnostic ? { environment: { E5_DIAGNOSTIC: '1' } } : {}),
      memoryReservationMiB: 32,
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e5-sidecar', logGroup }),
    });
    if (diagnostic) {
      taskDefinition.addVolume({ name: 'helper-config', host: { sourcePath: '/etc/amazon/efs' } });
      taskDefinition.addVolume({ name: 'tls-roots', host: { sourcePath: '/mnt/e5/efs_host_tls' } });
      sidecar.addMountPoints({ containerPath: '/host-efs', sourceVolume: 'helper-config', readOnly: false });
      sidecar.addMountPoints({ containerPath: '/mnt/e5/efs_host_tls', sourceVolume: 'tls-roots', readOnly: true });
    }
    for (const c of [container, sidecar]) {
      c.addMountPoints({ containerPath: '/bench/cache-ctl', sourceVolume: 'cache-ctl', readOnly: false });
    }
    container.addContainerDependencies({ container: sidecar, condition: ecs.ContainerDependencyCondition.START });
    resultsBucket.grantWrite(taskDefinition.taskRole);

    new CfnOutput(this, 'ClusterName', { value: cluster.clusterName });
    new CfnOutput(this, 'TaskDefinitionArn', { value: taskDefinition.taskDefinitionArn });
    new CfnOutput(this, 'CapacityProviderName', { value: capacityProvider.capacityProviderName });
    new CfnOutput(this, 'LogGroupName', { value: logGroup.logGroupName });
    new CfnOutput(this, 'SubnetId', { value: subnetId });
    new CfnOutput(this, 'SecurityGroupId', { value: workloadSecurityGroup.securityGroupId });
    new CfnOutput(this, 'FileSystemId', { value: fileSystem.fileSystemId });
    new CfnOutput(this, 'AsgName', { value: asg.autoScalingGroupName });
    new CfnOutput(this, 'InstanceType', { value: instanceType.toString() });
    new CfnOutput(this, 'ResultsBucketName', { value: resultsBucket.bucketName });
    new CfnOutput(this, 'DiagnosticsBucketName', { value: diagnosticsBucket.bucketName });
    new CfnOutput(this, 'FsxOpenZfsDns', { value: openzfs.attrDnsName });
    new CfnOutput(this, 'FsxLustreDns', { value: lustre.dnsName });
    new CfnOutput(this, 'FsxOntapSvmId', { value: svm.attrStorageVirtualMachineId });
  }
}

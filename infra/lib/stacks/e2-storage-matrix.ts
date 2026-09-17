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
import * as path from 'node:path';
import { Construct } from 'constructs';
import { ExperimentStack, ExperimentStackProps } from '../experiment-stack.js';

export interface E2StorageMatrixProps extends ExperimentStackProps {
  /** Instance type for the EC2 arm. Must carry NVMe instance store (a `*d` type). */
  readonly instanceType?: ec2.InstanceType;
  /**
   * Include the three FSx arms. Off by default because they dominate both the cost
   * (~$0.67/hr against ~$0.29 without) and the deploy time - ONTAP alone takes
   * 20-30 minutes to create, which turns a replication cycle from ~14 minutes into
   * ~45. Iterating on the apparatus without them is much faster.
   */
  readonly includeFsx?: boolean;
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

    // Results land in S3, not in the task log. Three tiers is ~12,000 CSV lines,
    // the awslogs driver emits one CloudWatch event per line, and a single
    // GetLogEvents call caps at 10,000 - so the last tier silently disappeared
    // from collection while the task still exited 0. The bucket is torn down with
    // the stack; the results are pulled out before that happens.
    const resultsBucket = new s3.Bucket(this, 'ResultsBucket', {
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
    });

    // --- FSx arms: the server-backed tiers AWS manages for you ----------------
    //
    // All three are the cheapest DEFENSIBLE configuration, chosen and costed in the
    // experiment README before anything was built: Single-AZ throughout, since this
    // is apparatus rather than production and replication would add cost without
    // changing what is measured.
    //
    // Mount options are held identical to the EFS arms wherever the protocol allows
    // (nfsvers=4.1, 1 MiB rsize/wsize, hard, timeo=600). That is the whole point -
    // if the tiers were tuned differently the comparison would measure tuning rather
    // than protocol, which is the confound this experiment exists to avoid.
    // Identical to the EFS arms except for one flag, and the exception is forced
    // rather than chosen: EFS *requires* `noresvport`, and FSx OpenZFS *rejects* it -
    // its default export demands a reserved source port, so the mount fails with
    // "mount.nfs: Operation not permitted". Dropped from both FSx NFS arms so those
    // two are identical to each other. It selects a source port and does not touch
    // the data path, so it is not a performance variable.
    const fsxMountOptions = 'nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2';
    // Outlives this stack, so it still holds the logs after a rollback.
    const diagnosticsBucketName = `cdk-hnb659fds-assets-${Stack.of(this).account}-${Stack.of(this).region}`;
    const fsxMounts: string[] = [];
    const fsxUserData: string[] = [];

    if (props.includeFsx) {
      const fsxSecurityGroup = new ec2.SecurityGroup(this, 'FsxSecurityGroup', {
        vpc,
        description: 'E2 FSx file systems',
        allowAllOutbound: false,
      });
      fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcp(2049), 'NFS (OpenZFS, ONTAP)');
      // Lustre is not NFS: LNet uses 988 for the data path and 1021-1023 for the
      // management traffic, so an NFS-shaped rule would silently fail to mount.
      fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcp(988), 'Lustre LNet');
      fsxSecurityGroup.addIngressRule(workloadSecurityGroup, ec2.Port.tcpRange(1018, 1023), 'Lustre management');
      // FSx file servers talk to each other and back to clients on the same ports.
      fsxSecurityGroup.addIngressRule(fsxSecurityGroup, ec2.Port.allTraffic(), 'FSx internal');
      // Lustre's LNet is BIDIRECTIONAL: the file servers open connections back to
      // the client, so an outbound-only client rule is not enough. Without these the
      // mount fails with "client profile could not be read from the MGS", which
      // reads like a wrong filesystem name rather than a firewall.
      workloadSecurityGroup.addIngressRule(fsxSecurityGroup, ec2.Port.tcp(988), 'Lustre LNet back to client');
      workloadSecurityGroup.addIngressRule(fsxSecurityGroup, ec2.Port.tcpRange(1018, 1023), 'Lustre management back to client');

      const subnetId = vpc.isolatedSubnets[0].subnetId;

      // OpenZFS: 64 GiB / 64 MBps is the documented floor, and the only FSx arm
      // that can be sized anywhere near the actual working set.
      const openzfs = new fsx.CfnFileSystem(this, 'FsxOpenZfs', {
        fileSystemType: 'OPENZFS',
        subnetIds: [subnetId],
        securityGroupIds: [fsxSecurityGroup.securityGroupId],
        storageCapacity: 64,
        storageType: 'SSD',
        openZfsConfiguration: {
          deploymentType: 'SINGLE_AZ_1',
          throughputCapacity: 64,
          rootVolumeConfiguration: {
            // no_root_squash: the benchmark container runs as root and would
            // otherwise be squashed to nobody, failing every write as a permission
            // error that looks like a filesystem defect.
            nfsExports: [{
              clientConfigurations: [{ clients: '*', options: ['rw', 'crossmnt', 'no_root_squash'] }],
            }],
          },
        },
      });

      // Lustre Scratch: the throughput-marketed configuration prediction 1 names
      // explicitly. 1200 GiB is the floor - it cannot be bought smaller.
      const lustre = new fsx.LustreFileSystem(this, 'FsxLustre', {
        vpc,
        vpcSubnet: vpc.isolatedSubnets[0],
        securityGroup: fsxSecurityGroup,
        storageCapacityGiB: 1200,
        lustreConfiguration: { deploymentType: fsx.LustreDeploymentType.SCRATCH_2 },
        removalPolicy: RemovalPolicy.DESTROY,
      });

      // ONTAP is three resources, not one: a file system, a storage virtual machine
      // that owns the NFS endpoint, and a volume with a junction path to mount.
      const ontap = new fsx.CfnFileSystem(this, 'FsxOntap', {
        fileSystemType: 'ONTAP',
        subnetIds: [subnetId],
        securityGroupIds: [fsxSecurityGroup.securityGroupId],
        storageCapacity: 1024,
        storageType: 'SSD',
        ontapConfiguration: {
          // First generation: its throughput floor is 128 MBps against
          // second-generation's 384, which makes it the cheaper arm.
          deploymentType: 'SINGLE_AZ_1',
          throughputCapacity: 128,
          preferredSubnetId: subnetId,
        },
      });
      const svm = new fsx.CfnStorageVirtualMachine(this, 'FsxOntapSvm', {
        fileSystemId: ontap.ref,
        name: 'e2svm',
        rootVolumeSecurityStyle: 'UNIX',
      });
      const ontapVolume = new fsx.CfnVolume(this, 'FsxOntapVolume', {
        name: 'e2vol',
        volumeType: 'ONTAP',
        ontapConfiguration: {
          storageVirtualMachineId: svm.attrStorageVirtualMachineId,
          junctionPath: '/vol1',
          sizeInBytes: String(64 * 1024 * 1024 * 1024),
          securityStyle: 'UNIX',
          tieringPolicy: { name: 'NONE' },
          // Required by the FSx API even though CDK's L1 types mark it optional -
          // omitting it fails the deploy with a BadRequest, not a synth error.
          //
          // Set FALSE deliberately. Storage efficiency is ONTAP's dedup/compression
          // layer; leaving it on would mean measuring that engine rather than the
          // filesystem, and the benchmark tree is highly compressible small files,
          // which is exactly the shape that would flatter it.
          storageEfficiencyEnabled: 'false',
        },
      });

      fsxUserData.push(
        'mkdir -p /mnt/fsx-openzfs /mnt/fsx-lustre /mnt/fsx-ontap',
        `for i in $(seq 1 24); do mount -t nfs -o ${fsxMountOptions} ${openzfs.attrDnsName}:/fsx /mnt/fsx-openzfs && break || sleep 10; done`,
        // Lustre needs its kernel module, which is in AL2023's own S3-backed repo -
        // so it installs through the gateway endpoint with no NAT. The running
        // kernel (6.1.182) is well past the documented 6.1.79 minimum.
        'dnf install -y lustre-client',
        // -o flock is REQUIRED for POSIX locking on Lustre; without it flock(2) is
        // silently a no-op and the conformance gate would report a lock failure that
        // is a configuration choice rather than a property of the filesystem.
        `LUSTRE_HOST=${lustre.dnsName}`,
        `for i in $(seq 1 24); do mount -t lustre -o noatime,flock ${lustre.dnsName}@tcp:/${lustre.mountName} /mnt/fsx-lustre && break || sleep 10; done`,
        // The ONTAP NFS endpoint is asked for rather than string-built: the DNS name
        // is derived from ids in a format that is easy to get subtly wrong, and a
        // wrong name fails as a timeout rather than an error.
        `ONTAP_DNS=$(aws fsx describe-storage-virtual-machines --region ${Stack.of(this).region} --storage-virtual-machine-ids ${svm.attrStorageVirtualMachineId} --query 'StorageVirtualMachines[0].Endpoints.Nfs.DNSName' --output text)`,
        'if [ -z "$ONTAP_DNS" ] || [ "$ONTAP_DNS" = "None" ]; then echo "could not resolve ONTAP NFS endpoint" >&2; fi',
        `for i in $(seq 1 24); do mount -t nfs -o ${fsxMountOptions} "$ONTAP_DNS":/vol1 /mnt/fsx-ontap && break || sleep 10; done`,
        // Same fail-closed rule as every other mount: a path that is not really a
        // mount gets measured as the root volume and reported under a tier's name.
        // FATAL, not a warning. The previous version logged and continued, and the
        // stack reported CREATE_COMPLETE with two of three FSx arms silently
        // unmounted - they were ordinary directories on the root volume, writable,
        // and would have benchmarked as "FSx is as fast as EBS". A deployment that
        // cannot mount its arms is not a usable deployment, so cfn-signal must fail.
        // Diagnostics BEFORE the fatal check, and to a bucket outside this stack.
        // A rollback terminates the instance and deletes the stack's own bucket and
        // log group, so a failed deploy previously destroyed the only evidence of
        // why it failed. The CDK bootstrap bucket outlives the stack, which makes it
        // the one durable place to put this.
        `aws s3 cp /var/log/cloud-init-output.log s3://${diagnosticsBucketName}/e2-diagnostics/$(date -u +%Y%m%dT%H%M%SZ)-$(hostname)-cloud-init.log --only-show-errors || true`,
        'findmnt -t nfs,nfs4,lustre -o TARGET,SOURCE,FSTYPE > /tmp/mounts.txt 2>&1 || true',
        // mount.lustre reports "Invalid argument" for every cause, so the useful
        // signal is in the ring buffer and in whether LNet can reach the servers.
        '{ echo "--- dmesg lustre ---"; dmesg 2>&1 | grep -i -E "lustre|lnet" | tail -40; '
          + 'echo "--- lnet ---"; lctl list_nids 2>&1; '
          + `lctl ping ${'${LUSTRE_HOST:-}'} 2>&1; } >> /tmp/mounts.txt || true`,
        `aws s3 cp /tmp/mounts.txt s3://${diagnosticsBucketName}/e2-diagnostics/$(date -u +%Y%m%dT%H%M%SZ)-$(hostname)-mounts.txt --only-show-errors || true`,
        'FSX_MOUNT_FAILURES=0',
        'for m in /mnt/fsx-openzfs /mnt/fsx-lustre /mnt/fsx-ontap; do',
        '  if [ "$(stat -c %d $m)" = "$(stat -c %d /)" ]; then',
        '    echo "FATAL: $m is not a mount - it is a directory on the root volume" >&2',
        '    FSX_MOUNT_FAILURES=$((FSX_MOUNT_FAILURES + 1))',
        '  else',
        '    mkdir -p "$m/bench" && chmod 777 "$m/bench"',
        '  fi',
        'done',
        // Fatal by default - a deployment that cannot mount its arms is not a usable
        // deployment. Overridable ONLY for apparatus debugging
        // (`cdk deploy --context mountFatal=false`), because a rollback terminates the
        // instance and each FSx create/destroy cycle is over an hour; keeping a
        // broken instance alive to iterate on the mount command is far cheaper than
        // guessing across deploys. Never set false for a run that produces results.
        this.node.tryGetContext('mountFatal') === 'false'
          ? 'echo "mountFatal=false: continuing with $FSX_MOUNT_FAILURES unmounted arm(s) - DEBUG ONLY, not valid for results" >&2'
          : 'test "$FSX_MOUNT_FAILURES" -eq 0',
      );

      fsxMounts.push(
        'fsx_openzfs=/bench/fsx-openzfs',
        'fsx_lustre=/bench/fsx-lustre',
        'fsx_ontap=/bench/fsx-ontap',
      );

      ontapVolume.node.addDependency(svm);
      new CfnOutput(this, 'FsxOpenZfsDns', { value: openzfs.attrDnsName });
      new CfnOutput(this, 'FsxLustreDns', { value: lustre.dnsName });
      new CfnOutput(this, 'FsxOntapSvmId', { value: svm.attrStorageVirtualMachineId });
    }

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

    // User data mounts EFS directly, so the mount target has to exist first.
    asg.node.addDependency(fileSystem.mountTargetsAvailable);

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

      // --- host-mounted EFS, the configuration ECS does not give you ---------
      //
      // The ECS-managed efsVolumeConfiguration below mounts EFS once PER TASK,
      // each with its own NFS client and its own efs-proxy TLS process (E1
      // established this directly on the host). Mounting on the host instead and
      // bind-mounting into the container is a materially different topology - one
      // client shared by every container - and it is the configuration H1's
      // original cache-sharing mechanism actually assumed. E1 refuted "ECS does
      // this for you"; it never tested "do it yourself".
      //
      // Two host mounts, because they separate two different costs:
      //   efs-host-tls    same TLS proxy as ECS uses, but one per HOST
      //   efs-host-plain  no TLS at all - isolates what the stunnel hop costs
      'dnf install -y amazon-efs-utils',
      'mkdir -p /mnt/efs-host-tls /mnt/efs-host-plain',
      `EFS_ID=${fileSystem.fileSystemId}`,
      `EFS_DNS=${fileSystem.fileSystemId}.efs.${Stack.of(this).region}.amazonaws.com`,
      // A mount target can report available before it answers, so retry rather
      // than racing it.
      'for i in $(seq 1 30); do getent hosts "$EFS_DNS" && break || sleep 5; done',
      'for i in $(seq 1 12); do mount -t efs -o tls "$EFS_ID":/ /mnt/efs-host-tls && break || sleep 10; done',
      'for i in $(seq 1 12); do mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport "$EFS_DNS":/ /mnt/efs-host-plain && break || sleep 10; done',
      // Same fail-closed rule as the container applies here: a directory that is
      // not actually a mount would be measured as the root volume and reported as
      // EFS, which is the one error that looks like a result.
      'test "$(stat -c %d /mnt/efs-host-tls)" != "$(stat -c %d /)"',
      'test "$(stat -c %d /mnt/efs-host-plain)" != "$(stat -c %d /)"',
      'mkdir -p /mnt/efs-host-tls/bench-tls /mnt/efs-host-plain/bench-plain',
      'chmod 777 /mnt/efs-host-tls/bench-tls /mnt/efs-host-plain/bench-plain',
    );

    if (fsxUserData.length) {
      asg.addUserData(...fsxUserData);
      asg.role.addToPrincipalPolicy(new iam.PolicyStatement({
        // Read-only, and scoped to the one call the boot sequence makes.
        actions: ['fsx:DescribeStorageVirtualMachines', 'fsx:DescribeFileSystems'],
        resources: ['*'],
      }));
      asg.role.addToPrincipalPolicy(new iam.PolicyStatement({
        actions: ['s3:PutObject'],
        resources: [`arn:aws:s3:::${diagnosticsBucketName}/e2-diagnostics/*`],
      }));
    }

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
    // Bind mounts of the host's own EFS mounts. Pointed at a subdirectory rather
    // than the filesystem root so the two arms cannot collide on the same paths.
    ec2TaskDefinition.addVolume({
      name: 'efs-host-tls',
      host: { sourcePath: '/mnt/efs-host-tls/bench-tls' },
    });
    ec2TaskDefinition.addVolume({
      name: 'efs-host-plain',
      host: { sourcePath: '/mnt/efs-host-plain/bench-plain' },
    });
    ec2TaskDefinition.addVolume({
      name: 'efs',
      efsVolumeConfiguration: {
        fileSystemId: fileSystem.fileSystemId,
        transitEncryption: 'ENABLED',
      },
    });
    // The same ECS-managed per-task mount without the efs-proxy hop, so the
    // container-direct row has both halves of the TLS modifier.
    ec2TaskDefinition.addVolume({
      name: 'efs-plain',
      efsVolumeConfiguration: {
        fileSystemId: fileSystem.fileSystemId,
        transitEncryption: 'DISABLED',
      },
    });

    for (const [volName, hostPath] of [
      ['fsx-openzfs', '/mnt/fsx-openzfs/bench'],
      ['fsx-lustre', '/mnt/fsx-lustre/bench'],
      ['fsx-ontap', '/mnt/fsx-ontap/bench'],
    ] as const) {
      if (props.includeFsx) {
        ec2TaskDefinition.addVolume({ name: volName, host: { sourcePath: hostPath } });
      }
    }

    const ec2Container = ec2TaskDefinition.addContainer('bench', {
      image: benchImage,
      memoryReservationMiB: 512,
      cpu: 1024,
      environment: {
        BENCH_MOUNTS: [
          'instance_store=/bench/instance-store', 'ebs=/bench/ebs',
          'efs=/bench/efs', 'efs_plain=/bench/efs-plain',
          'efs_host_tls=/bench/efs-host-tls', 'efs_host_plain=/bench/efs-host-plain',
          ...fsxMounts,
        ].join(' '),
        BENCH_S3_BUCKET: resultsBucket.bucketName,
        BENCH_ARM: 'ec2',
      },
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e2-ec2', logGroup }),
    });
    for (const [containerPath, sourceVolume] of [
      ['/bench/instance-store', 'instance-store'],
      ['/bench/ebs', 'ebs'],
      ['/bench/efs', 'efs'],
      ['/bench/efs-plain', 'efs-plain'],
      ['/bench/efs-host-tls', 'efs-host-tls'],
      ['/bench/efs-host-plain', 'efs-host-plain'],
    ] as const) {
      ec2Container.addMountPoints({ containerPath, sourceVolume, readOnly: false });
    }
    if (props.includeFsx) {
      for (const [containerPath, sourceVolume] of [
        ['/bench/fsx-openzfs', 'fsx-openzfs'],
        ['/bench/fsx-lustre', 'fsx-lustre'],
        ['/bench/fsx-ontap', 'fsx-ontap'],
      ] as const) {
        ec2Container.addMountPoints({ containerPath, sourceVolume, readOnly: false });
      }
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
    fargateTaskDefinition.addVolume({
      name: 'efs-plain',
      efsVolumeConfiguration: {
        fileSystemId: fileSystem.fileSystemId,
        transitEncryption: 'DISABLED',
      },
    });
    const fargateContainer = fargateTaskDefinition.addContainer('bench', {
      image: benchImage,
      environment: {
        // 'ephemeral' is exempt from the entrypoint's root-filesystem check by
        // design: on Fargate the task's own writable layer IS the tier measured.
        BENCH_MOUNTS: 'ephemeral=/bench/ephemeral efs=/bench/efs efs_plain=/bench/efs-plain',
        BENCH_S3_BUCKET: resultsBucket.bucketName,
        BENCH_ARM: 'fargate',
      },
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'e2-fargate', logGroup }),
    });
    for (const [containerPath, sourceVolume] of [
      ['/bench/efs', 'efs'],
      ['/bench/efs-plain', 'efs-plain'],
    ] as const) {
      fargateContainer.addMountPoints({ containerPath, sourceVolume, readOnly: false });
    }

    resultsBucket.grantWrite(ec2TaskDefinition.taskRole);
    resultsBucket.grantWrite(fargateTaskDefinition.taskRole);

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
    new CfnOutput(this, 'ResultsBucketName', { value: resultsBucket.bucketName });
  }
}

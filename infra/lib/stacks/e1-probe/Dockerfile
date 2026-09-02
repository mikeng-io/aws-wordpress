# E1 probe container.
#
# Built as a CDK asset and pushed to the private CDK assets ECR repository, rather
# than referenced from public.ecr.aws directly. The ecr.api and ecr.dkr interface
# endpoints serve PRIVATE repositories only - there is no PrivateLink for ECR
# Public - so a public.ecr.aws reference cannot be pulled from an isolated subnet
# with no internet route. The base image below is resolved at build time, on a
# machine that does have internet.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

# nfs-utils gives nfsstat, which reports per-operation NFS RPC counts. util-linux
# gives findmnt, which shows mount propagation and peer groups. Between them they
# answer whether two tasks share one NFS client.
RUN dnf install -y nfs-utils util-linux procps-ng && dnf clean all

CMD ["sleep", "infinity"]

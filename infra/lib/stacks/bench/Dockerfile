# Shared benchmark image for the storage experiments (E2, E3). One instrument,
# built once: every tier's numbers have to be comparable to every other tier's,
# and a per-experiment copy of bench.c is how that quietly stops being true.
#
# The mounts to measure are named at runtime via BENCH_MOUNTS, so the image is
# identical across experiments and only the task definition differs. Built locally
# and pushed to the private CDK assets repository - same reason as E1's probe:
# ECR Public has no PrivateLink, so it cannot be pulled from an isolated subnet.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

RUN dnf install -y gcc && dnf clean all

COPY bench.c /src/bench.c
RUN gcc -O2 -Wall -o /usr/local/bin/bench /src/bench.c

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

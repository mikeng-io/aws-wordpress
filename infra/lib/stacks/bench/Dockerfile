# Shared benchmark image for the storage experiments (E2, E3). One instrument,
# built once: every tier's numbers have to be comparable to every other tier's,
# and a per-experiment copy of bench.c is how that quietly stops being true.
#
# The mounts to measure are named at runtime via BENCH_MOUNTS, so the image is
# identical across experiments and only the task definition differs. Built locally
# and pushed to the private CDK assets repository - same reason as E1's probe:
# ECR Public has no PrivateLink, so it cannot be pulled from an isolated subnet.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

# awscli-2 comes from AL2023's own repos, which are S3-backed - so it installs
# through the S3 gateway endpoint with no NAT and no public egress.
# util-linux-core supplies flock(1); without it the conformance gate reports a
# missing tool as a filesystem defect, which is the exact misattribution it
# exists to prevent.
RUN dnf install -y gcc awscli-2 util-linux-core nfs-utils && dnf clean all

COPY bench.c /src/bench.c
RUN gcc -O2 -Wall -o /usr/local/bin/bench /src/bench.c
# Installed as `throughput`, not `tput`: ncurses already owns that name.
# E5's instrument. A separate binary so bench.c - E2 and E3's instrument - stays
# byte-identical. See experiments/E5-attribute-cache.
COPY agebench.c /src/agebench.c
RUN gcc -O2 -Wall -Werror -o /usr/local/bin/agebench /src/agebench.c -lm
COPY tput.c /src/tput.c
RUN gcc -O2 -Wall -Werror -pthread -o /usr/local/bin/throughput /src/tput.c

COPY request-drop cache-dropper /usr/local/bin/
COPY conformance.sh /usr/local/bin/conformance
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY e5-run.sh /usr/local/bin/e5-run
RUN chmod +x /usr/local/bin/conformance /usr/local/bin/entrypoint.sh /usr/local/bin/e5-run \
    /usr/local/bin/request-drop /usr/local/bin/cache-dropper
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

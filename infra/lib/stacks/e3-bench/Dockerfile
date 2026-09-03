# E3 apparatus image. One-shot benchmark: builds a small-file tree on two mount
# points (local ephemeral, EFS) and times every op individually. Built locally
# and pushed to the private CDK assets repository - same reason as E1's probe:
# ECR Public has no PrivateLink, so it cannot be pulled from an isolated subnet.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023

RUN dnf install -y gcc && dnf clean all

COPY bench.c /src/bench.c
RUN gcc -O2 -Wall -o /usr/local/bin/bench /src/bench.c

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

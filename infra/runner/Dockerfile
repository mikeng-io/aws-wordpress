# The environment experiments are deployed and collected from: the pinned Node from
# .nvmrc, AWS CLI v2, and a Docker CLI that drives the HOST's daemon through the
# mounted socket (CDK builds the bench image as an asset).
#
# It exists because the workstation's own toolchain drifted: Node 26 instead of the
# pinned 22.17.0, and an x86 AWS CLI v1 first on PATH that cannot execute at all. A
# result is reproducible from a commit only if the thing that produced it is too.
#
# Built for arm64, which is what the study's workstation and every benchmark host
# are. Versions are pinned rather than "latest" for the same reason as everything else.
FROM node:22.17.0-bookworm

ARG AWSCLI_VERSION=2.35.19
ARG DOCKER_VERSION=29.2.1

RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip python3 make git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-aarch64-${AWSCLI_VERSION}.zip" -o /tmp/awscli.zip \
 && unzip -q /tmp/awscli.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/aws /tmp/awscli.zip

# CLI only; the daemon is the host's. Matching the host daemon's version avoids an
# API-version negotiation failure, which surfaces mid-deploy as an asset build error.
RUN curl -fsSL "https://download.docker.com/linux/static/stable/aarch64/docker-${DOCKER_VERSION}.tgz" \
  | tar -xz -C /usr/local/bin --strip-components=1 docker/docker

# The repo is bind-mounted and owned by the host user; without this git refuses it,
# and RUN_ID (which embeds the commit) cannot be computed.
RUN git config --system --add safe.directory '*'

WORKDIR /repo

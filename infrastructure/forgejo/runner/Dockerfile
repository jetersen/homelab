FROM docker.io/library/golang:1.27.1-trixie@sha256:8f58fd67ea075142d947a60e0caa4317746a55118d312f027793d382c7741734 AS dnscontrol
WORKDIR /build
COPY infrastructure/dns/compat/go.mod infrastructure/dns/compat/go.sum ./compat/
RUN cd compat && go mod download
COPY infrastructure/dns/compat/*.go ./compat/
COPY infrastructure/dns/install.sh ./install.sh
RUN cd compat && go test ./... && cd .. && bash install.sh /out

FROM mcr.microsoft.com/dotnet/sdk:10.0.401-noble@sha256:e70cdb7f80b0348f5cb85f19a8f670fca061f033d57eed12fa003d58b0e06317 AS dotnet

FROM docker.io/pulumi/pulumi-base:3.267.0@sha256:78a0f1547f834efe340d2debac8f701e4c828a2c93355197142f04a48d5403bd AS pulumi
FROM ghcr.io/fluxcd/flux-cli:v2.9.5@sha256:704d5529535570a495249b643159c93a9aa88ffca07813c974a54b7ba6edbd86 AS flux
FROM docker.io/orhunp/git-cliff:2.14.2@sha256:1e696a381a1b0366bb6ccbb6bd4e50e73473fda88eab3a757b95e0d0d66c9531 AS git-cliff

FROM docker.io/library/docker:29.8.2-cli@sha256:b1805116a6a86cc591b5d5f60a910a0715cdcc9d18d866ad68b1457ead25c35c AS docker
FROM registry.k8s.io/kubectl:v1.37.1@sha256:b7cab618e281b1ee7484e7b706a96e2135fbb6e072c2a573a7dab4e87d7f2385 AS kubectl
FROM docker.io/library/node:24.21.0-trixie-slim@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66

RUN apt-get update \
    && apt-get install --no-install-recommends -y bash ca-certificates curl git jq openssh-client tar gzip python3 python3-venv libicu76 gcc libc6-dev libssl3t64 libstdc++6 zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/lib/docker/cli-plugins/docker-buildx
COPY --from=kubectl /bin/kubectl /usr/local/bin/kubectl
COPY --from=dnscontrol /out/dnscontrol /usr/local/bin/dnscontrol
COPY --from=dnscontrol /usr/local/go /usr/local/go
COPY --from=dotnet /usr/share/dotnet /usr/share/dotnet
COPY --from=pulumi /pulumi/bin/ /usr/local/bin/
COPY --from=flux /usr/local/bin/flux /usr/local/bin/flux
COPY --from=git-cliff /usr/local/bin/git-cliff /usr/local/bin/git-cliff
ENV DOTNET_ROOT=/usr/share/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    PATH="/opt/homelab-tools/node_modules/.bin:/opt/homelab-tools/python/bin:/usr/local/go/bin:/usr/share/dotnet:${PATH}"
COPY package.json package-lock.json requirements-dev.txt /opt/homelab-tools/
RUN cd /opt/homelab-tools \
    && npm ci --ignore-scripts \
    && npm cache clean --force \
    && python3 -m venv python \
    && python/bin/pip install --no-cache-dir --disable-pip-version-check -r requirements-dev.txt \
    && go version && dotnet --version && ruff --version && biome --version \
    && pulumi version && flux --version && git-cliff --version

ARG REVISION
ARG VERSION
ARG SOURCE_URL=https://forgejo.jetersen.dev/jetersen/homelab
LABEL org.opencontainers.image.source=$SOURCE_URL \
      org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.description="Tools for homelab Forgejo Actions jobs"
ENTRYPOINT []
CMD ["bash"]

FROM ghcr.io/renovatebot/renovate:44.132.2@sha256:0191afbc3937e5316263426fc0ce1450f5c143d42e3f91da8c6f771e317fae51
USER root
RUN apt-get update && apt-get install --no-install-recommends -y nix-bin \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /nix/store /nix/var/nix /etc/nix /cache \
    && printf 'build-users-group =\nsandbox = false\n' > /etc/nix/nix.conf \
    && chown -R 12021:12021 /nix /cache
COPY infrastructure/renovate/worker/config.cjs /opt/renovate/config.cjs
COPY .ci/renovate-upgrade-policy.mjs /opt/renovate/renovate-upgrade-policy.mjs
USER 12021
RUN mkdir -p /tmp/nix-check \
    && printf '{ outputs = _: {}; }\n' > /tmp/nix-check/flake.nix \
    && nix --extra-experimental-features 'nix-command flakes' flake lock /tmp/nix-check \
    && rm -rf /tmp/nix-check
ENV RENOVATE_CONFIG_FILE=/opt/renovate/config.cjs

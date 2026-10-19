FROM ghcr.io/renovatebot/renovate:44.132.2@sha256:0191afbc3937e5316263426fc0ce1450f5c143d42e3f91da8c6f771e317fae51
USER root
RUN apt-get update && apt-get install --no-install-recommends -y nix-bin patch \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /nix/store /nix/var/nix /etc/nix /cache \
    && printf 'build-users-group =\nsandbox = false\n' > /etc/nix/nix.conf \
    && chown -R 12021:12021 /nix /cache
ADD --checksum=sha256:1aeb9200bbc34ddfdd7130cd8cdb6efafcceb760443fb9d885c9d426c9fcd849 https://api.github.com/repos/renovatebot/renovate/tarball/44.132.2 /tmp/renovate-source.tar.gz
RUN mkdir /tmp/renovate-source \
    && tar -xzf /tmp/renovate-source.tar.gz --strip-components=1 -C /tmp/renovate-source \
    && test "$(node -p 'require("/usr/local/renovate/package.json").version')" = 44.132.2 \
    && cp -a /tmp/renovate-source/lib /tmp/renovate-source/data /usr/local/renovate/ \
    && cp -a /tmp/renovate-source/tools/. /usr/local/renovate/tools/ \
    && rm -rf /tmp/renovate-source /tmp/renovate-source.tar.gz
# Generator input is a development dependency omitted from the released image.
ADD --checksum=sha256:d01d0e2ca4e22cb402679532155342c71e2e871f25c32223c013b8b166ebdf5a https://registry.npmjs.org/emojibase-data/-/emojibase-data-17.0.0.tgz /tmp/emojibase.tgz
RUN mkdir -p /usr/local/renovate/node_modules/emojibase-data \
    && tar -xzf /tmp/emojibase.tgz --strip-components=1 -C /usr/local/renovate/node_modules/emojibase-data package/en/shortcodes/github.json \
    && rm /tmp/emojibase.tgz
COPY infrastructure/renovate/worker/reattempt-automerge.patch /tmp/reattempt-automerge.patch
COPY infrastructure/renovate/worker/reattempt-automerge.mjs /usr/local/renovate/lib/modules/platform/gitea/reattempt-automerge.mjs
COPY infrastructure/renovate/worker/should-force-rebase.mjs /usr/local/renovate/lib/workers/repository/update/branch/should-force-rebase.mjs
RUN cd /usr/local/renovate \
    && patch -p1 < /tmp/reattempt-automerge.patch \
    && ./node tools/generate-imports.mjs \
    && ./node --input-type=module -e "import assert from 'node:assert/strict'; import * as forgejo from './lib/modules/platform/forgejo/index.ts'; assert.equal(typeof forgejo.reattemptPlatformAutomerge, 'function')"
COPY --chmod=755 infrastructure/renovate/worker/renovate.sh /usr/local/sbin/renovate
COPY infrastructure/renovate/worker/config.cjs /opt/renovate/config.cjs
COPY .ci/renovate-upgrade-policy.mjs /opt/renovate/renovate-upgrade-policy.mjs
USER 12021
RUN mkdir -p /tmp/nix-check \
    && printf '{ outputs = _: {}; }\n' > /tmp/nix-check/flake.nix \
    && nix --extra-experimental-features 'nix-command flakes' flake lock /tmp/nix-check \
    && rm -rf /tmp/nix-check
ENV RENOVATE_CONFIG_FILE=/opt/renovate/config.cjs

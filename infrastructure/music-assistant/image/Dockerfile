FROM ghcr.io/music-assistant/server:2.10.6@sha256:45fdb050e06962097a07feeb092606ad119fac17965c8228a57146448d5fa772 AS patcher
RUN uv pip install --target /tmp/patcher patch-ng==1.19.1
COPY provider.patch /tmp/provider.patch
RUN PYTHONPATH=/tmp/patcher python -c \
    'import patch_ng; patch = patch_ng.fromfile("/tmp/provider.patch"); assert patch and patch.apply(root="/app/venv/lib/python3.14/site-packages"), "Provider patch failed"'

FROM ghcr.io/music-assistant/server:2.10.6@sha256:45fdb050e06962097a07feeb092606ad119fac17965c8228a57146448d5fa772
ARG REVISION
LABEL org.opencontainers.image.source="https://forgejo.jetersen.dev/jetersen/homelab" \
      org.opencontainers.image.version="2.10.6-videos.1" \
      org.opencontainers.image.revision="${REVISION}"
COPY --from=patcher /app/venv/lib/python3.14/site-packages/music_assistant/providers/ytmusic/ /app/venv/lib/python3.14/site-packages/music_assistant/providers/ytmusic/
COPY --from=patcher /app/venv/lib/python3.14/site-packages/music_assistant/translations/en.json /app/venv/lib/python3.14/site-packages/music_assistant/translations/en.json

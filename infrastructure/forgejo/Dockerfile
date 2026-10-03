FROM gcr.io/distroless/python3-debian13:nonroot@sha256:774595d652a294b54c9bd575b2d9fdd1a4b47547dc17b8bfa4c0e953c64855b3 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000

FROM runtime AS tested
COPY kubernetes/apps/forgejo/backup/stage-forgejo.py /workspace/kubernetes/apps/forgejo/backup/stage-forgejo.py
COPY infrastructure/forgejo/tests/test_backup.py /workspace/infrastructure/forgejo/tests/test_backup.py
RUN ["/usr/bin/python3", "-m", "unittest", "discover", "-s", "/workspace/infrastructure/forgejo/tests", "-p", "test_*.py"]

FROM runtime AS staging
ARG SOURCE_URL=https://github.com/jetersen/homelab
ARG REVISION
LABEL org.opencontainers.image.title="Forgejo backup staging" \
      org.opencontainers.image.description="Stage Forgejo stores for Kopiur and recover expired backup pauses" \
      org.opencontainers.image.source=$SOURCE_URL \
      org.opencontainers.image.revision=$REVISION
COPY --from=tested --chmod=0444 /workspace/kubernetes/apps/forgejo/backup/stage-forgejo.py /stage-forgejo.py
ENTRYPOINT ["/usr/bin/python3", "/stage-forgejo.py"]

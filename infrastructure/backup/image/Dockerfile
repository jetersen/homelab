FROM docker.io/library/golang:1.27.3-alpine@sha256:f2c872bcee949b7be9c490efd02b48a8a2fbf947cdf533f1c58525ec9d8170fd AS source
ENV CGO_ENABLED=0 GOMAXPROCS=2 GOFLAGS="-p=2 -trimpath"
# WORKDIR includes SOURCE_DATE_EPOCH in its cache key. Use explicit paths so
# commit timestamps update image metadata without invalidating compilation.
COPY infrastructure/backup/image/go.mod infrastructure/backup/image/go.sum /src/
RUN --mount=type=cache,target=/go/pkg/mod go -C /src mod download
COPY infrastructure/backup/image/*.go /src/

FROM source AS build
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go -C /src build -ldflags='-s -w' -o /backup-helper .

FROM gcr.io/distroless/static-debian13:nonroot@sha256:516757106de35205efb70b91ba03f6f1298424a0678c603255cf2852a7000087
ARG SOURCE_URL=https://github.com/jetersen/homelab
ARG REVISION
ARG VERSION
LABEL org.opencontainers.image.title="Application backup helpers" \
      org.opencontainers.image.source=$SOURCE_URL \
      org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.version=$VERSION
COPY --from=build --chmod=0555 /backup-helper /backup-helper
USER 1000:1000
ENTRYPOINT ["/backup-helper"]

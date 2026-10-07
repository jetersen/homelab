FROM docker.io/library/golang:1.27.1-alpine@sha256:8a5910f31396cd4d89662f56c68b3ae31d374308270a1c3bd96672ee5ed43414 AS source
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

FROM gcr.io/distroless/static-debian13:nonroot@sha256:e2e927ec666bae08560abb3c55d0659eceabb657f56b6782ab500a9fc7f555e3
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

FROM docker.io/library/golang:1.27.3-alpine AS build
RUN apk add --no-cache patch
WORKDIR /source
ADD --checksum=sha256:5453ceb891bd823038624dabb60ea9d55e42865dd050e3bd60fcfc2a89f86cfe https://api.github.com/repos/mogenius/renovate-operator/tarball/6.5.1 /tmp/operator.tar.gz
RUN tar -xzf /tmp/operator.tar.gz --strip-components=1
COPY infrastructure/renovate/operator/pending-events.patch /tmp/pending-events.patch
RUN patch -p1 < /tmp/pending-events.patch
COPY infrastructure/renovate/operator/pending_events_test.go src/internal/utils/pending_events_test.go
COPY infrastructure/renovate/operator/forgejo_push_test.go src/webhook/forgejo_push_test.go
WORKDIR /source/src
RUN go test ./internal/utils ./webhook ./internal/crdManager ./internal/renovate ./gitProviderClients/forgejoProvider
RUN CGO_ENABLED=0 go build -tags timetzdata -trimpath -ldflags='-s -w -X main.Version=6.5.1-events.1' -o /operator ./cmd/main.go
FROM ghcr.io/mogenius/renovate-operator:6.5.1@sha256:892eec306b8ad0040046328ac7ed47fdcd28946e6e26fc9911f2d6d6c6055c70
ARG REVISION
ARG VERSION
LABEL org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.version=$VERSION
COPY --from=build /operator /app/renovate-operator

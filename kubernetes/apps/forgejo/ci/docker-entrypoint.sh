#!/bin/sh
# Each StatefulSet ordinal owns this Docker data volume exclusively.
set -eu
export DOCKER_HOST=unix:///var/run/docker.sock
rm -f /tmp/cache-ready
parent=$(awk -F: '$1 == "0" {print $3}' /proc/self/cgroup)
test -n "$parent" && test "$parent" != /
dockerd-entrypoint.sh --config-file=/config/docker.json --tls=false --storage-driver=overlay2 --dns=172.23.0.10 --cgroup-parent="$parent" &
daemon=$!
cleaner=
stop() {
    if [ -n "$cleaner" ]; then kill "$cleaner" 2>/dev/null || true; fi
    kill -TERM "$daemon" 2>/dev/null || true
    wait "$daemon" || true
}
trap stop TERM INT
until docker info >/dev/null 2>&1; do
    kill -0 "$daemon"
    sleep 1
done
# Preserve explicitly labelled caches while removing disposable job volumes.
docker container prune --force
docker network prune --force
docker volume create --label ci.persistent=true dotfiles-nix-cache >/dev/null
docker volume prune --all --force --filter label!=ci.persistent=true
touch /tmp/cache-ready
# Bound growth without throwing away a warm cache after every job.
(
    trim_ticks=0
    while kill -0 "$daemon" 2>/dev/null; do
        # Return deleted blocks to the thin pool at startup and daily.
        # Filesystem free space alone does not release thin-pool allocations.
        if [ "$trim_ticks" -eq 0 ]; then
            fstrim -v /var/lib/docker || echo 'Docker filesystem trim failed' >&2
        fi
        sleep 600
        trim_ticks=$(( (trim_ticks + 1) % 144 ))
        available_kib=$(df -Pk /var/lib/docker | awk 'NR == 2 {print $4}')
        if [ "$available_kib" -lt 4194304 ]; then
            docker image prune --all --force --filter until=24h
        fi
    done
) &
cleaner=$!
status=0
wait "$daemon" || status=$?
kill "$cleaner" 2>/dev/null || true
exit "$status"

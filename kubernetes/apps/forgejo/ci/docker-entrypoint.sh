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
# No runner starts until stale containers and job volumes have been removed.
docker container prune --force
docker network prune --force
docker volume prune --all --force
touch /tmp/cache-ready
# Bound growth without throwing away a warm cache after every job.
(
    while kill -0 "$daemon" 2>/dev/null; do
        sleep 600
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

# Monitoring retention

VictoriaMetrics and VictoriaLogs retain data for one year. Configure metric
retention in `app/helmrelease.yaml` and log retention in
`../victoria-logs/app/helmrelease.yaml`.

The OSS metrics instance keeps the original sample resolution until expiry.
Compression and background compaction do not progressively reduce resolution.
Age-based downsampling requires VictoriaMetrics Enterprise; Grafana's larger
query steps affect displayed resolution, not stored samples. Logs keep complete
entries until their partitions expire.

Both stores use node-local directories through `local-path`. PVC sizes are
requests, not enforced quotas on the shared filesystem. Check actual data size,
filesystem free space, and ingestion trends before extending retention. Reserve
space for compaction and up to an additional month of metric partitions.
Increasing retention preserves future history; it does not restore expired data.

Live queries use local storage. An object-storage backup must be restored before
it can be queried. Remote hosting or replication is a separate deployment choice.

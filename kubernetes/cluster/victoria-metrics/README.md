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

Operational metrics and kubelet probe counters use a 30-second scrape interval.
Selected kube-state-metrics creation timestamps and EndpointSlice inventory use
separate two-minute scrapes; readiness and metadata joins keep the faster cadence.
Certificate expiry and renewal timestamps use five-minute scrapes, with a
15-minute lookback in the expiry alert. Slow scrapes have distinct jobs and their
metrics are excluded from the fast scrapes.

HTTP, TCP, DNS, and gateway blackbox probes run every 30 seconds, with a
10-second scrape timeout and five-second module timeout. Grafana's datasource
scrape interval is 30 seconds so its automatic rate windows match collection.
API SLI histogram buckets and total-latency sums/counts remain available; unused
total-request histogram buckets are excluded.

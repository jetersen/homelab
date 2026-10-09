# Monitoring retention

Configure retention in the [VictoriaMetrics values](app/helmrelease.yaml) and
[VictoriaLogs values](../victoria-logs/app/helmrelease.yaml).

The OSS metrics instance keeps the original sample resolution until expiry.
Compression and background compaction do not progressively reduce resolution.
Age-based downsampling requires VictoriaMetrics Enterprise; Grafana's larger
query steps affect displayed resolution, not stored samples. Logs keep complete
entries until their partitions expire.

Both stores use XFS on thick OpenEBS LocalPV LVM volumes. PVC capacities are
enforced and support expansion. Configure capacities in each store's
`app/lvm-storage.yaml`. Check actual data size, volume-group free space, and
ingestion trends before extending retention. Reserve
space for compaction and up to an additional month of metric partitions.
Increasing retention preserves future history; it does not restore expired data.

Live queries use local storage. An object-storage backup must be restored before
it can be queried. Remote hosting or replication is a separate deployment choice.

Scrape intervals and metric filters live in the
[metrics values](app/helmrelease.yaml), [infrastructure scrapes](app/infrastructure-scrapes.yaml),
and [probe configuration](app/probes.yaml). Keep Grafana's
[datasource interval](../grafana/app/helmrelease.yaml) aligned with collection.
When slowing a scrape, adjust alert lookbacks and avoid collecting the same
series in both fast and slow jobs. Preserve the histogram buckets and counters
used by alerts and [dashboard overrides](../grafana/app/dashboards/README.md).

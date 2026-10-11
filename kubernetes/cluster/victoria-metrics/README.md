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
and [probe configuration](app/probes.yaml). Default scrapes and rule evaluations
run once per minute; inventory and external probes use their slower configured
intervals. The upstream vmagent, vmalert, and vmsingle rule groups explicitly
evaluate every 30 seconds; the chart's group settings supply defaults and do not
override those source intervals. Fixed counter-rate windows span at least five minutes. Keep Grafana's
[datasource interval](../grafana/app/helmrelease.yaml) aligned with collection.
When slowing a scrape, adjust alert lookbacks and avoid collecting the same
series in both fast and slow jobs. Preserve the histogram buckets and counters
used by alerts and [dashboard overrides](../grafana/app/dashboards/README.md).

API availability SLO and error-budget rules are disabled. API request counters
and histogram sums/counts remain available for error rates and mean latency;
SLI latency buckets and their percentile recording rules are omitted. This
reduces collection and evaluation work without disabling API-down, certificate,
workload, storage, or backup alerts.

The [Talos API metrics patch](../../talos/patches/control-plane/api-metrics.yaml)
disables the unused request-duration histogram at its source. The separate SLI
histogram still supplies mean request latency. Metric filters also omit unused
feature inventory, block-I/O series, and diagnostic histogram buckets while
preserving their sums/counts and garbage-collection metrics.

cAdvisor network metrics retain pod CNI, Multus and VPN interfaces named
`ethN`, `netN`, `lanN`, `iotN`, `tunN`, `tapN` or `wgN`, where `N` is a number.
Extend the interface selector when adding another pod interface naming scheme.
Host interfaces and anonymous cgroup network totals are omitted because they
repeat node traffic; node exporter supplies host network metrics. CPU, memory
and filesystem collection remain independent of this network filter.
Startup flag inventory and controller reconciliation latency buckets are also
omitted with their optional dashboard panels. Reconciliation errors, counters
and histogram sums/counts remain available.

The API server's heap/CPU tradeoff is configured in the
[Talos GC patch](../../talos/patches/control-plane/api-gc.yaml). `GOGC` controls
the heap growth target rather than imposing a hard memory limit. Restore `100`
to use Go's default, and compare memory, CPU, and request latency when tuning it.

Synthetic probes cover NAS HTTPS/NFS ports, internal DNS answers, and DNS
recursion over UDP and TCP. Application availability relies on Kubernetes
readiness and workload alerts. Probe intervals and targets live in the
[probe configuration](app/probes.yaml).

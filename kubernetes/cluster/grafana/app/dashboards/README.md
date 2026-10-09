# Dashboard overrides

These dashboards retain upstream UIDs and replace the five corresponding dashboards disabled in the VictoriaMetrics HelmRelease. The generator pins upstream commits, checks expected panel/query shapes, and adapts cluster selectors for homelab's metrics without a cluster label. Diagnostics use retained histogram sums/counts and probe failure counters.

Regenerate with Python 3 and PyYAML installed:

```sh
python kubernetes/cluster/grafana/app/dashboards/generate.py
python kubernetes/cluster/grafana/app/dashboards/generate.py --check
python -m unittest discover -s kubernetes/cluster/grafana/app/dashboards
```

Update the pinned commits in `generate.py` to refresh upstream dashboards. Edit the generator instead of generated JSON. Review upstream query and layout changes before regenerating. The generator fails if expected panels, queries, or UIDs change.

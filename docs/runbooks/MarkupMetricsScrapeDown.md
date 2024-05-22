# MarkupMetricsScrapeDown

**Severity:** critical  **Service:** markup-svc  **Expression:** `up{job="markup-svc"} == 0`

## What this means

Prometheus has been unable to scrape `markup-svc:/metrics` for 2 min. Either markup-svc is down, `/metrics` is not mounted (the `--metrics-enabled` flag was dropped from the command line), or the network path between Prometheus and markup-svc is broken. **All markup-svc alerts that depend on `markup_decide_*` metrics are blind during this window** — including `MarkupDecideErrorRateHigh` and `MarkupDecideP99Slow`.

## First check (5 min)

1. **Container state** — `docker compose ps markup-svc --format 'table {{.Name}}\t{{.State}}\t{{.Status}}'`. If it's restarting or down, jump to the markup-svc logs (`docker compose logs markup-svc --tail 30`).
2. **Flags** — `docker compose ps markup-svc --format '{{.Command}}'` (or `docker inspect`). Confirm `--metrics-enabled` is present.
3. **Direct scrape** — from the Prometheus container: `wget -qO- http://markup-svc:8080/metrics | head -5`. From the host: `curl http://localhost:8080/metrics | head -5`. Tells you whether the service is up but the network is the problem, or both are broken.
4. **Prometheus target view** — open `http://localhost:9090/targets`, find the `markup-svc` job, read the "Last Error" column.

## If confirmed

- **Service crashed** — check logs for panic, OOM, or diagnose-failed boot. If boot failed because rules were broken, follow the same recovery as `AdminHotReloadRejected` (restore the last good rule set, `up -d --force-recreate markup-svc`).
- **--metrics-enabled missing** — operator removed it accidentally during a config bump. Restore the flag in `docker-compose.yaml` and recreate.
- **Network** — Prometheus and markup-svc are on different Docker compose networks. Verify both reference the same network; verify the `host.docker.internal` fallback if cross-compose.
- **Port collision** — `docker compose port markup-svc 8080` returns no mapping. Container is up but the listen-port flag is wrong.

## If false-positive

- **Mid-deploy** — if you just ran `docker compose up -d markup-svc`, expect a 30-60 s scrape gap while the container restarts. The `for: 2m` clock filters most of these; this only fires on real outages.
- **Prometheus restart** — if you just restarted Prometheus, the `up{}` series is briefly stale.

## Escalation

This is a **critical** alert — page the on-call immediately if the container shows running but the scrape still fails after 5 min (network / firewall / collector config issue). Otherwise treat as P2 and follow first-check + remediation.

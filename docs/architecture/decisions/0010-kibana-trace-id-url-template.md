# 10. Kibana `attrs.trace_id` renders as a clickable Jaeger link

## Status

Accepted — the `platform-logs-*` data view's `fieldFormatMap` formats `attrs.trace_id` with `id: url`, `urlTemplate: http://localhost:16686/trace/{{value}}`, `openLinkInCurrentTab: false`. Operators click a `trace_id` value in Kibana Discover and the matching Jaeger trace opens in a new tab — one click instead of copy / paste. The `kibana-init` script's import call retries with backoff so first-boot 503s from the saved-objects API no longer leak a half-provisioned state.

## Context

ADR-0004 wired the `platform-logs-*` + `jaeger-span-*` data views via the kibana-init container. ADR-0003 in decision-gateway already adds `attrs.trace_id` + `attrs.span_id` to every `gateway.access` event; ADR-0021 in markup-svc does the same on `markup-server.access`. The data is in Kibana, but the operator workflow still requires copying the trace_id and pasting it into Jaeger's URL or search box. The URL template formatter closes the loop with a native Kibana field renderer — zero extra UI, zero saved searches, zero custom plugins.

The kibana-init script's existing single POST hit a 503 from the saved-objects API during a recent restart even after `/api/status` reported "available". Adding retry-with-backoff makes the import resilient to that warmup race so the data view (with the new format) lands reliably on every restart.

## Decision

`config/kibana-saved-objects.ndjson` — `platform-logs` index-pattern attribute set grows:

```json
"fieldFormatMap": "{\"attrs.trace_id\":{\"id\":\"url\",\"params\":{\"urlTemplate\":\"http://localhost:16686/trace/{{value}}\",\"labelTemplate\":\"{{value}}\",\"openLinkInCurrentTab\":false}}}"
```

The format map is a JSON-encoded string per Kibana's data-view schema. `openLinkInCurrentTab: false` keeps the Kibana session intact when an operator clicks a trace_id. `labelTemplate: {{value}}` keeps the visible cell text identical to the unformatted trace ID — no surprise rendering.

`config/kibana-init.sh` — the single `curl -fsS POST` becomes a `while` loop that captures the HTTP status code with `-w %{http_code}` and retries non-2xx up to 20 times at 3 s intervals. After 20 failures the script exits non-zero so compose surfaces the problem.

## Consequences

### Closed

- One-click navigation from a Kibana access-log row to the matching Jaeger trace. Combined with the gateway.access + markup-server.access trace_id fields shipped in earlier ADRs, the operator's investigation workflow becomes Discover → row → trace ID click → Jaeger waterfall in two clicks.
- First-boot 503s from the saved-objects API no longer break the data-view provisioning. The container exits successfully and `attrs.trace_id` renders as a link on every clean `docker compose up`.

### Not closed

- The URL template is hard-coded to `localhost:16686`. Operators running Kibana behind a reverse proxy or accessing it from a non-localhost host need the template to point at their actual Jaeger URL. A future ADR moves the template to a Compose env var.
- Span-level deep linking. Clicking trace_id opens the trace; pulling `attrs.span_id` as an additional query param (`?uiFind=<span_id>`) would scroll Jaeger to the exact span. Adds operator-visible value when spans-per-trace grows; out of scope today.
- Back-link from Jaeger to Kibana (filter by `attrs.trace_id:"<id>"`). Jaeger's trace UI accepts `Logs > Open in External` extensions, but the saved-object provisioning for Jaeger is a separate code path. Lands when an operator opens an enhancement request.

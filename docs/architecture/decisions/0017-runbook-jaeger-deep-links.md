# 17. Runbook Jaeger deep-links

## Status

Accepted — every runbook step that previously named a Jaeger SPM / search query as prose now ships a clickable Jaeger URL. Two link shapes cover the four affected runbooks: `http://localhost:16686/monitor?service=<svc>` for SPM, and `http://localhost:16686/search?service=<svc>&...` for filtered span search (errors via `tags=%7B%22otel.status_code%22%3A%22ERROR%22%7D`, slowest via `minDuration=5ms`, both with `lookback=15m&limit=20`). `scripts/check-jaeger-links.sh` (wired into `make ci-local`) asserts every Jaeger URL in a runbook uses a recognized path, carries a `service=` query parameter, and references a known platform service.

## Context

ADR-0016 took the runbooks one click closer to operational fast-path by provisioning Kibana saved searches and linking runbook first-check steps to them. The remaining friction sat in the Jaeger steps: three runbooks (MarkupDecideP99Slow, GatewayRequestP99Slow, GatewayRequestErrorRateHigh) and one Jaeger step in MarkupDecideErrorRateHigh told the operator to "open SPM for `<svc>`, filter by..." — same copy-paste tax ADR-0016 closed for Kibana.

Unlike Kibana saved objects, Jaeger has no server-side "save my view" primitive. Filtered views are URLs, period. So the link IS the saved object. The pattern reduces to: (1) construct the right URL once, (2) put it in the runbook, (3) gate against URL drift in CI.

Two URL shapes cover every use case in the existing runbook set:

- **Service Performance Monitoring** — `http://localhost:16686/monitor?service=<svc>` opens Jaeger's SPM page already scoped to the service. The operator immediately sees the call rate / error rate / p99 chart for the service that paged them. No service-picker step.
- **Filtered span search** — `http://localhost:16686/search?service=<svc>&tags=<json>&lookback=15m&limit=20` lands on Jaeger's trace list with the service + filters already applied. Two flavors used today:
  - error spans: `tags=%7B%22otel.status_code%22%3A%22ERROR%22%7D` (URL-encoded `{"otel.status_code":"ERROR"}`)
  - slow spans: `minDuration=5ms` (matches the gateway / engine p99 SLO bound)

### Gate design

One option for the CI gate: validate the link round-trips against the live Jaeger by hitting the URL during `make ci-local`. Rejected — would couple `make ci-local` to a running stack, and the gate is supposed to be fast + offline. Instead the gate validates URL shape: known path (`/monitor` or `/search`), `service=` present, service value matches one of the three known platform services. Catches typos, drifted-renamed services, and someone pasting a non-Jaeger localhost URL. Doesn't catch a tag JSON that's syntactically wrong but URL-decodeable — that's a "type-check vs runtime-check" tradeoff, and the runtime check is one click anyway.

## Decision

Four runbook edits:

| Runbook | Previous prose | New link(s) |
|---|---|---|
| MarkupDecideErrorRateHigh (step 3) | "open SPM for `markup-svc`, filter `span_kind=SERVER` + `status_code=STATUS_CODE_ERROR`" | SPM link + error-search link |
| MarkupDecideP99Slow (step 4) | "open SPM for `markup-svc`, look at recent traces" | SPM link + slow-search link |
| GatewayRequestErrorRateHigh (step 3) | "open SPM for `decision-gateway`, filter ..." | SPM link + error-search link |
| GatewayRequestP99Slow (step 3) | "Jaeger Monitor (SPM) — gateway service, look at slow traces" | SPM link + slow-search link |

`scripts/check-jaeger-links.sh`:

1. Extracts every `http://localhost:16686/*` URL from `docs/runbooks/*.md`.
2. Verifies the path is `/monitor` or `/search` (the two we use today; extensions go through an ADR update).
3. Verifies `service=` is present.
4. Verifies the service value is one of `markup-svc | decision-gateway | traffic-gen` (the known platform services).

Wired into `make ci-local` via a new `check-jaeger-links` target.

## Consequences

### Closed

- The four Jaeger steps that named a query as prose are now one click. Operators don't pick a service from a dropdown and then add filters; SPM and trace search open already scoped + filtered.
- The same five-section runbook shape now ends in actionable links across all three signal sources (Grafana panels, Kibana saved searches, Jaeger views). The runbook structure is complete.
- The CI gate keeps Jaeger links honest. Renaming a service (or removing one) breaks `make ci-local` until the runbooks are updated. A typo in the path or service name fails the gate before review.

### Not closed

- Jaeger URL versioning. The `/monitor` and `/search` paths are stable in Jaeger 1.55 (per ADR-0006 in this repo); a future Jaeger major could break the URL shape. The CI gate would still pass with a dead link. Acceptable risk — the rebuild path is "open Jaeger UI, navigate to the view, copy the URL, paste it into the runbook" and the gate would catch the path mismatch on the next push.
- Saved-view primitive. Jaeger has no equivalent to Kibana's saved-objects API. If Jaeger gains one, ADR-0016's pattern can subsume the Jaeger links and this ADR can be superseded.
- Tag JSON validation. The gate doesn't decode the `tags=` query value to verify it's syntactically valid JSON. A malformed tag would render as no filter applied; operators would notice on the first click. Out of scope.
- Cross-environment URL hostnames. Same constraint as ADR-0016: links hard-code `localhost:16686`. A deployed environment would need different hosts. The compose-local stack is the only deployment target today.

### Performance impact

None. Static URL strings; no runtime cost.

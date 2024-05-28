# 16. Runbook saved searches in Kibana

## Status

Accepted — `config/kibana-saved-objects.ndjson` ships three additional saved objects of type `search`, one per runbook step that previously listed a Lucene query as prose. The runbooks now link directly to `http://<KIBANA>/app/discover#/view/<id>` instead of asking the operator to copy-paste a query. `scripts/check-saved-searches.sh` (wired into `make ci-local`) verifies every runbook link resolves to a saved object in the NDJSON and every saved object of type `search` is referenced by at least one runbook.

## Context

ADR-0015 closed the alert-payload gap by attaching a `runbook_url` annotation to every alert and shipping a five-section runbook per alert. The remaining friction is in the "First check" step: most runbooks tell the operator to run a specific Lucene query in Kibana (e.g. `service:"markup-svc" AND msg:"markup-server.access" AND attrs.status:>=500`). At 3 am, copy-pasting a query from a markdown file into Discover is doable but slow — and exactly the kind of micro-friction that gets skipped in favor of "just SSH and tail the logs," which loses the structured-query view that Kibana exists to provide.

Kibana already supports saved searches: a query + chosen columns + sort order packaged as a `search` saved object, openable via `app/discover#/view/<id>`. The same NDJSON provisioning path that ADR-0004 set up for data views supports `search` objects with no infrastructure change. The remaining question is whether the runbook references the saved-search ID or the query string.

### 1. Runbook embeds the KQL string

The runbook quotes the query inline; the operator copy-pastes into Discover.

Pros: query is readable in the markdown; no infrastructure dependency.
Cons: every operator does the copy-paste; the column set / sort order is not captured; a query update means editing the runbook prose.

### 2. Runbook links to a saved-search ID

The runbook says "open the `runbook: markup-svc 5xx access` saved search" with a clickable URL. The query, columns, and sort live in the NDJSON.

Pros: one click; column set + sort are part of the saved object; updating the query is a single NDJSON edit; the saved object is the source of truth.
Cons: requires the NDJSON provisioning path (already in place); the runbook is harder to read without Kibana running (the operator can't see the KQL in the markdown).

**Pick saved-search ID.** The point of a runbook is to be operationally fast, not to double as KQL documentation. The provisioning path is already paid for. The CI gate keeps the runbook ↔ NDJSON link honest. Future runbooks that want to add a new saved search add one NDJSON entry + one runbook link + run `make check-saved-searches`.

## Decision

`config/kibana-saved-objects.ndjson` now contains three `type: "search"` saved objects in addition to the two `type: "index-pattern"` objects from ADR-0004:

| id | runbook | KQL |
|---|---|---|
| `runbook-markup-svc-5xx` | MarkupDecideErrorRateHigh | `service:"markup-svc" and msg:"markup-server.access" and attrs.status >= 500` |
| `runbook-gateway-5xx` | GatewayRequestErrorRateHigh | `service:"decision-gateway" and msg:"gateway.access" and attrs.status >= 500` |
| `runbook-admin-rejected` | AdminHotReloadRejected | `service:"decision-gateway" and msg:"gateway.access" and attrs.path:"/admin*" and attrs.status >= 400` |

Each saved search:
- Uses the `platform-logs` data view (via `kibanaSavedObjectMeta.searchSourceJSON.indexRefName` → `references[].id`).
- Carries an opinionated column set focused on the fields the runbook's triage steps need (`attrs.correlation_id`, `attrs.status`, `attrs.route`, `attrs.path`, `attrs.error`, etc.).
- Sorts by `@timestamp` desc so newest events surface first.

Three runbooks (the ones whose first-check lists started with a Kibana query) now link to their saved search via `http://localhost:5601/app/discover#/view/<id>`. The three latency / scrape-down runbooks point primarily at Grafana + Jaeger and don't need a Kibana saved search yet; they can grow one when a future "first check" actually starts in Discover.

`scripts/check-saved-searches.sh` gates two directions:

1. Every `discover#/view/<id>` URL in a runbook resolves to an `id` present in the NDJSON.
2. Every `type: "search"` saved object in the NDJSON is referenced by at least one runbook (no orphans).

Wired into `make ci-local` via a new `check-saved-searches` target.

## Consequences

### Closed

- Runbook first-check steps that named a Kibana query are now one-click. The on-call clicks the link in the runbook (or in the AlertManager payload's `runbook_url` markdown render), Discover opens with the right query, columns, and sort. No copy-paste.
- The saved-search NDJSON is the source of truth for the query, columns, and sort order. Updating any one of those is an NDJSON edit; the runbook prose stays stable.
- The CI gate keeps the runbook ↔ NDJSON link honest. A typo in either side breaks `make ci-local` before it reaches Discover.

### Not closed

- The three runbooks that point at Jaeger / Grafana / shell commands (MarkupDecideP99Slow, MarkupMetricsScrapeDown, GatewayRequestP99Slow) don't have Kibana saved searches. The operator-flow for those starts elsewhere. A future ADR can add `app/jaeger#/search?service=...` deep-links if the same friction surfaces there.
- Kibana version coupling. `coreMigrationVersion: "8.11.4"` matches the Kibana image in compose. Bumping Kibana means re-exporting from the new version's UI and updating the NDJSON. Same constraint ADR-0004 already accepts.
- The Kibana hostname in the runbook links is `localhost:5601` (compose default). In a deployed environment the runbook prose would need updating, or the link would need to be a relative path the deploying operator templates. Out of scope; the compose-local stack is the only deployment target today.

### Performance impact

- Kibana boot: 3 extra saved-objects imported. ADR-0004's import already runs in <1s with 2 objects; 5 stays well under the kibana-init retry budget.
- Runtime: zero. Saved searches are static metadata; Discover evaluates the query like any user-typed one.

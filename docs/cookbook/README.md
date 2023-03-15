# pricing-observability cookbook

Operator-level recipes for the platform's observability surface. Each recipe is one page, names the relevant ADRs and config files, and ends with a "what to check after" section.

## Recipes

| Recipe | When to use |
|---|---|
| [logs-flowing.md](logs-flowing.md) | Bring the logs pipeline up alongside the platform stack and confirm every platform log line is queryable in Kibana by `attrs.correlation_id` |

## How these recipes are written

1. **Problem** — one sentence stating what the operator is trying to do.
2. **Recipe** — copy-paste commands.
3. **What's happening** — one paragraph explaining the mechanism.
4. **What to check after** — concrete signals (curl status, Kibana doc counts, container health) that confirm the recipe worked.
5. **Mistakes to avoid** — the misconfigurations that bite operators most.
6. **Relevant ADRs and config files** — pointers into the design docs.

If a recipe and an ADR disagree, the ADR is the source of truth — file a follow-up to fix the recipe.

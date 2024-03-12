#!/bin/sh
# Periodic dependency aggregation. Calls the image's entrypoint every
# INTERVAL seconds with DATE pinned to today so System Architecture
# stays fresh during exploration. See ADR-0007.

set -u

INTERVAL="${INTERVAL:-120}"
export STORAGE="${STORAGE:-elasticsearch}"
export ES_NODES="${ES_NODES:-http://elasticsearch:9200}"
export ES_NODES_WAN_ONLY="${ES_NODES_WAN_ONLY:-true}"
export MAIN_CLASS="${MAIN_CLASS:-io.jaegertracing.spark.dependencies.elasticsearch.ElasticsearchDependenciesJob}"

while true; do
  export DATE=$(date -u +%Y-%m-%d)
  echo "spark-deps-loop: running for DATE=$DATE"
  /entrypoint.sh || true
  sleep "$INTERVAL"
done

-- Elasticity + conversion analysis over the Pricing Decision Platform's
-- funnel-events and markup-decisions MinIO buckets.
--
-- Read the two buckets as external JSONL tables, join them on the
-- load-bearing decision_id key, group by (experiment, variant), and
-- emit conversion + walkoff + revenue per arm. Run against the local
-- compose MinIO:
--
--   duckdb -init elasticity.sql
--
-- or piped from the runner (see elasticity.py).
--
-- Notes:
--   - json_auto is forgiving with sparse fields (order_id, revenue,
--     phase are populated on only some event_types).
--   - LEFT JOINs from offers_shown so unclicked offers show up in the
--     impressions denominator, which is what elasticity math needs.

INSTALL httpfs;
LOAD httpfs;

SET s3_endpoint         = 'localhost:9000';
SET s3_access_key_id    = 'minio';
SET s3_secret_access_key = 'minio12345';
SET s3_use_ssl          = false;
SET s3_url_style        = 'path';

-- Every priced offer that was shown to a customer. Flattened from the
-- search.v1 event's offers[] array so one row = one impression.
CREATE OR REPLACE VIEW offers_shown AS
WITH searches AS (
  SELECT
    journey_id,
    search_id,
    query,
    UNNEST(offers) AS offer
  FROM read_json_auto('s3://funnel-events/search-v1/dt=*/hour=*/env=*/instance=*/*.jsonl.gz',
                       hive_partitioning = true,
                       ignore_errors = true)
)
SELECT
  s.journey_id,
  s.search_id,
  s.offer.decision_id      AS decision_id,
  s.offer.offer_id         AS offer_id,
  s.offer.position         AS position,
  s.offer.price            AS price,
  s.offer.markup_factor    AS markup_factor,
  s.offer.experiment       AS experiment,
  s.offer.variant          AS variant,
  s.query.customer_tier    AS customer_tier,
  s.query.country          AS country,
  s.query.route            AS route
FROM searches s
WHERE s.offer.decision_id IS NOT NULL;

-- Every terminal-successful purchase. One row per purchased booking.
CREATE OR REPLACE VIEW purchased AS
SELECT decision_id, order_id, revenue, journey_id
FROM read_json_auto('s3://funnel-events/booking-v1/dt=*/hour=*/env=*/event_type=booking.purchased/instance=*/*.jsonl.gz',
                     hive_partitioning = true,
                     ignore_errors = true);

-- Every terminal-abandonment at the initiated phase. The high
-- price-sensitivity cohort: customer saw the price, clicked to book,
-- then walked away before providing info.
CREATE OR REPLACE VIEW walked_at_init AS
SELECT decision_id, journey_id
FROM read_json_auto('s3://funnel-events/booking-v1/dt=*/hour=*/env=*/event_type=booking.timeout/instance=*/*.jsonl.gz',
                     hive_partitioning = true,
                     ignore_errors = true)
WHERE phase = 'initiated';

-- Every walk after reserve — payment-friction cohort.
CREATE OR REPLACE VIEW walked_at_reserve AS
SELECT decision_id, journey_id
FROM read_json_auto('s3://funnel-events/booking-v1/dt=*/hour=*/env=*/event_type=booking.timeout/instance=*/*.jsonl.gz',
                     hive_partitioning = true,
                     ignore_errors = true)
WHERE phase = 'reserved';

-- Main elasticity table: one row per (experiment, variant) with
-- conversion, walkoff, and revenue. NULL variant / experiment fall
-- into a "(none)" bucket so an operator running without arm labels
-- still sees baseline numbers.
CREATE OR REPLACE VIEW elasticity AS
SELECT
  COALESCE(NULLIF(o.experiment, ''), '(none)') AS experiment,
  COALESCE(NULLIF(o.variant, ''),    '(none)') AS variant,
  COUNT(*)                                     AS impressions,
  COUNT(p.decision_id)                         AS purchases,
  COUNT(wi.decision_id)                        AS walkoffs_at_init,
  COUNT(wr.decision_id)                        AS walkoffs_at_reserve,
  ROUND(COUNT(p.decision_id)   * 1.0 / COUNT(*), 4) AS conversion_rate,
  ROUND(COUNT(wi.decision_id)  * 1.0 / COUNT(*), 4) AS price_shock_rate,
  ROUND(COUNT(wr.decision_id)  * 1.0 / COUNT(*), 4) AS payment_friction_rate,
  ROUND(AVG(o.price), 4)                       AS avg_shown_price,
  ROUND(SUM(COALESCE(p.revenue, 0)), 4)        AS gmv
FROM offers_shown o
LEFT JOIN purchased        p ON p.decision_id  = o.decision_id
LEFT JOIN walked_at_init   wi ON wi.decision_id = o.decision_id
LEFT JOIN walked_at_reserve wr ON wr.decision_id = o.decision_id
GROUP BY experiment, variant
ORDER BY experiment, variant;

-- Top-level roll-up — the operator-facing default view.
.mode box
SELECT * FROM elasticity;

-- Journey-level view: how many searches per session, how many offers
-- across those searches, how many bookings. A quick sanity check on
-- session integrity when synthetic drivers scale up.
CREATE OR REPLACE VIEW journeys AS
SELECT
  o.journey_id,
  COUNT(DISTINCT o.search_id)  AS searches,
  COUNT(*)                     AS offers_shown,
  COUNT(p.decision_id)         AS purchases,
  MAX(o.customer_tier)         AS customer_tier,
  MAX(o.country)               AS country
FROM offers_shown o
LEFT JOIN purchased p ON p.decision_id = o.decision_id
GROUP BY o.journey_id
ORDER BY offers_shown DESC
LIMIT 5;

.print
.print --- top-5 journeys by impressions (session-integrity sanity check) ---
SELECT * FROM journeys;

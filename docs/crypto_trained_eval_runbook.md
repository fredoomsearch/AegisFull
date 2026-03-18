# Crypto Trained Evaluation Runbook

Date: 2026-03-16

## Purpose

Use this runbook to evaluate the crypto module as a measured product surface without mixing trained and demo results.

This runbook does not prove alpha by itself. It gives a clean, repeatable way to collect trained-only evidence.

## Preconditions

- `AEGIS_CRYPTO_USE_TRAINED_MODELS=1`
- Trained model artifacts are present and discoverable
- The UI/API is running with auth enabled
- Prediction logging is enabled

Optional hard guard:

```bash
export AEGIS_CRYPTO_REQUIRE_TRAINED_MODELS=1
```

That forces the API to fail closed instead of silently falling back to demo.

## Evaluation Scope

Use only:

- `engine=trained`
- net-after-fees metrics
- measured outcome history

Do not present `engine=all` or `engine=demo` as trained-model performance.

## Recommended Cost Assumptions

Default evaluation assumptions:

- fee: `10 bps`
- slippage: `5 bps`

Round-trip cost used by the stats API:

- `30 bps` total

Adjust these only if you have a justified venue/profile assumption.

## API Workflow

### 1. Verify trained predictions are being produced

```bash
curl -s -H "X-API-Key: $AEGIS_API_KEY" \
  "http://127.0.0.1:8000/crypto/predictions?limit=20&engine=trained"
```

### 2. Inspect trained-only measured stats

```bash
curl -s -H "X-API-Key: $AEGIS_API_KEY" \
  "http://127.0.0.1:8000/crypto/predictions/stats?engine=trained&limit=200&fee_bps=10&slippage_bps=5"
```

Focus on:

- `count`
- `trade_count`
- `accuracy`
- `net_expectancy_pct`
- `positive_net_rate`
- `max_drawdown_pct`
- `oos_window_hours`

### 3. Export a portfolio-safe report

JSON:

```bash
curl -L -H "X-API-Key: $AEGIS_API_KEY" \
  "http://127.0.0.1:8000/crypto/predictions/stats/export?engine=trained&format=json&limit=200&fee_bps=10&slippage_bps=5" \
  -o trained_eval.json
```

CSV:

```bash
curl -L -H "X-API-Key: $AEGIS_API_KEY" \
  "http://127.0.0.1:8000/crypto/predictions/stats/export?engine=trained&format=csv&limit=200&fee_bps=10&slippage_bps=5" \
  -o trained_eval.csv
```

Markdown report:

```bash
curl -L -H "X-API-Key: $AEGIS_API_KEY" \
  "http://127.0.0.1:8000/crypto/predictions/stats/export?engine=trained&format=md&limit=200&fee_bps=10&slippage_bps=5" \
  -o trained_eval.md
```

Bundle export in one step:

```bash
venv/bin/python -m app.scripts.export_crypto_eval_bundle \
  --symbol BTCUSDT \
  --engine trained \
  --limit 200 \
  --fee-bps 10 \
  --slippage-bps 5 \
  --out-dir artifacts/crypto_eval/trained_btcusdt
```

## UI Workflow

1. Open the Crypto stats panel.
2. Switch the engine filter to `Trained`.
3. Review:
   - net expectancy
   - positive net rate
   - max drawdown
   - OOS window
   - per-model breakdown
4. Export `JSON`, `CSV`, or `MD`.

## Release-Safe Portfolio Framing

Safe claims:

- trained-vs-demo evaluation is separated
- measured outcome logging exists
- net-after-fees metrics are exposed
- out-of-sample runtime window is tracked

Unsafe claims unless independently proven:

- profitable strategy
- market-beating alpha
- fixed win-rate claims
- future-return claims

## Evidence Threshold Suggestion

Do not present trained performance as credible until you have at least:

- a non-trivial trained-only sample count
- a meaningful OOS window
- positive net expectancy after costs
- acceptable drawdown for the strategy profile

The exact threshold is a product/release decision, not a hardcoded API truth.

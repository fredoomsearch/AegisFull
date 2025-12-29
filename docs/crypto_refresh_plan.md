# Crypto Model Refresh Plan

How to keep market data and models fresh without blocking user endpoints.

## Scripts

- Fetch snapshot: `python -m app.scripts.fetch_market_data --out data/crypto_data.csv --per-page 200 --pages 1`
- Train ensemble: `python -m app.scripts.train_models --csv-path data/crypto_data.csv` (add `--quick` for faster dev runs)

## Suggested schedule

- Every 30–60 min: run the fetch script to update `data/crypto_data.csv`.
- Daily (or every few hours if hardware allows): run the train script to refresh model artifacts and meta JSON.

Example cron (UTC) keeping fetch hourly and training daily at 03:00:

```
# m h dom mon dow command
0 * * * * /usr/bin/python3 -m app.scripts.fetch_market_data --out /home/youruser/Documents/whioutoKn/data/crypto_data.csv --per-page 200 --pages 1 >> /home/youruser/Documents/whioutoKn/logs/fetch.log 2>&1
0 3 * * * /usr/bin/python3 -m app.scripts.train_models --csv-path /home/youruser/Documents/whioutoKn/data/crypto_data.csv >> /home/youruser/Documents/whioutoKn/logs/train.log 2>&1
```

Adjust paths to your environment and consider `--quick` for dev boxes.

## Versioning and safety

- Keep timestamped copies of CSVs and models (e.g., under `artifacts/`) so you can roll back if a training run fails.
- Keep the previous model on disk; if the newest fails to load, fall back to the last good one.

## Automation options

- Cron/systemd/CI: schedule the two scripts in order (fetch then train).
- Optional admin-only endpoint: expose a background job trigger if you need on-demand refresh; do not train on user calls.

## Notes

- Live `/crypto` calls should remain fast and only read the latest artifacts; never fetch/train per request.
- If you cache live price lookups (Binance/CG) for a few seconds, you reduce external API load without hurting freshness much.

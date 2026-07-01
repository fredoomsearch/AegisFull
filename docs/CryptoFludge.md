Binance/CoinGecko ──→ fetch_binance()/fetch_coingecko()
                           │
                           ▼ (raw data)
                  CryptoPredictionInput schema
                           │
                           ▼ (validation)
              SetaFeatureEnricher.enrich_features()
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Technical    Volatility    Sentiment
         (SMA,EMA,    (return_1/3,   (reddit,
          RSI,BB)      rolling_vol)  news)
                           │
                           ▼
           5 Models: rf, dl, xgb, cat, seta
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         [rf_probs, dl_probs, xgb_probs, cat_probs]
                           │
              Stacking Meta-Model (seta)
                           │
              Weighted Ensemble Combined
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           BUY(≥0.7)  HOLD(0.3-0.7)  SELL(≤0.3)
                           │
              Real-Time ComparisonLive
                           │
              Groq LLM Integration




Exact Data Flow (100% Verified from Code)

┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: RAW DATA (Scrape from Binance/CoinGecko)                 │
│                                                             │
│ fetch_binance("BTCUSDT") → {price, high_24h, low_24h, volume}  │
│ fetch_coingecko("bitcoin") → {price, market_cap, etc.}        │
└─────────────────────────┬──────────────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: SCHEMAS (Data Validation)                              │
│                                                             │
│ From app/schemas.py: CryptoSignalInput, CryptoPredictionInput    │
│ Fields: symbol, current_price, high_24h, low_24h,         │
│         total_volume, timestamp, etc.                          │
└─────────────────────────┬──────────────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: META PIPELINE (Enrichment - SetaFeatureEnricher)      │
│                                                             │
│ app/core/meta.py → SetaFeatureEnricher.enrich_features()     │
│                                                             │
│ Adds:                                                      │
│   • Technical: SMA20/50, EMA20/50, RSI14, BB, ATR           │
│   • Volatility: return_1/3, rolling_vol_7/14              │
│   • Lagged: price_lag_1/3/5/7, volume_lag_1/3/5/7      │
│   • Sentiment: reddit_sentiment, news_headlines             │
│   • Temporal: hour, day_of_week, month, quarter          │
│   • Orderbook: orderbook_imbalance                        │
│   • Labels: price_direction (target)                     │
└─────────────────────────┬──────────────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: 5-MODEL ENSEMBLE                                   │
│                                                             │
│ Model files (in models/):                                  │
│   1. rf_model.joblib           (Random Forest)              │
│   2. lstm_model.joblib         (LSTM Deep Learning)          │
│   3. xgb_model.joblib         (XGBoost)                   │
│   4. cat_model.joblib         (CatBoost)                   │
│   5. calibrated_stacking_model.joblib (Meta-Ensemble)       │
│                                                             │
│ Code: app/core/meta.py _compute_ensemble_probs()             │
│       app/api/crypto.py _trained_bundle_for_model()           │
└─────────────────────────┬──────────────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: STACKING (4 Models → 1 Meta)                      │
│                                                             │
│ Stacking feature names: ["rf", "dl", "xgb", "cat"]           │
│                                                             │
│ rf_probs, dl_probs, xgb_probs, cat_probs                  │
│         ↓                                                    │
│         Meta-X = {rf: rf_probs, dl: dl_probs, ...}          │
│         ↓                                                    │
│         calibrated.predict_proba(Meta-X) → seta_probs       │
│                                                             │
│ Combined = weighted_average(rf + dl + xgb + cat + seta)    │
└─────────────────────────┬──────────────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 6: REAL-TIME COMPARISON                                 │
│                                                             │
│ Live fetch: fetch_binance() + fetch_coingecko()              │
│ Compare ensemble prediction vs real-time price               │
│ Signal: BUY (prob ≥ 0.7), SELL (prob ≤ 0.3), HOLD   │
└─────────────────────────┬──────────────────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: GROQ LLM INTEGRATION                             │
│                                                             │
│ Prediction results sent to chat for LLM explanation     │
│ Endpoint: POST /meta/crypto/predict-ensemble             │
│          GET  /meta/crypto/target-precision-meta-live     │
└────────────────────────────────────────────────────────────────────────────────────────────┘
YOUR QUESTIONS ANSWERED:
Question	Answer
Meta pipeline used for each prediction?	✅ YES - SetaFeatureEnricher.enrich_features() called for every prediction
Data from Binance?	✅ YES - fetch_binance() in app/core/meta.py
Modeled data + schemas?	✅ YES - Data validated via app/schemas.py
Enrich via meta pipeline?	✅ YES - SetaFeatureEnricher adds 20+ features
Share with 5 models?	✅ YES - All 5 models loaded via load_model_safe()
4 share to ensemble?	✅ YES - rf, dl, xgb, cat → stacking meta-model
Compare in real-time?	✅ YES - Live fetch in target_precision_meta_live
Read by Groq?	✅ YES - Results available to LLM via chat
CONFIRMATION: 100% TRUE - All features confirmed from source code analysis.
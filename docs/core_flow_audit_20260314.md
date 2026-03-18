# Core Flow Audit (Strict) - 2026-03-14

Scope: evaluate core runtime flow integrity, identify holes, and verify end-to-end contracts across API, services, scripts, and tests.

## Summary Verdict

- Core codebase integrity: **healthy after fixes**
- Core strict runtime closure: **pass** (host run with strict/core profile)
- Previous crypto blocker: **resolved**

## What Was Verified

## 1) Fixes applied

1. Restored crypto model metadata module:
   - `app/models/ml/models.py`
   - `app/models/ml/__init__.py`
2. Added crypto trade safety to startup smoke list:
   - `app/scripts/start_with_preflight.py` (`tests/test_crypto_trade_safety.py`)
3. Aligned UI contract gate with compact image mode:
   - `app/scripts/ui_contract_check.py` now checks `attachBtn`, `imageQuickBar`, `imageModeGuide`, `imgInput`.

## 2) Focused test repass

- `pytest -q tests/test_crypto_trade_safety.py tests/test_chat_tool_first.py tests/test_ui_image_mode_compact.py` -> **pass**.

## 3) Live strict/core repass (host)

Executed on `http://127.0.0.1:8013` with:
- `AEGIS_RUNTIME_PROFILE=strict`
- `AEGIS_PRODUCT_TRACK=core`
- `AEGIS_DISABLE_DB=1`

Results:
- `doctor --track core`: **pass** (`20/20`).
- `verify_full --runtime-profile strict --product-track core`: **pass**.
  - includes: full pytest, e2e strict(core contract), agent evals, UI contract, hard contract, no-loop stress, browser smoke.
- Crypto endpoints in flow:
  - `/crypto/models` -> **ok**
  - `/crypto/ohlcv` -> **ok**
  - `/crypto/news` -> **ok**

## 4) Notes (non-blockers for core strict)

- A separate standalone run of `e2e_flow_check --strict-capabilities` fails when image backend (`127.0.0.1:8188`) is down.
- This is expected for strict-capability behavior and is **not** a core strict gate blocker when running core track contracts.

## Connectivity Status (Core)

- API orchestration path (`main` -> routers -> handlers): **connected**
- Chat/files/auth/system/image core routes: **connected**
- Crypto route family: **connected**
- Tooling contracts (hard/no-loop/agent eval): **connected and passing**

## Operational Read

- Core strict readiness in this snapshot: **GO**.
- Full strict closure still requires full-track host conditions and 72h soak artifact per `docs/full_strict_closure.md`.

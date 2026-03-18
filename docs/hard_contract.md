# Hard Contract (Release Gate)

## Objetivo
Bloquear release cuando falle cualquiera de estas reglas:

1. No respuestas de extracto de archivo para prompts no orientados a proyecto.
2. Selección de fuente explícita y visible (`web_live`, `web_cache`, `local_project`, `local_model`).
3. No spam oculto de polling `401/403`.
4. Routing determinístico con fail-closed en ambigüedad.

## Gates implementados

- `app/scripts/adversarial_eval_check.py`
  - Suite determinística de 520 casos.
  - Incluye multi-turn (`project -> world -> project`), prompts de ruido y edge-cases de web.
  - En modo estricto falla si no alcanza el mínimo (`--min-cases`, default 500) o si no pasa 100%.

- `app/scripts/hard_contract_check.py`
  - Ejecuta adversarial eval.
  - En `--strict`, requiere `--base-url` (fail-closed si no está presente).
  - En `--strict`, ejecuta también un soak corto como bloqueador real (configurable).
  - En `--strict`, ejecuta también no-loop stress como bloqueador real.
  - Si hay `--base-url`, además valida tasas operativas desde `/system/metrics`:
    - `wrong_route_rate <= 0.5%`
    - `safety_fallback_rate <= 3%`
    - `poll_401_rate <= 2%`

- `app/scripts/soak_gate.py`
  - Soak configurable (default 72h).
  - Genera tráfico scriptado y valida umbrales al final.
  - Incluye retry por tick y cobertura mínima de rutas para evitar falsos negativos por un único glitch de transporte.

- `app/scripts/no_loop_stress_check.py`
  - Stress corto sobre `agent_run` con presupuestos acotados.
  - Falla si detecta violaciones de budget/stop_reason o latencias anómalas por run.
  - Soporta escenario de borde de auth (`--auth-edge-every`): inyecta key inválida cada N runs y valida respuesta `401/403` esperada.

## Integración de flujo

- `start_with_preflight.py` (perfil `strict`)
  - Paso nuevo: `hard-contract`.
  - `hard-contract` incluye soak corto por defecto en strict.
  - Paso nuevo: `no-loop-stress` (bloqueador en strict).
  - Si falla, no levanta servidor para demo/release.

- `verify_full.py` (perfil `strict`)
  - Paso nuevo: `hard-contract`.
  - No permite `--skip-hard-contract` en strict.
  - `hard-contract` incluye soak corto por defecto en strict.
  - Paso nuevo: `no-loop-stress` (no permite skip en strict).

- CI (`.github/workflows/ci.yml`)
  - Paso nuevo: `python -m app.scripts.adversarial_eval_check --strict --min-cases 500`
  - Si falla, bloquea pipeline.

## Observabilidad

- `app/services/runtime_metrics.py`
  - Contadores/rates para:
    - `safety_fallback_rate`
    - `poll_401_rate`
    - `ambiguous_route_rate`
    - `low_confidence_route_rate`
    - distribución de fuente por respuesta
    - distribución de bucket de confianza de ruteo (`high/medium/low/unknown`)
    - bloqueos por ruteo ambiguo

- Endpoints:
  - `GET /system/metrics`
  - `GET /system/snapshot` -> incluye `runtime_metrics`
  - `GET /system/readyz` -> incluye resumen de rates

## Flags de rollback

- `AEGIS_ROUTER_DETERMINISTIC_STRICT=1|0`
- `AEGIS_ROUTER_FAIL_CLOSED=1|0`
- `AEGIS_FOCUS_CLEAR_ON_TOPIC_SWITCH=1|0`

Con estas flags puedes volver atrás rápidamente sin deshacer código ni migraciones.

## Tuning rápido (soak en strict)

- `AEGIS_CONTRACT_SOAK_HOURS` (default `0.001` ~= 3.6s)
- `AEGIS_CONTRACT_SOAK_INTERVAL_SECONDS` (default `1.5`)
- `AEGIS_CONTRACT_SOAK_WINDOW_SECONDS` (default `900`)

También puedes forzar soak en modo no-strict con `--run-soak`.

## Tuning rápido (no-loop + auth edge)

- `AEGIS_CONTRACT_MAX_WRONG_ROUTE_RATE` (default `0.005`)
- `AEGIS_CONTRACT_MAX_SAFETY_FALLBACK_RATE` (default `0.03`)
- `AEGIS_CONTRACT_MAX_POLL_401_RATE` (default `0.02`)
- `AEGIS_CONTRACT_MAX_TRANSPORT_FAILURES` (default `0`)
- `AEGIS_CONTRACT_SOAK_ATTEMPTS_PER_TICK` (default `2`)
- `AEGIS_CONTRACT_SOAK_CHAT_TIMEOUT_SECONDS` (default `45`)
- `AEGIS_CONTRACT_SOAK_MIN_ROUTE_CHECKED` (default `1`)
- `AEGIS_CONTRACT_SOAK_STARTUP_TRANSPORT_GRACE` (default `1`)
- `AEGIS_CONTRACT_SOAK_MIN_ROUTE_ATTEMPT_TICKS` (default `3`)
- `AEGIS_CONTRACT_NO_LOOP_RUNS` (default `8`)
- `AEGIS_CONTRACT_NO_LOOP_REQUEST_TIMEOUT` (default `45`)
- `AEGIS_CONTRACT_NO_LOOP_MAX_SECONDS` (default `35`)
- `AEGIS_CONTRACT_MAX_NO_LOOP_FAILURES` (default `0`)
- `AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_EVERY` (default `0`, deshabilitado)
- `AEGIS_CONTRACT_NO_LOOP_AUTH_EDGE_INVALID_KEY` (default `invalid-no-loop-key`)
- `AEGIS_CONTRACT_MAX_NO_LOOP_AUTH_EDGE_UNEXPECTED` (default `0`)
- `AEGIS_CONTRACT_MAX_AMBIGUOUS_ROUTE_RATE` (default `0.5`)
- `AEGIS_CONTRACT_MAX_LOW_CONFIDENCE_ROUTE_RATE` (default `0.75`)

# Binance Live Integration Checklist

## Objetivo

Verificar y documentar la integración mínima con Binance live, asegurando que el endpoint `/crypto/trade` responde correctamente en modo live y bloquea si faltan credenciales o el flag de entorno.

## Pasos

1. **Variables de entorno requeridas:**
   - `BINANCE_API_KEY`
   - `BINANCE_API_SECRET`
   - `BINANCE_LIVE_TRADING=1`

2. **Prueba de integración:**
   - Ejecutar el script `crypto_testnet_rehearsal.py` con `--execution-mode live` y `--submit-if-allowed`.
   - Validar que:
     - Si las variables/flag no están presentes, la orden es bloqueada y el modo cae a `simulated`.
     - Si están presentes, la orden se envía a Binance live (solo si es seguro y autorizado).

3. **Evidencia:**
   - Archivar el resultado en `artifacts/release_evidence/crypto_live_rehearsal/` con resumen JSON y Markdown.
   - Documentar el resultado (éxito o bloqueo controlado) en PROGRESO_FASES.md.

## Notas de seguridad
- Nunca activar live trading en entornos no controlados.
- Validar siempre el flag y credenciales antes de habilitar órdenes reales.

---

Este checklist debe ejecutarse y actualizarse tras cada ciclo relevante de integración live.

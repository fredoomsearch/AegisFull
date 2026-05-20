# Criterios de promoción automática y challenger governance

## Objetivo

Definir y documentar los criterios para la promoción automática de modelos (challenger governance) en el sistema cripto, asegurando trazabilidad y gobernanza clara.

## Criterios mínimos (manual/semiautomático)

1. **Evidencia archivada:**
   - El modelo challenger debe tener al menos un ciclo completo de evidencia archivada (testnet y simulated, con métricas de calibración y credibilidad).
2. **Métricas mínimas:**
   - Precisión fuera de muestra (OOS) ≥ 55%
   - Brier score ≤ 0.25
   - Net expectancy positiva en testnet
   - Trade count mínimo (ej. ≥ 20 trades)
3. **No bloqueos regulatorios ni técnicos:**
   - Sin bloqueos activos en risk gate, credibilidad o calibración
   - Sin fallos críticos en smoke o evidence bundle
4. **Revisión humana:**
   - Un operador debe validar el bundle y aprobar la promoción (modo manual hasta cerrar el lazo automático)

## Criterios automáticos (futuro)

- Promoción automática solo si:
  - El modelo challenger supera al champion en precisión y net expectancy en la misma ventana OOS
  - No hay bloqueos en credibilidad, calibración ni drawdown
  - El bundle de evidencia es válido y firmado

## Proceso

1. Ejecutar el script de evaluación y archivar el bundle.
2. Validar métricas y credenciales.
3. Registrar la decisión (promoción o rechazo) en el log de governance.
4. Actualizar el modelo activo si corresponde.

---

Este documento debe actualizarse conforme evolucione la lógica de challenger governance y se cierre el lazo automático.

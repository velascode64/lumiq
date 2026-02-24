```md
# Plan: Evaluación Automática de Estrategias por Agente (Heartbeat + Triggers)

## Objetivo
Definir cómo un agente puede **evaluar el performance de una estrategia** y decidir si:
- mantenerla igual,
- ajustar parámetros,
- pausar,
- o escalar una alerta para revisión humana.

## Resumen (recomendación)
Usar un modelo **híbrido**:
1. **Heartbeat periódico** (salud y performance general)
2. **Triggers por eventos/riesgo** (evaluación inmediata cuando hay degradación)

Esto es mejor que elegir solo uno:
- solo heartbeat = reacción lenta
- solo triggers = análisis incompleto / reactivo

---

## Qué debe evaluar el agente

### 1. Salud operativa (runtime)
- ¿La estrategia sigue viva?
- ¿Está ejecutando iteraciones en tiempo esperado?
- ¿Hay errores repetidos?
- ¿Hay órdenes rechazadas / timeouts / desconexiones?

### 2. Performance financiera
- PnL realizado y no realizado
- Drawdown actual y máximo
- Win rate
- Avg win / avg loss
- Expectancy
- Sharpe (si aplica por horizonte)
- Exposición y tamaño de posición
- Tiempo promedio en trade

### 3. Calidad de decisiones (señales)
- Frecuencia de señales
- Señales que no terminan en orden
- Slippage / fill quality
- Si la lógica está “sobre-operando” o “sub-operando”
- Comportamiento por régimen (alcista/lateral/bajista)

---

## Heartbeat vs Trigger (cómo usar cada uno)

## A. Heartbeat (periódico)
### Propósito
Revisar salud y tendencia del performance aunque no haya incidentes.

### Frecuencia recomendada
- **Cada 5 min**: salud operativa + snapshot rápido
- **Cada 1 hora**: resumen de performance corto
- **Cada 24 horas**: evaluación profunda del agente

### Qué hace
- Lee métricas agregadas recientes
- Compara con baseline de la estrategia
- Detecta degradación gradual
- Genera recomendaciones (no necesariamente acciones)

### Ejemplo de salida
- `Estado: OK`
- `PnL 24h: -1.8%`
- `Drawdown actual: 3.2%`
- `Recomendación: observar, sin cambios`

---

## B. Trigger (por evento/riesgo)
### Propósito
Disparar una evaluación inmediata cuando ocurre algo anómalo o peligroso.

### Triggers recomendados (ejemplos)
- **PnL cae > 10%** en ventana definida (ej. 24h o desde inicio de run)
- Drawdown supera umbral (ej. 8%)
- 3+ pérdidas consecutivas grandes
- Error operativo repetido (ej. 5 rechazos de orden)
- Desviación de comportamiento (ej. frecuencia de trades anormal)
- Estrategia sin heartbeat por X minutos (posible freeze)

### Qué hace
- Congela snapshot de contexto
- Llama al agente evaluador
- Clasifica severidad
- Propone acción o ejecuta policy automática

### Ejemplo de salida
- `Severidad: alta`
- `Causa probable: aumento de volatilidad / parámetros agresivos`
- `Acción sugerida: reducir tamaño 30% o pausar`

---

## Arquitectura recomendada (simple y escalable)

## 1. Eventos y métricas (base de datos)
Guardar en DB (Supabase/Postgres) datos estructurados, no solo logs de texto.

### Requisito de diseño: módulo de logging (opcional)
- Este sistema de logging/telemetría debe implementarse como **módulo independiente** (ej. `strategy_observability` o `strategy_metrics_logger`), no mezclado dentro de cada estrategia.
- Las estrategias solo emiten eventos/snapshots a una interfaz común (`emit_event`, `emit_metric`, `emit_alert`).
- El backend del módulo decide el destino:
  - **DB habilitada/configurada** -> persiste en Supabase/Postgres
  - **DB no configurada** -> fallback a logs estructurados (archivo/stdout)

### Comportamiento por configuración (fallback)
- `DB logging enabled`: guardar eventos estructurados + métricas + triggers
- `DB logging disabled/not configured`: no se rompe el sistema; se registran eventos en logs para auditoría básica
- Esto permite desarrollo local/simple sin depender de DB, y producción con persistencia cuando esté lista

### Tablas mínimas
- `strategy_runs`
- `strategy_events`
- `equity_snapshots`
- `trade_fills`
- `daily_strategy_metrics`
- `strategy_alerts` (triggers de performance)
- `agent_evaluations`

## 2. Evaluador de estrategia (agente)
Un agente especializado que:
- consume métricas + eventos recientes
- compara contra baseline
- explica causas probables
- devuelve recomendación estructurada

## 3. Policy Engine (reglas automáticas)
Antes de ejecutar cambios reales, separar:
- `Agente recomienda`
- `Policy decide si se ejecuta automático`

Ejemplo:
- Si `drawdown > 10%` -> **pausar automáticamente**
- Si `PnL < -5%` 24h -> solo notificar y pedir confirmación

## 4. Notificaciones operativas (Telegram / otros canales)
Este módulo también debe poder **emitir notificaciones de eventos críticos** (además de persistir).

### Ejemplo de uso
- Si ocurre un trigger de pérdida grande (ej. `PnL <= -10% en 24h`)
  - guardar evento/alerta (DB o logs según configuración)
  - notificar por Telegram:
    - estrategia afectada
    - severidad
    - pérdida detectada
    - acción sugerida / ejecutada (si aplica)

### Principio
- Persistencia y notificación deben estar desacopladas:
  - un evento puede persistirse aunque falle Telegram
  - una notificación puede enviarse aunque no haya DB (fallback logs + Telegram)

---

## Flujo propuesto (híbrido)

### Flujo 1: Heartbeat
1. Scheduler corre heartbeat
2. Calcula/agrega métricas
3. Si todo normal, solo registra
4. Si ve degradación, crea `trigger soft`
5. Agente evalúa y recomienda

### Flujo 2: Trigger crítico
1. Evento de riesgo detectado (`PnL <= -10%`)
2. Se registra alerta crítica
3. Se invoca agente evaluador inmediatamente
4. Se ejecuta policy:
   - notificar
   - pausar
   - kill/panic (si regla lo exige)
5. Se guarda evaluación del agente para auditoría

---

## ¿Cuándo entra el agente? (respuesta directa)
Sí: **exactamente como dices**.

### Regla concreta recomendada
- Si una estrategia pierde **10% en un período definido** (por ejemplo 24h o desde `run_start`):
  - se dispara un **trigger crítico**
  - entra un **agente evaluador**
  - produce diagnóstico + recomendación
  - y una policy decide si:
    - pausa,
    - mata (`kill`),
    - o solo notifica

Esto debe convivir con el heartbeat periódico.

---

## Qué debe devolver el agente (formato recomendado)
Salida estructurada (no solo texto libre):

- `strategy_name`
- `run_id`
- `evaluation_time`
- `severity`: `low | medium | high | critical`
- `diagnosis`
- `likely_causes[]`
- `metrics_snapshot`
- `recommended_actions[]`
- `confidence`
- `requires_human_approval` (bool)

Esto permite automatizar sin depender de parsing de texto.

---

## Baselines y comparación (muy importante)
El agente no debe evaluar “en vacío”.

Debe comparar contra:
- baseline histórico de esa estrategia
- baseline por mercado/régimen
- baseline por versión de parámetros

Ejemplo:
- `-3%` puede ser normal en alta volatilidad para una estrategia agresiva
- pero crítico para una conservadora

---

## Acciones posibles (ordenadas por riesgo)
1. `notify_only`
2. `reduce_position_size`
3. `widen/narrow thresholds` (solo en paper primero)
4. `pause_strategy`
5. `kill_strategy`
6. `panic_stop` (cancelar órdenes + cerrar posiciones + kill)

---

## Guardrails (para no romper producción)
- El agente **no cambia parámetros en vivo automáticamente** al inicio
- Primero: recomienda
- Luego: validación humana o policy estricta
- Cambios automáticos solo en:
  - paper trading
  - estrategias marcadas como auto-tunable
  - límites acotados

---

## Fases de implementación (sin romper lo actual)

### Fase 1 (rápida)
- Heartbeat básico (health + PnL + drawdown)
- Trigger de pérdida > 10%
- Agente evaluador solo recomienda
- Notificación por Telegram

### Fase 2
- Persistencia estructurada en Supabase/Postgres
- Baselines por estrategia
- Evaluaciones guardadas (`agent_evaluations`)
- Dashboard simple de runs y alertas

### Fase 3
- Policy engine configurable
- Auto-pause / auto-kill
- Experimentos controlados de ajuste de parámetros (paper)

---

## Criterios de éxito
- Si una estrategia cae >10% en la ventana definida, se genera trigger y evaluación del agente
- El agente explica por qué recomienda pausar o ajustar
- Todo queda auditado (métricas + evaluación + acción tomada)
- No dependemos de logs de texto para análisis

---

## Decisiones recomendadas (defaults)
- Modelo: **híbrido (heartbeat + triggers)**
- Trigger crítico inicial: **PnL <= -10% en 24h** (ajustable)
- Heartbeat health: **cada 5 min**
- Heartbeat performance: **cada 1h**
- Agente al inicio: **solo recomendación**, no auto-cambios
- Acción automática permitida inicial: **notify + optional pause** (no tuning en vivo)
```

Si quieres, el siguiente paso te lo puedo bajar a un diseño más concreto de tablas (`Supabase`) y eventos exactos que necesitas emitir desde cada estrategia.

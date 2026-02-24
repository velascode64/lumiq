```md
# Plan: Heartbeat de Agente Agno para Evaluación y Auto-Ajuste

## Resumen
Implementar un heartbeat interno (cada 15 minutos) que evalúe todas las estrategias activas, razone contra el objetivo de `+$1000` sobre baseline `~$10000`, y aplique ajustes de parámetros en caliente vía `orchestrator.update_parameters`, con guardrails estrictos (`allowlist + rangos`).  
Notificará por Telegram solo cuando haya cambios o alertas, y guardará aprendizaje en SQLite para mejorar entre ciclos y reinicios.

## Alcance decidido
- Autonomía: auto-ajuste de parámetros (sin start/stop desde heartbeat).
- Frecuencia: cada 15 minutos.
- Scope: todas las estrategias activas.
- Seguridad: `allowlist + rangos` por estrategia.
- Notificaciones: solo cambios y alertas.
- Persistencia: SQLite local.

## Implementación propuesta

### 1. Nuevo servicio heartbeat
Crear `lumibot-dev/packages/core/agent_heartbeat.py`:
1. Scheduler con `APScheduler` (intervalo 15m).
2. Dependencias inyectadas: `agent`, `orchestrator`, `broker_config`, callback de notificación, logger.
3. Ciclo por heartbeat:
1. Leer `orchestrator.get_all_status()`.
2. Leer estado cuenta Alpaca (equity/cash/positions).
3. Construir snapshot + historial reciente.
4. Pedir al agente propuesta JSON de ajustes.
5. Validar con guardrails.
6. Aplicar cambios válidos con `update_parameters`.
7. Persistir evento en SQLite.
8. Notificar Telegram solo si hubo cambios/alertas.

### 2. Integración con bot de Telegram
Actualizar flujo de `telegram_trading_bot.py`:
1. Arrancar heartbeat al inicializar el bot.
2. Pararlo limpiamente al terminar polling.
3. Registrar `chat_id` que interactúan para enviar alertas del heartbeat.
4. Si no hay chats activos, solo log/persistencia.

### 3. Guardrails de parámetros
Crear `lumibot-dev/packages/core/heartbeat_guardrails.py`:
1. Catálogo por estrategia con parámetros permitidos y rangos.
2. Reglas globales:
1. Máximo 3 cambios por estrategia/ciclo.
2. Cooldown 30 min por parámetro.
3. Rechazar cambios abruptos (delta máximo configurable).
4. Registrar razón de rechazo.

Rangos iniciales para `LiveCryptoMeanReaversionStrategy`:
- `zscore_entry`: `[0.75, 1.60]`
- `zscore_exit`: `[0.10, 0.60]`
- `stop_loss_pct`: `[0.01, 0.06]`
- `take_profit_pct`: `[0.015, 0.10]`
- `base_position_pct`: `[0.05, 0.35]`
- `max_position_pct`: `[0.10, 0.40]`
- `aggressive_factor`: `[0.70, 1.80]`
- `max_open_positions`: `[1, 3]`

### 4. Memoria y aprendizaje persistente
SQLite en `lumibot-dev/packages/core/data/agent_heartbeat.db`:
1. `heartbeat_events`:
- timestamp, snapshot, agent_output, applied_changes, alerts, errors.
2. `baseline_state`:
- baseline_equity, baseline_timestamp.
3. `param_change_log`:
- strategy, param, old, new, reason, confidence, applied_at.

Retención sugerida: últimos 7 días.

### 5. Ajuste de agente Agno (persistencia)
En `agno_trading_agent.py`:
1. Añadir storage/memory persistente local:
- `SqliteStorage(...)`
- `Memory(db=SqliteMemoryDb(...))`
- `enable_agentic_memory=True`
2. Mantener reglas actuales:
- no start/stop por chat;
- sí consultar estado y ajustar parámetros.

## Contrato de salida del razonamiento (JSON)
El heartbeat exigirá salida JSON estricta del agente:
1. `summary`
2. `alerts[]`
3. `actions[]` con:
- `strategy`
- `parameter_updates`
- `reason`
- `confidence`

Solo se aplican acciones que pasen validación local.

## Variables `.env` nuevas
- `AGENT_HEARTBEAT_ENABLED=true`
- `AGENT_HEARTBEAT_INTERVAL_MINUTES=15`
- `AGENT_HEARTBEAT_DB_FILE=packages/core/data/agent_heartbeat.db`
- `AGENT_HEARTBEAT_MAX_PARAM_CHANGES=3`
- `AGENT_HEARTBEAT_PARAM_COOLDOWN_MINUTES=30`
- `AGENT_HEARTBEAT_NOTIFY_ONLY_ON_CHANGE=true`

## Manejo de fallos
1. Si falla LLM/MCP/red:
- no aplicar cambios;
- registrar error;
- continuar próximo ciclo.
2. Si falla fetch de cuenta Alpaca:
- operar con estado de estrategias;
- marcar evento parcial.
3. Si JSON inválido:
- descartar ciclo;
- guardar salida cruda.

## Validación funcional (manual)
1. Sin estrategias activas:
- heartbeat corre y persiste evento `idle`.
2. Con estrategia activa y propuesta válida:
- aplica cambios y notifica Telegram.
3. Propuesta fuera de rango:
- rechaza cambio y registra motivo.
4. Doble cambio al mismo parámetro antes de cooldown:
- segundo cambio bloqueado.
5. Reinicio del bot:
- mantiene baseline/historial desde SQLite.

## Notas operativas
- El heartbeat no ejecuta órdenes directas ni controla lifecycle.
- Start/stop sigue siendo por comandos (`/run`, `/stop`).
- Si una estrategia también se autoajusta internamente, heartbeat solo aplica dentro de guardrails.
```
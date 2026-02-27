# Lumiq: DB + Shared Memory Foundation for Autonomous Agent Collaboration (Fase 1-2)

## Proposito

Construir la base de datos y la capa de memoria compartida para que los agentes de Lumiq:

- compartan contexto y hallazgos entre si
- coordinen investigaciones y mejoras de estrategias
- persistan watchlists, alertas, reportes y resultados
- preparen el terreno para un futuro `LumibotLabTeam` (backtesting + optimizacion + generacion de estrategias)

Este documento define **solo Fase 1 y Fase 2**.

## Contexto (inspiracion aplicable de `automaton`)

Del repo `automaton` la idea util para Lumiq no es la “replicacion”, sino estos patrones:

- `state/` -> **DB como source of truth**
- `memory/` -> memoria separada por tipo (semantic/episodic/procedural)
- `orchestration/task-graph.ts` -> coordinacion por tareas y resultados
- `social/client.ts` -> mensajes tipados con deduplicacion/rate-limit
- `heartbeat/tasks.ts` -> cron/heartbeat con persistencia y reintentos

En Lumiq aplicaremos una version mas simple y enfocada a trading/strategies.

---

## Decision Principal

### DB
- **Supabase Postgres** como base de datos principal (server-side via service role)
- Migraciones en `supabase/migrations/`
- `JSON`/`JSONB` para payloads flexibles
- `TEXT + CHECK` para enums (simple y portable)

### Patrón de coordinación entre agentes
- **No** usar solo “conversacion LLM” para coordinación
- **Sí** usar:
  - `agent_messages` (mensajes tipados)
  - `tasks` / `task_runs`
  - `artifacts`
  - `memory_*` (shared knowledge)

### Agno
- Los agentes de Agno seguiran existiendo como hoy
- Agregaremos tools de DB/memory para que lean/escriban conocimiento compartido
- Session memory de Agno puede usarse luego, pero **la coordinación principal** irá en tablas propias de Lumiq

---

## Scope

## Fase 1 (Fundacion: 1-2 semanas)

- Supabase + Postgres + migraciones
- mover watchlist/alerts a DB
- `agent_messages`, `tasks`, `artifacts`
- persistencia de reportes/hallazgos minimos

## Fase 2 (Memoria compartida: 1-2 semanas)

- `memory_semantic`, `memory_episodic`, `memory_procedural`
- tools `remember`, `recall`, `log_experiment`
- namespacing por `team/strategy/ticker`

## Fuera de scope (por ahora)

- RAG/vector search (pgvector) para documentos largos
- auto-deploy live sin aprobacion humana
- self-modification de codigo en produccion
- task graph completo estilo colony/openclaw

---

## Arquitectura Objetivo (Fase 1-2)

### Equipos actuales (operativos)
- `TradingAlertTeam` (alerts, technicals, news, live_trading, strategy_ops)

### Equipo futuro (se habilita con esta base)
- `LumibotLabTeam` (research, hypothesis, codex bridge, backtest, evaluator, risk reviewer)

### Capa de persistencia compartida (nueva)
- Supabase Postgres
- accesible desde `platform/*` y tools de agentes

### Integracion con la estructura actual de Lumiq
- `lumiq/platform/alerts/*` -> dejar de usar JSON como source of truth
- `lumiq/platform/portfolio/review.py` -> watchlist desde DB
- `lumiq/platform/news/news_monitor.py` -> watchlist desde DB
- `lumiq/app/services/chat_service.py` -> comandos de watchlist/alerts apuntan a DB services
- `lumiq/agents/agno/members/*` -> tools de memoria/coordination

---

## Supabase Setup (Recomendado)

## Proyecto y acceso

- Crear proyecto Supabase para Lumiq
- Usar **server-side service role key** desde `lumiq` (FastAPI/runtime)
- No exponer DB directo a Telegram/frontend

## Variables de entorno (backend)

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `LUMIQ_DATABASE_URL` (opcional si usas SQLAlchemy/psycopg directo)

Recomendacion:
- v1 usar cliente Supabase **o** psycopg/SQLAlchemy para queries directos
- migraciones y schema management con **Supabase CLI**

## Supabase CLI workflow (v1)

- `supabase init`
- `supabase link --project-ref <project-ref>`
- `supabase migration new <name>`
- `supabase db push` (staging/prod)

---

## Schema v1 (Fase 1)

## 1) Watchlist y grupos

### `watchlist_groups`
Propósito: reemplazar `watchlist.json` y permitir agrupación/favoritos/benchmarks.

Campos:
- `id uuid pk default gen_random_uuid()`
- `name text not null` (ej. `fang`, `crypto`, `cybersecurity`)
- `kind text not null` (`group`, `favorites`, `benchmarks`)
- `description text null`
- `is_active boolean not null default true`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Constraints:
- unique (`name`)
- check `kind in ('group','favorites','benchmarks')`

### `watchlist_items`
Propósito: items dentro de grupos.

Campos:
- `id uuid pk`
- `group_id uuid not null fk -> watchlist_groups.id on delete cascade`
- `symbol text not null` (normalizado, ej `ETH/USD`, `AAPL`)
- `asset_class text not null` (`stock`, `crypto`, `etf`, `other`)
- `display_name text null` (ej. `Cloudflare`)
- `priority int not null default 0`
- `is_favorite boolean not null default false`
- `meta jsonb not null default '{}'::jsonb`
- `created_at timestamptz not null default now()`

Constraints/Indexes:
- unique (`group_id`, `symbol`)
- index (`symbol`)
- check `asset_class in ('stock','crypto','etf','other')`

Notas:
- `favorites` se modela como grupo con `kind='favorites'`
- benchmarks pueden vivir en un grupo `benchmarks` o grupos por clase (`benchmarks_stocks`, `benchmarks_crypto`)

---

## 2) Alertas (persistencia)

### `alerts`
Propósito: reemplazar `alert_rules.json`.

Campos:
- `id uuid pk`
- `chat_id bigint null` (si quieres multi-chat)
- `symbol text not null`
- `rule_type text not null` (`percent_drop`, `percent_rise`, `target_price`, `rsi_threshold`, etc.)
- `threshold numeric null`
- `target_price numeric null`
- `reference_price numeric null`
- `cooldown_seconds int null`
- `is_active boolean not null default true`
- `source text not null default 'manual'` (`manual`, `agent`, `system`)
- `created_by_agent text null`
- `meta jsonb not null default '{}'::jsonb`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Indexes:
- index (`symbol`)
- index (`is_active`)
- index (`chat_id`, `is_active`)

### `alert_events`
Propósito: historial de disparos/evaluaciones.

Campos:
- `id uuid pk`
- `alert_id uuid not null fk -> alerts.id on delete cascade`
- `symbol text not null`
- `event_type text not null` (`triggered`, `cooldown_skip`, `deactivated`, `error`)
- `price numeric null`
- `reference_price numeric null`
- `message text null`
- `payload jsonb not null default '{}'::jsonb`
- `created_at timestamptz not null default now()`

Indexes:
- index (`alert_id`, `created_at desc`)
- index (`symbol`, `created_at desc`)

---

## 3) Coordinacion entre agentes (mensajes + tareas + artefactos)

### `agent_messages`
Propósito: mensajeria tipada entre agentes/teams (no solo chat history LLM).

Campos:
- `id uuid pk`
- `thread_id text not null` (ej. `lab:eth-momentum-2026q1`)
- `from_agent text not null` (ej. `HypothesisAgent`)
- `to_agent text null` (ej. `BacktestRunnerAgent`) — null si broadcast al team
- `to_team text null` (ej. `LumibotLabTeam`)
- `message_type text not null`
  - ejemplos: `research_hypothesis`, `backtest_request`, `backtest_result`, `risk_review`, `deployment_recommendation`, `observation`
- `priority text not null default 'normal'` (`low`,`normal`,`high`,`urgent`)
- `status text not null default 'pending'` (`pending`,`read`,`processed`,`failed`)
- `subject text null`
- `payload jsonb not null`
- `related_strategy_id uuid null`
- `related_backtest_run_id uuid null`
- `related_symbol text null`
- `created_at timestamptz not null default now()`
- `processed_at timestamptz null`

Indexes:
- index (`thread_id`, `created_at`)
- index (`to_agent`, `status`, `created_at`)
- index (`to_team`, `status`, `created_at`)
- index (`message_type`)

### `tasks`
Propósito: unidad de trabajo para investigación/analisis/ejecución de backtests.

Campos:
- `id uuid pk`
- `task_key text unique not null` (idempotencia)
- `team_name text not null`
- `task_type text not null`
  - ejemplos: `backtest_run`, `evaluate_strategy`, `fetch_signals`, `news_digest_analysis`, `strategy_patch_request`
- `status text not null`
  - `pending`, `queued`, `running`, `completed`, `failed`, `cancelled`, `blocked`
- `priority int not null default 50`
- `requested_by text not null` (`user`, `cron`, `agent:<name>`)
- `owner_agent text null`
- `title text not null`
- `description text null`
- `input jsonb not null default '{}'::jsonb`
- `result jsonb not null default '{}'::jsonb`
- `error text null`
- `scheduled_for timestamptz null`
- `started_at timestamptz null`
- `finished_at timestamptz null`
- `created_at timestamptz not null default now()`

Indexes:
- index (`team_name`, `status`, `priority desc`, `created_at`)
- index (`owner_agent`, `status`)
- index (`task_type`, `created_at`)
- index (`scheduled_for`)

### `task_runs`
Propósito: historial/reintentos de ejecución por task.

Campos:
- `id uuid pk`
- `task_id uuid not null fk -> tasks.id on delete cascade`
- `runner text not null` (ej. `backtest-worker`, `news-cron`, `api`)
- `attempt int not null`
- `status text not null` (`running`,`completed`,`failed`)
- `started_at timestamptz not null default now()`
- `finished_at timestamptz null`
- `logs_summary text null`
- `metrics jsonb not null default '{}'::jsonb`
- `error text null`

Index:
- index (`task_id`, `attempt desc`)

### `artifacts`
Propósito: indexar archivos/resultados generados (csv, plots, reports, notebooks, diffs).

Campos:
- `id uuid pk`
- `artifact_type text not null` (`csv`,`json`,`plot`,`report`,`strategy_code`,`diff`,`log`)
- `storage_kind text not null default 'local_fs'` (`local_fs`,`supabase_storage`,`external`)
- `path text not null`
- `checksum text null`
- `size_bytes bigint null`
- `mime_type text null`
- `meta jsonb not null default '{}'::jsonb`
- `created_by text not null` (agent/worker)
- `task_id uuid null fk -> tasks.id on delete set null`
- `created_at timestamptz not null default now()`

Indexes:
- index (`task_id`)
- index (`artifact_type`, `created_at desc`)

---

## 4) Reportes y hallazgos minimos (Fase 1)

### `reports`
Propósito: persistencia ligera de reportes que hoy llegan por Telegram (monitoring + auditoria).

Campos:
- `id uuid pk`
- `report_type text not null` (`pre_open`,`midday`,`close`,`weekly`,`news_preopen`)
- `scope_type text not null` (`watchlist`,`group`,`portfolio`,`symbol`)
- `scope_value text null` (ej. `cybersecurity`)
- `chat_id bigint null`
- `title text not null`
- `summary text not null`
- `payload jsonb not null default '{}'::jsonb` (version estructurada opcional)
- `created_by text not null` (`cron`, `agent:<name>`, `user`)
- `created_at timestamptz not null default now()`

Indexes:
- index (`report_type`, `created_at desc`)
- index (`scope_type`, `scope_value`, `created_at desc`)

### `observations`
Propósito: hallazgos cortos reutilizables (pre-memoria formal).

Campos:
- `id uuid pk`
- `source_agent text not null`
- `team_name text null`
- `observation_type text not null` (`market`, `strategy`, `risk`, `alert`, `news`)
- `symbol text null`
- `strategy_name text null`
- `severity text not null default 'info'` (`info`,`warning`,`critical`)
- `content text not null`
- `payload jsonb not null default '{}'::jsonb`
- `created_at timestamptz not null default now()`

Indexes:
- index (`symbol`, `created_at desc`)
- index (`strategy_name`, `created_at desc`)
- index (`observation_type`, `created_at desc`)

---

## Schema v2 (Fase 2: Shared Memory)

Objetivo: permitir que agentes recuerden hechos, experimentos y procedimientos, con namespace por team/strategy/ticker.

## Namespace estándar (en todas las tablas de memoria)

Campos comunes:
- `team_name text null` (ej. `TradingAlertTeam`, `LumibotLabTeam`)
- `strategy_name text null` (ej. `ETHMomentumLive`)
- `symbol text null` (ej. `ETH/USD`)
- `scope_key text generated/logical` (opcional en query layer; no obligatorio en DB)

Regla:
- toda escritura de memoria debe incluir **al menos uno**: `team_name`, `strategy_name`, `symbol`

### `memory_semantic`
Hechos relativamente estables.

Campos:
- `id uuid pk`
- `team_name text null`
- `strategy_name text null`
- `symbol text null`
- `category text not null` (ej. `regime`, `risk_rule`, `asset_behavior`, `strategy_fact`)
- `fact_key text not null`
- `fact_value text not null`
- `confidence numeric not null default 1.0`
- `source text not null` (`agent`, `user`, `backtest`, `report`, `manual`)
- `source_ref text null` (artifact/report/task id)
- `meta jsonb not null default '{}'::jsonb`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Constraints/Indexes:
- unique (`team_name`, `strategy_name`, `symbol`, `category`, `fact_key`)
- index (`category`)
- index (`symbol`)
- full-text opcional posterior

### `memory_episodic`
Eventos/experimentos concretos con outcome.

Campos:
- `id uuid pk`
- `team_name text null`
- `strategy_name text null`
- `symbol text null`
- `episode_type text not null`
  - `backtest_run`, `optimization_trial`, `incident`, `signal_review`, `alert_postmortem`
- `title text not null`
- `summary text not null`
- `outcome text null` (`success`,`failure`,`mixed`)
- `importance numeric not null default 0.5`
- `task_id uuid null fk -> tasks.id`
- `artifact_id uuid null fk -> artifacts.id`
- `payload jsonb not null default '{}'::jsonb`
- `created_by text not null`
- `created_at timestamptz not null default now()`

Indexes:
- index (`episode_type`, `created_at desc`)
- index (`strategy_name`, `created_at desc`)
- index (`symbol`, `created_at desc`)

### `memory_procedural`
Playbooks/checklists/procedimientos que los agentes pueden reutilizar.

Campos:
- `id uuid pk`
- `team_name text null`
- `strategy_name text null`
- `symbol text null`
- `procedure_name text not null`
- `description text not null`
- `steps jsonb not null` (lista ordenada de pasos)
- `version int not null default 1`
- `success_count int not null default 0`
- `failure_count int not null default 0`
- `last_used_at timestamptz null`
- `created_by text not null`
- `meta jsonb not null default '{}'::jsonb`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Constraints/Indexes:
- unique (`team_name`, `strategy_name`, `symbol`, `procedure_name`, `version`)
- index (`procedure_name`)

---

## Tools de Agentes (Fase 1-2)

## Fase 1: coordinación + persistencia

### Watchlist tools
- `watchlist_list_groups()`
- `watchlist_list_items(group_name)`
- `watchlist_create_group(name, kind='group')`
- `watchlist_add_items(group_name, symbols[])`
- `watchlist_remove_item(group_name, symbol)`
- `watchlist_remove_group(name)`

### Alerts tools (DB-backed)
- `alerts_list(chat_id=None, active_only=True)`
- `alerts_create(...)`
- `alerts_update(...)`
- `alerts_deactivate(alert_id)`
- `alerts_log_event(alert_id, event_type, payload)`

### Coordination tools
- `send_agent_message(thread_id, to_agent|to_team, message_type, payload, ...)`
- `poll_agent_messages(to_agent|to_team, status='pending', limit=...)`
- `mark_agent_message_processed(message_id, status='processed'|'failed')`
- `create_task(task_type, input, team_name, task_key, ...)`
- `claim_task(task_id, owner_agent)`
- `complete_task(task_id, result, artifacts=[])`
- `fail_task(task_id, error)`
- `create_artifact(...)`
- `create_report(...)`
- `log_observation(...)`

## Fase 2: memory tools

### Semantic memory
- `remember_fact(team_name?, strategy_name?, symbol?, category, key, value, confidence=1.0, source=...)`
- `recall_facts(category?, symbol?, strategy_name?, query?)`

### Episodic memory
- `log_experiment(team_name?, strategy_name?, symbol?, episode_type, title, summary, outcome, payload, task_id?, artifact_id?)`
- `recall_episodes(symbol?, strategy_name?, episode_type?, limit=20)`

### Procedural memory
- `save_procedure(team_name?, strategy_name?, symbol?, procedure_name, description, steps[])`
- `recall_procedure(procedure_name|query, team_name?, strategy_name?, symbol?)`
- `record_procedure_outcome(procedure_id, success: bool)`

### Memory review helper (muy util)
- `review_memory_scope(team_name?, strategy_name?, symbol?)`
  - resumen corto para inyectar contexto a otros agentes

---

## Flujo de “Agentes Conversan” (v1 recomendado)

No hacer:
- “agent A le pregunta en lenguaje natural a agent B” sin persistencia

Hacer:
1. Agent A crea `task` o `agent_message` tipado
2. Agent B toma el task / poll de mensajes
3. Agent B ejecuta tool deterministic (backtest/news/tecnicals/etc.)
4. Agent B persiste:
   - `task_run`
   - `artifacts`
   - `observations`
   - `memory_*` (si aplica)
5. Agent B responde con `agent_message` de resultado

Esto permite:
- auditoria
- reintentos
- evitar duplicados
- que otros agentes lean el resultado luego

---

## Integracion con Lumiq (cambios por modulo)

## Fase 1

### `platform/portfolio/review.py`
- Reemplazar `WatchlistStore` JSON por `WatchlistRepository` (DB)
- Mantener interface pública similar para no romper reportes

### `platform/alerts/alert_system.py`
- Reemplazar stores JSON (`alert_rules_store`, `portfolio_store`) por repositorio DB
- `alert_events` se escriben en DB

### `platform/news/news_monitor.py`
- Leer watchlist desde DB
- Persistir `reports` / `observations` del digest pre-open

### `app/services/chat_service.py`
- Operaciones de watchlist y alertas deben ir a repositorios DB
- Comandos siguen igual para el usuario (misma UX)

### `agents/agno/members/*`
- Agregar tools de coordinación (`agent_messages`, `tasks`, `artifacts`, `observations`)

## Fase 2

### `agents/agno/members/technical_agent.py`
- poder leer `memory_semantic` (hechos de comportamiento de activos)
- loggear hallazgos relevantes en `memory_episodic`

### `agents/agno/members/news_agent.py`
- guardar catalizadores relevantes en `memory_semantic` y `observations`
- loggear episodios de impacto notable (`episodic`)

### `agents/agno/members/strategy_ops_agent.py`
- log de cambios importantes de parametros en `memory_episodic`
- leer procedimientos (`memory_procedural`) de operation checklists

---

## Migración de Datos (sin romper la app)

## Fuente actual a migrar
- `watchlist.json` (watchlists/grupos/favorites/benchmarks)
- `alert_rules.json`
- `portfolio.json` (si aún se usa localmente para algo de alerts/portfolio)

## Estrategia de migración
1. Crear tablas y repositorios
2. Crear script one-off de import:
   - `scripts/migrate_watchlist_json_to_db.py`
   - `scripts/migrate_alerts_json_to_db.py`
3. Switch por feature flag:
   - `LUMIQ_USE_DB_WATCHLIST=true`
   - `LUMIQ_USE_DB_ALERTS=true`
4. Mantener fallback JSON temporal solo durante transición
5. Eliminar JSON stores como source of truth

---

## Seguridad / Acceso (Supabase)

## v1 (server-side only)
- Backend Lumiq usa `SUPABASE_SERVICE_ROLE_KEY`
- No acceso DB directo desde Telegram/frontend
- RLS puede dejarse:
  - deshabilitado inicialmente para tablas internas, **o**
  - habilitado con políticas de service-only (si quieres endurecer desde el inicio)

Recomendacion v1:
- server-only, sin RLS compleja todavía
- agregar RLS cuando entren usuarios frontend multi-tenant

## v2+ (multiusuario)
- agregar `owner_user_id` / `workspace_id`
- RLS por workspace/chat/user

---

## Observabilidad y Auditoria (mínimo en Fase 1-2)

Guardar siempre:
- `created_by` (user/agent/cron/worker)
- timestamps
- `task_runs`
- `artifacts`
- `reports`

Objetivo:
- saber quien cambió qué
- reconstruir por qué una estrategia se mejoró o empeoró

---

## Acceptance Criteria

## Fase 1
- Watchlist CRUD funciona desde Telegram y persiste en DB
- Alertas persisten en DB y alert stream sigue funcionando
- Reporte diario/semanal usa watchlist desde DB
- `agent_messages`, `tasks`, `artifacts`, `reports`, `observations` se pueden crear/leer desde servicios
- Ningún feature visible actual se rompe (Telegram/API siguen funcionando)

## Fase 2
- Agentes pueden guardar y consultar memoria semantic/episodic/procedural
- Namespacing por `team/strategy/ticker` funciona
- Se puede registrar un experimento de backtest y recuperarlo
- Se puede guardar y reutilizar un procedimiento (playbook/checklist)
- Los agentes tienen un helper de `review_memory_scope(...)` para contexto compartido

---

## Roadmap inmediato (ejecución)

## Semana 1 (Fase 1a)
- Supabase init + migraciones base
- repositorios DB (`watchlist`, `alerts`)
- migración de JSON -> DB
- switch de `platform/portfolio/review.py` y `platform/alerts/alert_system.py`

## Semana 2 (Fase 1b)
- `agent_messages`, `tasks`, `task_runs`, `artifacts`, `reports`, `observations`
- tools mínimas de coordinación para agentes
- persistencia de reportes/hallazgos desde cron

## Semana 3 (Fase 2a)
- tablas `memory_semantic`, `memory_episodic`, `memory_procedural`
- tools `remember/recall/log_experiment`
- integración básica en `news_agent` + `technical_agent`

## Semana 4 (Fase 2b)
- procedural memory para playbooks
- `review_memory_scope` helper
- pruebas end-to-end con un “mini flujo de investigación”

---

## Preparación para Fase 3 (LumibotLabTeam + Codex)

Esta base deja listo:
- `tasks` para backtests/optimizaciones
- `artifacts` para CSVs/equity curves/reports/diffs
- `memory_episodic` para resultados de experimentos
- `memory_procedural` para playbooks de iteración
- `agent_messages` para coordinación entre `HypothesisAgent`, `BacktestRunnerAgent`, `EvaluatorAgent`, `CodexBridgeAgent`

El siguiente paso (Fase 3) ya puede construir encima sin rehacer la base.


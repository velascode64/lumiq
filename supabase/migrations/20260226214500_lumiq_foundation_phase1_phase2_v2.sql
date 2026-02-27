-- Lumiq Foundation (Phase 1 + Phase 2)
-- Domain persistence + agent coordination + shared memory
-- Safe/idempotent creation for Supabase Postgres

create extension if not exists pgcrypto;

-- =========================
-- Watchlist / Groups
-- =========================

create table if not exists public.watchlist_groups (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  kind text not null check (kind in ('group', 'favorites', 'benchmarks')),
  description text,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.watchlist_items (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.watchlist_groups(id) on delete cascade,
  symbol text not null,
  asset_class text not null default 'other' check (asset_class in ('stock','crypto','etf','other')),
  display_name text,
  priority integer not null default 0,
  is_favorite boolean not null default false,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint uq_watchlist_group_symbol unique (group_id, symbol)
);

create index if not exists idx_watchlist_groups_kind on public.watchlist_groups(kind);
create index if not exists idx_watchlist_items_group_id on public.watchlist_items(group_id);
create index if not exists idx_watchlist_items_symbol on public.watchlist_items(symbol);

-- =========================
-- Alerts
-- =========================

create table if not exists public.alerts (
  id text primary key,
  chat_id bigint,
  symbol text not null,
  rule_type text not null,
  threshold numeric,
  target_price numeric,
  reference_price numeric,
  cooldown_seconds integer,
  is_active boolean not null default true,
  source text not null default 'manual',
  created_by_agent text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_alerts_chat_id on public.alerts(chat_id);
create index if not exists idx_alerts_symbol on public.alerts(symbol);
create index if not exists idx_alerts_rule_type on public.alerts(rule_type);
create index if not exists idx_alerts_is_active on public.alerts(is_active);

create table if not exists public.alert_events (
  id uuid primary key default gen_random_uuid(),
  alert_id text not null references public.alerts(id) on delete cascade,
  symbol text not null,
  event_type text not null,
  price numeric,
  reference_price numeric,
  message text,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_alert_events_alert_id on public.alert_events(alert_id);
create index if not exists idx_alert_events_symbol on public.alert_events(symbol);
create index if not exists idx_alert_events_event_type on public.alert_events(event_type);
create index if not exists idx_alert_events_created_at on public.alert_events(created_at desc);

-- =========================
-- Agent Coordination
-- =========================

create table if not exists public.agent_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id text not null,
  from_agent text not null,
  to_agent text,
  to_team text,
  message_type text not null,
  priority text not null default 'normal' check (priority in ('low','normal','high','urgent')),
  status text not null default 'pending' check (status in ('pending','read','processed','failed')),
  subject text,
  payload jsonb not null,
  related_strategy_id uuid,
  related_backtest_run_id uuid,
  related_symbol text,
  created_at timestamptz not null default now(),
  processed_at timestamptz
);

create index if not exists idx_agent_messages_thread on public.agent_messages(thread_id, created_at);
create index if not exists idx_agent_messages_to_agent_status on public.agent_messages(to_agent, status, created_at);
create index if not exists idx_agent_messages_to_team_status on public.agent_messages(to_team, status, created_at);
create index if not exists idx_agent_messages_type on public.agent_messages(message_type);
create index if not exists idx_agent_messages_related_symbol on public.agent_messages(related_symbol);

create table if not exists public.tasks (
  id uuid primary key default gen_random_uuid(),
  task_key text not null unique,
  team_name text not null,
  task_type text not null,
  status text not null default 'pending' check (status in ('pending','queued','running','completed','failed','cancelled','blocked')),
  priority integer not null default 50,
  requested_by text not null,
  owner_agent text,
  title text not null,
  description text,
  input jsonb not null default '{}'::jsonb,
  result jsonb not null default '{}'::jsonb,
  error text,
  scheduled_for timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_tasks_team_status_priority on public.tasks(team_name, status, priority desc, created_at);
create index if not exists idx_tasks_owner_agent_status on public.tasks(owner_agent, status);
create index if not exists idx_tasks_type_created on public.tasks(task_type, created_at desc);
create index if not exists idx_tasks_scheduled_for on public.tasks(scheduled_for);

create table if not exists public.task_runs (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references public.tasks(id) on delete cascade,
  runner text not null,
  attempt integer not null,
  status text not null check (status in ('running','completed','failed')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  logs_summary text,
  metrics jsonb not null default '{}'::jsonb,
  error text
);

create index if not exists idx_task_runs_task_attempt on public.task_runs(task_id, attempt desc);

create table if not exists public.artifacts (
  id uuid primary key default gen_random_uuid(),
  artifact_type text not null,
  storage_kind text not null default 'local_fs',
  path text not null,
  checksum text,
  size_bytes bigint,
  mime_type text,
  meta jsonb not null default '{}'::jsonb,
  created_by text not null,
  task_id uuid references public.tasks(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists idx_artifacts_task_id on public.artifacts(task_id);
create index if not exists idx_artifacts_type_created on public.artifacts(artifact_type, created_at desc);

-- =========================
-- Reports / Observations
-- =========================

create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(),
  report_type text not null,
  scope_type text not null,
  scope_value text,
  chat_id bigint,
  title text not null,
  summary text not null,
  payload jsonb not null default '{}'::jsonb,
  created_by text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_reports_type_created on public.reports(report_type, created_at desc);
create index if not exists idx_reports_scope on public.reports(scope_type, scope_value, created_at desc);
create index if not exists idx_reports_chat_id on public.reports(chat_id);

create table if not exists public.observations (
  id uuid primary key default gen_random_uuid(),
  source_agent text not null,
  team_name text,
  observation_type text not null,
  symbol text,
  strategy_name text,
  severity text not null default 'info' check (severity in ('info','warning','critical')),
  content text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_observations_symbol_created on public.observations(symbol, created_at desc);
create index if not exists idx_observations_strategy_created on public.observations(strategy_name, created_at desc);
create index if not exists idx_observations_type_created on public.observations(observation_type, created_at desc);

-- =========================
-- Shared Memory (Phase 2)
-- =========================

create table if not exists public.memory_semantic (
  id uuid primary key default gen_random_uuid(),
  team_name text,
  strategy_name text,
  symbol text,
  category text not null,
  fact_key text not null,
  fact_value text not null,
  confidence numeric(4,3) not null default 1.0,
  source text not null,
  source_ref text,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_memory_semantic_scope_key unique (team_name, strategy_name, symbol, category, fact_key)
);

create index if not exists idx_memory_semantic_category on public.memory_semantic(category);
create index if not exists idx_memory_semantic_symbol on public.memory_semantic(symbol);
create index if not exists idx_memory_semantic_strategy on public.memory_semantic(strategy_name);
create index if not exists idx_memory_semantic_team on public.memory_semantic(team_name);

create table if not exists public.memory_episodic (
  id uuid primary key default gen_random_uuid(),
  team_name text,
  strategy_name text,
  symbol text,
  episode_type text not null,
  title text not null,
  summary text not null,
  outcome text,
  importance numeric(4,3) not null default 0.5,
  task_id uuid,
  artifact_id uuid,
  payload jsonb not null default '{}'::jsonb,
  created_by text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_memory_episodic_type_created on public.memory_episodic(episode_type, created_at desc);
create index if not exists idx_memory_episodic_symbol_created on public.memory_episodic(symbol, created_at desc);
create index if not exists idx_memory_episodic_strategy_created on public.memory_episodic(strategy_name, created_at desc);
create index if not exists idx_memory_episodic_team_created on public.memory_episodic(team_name, created_at desc);

create table if not exists public.memory_procedural (
  id uuid primary key default gen_random_uuid(),
  team_name text,
  strategy_name text,
  symbol text,
  procedure_name text not null,
  description text not null,
  steps jsonb not null,
  version integer not null default 1,
  success_count integer not null default 0,
  failure_count integer not null default 0,
  last_used_at timestamptz,
  created_by text not null,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_memory_procedural_name on public.memory_procedural(procedure_name);
create index if not exists idx_memory_procedural_symbol on public.memory_procedural(symbol);
create index if not exists idx_memory_procedural_strategy on public.memory_procedural(strategy_name);
create index if not exists idx_memory_procedural_team on public.memory_procedural(team_name);

-- =========================
-- Chat Context (deterministic routing context)
-- =========================

create table if not exists public.chat_sessions (
  chat_id bigint primary key,
  user_id bigint,
  active_domain text,
  active_symbol text,
  active_group text,
  timeframe text,
  last_agent text,
  context_json jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index if not exists idx_chat_sessions_user_id on public.chat_sessions(user_id);

create table if not exists public.chat_turns (
  id uuid primary key default gen_random_uuid(),
  chat_id bigint not null,
  user_id bigint,
  role text not null check (role in ('user','assistant','system')),
  content text not null,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_chat_turns_chat_created on public.chat_turns(chat_id, created_at desc);
create index if not exists idx_chat_turns_user_id on public.chat_turns(user_id);


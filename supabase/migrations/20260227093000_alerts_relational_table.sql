BEGIN;

CREATE TABLE IF NOT EXISTS public.alerts (
    id text PRIMARY KEY,
    chat_id bigint NULL,
    user_id bigint NULL,
    symbol text NOT NULL,
    rule_type text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    cooldown_seconds integer NOT NULL DEFAULT 3600,
    threshold_pct numeric(18,8) NULL,
    target_price numeric(18,8) NULL,
    reference_price numeric(18,8) NULL,
    last_triggered_price numeric(18,8) NULL,
    last_triggered_at timestamptz NULL,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);

CREATE INDEX IF NOT EXISTS idx_alerts_chat_id ON public.alerts(chat_id);
CREATE INDEX IF NOT EXISTS idx_alerts_user_id ON public.alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON public.alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_rule_type ON public.alerts(rule_type);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON public.alerts(active);
CREATE INDEX IF NOT EXISTS idx_alerts_last_triggered_at ON public.alerts(last_triggered_at DESC);

DO $$
BEGIN
  IF to_regclass('public.alerts_state') IS NOT NULL THEN
    INSERT INTO public.alerts (
      id,
      chat_id,
      user_id,
      symbol,
      rule_type,
      active,
      cooldown_seconds,
      threshold_pct,
      target_price,
      reference_price,
      last_triggered_price,
      last_triggered_at,
      params,
      created_at,
      updated_at
    )
    SELECT
      COALESCE(rule->>'id', md5(random()::text || clock_timestamp()::text)) AS id,
      NULLIF(rule->>'chat_id', '')::bigint AS chat_id,
      NULLIF(rule->>'user_id', '')::bigint AS user_id,
      UPPER(COALESCE(rule->>'symbol', '')) AS symbol,
      COALESCE(rule->>'type', rule->>'rule_type', '') AS rule_type,
      COALESCE((rule->>'active')::boolean, true) AS active,
      COALESCE((rule->>'cooldown_seconds')::integer, 3600) AS cooldown_seconds,
      NULLIF(rule->>'threshold', '')::numeric(18,8) AS threshold_pct,
      NULLIF(rule->>'target', '')::numeric(18,8) AS target_price,
      NULLIF(rule->>'reference_price', '')::numeric(18,8) AS reference_price,
      NULLIF(rule->>'last_triggered_price', '')::numeric(18,8) AS last_triggered_price,
      NULLIF(rule->>'last_triggered_at', '')::timestamptz AS last_triggered_at,
      COALESCE(
        (
          rule
          - 'id'
          - 'chat_id'
          - 'user_id'
          - 'symbol'
          - 'type'
          - 'rule_type'
          - 'active'
          - 'cooldown_seconds'
          - 'threshold'
          - 'target'
          - 'reference_price'
          - 'last_triggered_at'
          - 'last_triggered_price'
        ),
        '{}'::jsonb
      ) AS params,
      timezone('utc', now()) AS created_at,
      timezone('utc', now()) AS updated_at
    FROM public.alerts_state s,
         LATERAL jsonb_array_elements(COALESCE(s.payload->'rules', '[]'::jsonb)) AS rule
    WHERE COALESCE(rule->>'id', '') <> ''
      AND NOT EXISTS (
        SELECT 1 FROM public.alerts a WHERE a.id = COALESCE(rule->>'id', '')
      );
  END IF;
END $$;

COMMIT;

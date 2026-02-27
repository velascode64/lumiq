-- Consolidate alert persistence into a single JSON state table.
-- Keep migration idempotent for repeated environments.

CREATE TABLE IF NOT EXISTS public.alerts_state (
    id integer PRIMARY KEY,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT alerts_state_singleton CHECK (id = 1)
);

-- Seed from previous normalized tables if they still exist and singleton row is missing.
DO $$
DECLARE
  has_alerts boolean;
  has_alert_events boolean;
BEGIN
  SELECT to_regclass('public.alerts') IS NOT NULL INTO has_alerts;
  SELECT to_regclass('public.alert_events') IS NOT NULL INTO has_alert_events;

  IF NOT EXISTS (SELECT 1 FROM public.alerts_state WHERE id = 1) THEN
    IF has_alerts THEN
      INSERT INTO public.alerts_state (id, payload, updated_at)
      SELECT
        1,
        jsonb_build_object(
          'schema_version', 1,
          'updated_at', now(),
          'rules',
          COALESCE(
            jsonb_agg(
              jsonb_build_object(
                'id', a.id,
                'chat_id', a.chat_id,
                'symbol', a.symbol,
                'type', a.rule_type,
                'threshold', a.threshold,
                'target', a.target_price,
                'reference_price', a.reference_price,
                'cooldown_seconds', a.cooldown_seconds,
                'active', a.is_active,
                'source', a.source,
                'created_by_agent', a.created_by_agent,
                'created_at', a.created_at
              ) ORDER BY a.created_at ASC
            ),
            '[]'::jsonb
          ),
          'events',
          CASE
            WHEN has_alert_events THEN (
              SELECT COALESCE(
                jsonb_agg(
                  jsonb_build_object(
                    'id', e.id,
                    'alert_id', e.alert_id,
                    'symbol', e.symbol,
                    'event_type', e.event_type,
                    'price', e.price,
                    'reference_price', e.reference_price,
                    'message', e.message,
                    'payload', e.payload,
                    'created_at', e.created_at
                  ) ORDER BY e.created_at ASC
                ),
                '[]'::jsonb
              )
              FROM public.alert_events e
            )
            ELSE '[]'::jsonb
          END
        ),
        now()
      FROM public.alerts a;
    ELSE
      INSERT INTO public.alerts_state (id, payload, updated_at)
      VALUES (
        1,
        jsonb_build_object(
          'schema_version', 1,
          'updated_at', now(),
          'rules', '[]'::jsonb,
          'events', '[]'::jsonb
        ),
        now()
      );
    END IF;
  END IF;
END
$$;

DROP TABLE IF EXISTS public.alert_events;
DROP TABLE IF EXISTS public.alerts;


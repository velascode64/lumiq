BEGIN;

CREATE TABLE IF NOT EXISTS public.watchlist_groups (
    id text PRIMARY KEY,
    chat_id bigint NULL,
    user_id bigint NULL,
    name text NOT NULL,
    kind text NOT NULL DEFAULT 'custom',
    tickers jsonb NOT NULL DEFAULT '[]'::jsonb,
    benchmarks jsonb NOT NULL DEFAULT '{}'::jsonb,
    meta jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    CONSTRAINT uq_watchlist_groups_owner_name UNIQUE (chat_id, user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_watchlist_groups_chat_id ON public.watchlist_groups(chat_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_groups_user_id ON public.watchlist_groups(user_id);
CREATE INDEX IF NOT EXISTS idx_watchlist_groups_kind ON public.watchlist_groups(kind);

DO $$
BEGIN
  IF to_regclass('public.watchlist_state') IS NOT NULL THEN
    INSERT INTO public.watchlist_groups (
      id,
      chat_id,
      user_id,
      name,
      kind,
      tickers,
      benchmarks,
      meta,
      created_at,
      updated_at
    )
    SELECT
      'watchlist-' || lower(grp.name) AS id,
      NULL::bigint AS chat_id,
      NULL::bigint AS user_id,
      lower(grp.name) AS name,
      'custom' AS kind,
      COALESCE(
        (
          SELECT jsonb_agg(
            CASE
              WHEN position('/' in upper(btrim(elem.value))) > 0 THEN replace(upper(btrim(elem.value)), '-', '/')
              WHEN position('-' in upper(btrim(elem.value))) > 0 AND length(upper(btrim(elem.value))) <= 12 THEN replace(upper(btrim(elem.value)), '-', '/')
              ELSE upper(btrim(elem.value))
            END
            ORDER BY elem.ord
          )
          FROM jsonb_array_elements_text(COALESCE(grp.tickers::jsonb, '[]'::jsonb)) WITH ORDINALITY AS elem(value, ord)
          WHERE btrim(elem.value) <> ''
        ),
        '[]'::jsonb
      ) AS tickers,
      '{}'::jsonb AS benchmarks,
      '{}'::jsonb AS meta,
      timezone('utc', now()) AS created_at,
      timezone('utc', now()) AS updated_at
    FROM public.watchlist_state s,
         LATERAL jsonb_each(COALESCE((s.payload::jsonb)->'groups', '{}'::jsonb)) AS grp(name, tickers)
    WHERE NOT EXISTS (
      SELECT 1 FROM public.watchlist_groups wg WHERE wg.id = 'watchlist-' || lower(grp.name)
    );

    INSERT INTO public.watchlist_groups (
      id,
      chat_id,
      user_id,
      name,
      kind,
      tickers,
      benchmarks,
      meta,
      created_at,
      updated_at
    )
    SELECT
      'watchlist-favorites' AS id,
      NULL::bigint AS chat_id,
      NULL::bigint AS user_id,
      'favorites' AS name,
      'favorites' AS kind,
      COALESCE(
        (
          SELECT jsonb_agg(
            CASE
              WHEN position('/' in upper(btrim(elem.value))) > 0 THEN replace(upper(btrim(elem.value)), '-', '/')
              WHEN position('-' in upper(btrim(elem.value))) > 0 AND length(upper(btrim(elem.value))) <= 12 THEN replace(upper(btrim(elem.value)), '-', '/')
              ELSE upper(btrim(elem.value))
            END
            ORDER BY elem.ord
          )
          FROM jsonb_array_elements_text(COALESCE((s.payload::jsonb)->'favorites', '[]'::jsonb)) WITH ORDINALITY AS elem(value, ord)
          WHERE btrim(elem.value) <> ''
        ),
        '[]'::jsonb
      ) AS tickers,
      COALESCE((s.payload::jsonb)->'benchmarks', '{}'::jsonb) AS benchmarks,
      '{}'::jsonb AS meta,
      timezone('utc', now()) AS created_at,
      timezone('utc', now()) AS updated_at
    FROM public.watchlist_state s
    WHERE jsonb_array_length(COALESCE((s.payload::jsonb)->'favorites', '[]'::jsonb)) > 0
      AND NOT EXISTS (
        SELECT 1 FROM public.watchlist_groups wg WHERE wg.id = 'watchlist-favorites'
      );
  END IF;
END $$;

COMMIT;

-- Consolidate watchlist persistence into a single JSON state table.

CREATE TABLE IF NOT EXISTS public.watchlist_state (
    id integer PRIMARY KEY,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT watchlist_state_singleton CHECK (id = 1)
);

DO $$
DECLARE
  has_groups boolean;
  has_items boolean;
BEGIN
  SELECT to_regclass('public.watchlist_groups') IS NOT NULL INTO has_groups;
  SELECT to_regclass('public.watchlist_items') IS NOT NULL INTO has_items;

  IF NOT EXISTS (SELECT 1 FROM public.watchlist_state WHERE id = 1) THEN
    IF has_groups AND has_items THEN
      INSERT INTO public.watchlist_state (id, payload, updated_at)
      WITH group_rows AS (
        SELECT
          g.name AS gname,
          g.kind AS gkind,
          COALESCE(
            jsonb_agg(i.symbol ORDER BY i.priority DESC, i.symbol ASC)
              FILTER (WHERE i.symbol IS NOT NULL),
            '[]'::jsonb
          ) AS symbols,
          COALESCE(bool_or(i.is_favorite), false) AS has_favorite
        FROM public.watchlist_groups g
        LEFT JOIN public.watchlist_items i ON i.group_id = g.id
        GROUP BY g.name, g.kind
      ),
      groups_json AS (
        SELECT COALESCE(
          jsonb_object_agg(lower(gname), symbols)
            FILTER (WHERE gkind IN ('group', 'favorites')),
          '{}'::jsonb
        ) AS groups_obj
        FROM group_rows
      ),
      favorites_json AS (
        SELECT COALESCE(
          jsonb_agg(DISTINCT i.symbol) FILTER (WHERE i.is_favorite = true),
          '[]'::jsonb
        ) AS favorites_arr
        FROM public.watchlist_items i
      ),
      benchmarks_json AS (
        SELECT COALESCE(
          jsonb_object_agg(lower(gname), symbols) FILTER (WHERE gkind = 'benchmarks'),
          '{}'::jsonb
        ) AS benchmarks_obj
        FROM group_rows
      )
      SELECT
        1,
        jsonb_build_object(
          'schema_version', 1,
          'updated_at', now(),
          'groups', COALESCE(gj.groups_obj, '{}'::jsonb),
          'favorites', COALESCE(fj.favorites_arr, '[]'::jsonb),
          'benchmarks',
            CASE
              WHEN bj.benchmarks_obj = '{}'::jsonb THEN
                jsonb_build_object('stocks', jsonb_build_array('SPY', 'QQQ'), 'crypto', jsonb_build_array('BTC/USD', 'ETH/USD'))
              ELSE bj.benchmarks_obj
            END
        ),
        now()
      FROM groups_json gj, favorites_json fj, benchmarks_json bj;
    ELSE
      INSERT INTO public.watchlist_state (id, payload, updated_at)
      VALUES (
        1,
        jsonb_build_object(
          'schema_version', 1,
          'updated_at', now(),
          'groups', '{}'::jsonb,
          'favorites', '[]'::jsonb,
          'benchmarks', jsonb_build_object('stocks', jsonb_build_array('SPY', 'QQQ'), 'crypto', jsonb_build_array('BTC/USD', 'ETH/USD'))
        ),
        now()
      );
    END IF;
  END IF;
END
$$;

DROP TABLE IF EXISTS public.watchlist_items;
DROP TABLE IF EXISTS public.watchlist_groups;


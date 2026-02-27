BEGIN;

ALTER TABLE public.watchlist_groups
    ALTER COLUMN id SET DEFAULT gen_random_uuid()::text;

COMMIT;

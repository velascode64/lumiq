BEGIN;

ALTER TABLE public.alerts
    ALTER COLUMN cooldown_seconds SET DEFAULT 3600;

UPDATE public.alerts
SET cooldown_seconds = 3600,
    updated_at = timezone('utc', now())
WHERE cooldown_seconds IS NULL OR cooldown_seconds = 300;

COMMIT;

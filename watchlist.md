# My Portfolio Watchlists

This file is the human-readable source of truth for the watchlists you want Lumiq to monitor.

## Crypto
- BTC
- ETH
- BCH
- COIN
- MSTR
- SOL
- HOOD
- IBIT
- XRPC
- BSOL
- XRP
- DOGE

## FAANG
- META
- QQQ
- XLK
- TSLA
- GOOGL
- AAPL
- AMZN
- NFLX
- UBER

## AI Semiconductors
- ASML
- TT
- MU
- SMH
- TSM
- SOXX
- AMD
- NVDA
- EWW
- QCOM
- INTC

## AI
- PLTR
- ADI
- AVGO
- SOXX
- NBIS
- CHAT
- IGPT
- ARTY
- ROBT
- AIQ
- BOTZ
- APLD

## ETFs
- SPY
- DIA
- VTI
- BOXX
- VXUS
- BND
- BINC
- BNDX
- TOPT

## Gold
- GLD
- IAU
- SLV
- ICOP

## Supabase Seed SQL

Run this in Supabase SQL Editor to load the watchlists into `public.watchlist_groups`.

Notes:
- `chat_id` and `user_id` are `NULL` for now
- `benchmarks` stay on the same row as optional JSON
- the script is rerunnable because it deletes the current global rows first

```sql
BEGIN;

DELETE FROM public.watchlist_groups
WHERE chat_id IS NULL
  AND user_id IS NULL
  AND name IN ('crypto', 'faang', 'ai-semiconductors', 'ai', 'etfs', 'gold');

INSERT INTO public.watchlist_groups (chat_id, user_id, name, kind, tickers, benchmarks, meta)
VALUES
  (
    NULL,
    NULL,
    'crypto',
    'custom',
    '["BTC","ETH","BCH","COIN","MSTR","SOL","HOOD","IBIT","XRPC","BSOL","XRP","DOGE"]'::jsonb,
    '{"crypto":["BTC/USD","ETH/USD"]}'::jsonb,
    '{}'::jsonb
  )
;

INSERT INTO public.watchlist_groups (chat_id, user_id, name, kind, tickers, benchmarks, meta)
VALUES
  (
    NULL,
    NULL,
    'faang',
    'custom',
    '["META","QQQ","XLK","TSLA","GOOGL","AAPL","AMZN","NFLX","UBER"]'::jsonb,
    '{"stocks":["SPY","QQQ"]}'::jsonb,
    '{}'::jsonb
  )
;

INSERT INTO public.watchlist_groups (chat_id, user_id, name, kind, tickers, benchmarks, meta)
VALUES
  (
    NULL,
    NULL,
    'ai-semiconductors',
    'custom',
    '["ASML","TT","MU","SMH","TSM","SOXX","AMD","NVDA","EWW","QCOM","INTC"]'::jsonb,
    '{"stocks":["SOXX","SMH","QQQ"]}'::jsonb,
    '{}'::jsonb
  )
;

INSERT INTO public.watchlist_groups (chat_id, user_id, name, kind, tickers, benchmarks, meta)
VALUES
  (
    NULL,
    NULL,
    'ai',
    'custom',
    '["PLTR","ADI","AVGO","SOXX","NBIS","CHAT","IGPT","ARTY","ROBT","AIQ","BOTZ","APLD"]'::jsonb,
    '{"stocks":["QQQ","SOXX"]}'::jsonb,
    '{}'::jsonb
  )
;

INSERT INTO public.watchlist_groups (chat_id, user_id, name, kind, tickers, benchmarks, meta)
VALUES
  (
    NULL,
    NULL,
    'etfs',
    'custom',
    '["SPY","DIA","VTI","BOXX","VXUS","BND","BINC","BNDX","TOPT"]'::jsonb,
    '{"stocks":["SPY","QQQ","DIA"]}'::jsonb,
    '{}'::jsonb
  )
;

INSERT INTO public.watchlist_groups (chat_id, user_id, name, kind, tickers, benchmarks, meta)
VALUES
  (
    NULL,
    NULL,
    'gold',
    'custom',
    '["GLD","IAU","SLV","ICOP"]'::jsonb,
    '{"stocks":["GLD","SLV"]}'::jsonb,
    '{}'::jsonb
  )
;

COMMIT;
```

If you want these rows tied to your Telegram account later, replace `NULL` in `chat_id` with your real chat id.

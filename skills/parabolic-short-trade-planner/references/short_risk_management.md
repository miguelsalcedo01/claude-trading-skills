# Short Risk Management

## SEC Rule 201 (Short Sale Restriction)

Triggered when a security's regular-session intraday price drops 10%
or more from the prior day's regular-session close. While active:

- New short sales are restricted to prices ABOVE the national best bid
  (the "uptick rule").
- The restriction holds for the rest of the trading day **and** the
  full next trading day.

**Implementation note**: this skill inherits `prior_regular_close` from
Phase 1's `key_levels.prior_close` (sourced from FMP's
`historical-price-eod/full`, which is the regular-session 4:00 PM ET
close). It does NOT use FMP's quote endpoint `previousClose`, which
can drift to the aftermarket print.

`ssr_state_tracker.py` persists per-symbol state to
`state/parabolic_short/ssr_state_<ticker>_<date>.json` so today's
`ssr_triggered_today` rolls forward to tomorrow's
`ssr_carryover_from_prior_day`.

## Borrow inventory: Alpaca specifics

Alpaca only allows new short opens on Easy-To-Borrow (ETB) names. The
adapter encodes this exactly:

```
can_open_new_short = shortable AND easy_to_borrow
borrow_fee_apr     = None   # varies daily per symbol; NOT zero for ETB
manual_locate_required = True   # always
```

**ETB is not free borrow.** Alpaca (like essentially every broker) charges
a daily stock-borrow fee on short positions including ETB names; the rate
varies by symbol and day. This planner cannot know the rate in advance, so
it reports no number rather than a misleading `0.0` — factor carry cost
into any hold that extends beyond the day.

A name that is `shortable=True` but `easy_to_borrow=False` (HTB) cannot
be opened on Alpaca regardless of locate. Phase 2 marks these as
`borrow_inventory_unavailable` (a hard blocker) and renders the plan
as `plan_status: watch_only`.

`manual_locate_required` is True even on ETB names. The trader still
confirms locate at the broker before entry — it's an advisory reason,
not blocking, so plans for ETB names stay actionable.

## Position sizing

The `size_recipe_builder.py` outputs:

- `risk_usd` — per-trade risk in USD (account_size × risk_bps/10000).
- `max_position_value_usd` — per-symbol position cap (account_size ×
  max_position_pct/100), tightened if `current_short_exposure` is high.
- `shares_formula` — string form of the formula. Phase 3 evaluates it
  at trigger fire when actual entry/stop are known.
- `exposure_cap_applied` — True if the per-symbol cap was tightened
  because the aggregate short-book budget was already mostly used.
- `remaining_short_exposure_capacity_usd` — how much short-book
  headroom is left.

This deliberately excludes a fixed share count. ORL / first-red /
VWAP-fail entries only have known prices intraday, so committing to a
share count pre-market would be inaccurate.

## Short-Selling Tail Risk

Every number this planner emits is **planned** risk. On this specific
strategy — shorting parabolic small caps — realized loss is routinely
**2-5× planned risk** when a tail event intervenes. Assume it will.

- **Asymmetric loss**: a long can lose 100%; a short's loss is unbounded.
  A parabolic that doubles against the entry costs 100% of position value.
- **LULD trading halts**: parabolic small caps halt constantly. A stop
  above the high of day **cannot fill through a halt**, and the reopening
  print can be multiples of the planned risk away. `risk_at_trigger_usd`
  is not a maximum loss — treat 3× as the working assumption.
- **Short squeezes**: forced buying from other shorts' stops and margin
  calls accelerates exactly when the trade is most wrong.
- **Forced buy-ins**: the broker can close the position without consent
  if borrow is recalled, at any price.
- **Borrow fees**: accrue daily, including on ETB names (see above).
- **No re-entry**: after 2 stopped attempts on the same name in one day,
  stand down. Re-shorting a runner on tilt is the canonical short-side
  account-blowup pattern. The FSM's per-plan no-re-entry rule does not
  protect against manually spinning up a fresh plan — that discipline is
  the trader's.

## Daily loss limits

Not enforced in this MVP. The trader is responsible for honoring
account-level circuit breakers (see the `drawdown-circuit-breaker`
skill). A future revision can add a `state/` file recording realized
P&L and reject new plans when the daily loss limit is hit.

"""SEC Rule 201 (Short Sale Restriction) state tracker.

Rule 201 fires whenever a security drops 10 % or more from its prior-day
regular-session close. While active it bans short sales at or below the
national best bid for the rest of that day **and** the next trading day,
which Phase 2 must surface as a blocking reason.

Contract notes:
- ``prior_regular_close`` is the **regular-session 4:00 PM ET close**, not
  the after-hours quote. The screener inherits this value from Phase 1's
  ``key_levels.prior_close`` (which comes from
  ``historical-price-eod/full``). Phase 2 never re-pulls the previous day's
  close from FMP's ``quote`` endpoint because that field can drift to the
  aftermarket value.
- The state file lives in ``state/parabolic_short/ssr_state_<date>.json``
  so a re-run of generate_pre_market_plan can roll yesterday's
  ``ssr_triggered_today`` forward into today's
  ``ssr_carryover_from_prior_day`` deterministically.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SSR_DROP_THRESHOLD_PCT = 10.0


def evaluate_ssr(
    *,
    prior_regular_close: float,
    current_price: float,
    session_low: float | None = None,
    prior_day_state: dict | None = None,
) -> dict:
    """Compute the SSR state for a single symbol on the trading day.

    Rule 201 is a *latching* trigger: it fires when the **intraday low** of the
    regular session touches -10% from the prior regular-session close, and it
    stays on for the rest of the day even if price recovers. Callers should
    therefore pass ``session_low`` whenever regular-session bars are available;
    ``current_price`` alone can miss a trigger that already happened earlier in
    the session. Note that SSR is determined from regular-session consolidated
    prices — a premarket-only -10% print does not itself trigger SSR, but this
    planner treats it as triggered anyway (conservative for a short planner).

    Args:
        prior_regular_close: yesterday's 4:00 PM ET close (regular session).
        current_price: latest known intraday or premarket print.
        session_low: lowest regular-session print so far today, if known.
            The trigger latches off ``min(session_low, current_price)``.
        prior_day_state: prior trading day's stored SSR state, if any. When
            ``ssr_triggered_today`` was True on the prior trading day, today
            inherits ``ssr_carryover_from_prior_day=True`` per Rule 201.
    """
    if prior_regular_close <= 0:
        raise ValueError(f"prior_regular_close must be positive: {prior_regular_close}")

    low_print = current_price
    if session_low is not None and session_low < low_print:
        low_print = session_low
    drop_pct = (prior_regular_close - low_print) / prior_regular_close * 100.0
    triggered_today = drop_pct >= SSR_DROP_THRESHOLD_PCT

    carryover = bool(prior_day_state and prior_day_state.get("ssr_triggered_today"))

    return {
        "ssr_triggered_today": triggered_today,
        "ssr_carryover_from_prior_day": carryover,
        "prior_regular_close": prior_regular_close,
        "prior_regular_close_source": "phase1_inherit",
        "uptick_rule_active": triggered_today or carryover,
        "drop_from_prior_close_pct": round(drop_pct, 2),
    }


def state_path(state_dir: str | Path, ticker: str, as_of: str) -> Path:
    """Where today's per-symbol SSR state file lives."""
    return Path(state_dir) / f"ssr_state_{ticker}_{as_of}.json"


def load_prior_day_state(state_dir: str | Path, ticker: str, as_of: str) -> dict | None:
    """Read the prior *trading day's* state file so today can compute carryover.

    Rule 201 carryover is "remainder of day + next trading day", so a stock
    that trips SSR on Friday is still restricted on Monday. We walk back up to
    five calendar days (covering weekends and long holiday weekends) and use
    the most recent state file found. Only trading days produce state files,
    so the first hit is the prior trading day. Market holidays without a
    stored file simply yield ``None`` (no carryover signal available).
    """
    try:
        as_of_date = date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return None
    for days_back in range(1, 6):
        prior = (as_of_date - timedelta(days=days_back)).isoformat()
        p = state_path(state_dir, ticker, prior)
        if not p.exists():
            continue
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def save_state(state_dir: str | Path, ticker: str, as_of: str, state: dict) -> Path:
    """Persist today's state for tomorrow's carryover lookup."""
    p = state_path(state_dir, ticker, as_of)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["written_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p

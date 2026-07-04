#!/usr/bin/env python3
"""
Component 6: S&P 500 vs Breadth Divergence (Weight: 10%)

Detects divergence between price action and breadth participation.

Uses dual windows:
  - 60-day window (weight 0.6): Medium-term structural divergence
  - 20-day window (weight 0.4): Short-term early warning

Composite score = 60d_score * 0.6 + 20d_score * 0.4

With fewer than 60 rows the 60d window would silently cover the same span
as the 20d window while keeping its 0.6 weight and "structural" label, so
in that case scoring falls back to the single 20d window and the output
says so (`windows_used`).

Early Warning: 20d bearish (<=25) while 60d healthy (>=50) flags
an emerging short-term divergence before it becomes structural.

Input: S&P500_Price, Breadth_Index_8MA (last 60+ days for dual windows)

Scoring per window (100 = healthy):
  Both rising                        -> 70 (healthy rally)
  Both falling                       -> 30 (consistent decline)
  SP up(>3%) & Breadth down(<-0.05)  -> 10 (dangerous divergence)
  SP up(>1%) & Breadth down(<-0.03)  -> 25
  SP down(<-3%) & Breadth up(>+0.05) -> 80 (bullish divergence)
  SP down(<-1%) & Breadth up(>+0.03) -> 65
  Otherwise                          -> 50
"""


def calculate_divergence(rows: list[dict]) -> dict:
    """
    Calculate S&P 500 vs breadth divergence score using dual windows.

    Args:
        rows: All detail rows sorted by date ascending.

    Returns:
        Dict with score, signal, windows, and component details.
    """
    if not rows or len(rows) < 21:
        return {
            "score": 50,
            "signal": "NO DATA: Insufficient data for divergence analysis",
            "data_available": False,
        }

    latest = rows[-1]

    w20 = _compute_window(rows, 20)
    has_60d = len(rows) >= 61
    if has_60d:
        w60 = _compute_window(rows, 60)
        score = round(w60["score"] * 0.6 + w20["score"] * 0.4, 1)
        windows_used = "60d+20d"
    else:
        # Not enough history for a genuine structural window — score on the
        # 20d window alone rather than double-counting it under a 60d label.
        w60 = None
        score = float(w20["score"])
        windows_used = "20d_only (insufficient history for 60d window)"
    score = max(0, min(100, score))

    # Early Warning: short-term bearish divergence while long-term healthy
    early_warning = bool(w60) and w20["score"] <= 25 and w60["score"] >= 50

    # Headline reflects the window driving the composite: the WORST window,
    # so a 20d early-warning cannot hide behind a healthy 60d label.
    headline = w20 if (w60 is None or w20["score"] <= w60["score"]) else w60
    signal = _generate_signal(
        headline["sp_pct"],
        headline["breadth_chg"],
        headline["div_type"],
        headline["lookback_days"],
        early_warning,
    )

    compat = w60 if w60 is not None else w20
    result = {
        "score": score,
        "signal": signal,
        "data_available": True,
        "windows_used": windows_used,
        # Top-level backward compatibility (structural window when available)
        "sp500_pct_change": round(compat["sp_pct"], 2),
        "breadth_change": round(compat["breadth_chg"], 4),
        "sp500_latest": latest["S&P500_Price"],
        "sp500_past": compat["sp_past"],
        "ma8_latest": latest["Breadth_Index_8MA"],
        "ma8_past": compat["ma8_past"],
        "lookback_days": compat["lookback_days"],
        "divergence_type": compat["div_type"],
        "date": latest["Date"],
        "window_20d": {
            "score": w20["score"],
            "divergence_type": w20["div_type"],
            "sp500_pct_change": round(w20["sp_pct"], 2),
            "breadth_change": round(w20["breadth_chg"], 4),
            "lookback_days": w20["lookback_days"],
        },
        "early_warning": early_warning,
    }
    if w60 is not None:
        result["window_60d"] = {
            "score": w60["score"],
            "divergence_type": w60["div_type"],
            "sp500_pct_change": round(w60["sp_pct"], 2),
            "breadth_change": round(w60["breadth_chg"], 4),
            "lookback_days": w60["lookback_days"],
        }
    return result


def _compute_window(rows: list[dict], lookback: int) -> dict:
    """Compute divergence metrics for a single lookback window.

    A "N-day window" spans N trading days of change, so the past reference
    row is ``rows[-lookback - 1]`` (guarded against short input).
    """
    past_index = -min(lookback + 1, len(rows))
    latest = rows[-1]
    past = rows[past_index]
    actual_lookback = -past_index - 1

    sp_latest = latest["S&P500_Price"]
    sp_past = past["S&P500_Price"]
    ma8_latest = latest["Breadth_Index_8MA"]
    ma8_past = past["Breadth_Index_8MA"]

    if sp_past <= 0:
        return {
            "score": 50,
            "sp_pct": 0.0,
            "breadth_chg": 0.0,
            "div_type": "Invalid data",
            "sp_past": sp_past,
            "ma8_past": ma8_past,
            "lookback_days": actual_lookback,
        }

    sp_pct = (sp_latest - sp_past) / sp_past * 100
    breadth_chg = ma8_latest - ma8_past

    score, div_type = _score_divergence(sp_pct, breadth_chg)
    score = max(0, min(100, score))

    return {
        "score": score,
        "sp_pct": sp_pct,
        "breadth_chg": breadth_chg,
        "div_type": div_type,
        "sp_past": sp_past,
        "ma8_past": ma8_past,
        "lookback_days": actual_lookback,
    }


def _score_divergence(sp_pct: float, breadth_chg: float) -> tuple[int, str]:
    """Score based on price/breadth divergence. Returns (score, type_label)."""
    sp_up = sp_pct > 0
    breadth_up = breadth_chg > 0

    # Dangerous divergence: SP up, breadth down
    if sp_pct > 3.0 and breadth_chg < -0.05:
        return 10, "Dangerous bearish divergence"
    if sp_pct > 1.0 and breadth_chg < -0.03:
        return 25, "Moderate bearish divergence"

    # Bullish divergence: SP down, breadth up
    if sp_pct < -3.0 and breadth_chg > 0.05:
        return 80, "Strong bullish divergence"
    if sp_pct < -1.0 and breadth_chg > 0.03:
        return 65, "Moderate bullish divergence"

    # Near-flat movements (noise level)
    if abs(sp_pct) < 0.5 and abs(breadth_chg) < 0.01:
        return 50, "Near-flat (insufficient movement)"

    # Aligned movements
    if sp_up and breadth_up:
        return 70, "Healthy alignment (both rising)"
    if not sp_up and not breadth_up:
        return 30, "Consistent decline (both falling)"

    return 50, "Mixed signals"


def _generate_signal(
    sp_pct: float,
    breadth_chg: float,
    div_type: str,
    lookback_days: int,
    early_warning: bool = False,
) -> str:
    """Generate human-readable signal from the window driving the composite."""
    signal = f"{div_type}: S&P {sp_pct:+.1f}%, Breadth 8MA {breadth_chg:+.3f} over {lookback_days}d"
    if early_warning:
        signal += " [EARLY WARNING: 20d bearish divergence while 60d still healthy]"
    return signal

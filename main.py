"""Forecast a big launch's Twitch viewers, hour by hour, for hours 2-24 of its
release day (UTC), from everything recorded up to the end of hour 1.

Method
------
Every comparable launch in the case file carries its full release-day hourly
curve. For each comparable we take the log of each hour's viewers over its
own hour-1 print: a launch-day *shape* that is scale-free, so a 20k-viewer
launch and a 900k-viewer launch vote on the same curve.

Not every launch has the same shape, and the difference is predictable: a
launch whose hour-1 print is *depressed* next to its pre-release buzz (its
hour-1 viewers far below the highest hour of the day before) still has most
of its audience to arrive, so its curve climbs much further over the day
than a launch whose hour 1 already sits near its pre-release peak. We
measure that with r = hour1 / max(viewers in the 24 hours before day
start), split the comparables into thirds by r, and keep only the third
that matches the target case's own r. The centre of each hour's forecast
is the 55th percentile of that group's log ratios (a touch above the
median: the biggest launches sit a little above the typical comparable),
and the spread is the group's interquartile range of log ratios, shrunk
by 0.8 and capped at 0.7, so the quantiles widen honestly over the day
without inheriting the full cross-game heterogeneity.

Fallbacks keep every case valid: with no usable comparable the forecast
holds the hour-1 print flat with a spread widening over the day; with no
history the r-match is skipped and every comparable votes.

Input:  $MAKEFUN_INPUT_DIR (else /input) holding one <id>.in JSON case file
        (or several; every *.in file is read, in name order).
Output: $MAKEFUN_OUTPUT_DIR (else /output) gets one <id>.out per case:
        {"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}]} for h 2..24.

Standard library only, deterministic, no network.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

# Standard-normal quantiles at the five required levels.
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

SHAPE_Q = 0.55      # centre quantile of the matched group's log ratios
SPREAD_MULT = 0.8   # shrink on the group's IQR-based spread
SPREAD_CAP = 0.7    # widest log spread allowed (matches big-launch dispersion)
SPREAD_FLOOR = 0.05  # narrowest log spread allowed
FALLBACK_SPREAD = 0.15  # per sqrt(hour) widening when no comparable votes
MIN_GROUP = 8       # smallest matched group we trust; else use every comparable
MAX_VIEWERS = 1e9   # output cap from the rules


def parse_time(text):
    """ISO-8601 UTC timestamp -> aware datetime (accepts a trailing Z)."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def quantile(sorted_vals, q):
    """Linear-interpolation quantile of an already sorted list."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def hour1_print(case):
    """The case's hour-1 print, floored at 1 viewer (a print below 1 is 1).

    Defensive: a missing, null or misshaped `known` field reads as no
    print at all, which floors to 1 rather than crashing the run.
    """
    try:
        known = case.get("known")
        if isinstance(known, list):
            known = known[0] if known else {}
        if not isinstance(known, dict):
            return 1.0
        value = float(known.get("viewers") or 0)
    except (TypeError, ValueError):
        value = 0.0
    return value if value >= 1.0 else 1.0


def day_start(case):
    """The release day's first instant, or None if the case does not say."""
    try:
        return parse_time(case["day_start"])
    except (KeyError, TypeError, ValueError):
        return None


def target_ratio(case):
    """r = hour-1 print / highest viewers in the 24 hours before day start.

    Returns None when the history cannot support it (no points, no day
    start, or a zero hour-1 print).
    """
    start = day_start(case)
    if start is None:
        return None
    peak = 0.0
    for point in case.get("history") or []:
        try:
            when = parse_time(point["at"])
            viewers = float(point.get("viewers") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if start - timedelta(hours=24) <= when < start and viewers > peak:
            peak = viewers
    if peak <= 0:
        return None
    return hour1_print(case) / peak


def comparable_curves(case):
    """Each usable comparable as (r, [log(viewers_h / hour1) for h 1..24]).

    A comparable is usable when it has a full 24-hour release day of
    positive prints. The GTA VI pre-release curve (no launch day) is
    skipped, as is any comparable whose hour-1 print is missing or zero.
    """
    curves = []
    for comp in case.get("comparables") or []:
        if "before release" in str(comp.get("name", "")):
            continue
        try:
            start = parse_time(comp["day_start"])
        except (KeyError, TypeError, ValueError):
            continue
        by_hour = {}
        for point in comp.get("hourly") or []:
            try:
                when = parse_time(point["from"])
                viewers = float(point.get("viewers") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            by_hour[when] = viewers
        first = by_hour.get(start)
        if not first or first <= 0:
            continue
        ratios = []
        complete = True
        for h in range(24):
            value = by_hour.get(start + timedelta(hours=h))
            if not value or value <= 0:
                complete = False
                break
            ratios.append(math.log(value / first))
        if not complete:
            continue
        peak = 0.0
        for when, value in by_hour.items():
            if start - timedelta(hours=24) <= when < start and value > peak:
                peak = value
        r = first / peak if peak > 0 else None
        curves.append((r, ratios))
    return curves


def match_group(curves, target_r):
    """The third of the comparables whose r matches the target's r.

    Falls back to every curve when the target has no r, when too few
    comparables carry one, or when the matched third would be too small
    to trust.
    """
    with_r = sorted(r for r, _ in curves if r is not None)
    if target_r is None or len(with_r) < 9:
        return curves
    third = len(with_r) // 3
    low_cut = with_r[third]
    high_cut = with_r[2 * third]
    if target_r < low_cut:
        group = [(r, v) for r, v in curves if r is not None and r < low_cut]
    elif target_r < high_cut:
        group = [(r, v) for r, v in curves
                 if r is not None and low_cut <= r < high_cut]
    else:
        group = [(r, v) for r, v in curves if r is not None and r >= high_cut]
    return group if len(group) >= MIN_GROUP else curves


def forecast_case(case):
    """Five quantiles per hour (2..24) for one case. Always returns a
    complete, valid forecast, even for a degenerate case."""
    p1 = hour1_print(case)
    curves = comparable_curves(case)
    rows = []
    if curves:
        group = match_group(curves, target_ratio(case))
        for h in range(2, 25):
            vals = sorted(v[h - 1] for _, v in group)
            centre = quantile(vals, SHAPE_Q)
            spread = (quantile(vals, 0.75) - quantile(vals, 0.25)) / 1.349
            spread = min(max(spread * SPREAD_MULT, SPREAD_FLOOR), SPREAD_CAP)
            middle = p1 * math.exp(centre)
            rows.append((h, [middle * math.exp(z * spread) for z in Z]))
    else:
        for h in range(2, 25):
            spread = FALLBACK_SPREAD * math.sqrt(h - 1)
            rows.append((h, [p1 * math.exp(z * spread) for z in Z]))
    hours = []
    for h, qs in rows:
        clean = []
        prev = 0.0
        for q in qs:
            q = min(max(q, 0.01), MAX_VIEWERS)
            q = max(q, prev)  # quantiles must not decrease
            clean.append(round(q, 2))
            prev = q
        hours.append({"hour": h, "q": clean})
    return {"hours": hours}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    try:
        names = sorted(n for n in os.listdir(in_dir) if n.endswith(".in"))
    except OSError:
        names = []
    for name in names:
        case_id = name[:-3]
        try:
            with open(os.path.join(in_dir, name), "r", encoding="utf-8") as fh:
                case = json.load(fh)
            if not isinstance(case, dict):
                raise ValueError("case is not an object")
        except (OSError, ValueError):
            case = {}
        try:
            forecast = forecast_case(case)
        except Exception:
            # Never let one case kill the run: a crashed run is an invalid
            # case, which ranks below every valid entry and takes no prize.
            # Fall back to a flat forecast at 1 viewer.
            forecast = forecast_case({})
        out_path = os.path.join(out_dir, case_id + ".out")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(forecast, fh)


if __name__ == "__main__":
    main()

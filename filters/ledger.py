"""Source Signal Ledger — learn which sources are actually worth your attention.

The original two-week-evaluation goal. Every run logs its items to data/history.json with the source
and the score, so after 100 runs we can answer honestly: of everything source X produced, how much was
ever worth acting on?

The first real answer (3,569 items): devpost 76.7% useful, programs 63.2% - while reddit produced 600
items of which 8 cleared HIGH (1.3%). Depth of ranking beats breadth of sources.

Honesty rules baked in:
  * A source needs MIN_SAMPLE items before we judge it. Eight observations is not evidence.
  * The adjustment is BOUNDED and never silences a source - it nudges ranking, it does not censor.
  * When explicit act/skip data exists (data/tracker.json) it is preferred over score-yield, because
    what you actually did beats what the model guessed. Until then we say which basis was used.
"""

from __future__ import annotations

import json
from collections import defaultdict

import config

MIN_SAMPLE = 30      # below this we have no opinion
HIGH = 7             # config.HIGH_SCORE: "worth acting on this week"

# hit-rate -> score adjustment. Deliberately a small, explainable step function rather than a
# formula nobody can reason about at 8am.
_BANDS = [(0.50, +1.0, "proven"), (0.25, +0.5, "good"), (0.10, 0.0, "average"),
          (0.05, -0.5, "thin"), (0.00, -1.0, "mostly noise")]


def _item_score(it: dict) -> int:
    ai = it.get("ai_score")
    if isinstance(ai, (int, float)) and ai >= 0:
        return int(ai)
    s = it.get("score")
    return int(s) if isinstance(s, (int, float)) else 0


def _history_items(path=None) -> list:
    path = path or (config.DATA_DIR / "history.json")
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return data
    return [i for r in data.get("runs", []) for i in r.get("items", [])]


def _tracker_actions() -> dict:
    """{source: (acted, skipped)} from real button taps, or {} when you have not used them."""
    try:
        data = json.loads(open(config.DATA_DIR / "tracker.json", encoding="utf-8").read())
    except (OSError, ValueError):
        return {}
    out = defaultdict(lambda: [0, 0])
    for entry in data.values():
        src = (entry.get("source") or "").strip()
        st = (entry.get("status") or "").lower()
        if not src:
            continue
        if st in ("applied", "planned"):
            out[src][0] += 1
        elif st == "skipped":
            out[src][1] += 1
    return {k: tuple(v) for k, v in out.items()}


def build(path=None) -> dict:
    """{source: {items, high, critical, hit_rate, band, adjust, basis, judged}}"""
    items = _history_items(path)
    actions = _tracker_actions()
    by = defaultdict(list)
    for it in items:
        by[(it.get("source") or "?")].append(_item_score(it))

    ledger = {}
    for src, scores in by.items():
        n = len(scores)
        high = sum(1 for s in scores if s >= HIGH)
        crit = sum(1 for s in scores if s >= config.CRITICAL_SCORE)

        acted, skipped = actions.get(src, (0, 0))
        if acted + skipped >= 10:                     # real behaviour beats a model's guess
            rate, basis = acted / (acted + skipped), "your own applied/skipped taps"
        else:
            rate, basis = (high / n if n else 0.0), "score yield (no act/skip data yet)"

        judged = n >= MIN_SAMPLE
        adjust, band = 0.0, "not enough data"
        if judged:
            for threshold, adj, label in _BANDS:
                if rate >= threshold:
                    adjust, band = adj, label
                    break
        ledger[src] = {"items": n, "high": high, "critical": crit, "hit_rate": rate,
                       "band": band, "adjust": adjust, "basis": basis, "judged": judged,
                       "acted": acted, "skipped": skipped}
    return ledger


_CACHE = None


def adjustment(source: str) -> float:
    """Bounded score nudge for a source. 0.0 when we have no right to an opinion."""
    global _CACHE
    if _CACHE is None:
        _CACHE = build()
    return float((_CACHE.get(source) or {}).get("adjust", 0.0))


def note(source: str) -> str:
    """Short human reason, for the brief. '' when the ledger has no opinion."""
    entry = (_CACHE if _CACHE is not None else build()).get(source)
    if not entry or not entry["judged"] or entry["adjust"] == 0:
        return ""
    return f"{source} is {entry['hit_rate']*100:.0f}% useful to you ({entry['band']})"


def report(path=None) -> str:
    led = build(path)
    if not led:
        return "No history yet - run a few hunts first."
    rows = sorted(led.items(), key=lambda kv: -kv[1]["hit_rate"])
    out = [f"{'source':<14}{'items':>7}{'>=7':>6}{'hit%':>7}{'adj':>6}  verdict",
           "-" * 62]
    for src, e in rows:
        adj = f"{e['adjust']:+.1f}" if e["judged"] else "  ."
        out.append(f"{src:<14}{e['items']:>7}{e['high']:>6}{e['hit_rate']*100:>6.1f}%{adj:>6}  {e['band']}")
    out.append("-" * 62)
    basis = next(iter(led.values()))["basis"]
    out.append(f"basis: {basis}   (a source needs {MIN_SAMPLE}+ items before it is judged)")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(report())

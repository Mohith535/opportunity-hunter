"""
Policy layer — turns a score into decisions (level / notify / dump).

Deliberately separate from the scorer so that swapping the rule-based score for
the Phase 2 LLM score is a one-line change here (in `effective_score`), with no
impact on sources, the brief, notifiers, or TaskFlow.
"""

from dataclasses import dataclass

import config


@dataclass
class Decision:
    level: str              # CRITICAL | HIGH | MEDIUM | LOW
    notify: bool            # send desktop/phone notification?
    dump_to_taskflow: bool  # auto-create a TaskFlow task?


def effective_score(item) -> int:
    """The score decisions are based on.

    Phase 1: rule-based score. Phase 2: prefer item.ai_score when it's been
    computed (>= 0). This is the single switch-over point.
    """
    if item.ai_score >= 0:
        return item.ai_score
    return item.score


def classify(score: int) -> str:
    if score >= config.CRITICAL_SCORE:
        return "CRITICAL"
    if score >= config.HIGH_SCORE:
        return "HIGH"
    if score >= config.MEDIUM_SCORE:
        return "MEDIUM"
    return "LOW"


def decide(item) -> Decision:
    score = effective_score(item)
    return Decision(
        level=classify(score),
        notify=score >= config.NOTIFY_MIN_SCORE,
        dump_to_taskflow=config.TASKFLOW_AUTO_DUMP and score >= config.TASKFLOW_MIN_SCORE,
    )


if __name__ == "__main__":
    from models import Opportunity

    for s in (10, 8, 6, 3):
        item = Opportunity("x", "u", "t")
        item.score = s
        d = decide(item)
        print(f"score={s:>2} -> level={d.level:<8} notify={d.notify!s:<5} dump={d.dump_to_taskflow}")

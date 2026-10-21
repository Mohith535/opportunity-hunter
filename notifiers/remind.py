"""
"Remind me" from the laptop (22 Oct 2026): sets a reminder — or a staged plan of them — on the bot,
which sends each one at 09:00 IST on its date with ⏰ Again and Applied/Skip (or Done, for a to-do).

    py -m notifiers.remind srfp-2027 "IAS Summer Research Fellowship" \
        --url https://webjapps.ias.ac.in/fellowship2027/ --deadline 2026-11-30 \
        --step 2026-10-26 "Ask a teacher this week" --step 2026-11-01 "Write the 150-250 words"
    py -m notifiers.remind oph-questions "Two OPH questions" --todo --step 2026-10-29 "Kaggle key; LoopLab"

Needs OH_WORKER_URL + OH_WORKER_TOKEN in .env (the same pair the target sync uses). Prints no secrets.
"""
import argparse
import sys

import requests

import config
from filters.target import _bot


def remind(key: str, title: str, steps: list[dict], url: str = "", deadline: str = "",
           todo: bool = False) -> dict:
    """POST /remind. Returns the bot's answer, or {"error": ...}. Never raises."""
    base, tok = _bot()
    if not base:
        return {"error": "OH_WORKER_URL / OH_WORKER_TOKEN are not set"}
    body = {"key": key, "title": title, "steps": steps, "url": url, "deadline": deadline, "todo": todo}
    try:
        r = requests.post(f"{base}/remind", json=body, timeout=config.REQUEST_TIMEOUT,
                          headers={"Authorization": f"Bearer {tok}", "User-Agent": config.USER_AGENT})
        return r.json() if r.headers.get("content-type", "").startswith("application/json") \
            else {"error": f"HTTP {r.status_code}"}
    except (requests.RequestException, ValueError) as e:
        return {"error": type(e).__name__}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Set a reminder (or a staged plan) on the bot.")
    ap.add_argument("key")
    ap.add_argument("title")
    ap.add_argument("--step", nargs=2, action="append", metavar=("DATE", "NOTE"), required=True)
    ap.add_argument("--url", default="")
    ap.add_argument("--deadline", default="")
    ap.add_argument("--todo", action="store_true", help="a to-do: Done + Again buttons")
    a = ap.parse_args()
    out = remind(a.key, a.title, [{"at": d, "note": n} for d, n in a.step], a.url, a.deadline, a.todo)
    print(out)
    sys.exit(1 if "error" in out else 0)

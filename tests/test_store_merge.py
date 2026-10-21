"""Tests for merging the cloud's history into the laptop's (22 Oct 2026).

Run:  python tests/test_store_merge.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
import store

R = []
def check(name, cond, detail=""):
    R.append((name, bool(cond), detail))

# Never touch the real data/: every path points into a temp folder.
tmp = Path(tempfile.mkdtemp())
config.HISTORY_FILE, config.SEEN_FILE, config.FEED_FILE = tmp / "history.json", tmp / "seen.json", tmp / "feed.json"
store.ETAG_FILE = tmp / ".cloud_etag"

def item(k, score=5):
    return {"key": k, "title": f"T{k}", "url": f"https://x/{k}", "source": "s", "score": score, "tags": []}

cloud = {"runs": [{"date": "2026-10-19", "items": [item("a")]}, {"date": "2026-10-21", "items": [item("m", 9)]}]}
laptop = {"runs": [{"date": "2026-10-19", "items": [item("a")]}, {"date": "2026-10-20", "items": [item("l")]}]}
m = store.merge_history(laptop, cloud)
check("1. both copies' runs, a shared run once, in date order",
      [r["date"] for r in m["runs"]] == ["2026-10-19", "2026-10-20", "2026-10-21"], m)
check("2. merging again changes nothing (the 30-minute sync is idempotent)", store.merge_history(m, cloud) == m)
same_day = store.merge_history({"runs": [{"date": "2026-10-21", "items": [item("l2")]}]}, cloud)
check("3. two different runs on the same day are both kept, the cloud's first",
      [r["items"][0]["key"] for r in same_day["runs"]] == ["a", "m", "l2"])

s = store.merge_seen({"items": {"k": {"title": "K", "first_seen": "2026-10-01", "last_seen": "2026-10-10", "times_seen": 4},
                                "only_mine": {"title": "X", "first_seen": "2026-10-02", "times_seen": 1}}},
                     {"items": {"k": {"title": "K", "first_seen": "2026-09-30", "last_seen": "2026-10-05", "times_seen": 2}}})
check("4. seen: earliest first_seen, latest last_seen, most times_seen, nothing dropped",
      s["items"]["k"] == {"title": "K", "first_seen": "2026-09-30", "last_seen": "2026-10-10", "times_seen": 4}
      and "only_mine" in s["items"], s)

config.HISTORY_FILE.write_text(json.dumps(laptop), encoding="utf-8")
before, after = store.merge_in(cloud, {"items": {}})
feed = json.loads(config.FEED_FILE.read_text(encoding="utf-8"))
check("5. merge_in writes the union and refreshes the feed — the cloud's 9/10 is on top",
      (before, after) == (2, 3) and feed["items"][0]["key"] == "m", (before, after, feed["items"][:1]))

class _Resp:
    def __init__(self, code, body=None, etag=""):
        self.status_code, self._b, self.headers = code, body, ({"ETag": etag} if etag else {})
    def json(self): return self._b
    def raise_for_status(self):
        if self.status_code >= 400:
            raise store_requests.HTTPError(str(self.status_code))
import requests as store_requests
calls = []
def fake_get(url, timeout=None, headers=None):
    calls.append((url.rsplit("/", 1)[-1], (headers or {}).get("If-None-Match")))
    if (headers or {}).get("If-None-Match") == '"v1"':
        return _Resp(304)
    return _Resp(200, cloud if url.endswith("history.json") else {"items": {}}, '"v1"' if url.endswith("history.json") else "")
_g = store_requests.get
store_requests.get = fake_get
try:
    first = store.pull_cloud()
    second = store.pull_cloud()
finally:
    store_requests.get = _g
check("6. the first pull merges and keeps the ETag; the next asks If-None-Match and downloads nothing",
      "merged" in first and "not changed" in second and calls[-1] == ("history.json", '"v1"')
      and len(calls) == 3, (first, second, calls))
store_requests.get = lambda *a, **k: (_ for _ in ()).throw(store_requests.ConnectionError("offline"))
try:
    offline = store.pull_cloud()
finally:
    store_requests.get = _g
check("7. offline: one log line, no crash, the local file untouched",
      "could not merge" in offline and len(json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))["runs"]) == 3)

print("=" * 72)
for name, ok, detail in R:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))
print("=" * 72)
passed = sum(1 for _, ok, _ in R if ok)
print(f"{passed}/{len(R)} passed")
sys.exit(0 if passed == len(R) else 1)

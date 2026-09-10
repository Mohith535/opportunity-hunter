"""Real-world scenario tests for the Inbox Assistant dashboard.

These are the situations that actually happen to Mohith - written after a real miss: a EUR 300 paid
offer landed in the inbox and the dashboard buried it at 3/10 INFO because the LLM chain was down.
Run:  python tests/test_inbox_scenarios.py
"""
import datetime
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inbox.scan import high_signal, is_junk
from inbox.render import render_html, _build_data

TODAY = datetime.datetime.now().date()
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def mail(subject, sender="a@b.com", imp=3, cat="INFO", dl="", gid="x1", triaged=True, signal=""):
    return {"from": sender, "subject": subject, "id": gid, "category": cat,
            "importance": imp, "deadline": dl, "summary": subject[:60],
            "triaged": triaged, "signal": signal}


def task(title, days_over=0, pri="Critical", tid=1):
    return {"id": tid, "title": title, "priority": pri, "tags": [],
            "date": "", "days_over": days_over}


# 1 - THE REAL MISS: a paid offer must never be buried, in every currency order
for subj in ["Paid project: build agents in phone (\u20ac300)",
             "Build an AI agent - EUR 300 budget",
             "Mobile agent build - 300 EUR"]:
    floor, _ = high_signal(subj, "raj@startup.io")
    check(f"1. paid offer surfaces [{subj[:28]}]", floor >= 4, f"floor={floor}")

# 2 - marketing that merely LOOKS like an offer must not be boosted
for subj, snd in [("Save big on Coursera Plus: Now \u20b97,499/year", "no-reply@coursera.org"),
                  ("Get 70% off - limited time offer!", "deals@shop.com"),
                  ("Weekly AI newsletter", "news@sub.com")]:
    floor, _ = high_signal(subj, snd)
    check(f"2. promo NOT boosted [{subj[:26]}]", floor == 0, f"floor={floor}")

# 3 - a human waiting on you beats an automated Re:
h, _ = high_signal("Re: your demo - can we talk?", "priya@company.com")
a, _ = high_signal("Re: Your order shipped", "no-reply@amazon.in")
check("3. human reply boosted, automated Re: not", h >= 4 and a == 0, f"human={h} auto={a}")

# 4 - OTP / security still hidden (privacy promise intact)
hid, why = is_junk({"subject": "Your one-time code is 123456", "from": "x@y.com"})
keep, _ = is_junk({"subject": "Project proposal", "from": "x@y.com"})
check("4. OTP hidden, normal mail kept", hid and not keep, why)

# 5 - LLM DOWN: unranked mail is VISIBLE + flagged, never buried
summary = {"window": "t", "hidden": {}, "total": 2, "untriaged": 2, "day": {}, "opps": [],
           "shown": [mail("Build an agent for us - EUR 300", imp=5, triaged=False, signal="money"),
                     mail("Random newsletter", imp=5, triaged=False)]}
html = render_html(summary)
data = json.loads(re.search(r"var DATA=(\{.*?\});\s*\n\s*var base", html, re.S).group(1))
check("5. unranked mail is visible (imp>=4)", all(i["imp"] >= 4 for i in data["items"]))
check("5. untriaged warning shown to user", "could not be ranked" in html and data["untriaged"] == 2)
check("5. unranked chip rendered", "unranked" in html)

# 6 - the dashboard survives an empty TaskFlow
html2 = render_html({"window": "t", "hidden": {}, "total": 1, "day": {}, "opps": [],
                     "shown": [mail("hello", imp=6)]})
check("6. no TaskFlow tasks -> still renders", "<div class=\"grid\">" in html2 and "Attention radar" in html2)

# 7 - the dashboard survives a completely quiet day
html3 = render_html({"window": "t", "hidden": {}, "total": 0, "day": {}, "opps": [], "shown": []})
check("7. zero emails + zero tasks -> renders", "You are clear" in html3 or "<div class=\"grid\">" in html3)

# 8 - hostile subject cannot break out of the page or the script tag
nasty = "</script><script>alert(1)</script> \"quotes\" <b>&amp;</b> \u20b9500"
html4 = render_html({"window": "t", "hidden": {}, "total": 1, "day": {}, "opps": [],
                     "shown": [mail(nasty, imp=7)]})
raw = re.search(r"var DATA=(\{.*?\});\s*\n\s*var base", html4, re.S).group(1)
check("8. no </script> breakout in injected data", "</script>" not in raw)
check("8. script tag count is exactly 1", html4.count("<script>") == 1)

# 9 - a task with no id must not render a bogus action button
d9 = _build_data({"shown": [], "hidden": {}, "opps": [],
                  "day": {"overdue": [{"id": None, "title": "orphan task", "priority": "Critical",
                                       "days_over": 3, "date": ""}], "due_today": [], "upcoming": []}})
check("9. task without an id still builds safely", d9["items"][0]["tid"] is None)

# 10 - very long subject is truncated (layout cannot be blown out)
d10 = _build_data({"shown": [mail("L" * 400, imp=6)], "hidden": {}, "opps": [], "day": {}})
check("10. long subject truncated", len(d10["items"][0]["title"]) <= 140)

# 11 - Gmail APP deep link is wired for Android, web link kept as fallback
d11 = _build_data({"shown": [mail("hi", gid="ABC123", imp=6)], "hidden": {}, "opps": [], "day": {}})
check("11. email carries gid for the app link", d11["items"][0]["gid"] == "ABC123")
check("11. Android intent + fallback in page", "intent://mail.google.com" in html2
      and "browser_fallback_url" in html2 and "com.google.android.gm" in html2)

# 12 - source toggle exists with all three states
check("12. All / Inbox / Tasks toggle built with 3 states",
      "'all','mail','task'" in html2 and 'data-src="' in html2)
check("12b. toggle actually filters by source",
      'state.src==="mail"' in html2 and 'state.src==="task"' in html2)

# 13 - opportunities count as inbox-side, tasks as task-side (toggle correctness)
d13 = _build_data({"shown": [mail("m", imp=6)], "hidden": {}, "day": {"overdue": [task("t", 3)],
                   "due_today": [], "upcoming": []},
                   "opps": [{"title": "o", "url": "u", "date": "", "source": "mlh", "score": 7}]})
srcs = sorted({i["source"] for i in d13["items"]})
check("13. three distinct sources for the toggle", srcs == ["mail", "opp", "task"], str(srcs))


# 14 - REGRESSION (caught in a LIVE run, not by the first tests): promo wording must not be boosted
for _s in ["Coursera subscription promo", "HP promotional offers", "Today's best deals"]:
    _f, _ = high_signal(_s, "no-reply@x.com")
    check(f"14. promo wording not boosted [{_s[:26]}]", _f == 0, f"floor={_f}")

# 15 - REGRESSION: an explicit NOISE verdict is never overridden by the backstop
_noisy = {"from": "ads@x.com", "subject": "Special offer - EUR 999 laptop", "id": "n1",
          "category": "NOISE", "importance": 1, "deadline": "", "summary": "ad"}
_d15 = _build_data({"shown": [_noisy], "hidden": {}, "opps": [], "day": {}})
check("15. NOISE stays low despite money+offer words", _d15["items"][0]["imp"] <= 2,
      f'imp={_d15["items"][0]["imp"]}')

# 16 - and after all that tightening, the genuine paid offer STILL surfaces
_f16, _ = high_signal("Build an AI agent for us - EUR 300", "raj@startup.io")
check("16. genuine paid offer still surfaces", _f16 >= 5, f"floor={_f16}")

print("\n" + "=" * 68)
print("REAL-WORLD SCENARIO TESTS")
print("=" * 68)
passed = 0
for name, ok, detail in results:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    passed += ok
print("=" * 68)
print(f"{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)

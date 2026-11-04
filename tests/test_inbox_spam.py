"""Spam is read, flagged and judged - never hidden, never trusted blindly.

Written 30 Oct, after he said some important mail "jumps straight to spam... may be this a job offer".
Until then messages.list ran without includeSpamTrash, so Gmail's Spam folder was never read at all.
Gmail and the model are both faked: nothing here touches the network.
Run:  python tests/test_inbox_spam.py
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# ── a fake Gmail: inbox has a and b; Spam has b again and c ─────────────────────────────────────
calls = []


class _Exec:
    def __init__(self, resp):
        self.resp = resp

    def execute(self):
        return self.resp


class _Messages:
    def list(self, **kw):
        calls.append(kw)
        ids = ["b", "c"] if "in:spam" in kw["q"] else ["a", "b"]
        return _Exec({"messages": [{"id": i} for i in ids]})

    def get(self, userId, id, format, metadataHeaders):  # noqa: A002 - Gmail's own argument name
        return _Exec({"payload": {"headers": [{"name": "From", "value": f"{id}@x.com"},
                                              {"name": "Subject", "value": f"subject {id}"}]},
                      "snippet": "hi", "labelIds": ["SPAM"] if id == "c" else ["INBOX"]})


class _Service:
    def users(self):
        return types.SimpleNamespace(messages=lambda: _Messages())


import gmail_digest as gd  # noqa: E402


class _Creds:
    valid, expired, refresh_token = True, False, None
    scopes = list(gd._SCOPES)

    @classmethod
    def from_authorized_user_file(cls, path, scopes):
        return cls()

    def to_json(self):
        return "{}"


for name, attrs in {
        "google": {}, "google.auth": {}, "google.auth.transport": {},
        "google.auth.transport.requests": {"Request": object},
        "google.oauth2": {}, "google.oauth2.credentials": {"Credentials": _Creds},
        "google_auth_oauthlib": {}, "google_auth_oauthlib.flow": {"InstalledAppFlow": object},
        "googleapiclient": {}, "googleapiclient.discovery": {"build": lambda *a, **k: _Service()}}.items():
    sys.modules[name] = types.SimpleNamespace(**attrs)

token = os.path.join(tempfile.mkdtemp(), "token.json")
open(token, "w").write("{}")
got = gd.fetch_today_oauth(token_path=token, query="newer_than:1d")

# 1 - Spam is asked for, on its own call, and trash is not
spam_call = [c for c in calls if "in:spam" in c["q"]]
check("1. a separate Spam query runs", len(spam_call) == 1, str(calls))
check("1b. it sets includeSpamTrash (Gmail drops Spam otherwise)",
      spam_call and spam_call[0].get("includeSpamTrash") is True, str(spam_call))
check("1c. Spam has its own cap, so it can't crowd out the inbox",
      spam_call and spam_call[0]["maxResults"] == gd._MAX_SPAM and gd._MAX_SPAM < gd._MAX_EMAILS)
check("1d. trash is never read", all("trash" not in c["q"] or "-in:trash" in c["q"] for c in calls))

# 2 - one message in both lists is read once; the Spam one keeps its label
check("2. inbox + spam merged, duplicate read once", [m["id"] for m in got] == ["a", "b", "c"],
      str([m["id"] for m in got]))
check("2b. the Spam message carries the SPAM label", got[-1]["labels"] == ["SPAM"])

# 3 - the model is TOLD which one came from Spam, and the result is flagged
import importlib  # noqa: E402

scan_mod = importlib.import_module("inbox.scan")   # the package re-exports a function named scan

seen_prompt = []
scan_mod.fetch_today_oauth = lambda *a, **k: [
    {"from": "hr@realco.in", "subject": "Interview invite", "snippet": "slot on Friday",
     "labels": ["SPAM"], "id": "s1"},
    {"from": "team@uni.edu", "subject": "Lab schedule", "snippet": "room change",
     "labels": ["INBOX"], "id": "i1"}]


def _fake_complete(prompt, **kw):
    seen_prompt.append(prompt)
    return ("1 | OPPORTUNITY | 8 | - | In Spam: an interview invite from a real company\n"
            "2 | INFO | 3 | - | lab room changed")


scan_mod.complete = _fake_complete
out = scan_mod.scan(days=1)
check("3. the triage prompt marks the Spam email", "[IN SPAM]" in seen_prompt[0]
      and seen_prompt[0].count("[IN SPAM]") == 2, "expected the rule line + one marked email")
by_id = {s["id"]: s for s in out["shown"]}
check("3b. the Spam item is flagged spam", by_id["s1"]["spam"] is True)
check("3c. the inbox item is not", by_id["i1"]["spam"] is False)
check("3d. a real offer in Spam still ranks at the top", out["shown"][0]["id"] == "s1")

# 3e - 4 Nov: the real Zaalima mail (his Spam, 30 Oct). The model said 8/10 "reply to confirm"; the posting's
# own words decide instead. A real shortlist and a hackathon's entry fee are left alone.
ZAALIMA = ("Exciting News: Internship Offer from Zaalima Development! Dear Mohith Kannan K, Greetings from Zaalima "
           "Development! We are pleased to inform you that your email has been successfully shortlisted for "
           "further consideration. STEP 1 Fill the application form")
scan_mod.fetch_today_oauth = lambda *a, **k: [
    {"from": "Zaalima <hr@zaalima.in>", "subject": "Internship Offer", "snippet": ZAALIMA, "labels": ["SPAM"], "id": "z1"},
    {"from": "careers@loreal.com", "subject": "You have been shortlisted for the L'Oréal internship",
     "snippet": "Please confirm your slot for the next round.", "labels": ["INBOX"], "id": "l1"}]
scan_mod.complete = lambda prompt, **kw: ("1 | OPPORTUNITY | 8 | - | Zaalima internship shortlisted, reply to confirm\n"
                                          "2 | OPPORTUNITY | 8 | - | L'Oréal shortlist, confirm your slot")
z = {s["id"]: s for s in scan_mod.scan(days=1)["shown"]}
check("3e. a fee-funnel 'offer' is NOISE 0 whatever the model said, and says why",
      z["z1"]["category"] == "NOISE" and z["z1"]["importance"] == 0 and z["z1"]["summary"].startswith("Likely scam")
      and z["z1"]["signal"] == "", z["z1"])
check("3f. a real shortlist keeps the model's 8/10", z["l1"]["importance"] == 8 and z["l1"]["category"] == "OPPORTUNITY")
check("3g. fee words alone don't fire (a hackathon entry fee is real); beside 'internship' they do",
      scan_mod.scam_tell("Hackathon 2026", "registration fee: ₹250 per team") == ""
      and scan_mod.scam_tell("Internship selection", "pay the refundable training fee of ₹399") == "it charges a fee"
      and "Interested" in scan_mod.scam_tell("Internship", "drop \"Interested\" — comment Interested on our post"))

# 4 - the page says it out loud
from inbox.render import _build_data, render_html  # noqa: E402

d = _build_data({"shown": out["shown"], "hidden": {}, "opps": [], "day": {}})
item = next(i for i in d["items"] if i.get("gid") == "s1")
check("4. the page item carries spam", item.get("spam") is True)
check("4b. its first 'why' line says Gmail put it in Spam", "Spam" in item["why"][0], str(item["why"]))
check("4c. the badge is in the page", "in spam" in render_html(
    {"shown": out["shown"], "hidden": {}, "opps": [], "day": {}}))

print("=" * 68)
passed = 0
for name, ok, detail in results:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    passed += ok
print("=" * 68)
print(f"{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)

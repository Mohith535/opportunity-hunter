"""Write the Cloudflare bot's copy of the target to hunt_target.json on the runner.

Used by .github/workflows/daily.yml. Prints one line WITHOUT the target's content — this repo is
public, so its Action logs are too. Exits 1 (and writes nothing) if the response is not a target,
so the workflow falls back to the OH_TARGET_JSON secret."""
import json
import sys

try:
    entry = json.load(open(sys.argv[1], encoding="utf-8"))
    target = entry["target"]
    assert isinstance(target, dict)
except (OSError, ValueError, KeyError, AssertionError, IndexError):
    print("target: the bot's copy was unreadable, falling back to the secret")
    sys.exit(1)
with open("hunt_target.json", "w", encoding="utf-8") as f:
    json.dump(target, f, ensure_ascii=False)
print(f"target: from the bot (changed {str(entry.get('updated_at', '?'))[:10]} from your {entry.get('source', '?')})")

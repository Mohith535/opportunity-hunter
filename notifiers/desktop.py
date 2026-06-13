"""
Desktop notifications via plyer (CLAUDE.md §8.1).

Best-effort: plyer can silently no-op or raise on some Windows setups, so this
is fully wrapped — a missing notification backend never crashes the run.
"""

import config
from util import log


def send_desktop(title: str, message: str) -> bool:
    if not config.DESKTOP_NOTIFICATIONS:
        return False
    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=message,
            app_name="OpportunityHunter",
            timeout=10,
        )
        return True
    except Exception as e:  # noqa: BLE001 — backend issues vary by platform
        log(f"[desktop] notification failed: {e}", level="WARN")
        return False


if __name__ == "__main__":
    ok = send_desktop("🎯 Opportunity Hunter", "Desktop notification test — it works!")
    print("sent:", ok)

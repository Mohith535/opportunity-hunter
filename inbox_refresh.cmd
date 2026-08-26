@echo off
REM ── Auto-refresh the private Inbox / My-Day dashboard ──────────────────────────
REM Registered as a Windows Scheduled Task so the phone page stays current on its own.
REM --headless: if the weekly Gmail sign-in has expired, it exits cleanly (never opens
REM a browser and hangs). When that happens, run `python -m inbox` once to sign in again.
cd /d "E:\agent for my self"
"C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe" -m inbox --days 1 --publish --headless >> "logs\inbox_refresh.log" 2>&1

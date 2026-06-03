@echo off
rem Set your admin key here — keep this file local, do not commit with a real key
set LEDGER_ADMIN_KEY=YOUR_KEY_HERE
python "%~dp0ledger_server.py"

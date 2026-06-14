@echo off
cd /d "%~dp0"
set ANTHROPIC_API_KEY=PASTE_YOUR_KEY_HERE
python publish.py --watch-dir "H:\My Drive\daily reads"
pause

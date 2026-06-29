@echo off
chcp 65001 >nul
cd /d "%~dp0"
python fetch_event_stories.py %*

pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
python extract_story.py %*

pause

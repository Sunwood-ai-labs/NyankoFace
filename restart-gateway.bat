@echo off
cd /d %~dp0
echo ==== restart %date% %time% ==== > restart.log
docker compose restart gateway >> restart.log 2>&1
echo EXITCODE=%ERRORLEVEL% >> restart.log
echo ==== end ==== >> restart.log

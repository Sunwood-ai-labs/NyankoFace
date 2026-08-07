@echo off
cd /d %~dp0
echo ==== status %date% %time% ==== > status.log
docker compose ps -a >> status.log 2>&1
docker images >> status.log 2>&1
echo ==== end ==== >> status.log

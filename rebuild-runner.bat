@echo off
cd /d %~dp0
echo ==== rebuild %date% %time% ==== > rebuild.log
docker compose up -d --build spaces-runner >> rebuild.log 2>&1
echo EXITCODE=%ERRORLEVEL% >> rebuild.log
docker compose ps spaces-runner >> rebuild.log 2>&1
echo ==== end ==== >> rebuild.log

@echo off
cd /d %~dp0
echo ==== fix %date% %time% ==== > fix.log
docker compose up -d gateway >> fix.log 2>&1
echo UP_EXITCODE=%ERRORLEVEL% >> fix.log
docker compose logs --tail 30 gateway >> fix.log 2>&1
docker compose ps >> fix.log 2>&1
netstat -ano | findstr :8080 >> fix.log 2>&1
echo ==== end ==== >> fix.log

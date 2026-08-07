@echo off
REM Rebuild images after changing forgejo\custom\ or frontend\ files,
REM then restart the containers.
cd /d "%~dp0"
echo === Building nyankoface-forgejo and nyankoface-frontend images...
docker compose build forgejo frontend
if errorlevel 1 goto :err
echo === Restarting containers...
docker compose up -d forgejo frontend
if errorlevel 1 goto :err
docker compose ps
echo === Done. Check http://127.0.0.1:8090/git/nyankoface/realtime-voice-space/src/branch/main
exit /b 0
:err
echo Build or restart failed.
exit /b 1

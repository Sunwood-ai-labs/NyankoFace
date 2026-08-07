@echo off
rem NyankoFace 起動スクリプト — ログは compose-up.log に出力されます
cd /d %~dp0
echo ==== start %date% %time% ==== > compose-up.log
docker version >> compose-up.log 2>&1
if not exist .env copy .env.example .env >> compose-up.log 2>&1
docker compose up -d --build >> compose-up.log 2>&1
echo EXITCODE=%ERRORLEVEL% >> compose-up.log
docker compose ps >> compose-up.log 2>&1
echo ==== done %date% %time% ==== >> compose-up.log

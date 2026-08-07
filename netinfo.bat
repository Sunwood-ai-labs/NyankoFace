@echo off
cd /d %~dp0
echo ==== netinfo ==== > netinfo.log
ipconfig | findstr /i "IPv4" >> netinfo.log
node --version >> netinfo.log 2>&1
curl -s -o nul -w "local8090=%%{http_code}" http://localhost:8090/ >> netinfo.log 2>&1
echo. >> netinfo.log
echo ==== end ==== >> netinfo.log

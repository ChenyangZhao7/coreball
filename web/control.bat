@echo off
chcp 65001 >nul
cd /d "%~dp0.."
start "" /min cmd /c "python tools\control_server.py"
timeout /t 1 >nul
start "" "http://127.0.0.1:8010/"
echo CoreBall control: http://127.0.0.1:8010/
echo 先打开 Blender 的「指挥」场景：会收 UDP 4590 指令，并回传 4591 遥测。
pause

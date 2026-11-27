@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist "blender\out\cmd\coreball_command.blend" (
  echo 找不到 blender\out\cmd\coreball_command.blend
  echo 先运行 blender\重建.bat 生成场景。
  pause
  exit /b 1
)

echo 启动 Blender 指挥场景...
start "" "%~dp0..\blender\指挥.bat"

echo 启动控制桥...
start "" /min cmd /c "python tools\control_server.py"

timeout /t 2 >nul
start "" "http://127.0.0.1:8010/"

echo.
echo CoreBall 操作台: http://127.0.0.1:8010/
echo Blender 启动需要几秒，页面会自动连上。
echo 关闭本窗口不会停掉服务；要停服务请关掉最小化的 python 窗口和 Blender。
pause

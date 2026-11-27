@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist "blender\out\cmd\coreball_command.blend" (
  echo 找不到 blender\out\cmd\coreball_command.blend
  echo 先运行 blender\重建.bat 生成场景。
  pause
  exit /b 1
)

tasklist /fi "imagename eq blender.exe" 2>nul | findstr /i "blender.exe" >nul
if errorlevel 1 (
  echo 启动 Blender 指挥场景...
  start "" "%~dp0..\blender\指挥.bat"
) else (
  echo Blender 已在运行，跳过启动。
)

echo 启动控制桥...
netstat -ano | findstr ":8010" | findstr LISTENING >nul
if errorlevel 1 start "" /min cmd /c ".venv\Scripts\python.exe tools\control_server.py"

echo 启动摄像头...
netstat -ano | findstr ":8765" | findstr LISTENING >nul
if errorlevel 1 start "" /min cmd /c ".venv\Scripts\python.exe tools\camera_web.py --raw"

echo 等待控制桥...
set /a tries=0
:wait
netstat -ano | findstr ":8010" | findstr LISTENING >nul
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% geq 20 goto ready
timeout /t 1 >nul
goto wait
:ready

set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BROWSER%" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%BROWSER%" set "BROWSER=msedge.exe"
start "" "%BROWSER%" --app=http://127.0.0.1:8010/?view=camera --window-size=1600,1000 --start-maximized

echo.
echo 操作台窗口：左边实时画面，右边操作。
echo 关闭本窗口不会停掉服务；要停服务请关掉最小化的 python 窗口和 Blender。
pause

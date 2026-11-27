"""把 CoreBall 打成一个独立 Windows 文件夹（含 Blender）。

用法：
  .venv\\Scripts\\python.exe tools\\package_app.py
产物：
  dist\\CoreBall\\            可直接运行 / 复制给别人
  dist\\CoreBall\\Install-CoreBall.bat
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "CoreBall"
SITE = ROOT / ".venv" / "Lib" / "site-packages"
BLENDER_SRC = Path(os.environ.get(
    "COREBALL_BLENDER",
    r"C:\Users\21165\Apps\blender-4.5.16\blender-4.5.16-windows-x64",
))

TOOLS = ("control_server.py", "camera_web.py", "tension.py", "body.py", "telemetry.py")
PYLIBS = ("cv2", "numpy", "numpy.libs")


def copy_tree(src, dst, ignore=None):
    print("copy", src, "->", dst)
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)


def write_bat(path, text):
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def build_files():
    if not BLENDER_SRC.exists():
        raise SystemExit("找不到 Blender：%s（可用 COREBALL_BLENDER 指定）" % BLENDER_SRC)
    if OUT.exists():
        print("清理", OUT)
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    copy_tree(BLENDER_SRC, OUT / "Blender")
    (OUT / "app" / "blend").mkdir(parents=True)
    (OUT / "app" / "blender").mkdir(parents=True)
    (OUT / "app" / "tools").mkdir(parents=True)
    (OUT / "app" / "pylibs").mkdir(parents=True)

    shutil.copy2(ROOT / "blender" / "out" / "cmd" / "coreball_command.blend",
                 OUT / "app" / "blend" / "coreball_command.blend")
    for name in ("cmd_runtime.py", "actions.json"):
        shutil.copy2(ROOT / "blender" / name, OUT / "app" / "blender" / name)
    for name in TOOLS:
        src = ROOT / name if name == "body.py" else ROOT / "tools" / name
        shutil.copy2(src, OUT / "app" / "tools" / name)

    ignore = shutil.ignore_patterns("test", "__pycache__", "*.pyc", "*.bat", "_wide.html")
    copy_tree(ROOT / "web", OUT / "app" / "web", ignore=ignore)

    for name in PYLIBS:
        copy_tree(SITE / name, OUT / "app" / "pylibs" / name)


def build_exe():
    print("PyInstaller -> CoreBall.exe")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "CoreBall",
        "--distpath", str(OUT),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build" / "pyinstaller"),
        str(ROOT / "tools" / "app_launcher.py"),
    ]
    subprocess.run(cmd, check=True)


INSTALL = r"""@echo off
chcp 65001 >nul
set "SRC=%~dp0."
set "DST=%LOCALAPPDATA%\CoreBall"
echo 安装 CoreBall 到 %DST%
taskkill /f /im CoreBall.exe >nul 2>&1
ping -n 3 127.0.0.1 >nul
robocopy "%SRC%" "%DST%" /E /XF "Install-CoreBall.bat" /R:2 /W:1 /NFL /NDL /NJH /NJS /NC /NS /NP >nul
if errorlevel 8 (
  echo.
  echo 复制失败。先关闭正在运行的 CoreBall 和 Blender，再运行一次。
  pause
  exit /b 1
)
set "COREBALL_HOME=%DST%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=$env:COREBALL_HOME; $w=New-Object -ComObject WScript.Shell; $desk=[Environment]::GetFolderPath('Desktop'); $s=$w.CreateShortcut($desk+'\CoreBall 操作台.lnk'); $s.TargetPath=$d+'\CoreBall.exe'; $s.WorkingDirectory=$d; $s.IconLocation=$d+'\CoreBall.exe,0'; $s.Save(); $start=[Environment]::GetFolderPath('Programs')+'\CoreBall'; New-Item -ItemType Directory -Force -Path $start | Out-Null; $s2=$w.CreateShortcut($start+'\CoreBall 操作台.lnk'); $s2.TargetPath=$d+'\CoreBall.exe'; $s2.WorkingDirectory=$d; $s2.IconLocation=$d+'\CoreBall.exe,0'; $s2.Save();"
echo 安装完成。桌面和开始菜单都有「CoreBall 操作台」。
start "" "%DST%\CoreBall.exe"
pause
"""

STOP = r"""@echo off
chcp 65001 >nul
taskkill /f /im CoreBall.exe >nul 2>&1
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$root=$env:ROOT; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($root) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo 已停止 CoreBall。
pause
"""

UNINSTALL = r"""@echo off
chcp 65001 >nul
call "%~dp0Stop-CoreBall.bat" >nul 2>&1
del "%USERPROFILE%\Desktop\CoreBall 操作台.lnk" >nul 2>&1
rmdir /s /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\CoreBall" >nul 2>&1
set "ROOT=%LOCALAPPDATA%\CoreBall"
start "" powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 2; Remove-Item -LiteralPath $env:LOCALAPPDATA+'\CoreBall' -Recurse -Force -ErrorAction SilentlyContinue"
echo 快捷方式已删除，程序目录会在 2 秒后删除。
pause
"""

README = """CoreBall 独立版
================

安装
  1. 解压整个文件夹（不要只复制 exe）。
  2. 双击 Install-CoreBall.bat。
  3. 桌面 / 开始菜单会出现「CoreBall 操作台」。

使用
  - 打开后左边是实时画面，右边是操作台。
  - 顶栏「摄像头」开关可以关闭/打开摄像头。
  - 3D 工位 / 2D 地图 / 实时画面 在左上角切换。
  - 关闭 CoreBall 启动窗口会停止 Blender、控制桥和摄像头。
  - 也可以用 Stop-CoreBall.bat 一键停止。

卸载
  双击 Uninstall-CoreBall.bat，或删除 %LOCALAPPDATA%\\CoreBall。

端口
  8010 控制桥，8765 摄像头，4590/4591 Blender 指令/遥测；都只监听本机。

注意
  - 首次启动 Blender 需要几秒，页面会自动连上。
  - 如果 Windows 安全软件拦截 Blender，请允许。
  - 安装包内含 Blender（GPL），许可证见 Blender 目录。
"""


def build_scripts():
    write_bat(OUT / "Install-CoreBall.bat", INSTALL)
    write_bat(OUT / "Stop-CoreBall.bat", STOP)
    write_bat(OUT / "Uninstall-CoreBall.bat", UNINSTALL)
    (OUT / "README.txt").write_text(README.replace("\n", "\r\n"), encoding="utf-8")


def main():
    build_files()
    build_exe()
    build_scripts()
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1024 / 1024
    print("完成：%s（%.0f MB）" % (OUT, size))
    print("把整个 dist\\CoreBall 文件夹压缩后发给别人；对方解压后运行 Install-CoreBall.bat。")


if __name__ == "__main__":
    main()




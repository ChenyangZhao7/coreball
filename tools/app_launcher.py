"""CoreBall 独立版启动器：Blender + 控制桥 + 摄像头 + 应用窗口。

打包后由 CoreBall.exe 调用；源码运行时从仓库根目录找 Blender/app。
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def port_open(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def find_browser():
    roots = [
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
        os.environ.get("LOCALAPPDATA"),
    ]
    rels = [
        ("Microsoft", "Edge", "Application", "msedge.exe"),
        ("Google", "Chrome", "Application", "chrome.exe"),
    ]
    for root in roots:
        if not root:
            continue
        for rel in rels:
            p = Path(root).joinpath(*rel)
            if p.exists():
                return str(p)
    return None


def open_window(url):
    browser = find_browser()
    if browser:
        subprocess.Popen(
            [browser, "--app=" + url, "--window-size=1600,1000", "--start-maximized"],
            creationflags=CREATE_NO_WINDOW,
        )
    else:
        webbrowser.open(url)


def main():
    if os.name == "nt":
        os.system("chcp 65001 >nul")
    base = base_dir()
    blender = base / "Blender" / "blender.exe"
    python = base / "Blender" / "4.5" / "python" / "bin" / "python.exe"
    blend = base / "app" / "blend" / "coreball_command.blend"
    cmd = base / "app" / "blender" / "cmd_runtime.py"
    tools = base / "app" / "tools"
    pylibs = base / "app" / "pylibs"
    url = "http://127.0.0.1:8010/?view=camera"

    for p in (blender, python, blend, cmd, tools):
        if not p.exists():
            print("缺少文件：", p)
            input("按回车退出...")
            return 2

    if port_open(8010):
        print("CoreBall 已经在运行，直接打开窗口。")
        open_window(url)
        input("按回车退出此窗口（不会停止 CoreBall）...")
        return 0

    env = os.environ.copy()
    env["PYTHONPATH"] = str(pylibs) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    procs = []

    print("启动 Blender 指挥场景...")
    procs.append(subprocess.Popen(
        [str(blender), str(blend), "--python", str(cmd)],
        cwd=str(base),
    ))

    print("启动控制桥...")
    procs.append(subprocess.Popen(
        [str(python), str(tools / "control_server.py")],
        cwd=str(base), env=env, creationflags=CREATE_NO_WINDOW,
    ))

    print("启动摄像头...")
    procs.append(subprocess.Popen(
        [str(python), str(tools / "camera_web.py"), "--raw"],
        cwd=str(base), env=env, creationflags=CREATE_NO_WINDOW,
    ))

    for _ in range(60):
        if port_open(8010):
            break
        time.sleep(0.5)

    if not port_open(8010):
        print("控制桥没有起来。请检查 Blender 是否被安全软件拦截。")
        input("按回车退出...")
        for p in procs:
            if p.poll() is None:
                p.terminate()
        return 3

    print("打开操作台窗口...")
    open_window(url)
    print("CoreBall 已启动：", url)
    print("关闭此窗口会停止 Blender、控制桥和摄像头。")
    try:
        while True:
            if all(p.poll() is not None for p in procs):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

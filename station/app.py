"""控制台入口：HTTP API + 静态页 + UDP link。"""
import argparse
import json
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from station import commands
from station import config as cfg
from station.history import History
from station.link import Link
from station.predictor import Predictor

STATION_WEB = Path(__file__).with_name("web")
SHARED_WEB = Path(__file__).resolve().parents[1] / "web"
DATA = Path(__file__).with_name("data")


class App:
    def __init__(self, config=None, link=None, history=None, now=time.time):
        self.cfg = config or cfg
        self.now = now
        self.lock = threading.RLock()
        self.arbiter = commands.Arbiter(now=now)
        self.link = link if link is not None else Link()
        self.history = history or History(DATA / "history.jsonl")

    # ---------------- 命令 ----------------
    def submit(self, source, kind, payload, reason="", ttl_s=None,
               confidence=1.0):
        if not source or not kind:
            return 400, {"ok": False, "error": "source/kind 不能为空"}
        if source not in self.cfg.PRIORITIES or kind not in commands.KINDS:
            return 409, {"ok": False, "error": "source/kind 不合法"}
        if kind == "jog" and source != "manual":
            return 409, {"ok": False, "error": "只有 manual 可以 jog"}
        command = commands.Command(
            source=source, kind=kind, payload=payload or {},
            reason=reason or "", ttl_s=ttl_s, confidence=float(confidence or 1.0),
            created_at=self.now())
        return self.submit_command(command)

    def submit_command(self, command):
        with self.lock:
            try:
                status = self.arbiter.submit(command)
            except (commands.BadCommand, ValueError) as e:
                return 400, {"ok": False, "error": str(e)}

            entry = {"t": self.now()}
            entry.update(command.to_dict())
            self.history.append(entry)
            if status == "accepted":
                self.link.send(commands.to_intent(command))
            return 200, {"ok": True, "status": status, "id": command.id,
                         "command": command.to_dict()}

    def state(self):
        with self.lock:
            out = self.arbiter.status()
        latest = self.link.latest()
        out["link"] = {
            "connected": bool(latest and not latest.get("stale")),
            "age_ms": latest.get("age_ms") if latest else None,
        }
        out["telemetry"] = latest
        return out

    # ---------------- 模式/建议 ----------------
    def set_mode(self, mode):
        with self.lock:
            try:
                self.arbiter.set_mode(mode)
            except commands.BadCommand as e:
                return 400, {"ok": False, "error": str(e)}
            return 200, {"ok": True, "mode": mode}

    def accept(self, sid):
        with self.lock:
            try:
                command = self.arbiter.accept(sid)
            except KeyError:
                return 404, {"ok": False, "error": "没有这条建议"}
            if command is None:
                return 409, {"ok": False, "error": "建议已过期或不可执行"}
            self.link.send(commands.to_intent(command))
            entry = {"t": self.now()}
            entry.update(command.to_dict())
            self.history.append(entry)
            return 200, {"ok": True, "command": command.to_dict()}

    def reject(self, sid):
        with self.lock:
            try:
                self.arbiter.reject(sid)
            except KeyError:
                return 404, {"ok": False, "error": "没有这条建议"}
            return 204, {"ok": True}

    def settings(self, prediction_auto):
        with self.lock:
            self.arbiter.set_prediction_auto(prediction_auto)
            return 200, {"ok": True,
                         "prediction_auto": self.arbiter.prediction_auto}

    def recent_history(self, n=50):
        return self.history.recent(n)


class Handler(SimpleHTTPRequestHandler):
    app = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATION_WEB), **kwargs)

    def translate_path(self, path):
        clean = unquote(urlsplit(path).path)
        if clean.startswith("/shared/"):
            root = SHARED_WEB
            rel = clean[len("/shared/"):]
        else:
            root = STATION_WEB
            rel = clean.lstrip("/")
        target = (root / rel).resolve()
        base = root.resolve()
        if target != base and base not in target.parents:
            return str(STATION_WEB / "__missing__")
        return str(target)

    def _send(self, status, payload):
        body = b"" if status == 204 else json.dumps(
            payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path
        if path == "/api/state":
            return self._send(200, self.app.state())
        if path == "/api/history":
            q = parse_qs(parts.query)
            try:
                n = int(q.get("limit", ["50"])[0])
            except ValueError:
                n = 50
            return self._send(200, {"items": self.app.recent_history(n)})
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        routes = {"/api/command", "/api/mode", "/api/suggestion/accept",
                  "/api/suggestion/reject", "/api/settings"}
        if path not in routes:
            return self.send_error(404)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 8192:
                raise ValueError("bad length")
            data = json.loads(self.rfile.read(size).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("bad json")
        except Exception:
            return self._send(400, {"ok": False, "error": "请求不是合法 JSON"})

        if path == "/api/command":
            status, payload = self.app.submit(
                data.get("source"), data.get("kind"), data.get("payload") or {},
                data.get("reason", ""), data.get("ttl_s"),
                data.get("confidence", 1.0))
        elif path == "/api/mode":
            status, payload = self.app.set_mode(data.get("mode"))
        elif path == "/api/suggestion/accept":
            status, payload = self.app.accept(data.get("id"))
        elif path == "/api/suggestion/reject":
            status, payload = self.app.reject(data.get("id"))
        else:
            status, payload = self.app.settings(data.get("prediction_auto", False))
        self._send(status, payload)

    def log_message(self, fmt, *args):
        pass  # 本地工具：不刷访问日志


def create_server(host, port, app):
    handler = type("BoundHandler", (Handler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None):
    ap = argparse.ArgumentParser(description="CoreBall 独立控制台")
    ap.add_argument("--port", type=int, default=cfg.PORT)
    ap.add_argument("--no-prediction", action="store_true")
    args = ap.parse_args(argv)

    link = Link()
    try:
        link.start()
    except OSError as e:
        print("station: %s" % e)
        return 2
    app = App(link=link)
    stop = threading.Event()
    if not args.no_prediction:
        predictor = Predictor(app.submit_command, link.latest)
        threading.Thread(target=predictor.run, args=(stop,), daemon=True).start()

    server = create_server(cfg.HOST, args.port, app)
    print("CoreBall station: http://%s:%d/" % (cfg.HOST, args.port))
    print("UDP 4590 发送 / 4591 接收；不要同时开 control_server.py")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        link.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

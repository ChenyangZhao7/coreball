"""Local bridge for the 2D/3D debug console.

Serves web/ and forwards POST /intent to the Blender command scene over UDP
(127.0.0.1:4590). Blender pushes telemetry back to UDP 127.0.0.1:4591; the
latest frame is available at GET /state.

Browsers cannot send UDP directly, hence this bridge.

Usage:
  python tools/control_server.py
  # then open http://127.0.0.1:8010/
"""
import json
import os
import socket
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
UDP_ADDR = ("127.0.0.1", 4590)
TELEMETRY_ADDR = ("127.0.0.1", 4591)
PORT = 8010


class TelemetryStore:
    """最新一帧遥测；带接收时间和超时标记。"""

    def __init__(self, max_age=1.0):
        self.max_age = float(max_age)
        self._lock = threading.Lock()
        self._snap = None
        self._at = 0.0

    def put(self, raw, now=None):
        try:
            snap = json.loads(raw.decode("utf-8"))
        except Exception:
            return False
        if not isinstance(snap, dict):
            return False
        with self._lock:
            self._snap = snap
            self._at = time.monotonic() if now is None else float(now)
        return True

    def get(self, now=None):
        with self._lock:
            if self._snap is None:
                return None
            age = (time.monotonic() if now is None else float(now)) - self._at
            out = dict(self._snap)
        out["ok"] = True
        out["age_ms"] = int(round(age * 1000.0))
        out["stale"] = age > self.max_age
        return out


STORE = TelemetryStore()


def start_telemetry(port=TELEMETRY_ADDR[1], host="127.0.0.1", store=None):
    """后台收 Blender 的遥测包；返回 (socket, thread)。关掉 socket 即退出。"""
    store = STORE if store is None else store
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host, port))

    def loop():
        while True:
            try:
                data, _ = s.recvfrom(8192)
            except OSError:
                break
            store.put(data)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return s, t


class Handler(SimpleHTTPRequestHandler):
    store = None
    udp_addr = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB, **kwargs)

    def _store(self):
        return self.store if self.store is not None else STORE

    def _udp(self):
        return self.udp_addr if self.udp_addr is not None else UDP_ADDR

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/state":
            snap = self._store().get()
            return self._send_json(snap if snap is not None else {"ok": False})
        if path == "/":
            query = self.path[len(path):]
            self.path = "/control.html" + query
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/intent":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > 8192:
                raise ValueError("bad length")
            raw = self.rfile.read(n)
            msg = json.loads(raw.decode("utf-8"))   # validate only
            if not isinstance(msg, dict) or not msg.get("intent"):
                raise ValueError("missing intent")
        except Exception:
            self.send_error(400, "bad json")
            return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(raw, self._udp())
            s.close()
        except OSError as e:
            self.send_error(503, "udp: %s" % e)
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        print("[control] " + fmt % args)


def create_server(host="127.0.0.1", port=PORT, udp_addr=None, store=None):
    handler = type("BoundHandler", (Handler,), {
        "udp_addr": udp_addr,
        "store": store,
    })
    return ThreadingHTTPServer((host, port), handler)


if __name__ == "__main__":
    try:
        start_telemetry()
    except OSError as e:
        print("CoreBall: 遥测端口 %s 打不开（%s），页面会显示未连接"
              % (TELEMETRY_ADDR, e))
    print("CoreBall control: http://127.0.0.1:%d/  -> UDP %s, telemetry %s" %
          (PORT, UDP_ADDR, TELEMETRY_ADDR))
    with create_server() as http:
        http.serve_forever()

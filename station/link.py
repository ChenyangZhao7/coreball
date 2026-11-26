"""UDP 4590 发送 / 4591 接收。"""
import json
import socket
import threading
import time

from . import config


class Link:
    def __init__(self, intent_addr=config.INTENT_ADDR,
                 telemetry_addr=config.TELEMETRY_ADDR, sock=None,
                 now=time.monotonic):
        self.intent_addr = tuple(intent_addr)
        self.telemetry_addr = tuple(telemetry_addr)
        self._sock = sock
        self._tele = None
        self._thread = None
        self._running = False
        self._now = now
        self._lock = threading.Lock()
        self._snap = None
        self._at = None

    def start(self):
        if self._tele is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(self.telemetry_addr)
        except OSError as e:
            sock.close()
            raise OSError(
                "遥测端口 %d 被占用；先停掉 tools/control_server.py"
                % self.telemetry_addr[1]) from e
        self._tele = sock
        self._running = True
        self._thread = threading.Thread(target=self._recv_loop, args=(sock,),
                                        daemon=True)
        self._thread.start()

    def _recv_loop(self, sock):
        while self._running:
            try:
                raw, _ = sock.recvfrom(8192)
            except OSError:
                break
            self.put_telemetry(raw)

    def stop(self):
        self._running = False
        sock = self._tele
        self._tele = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send(self, intent):
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        data = json.dumps(intent, ensure_ascii=False).encode("utf-8")
        self._sock.sendto(data, self.intent_addr)

    def put_telemetry(self, raw, now=None):
        try:
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            data = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return False
        if not isinstance(data, dict):
            return False
        with self._lock:
            self._snap = data
            self._at = self._now() if now is None else float(now)
        return True

    def age_ms(self):
        with self._lock:
            if self._at is None:
                return None
            age = self._now() - self._at
        return int(round(age * 1000.0))

    def latest(self):
        with self._lock:
            if self._snap is None:
                return None
            snap = dict(self._snap)
            age = self._now() - self._at if self._at is not None else None
        if age is None:
            return None
        age_ms = int(round(age * 1000.0))
        snap["age_ms"] = age_ms
        snap["stale"] = age_ms >= 1000
        return snap

    def connected(self, max_age=1.0):
        age = self.age_ms()
        return age is not None and age < max_age * 1000.0

"""模拟预测源：固定给“往右 200 mm”的建议，不直接发 UDP。"""
import threading
import time

from . import commands
from . import config


class Predictor:
    def __init__(self, submit, latest, now=time.time,
                 interval=config.PREDICTION_INTERVAL,
                 confidence=config.PREDICTION_CONFIDENCE):
        self.submit = submit
        self.latest = latest
        self.now = now
        self.interval = float(interval)
        self.confidence = float(confidence)
        self.last = -1e9

    def tick(self, now=None):
        now = self.now() if now is None else float(now)
        snap = self.latest()
        if (not snap or not snap.get("ball") or snap.get("stale")
                or snap.get("body") != "winch"):
            return None
        if now - self.last < self.interval:
            return None
        x, y, z = snap["ball"]
        command = commands.Command(
            source="prediction", kind="goto",
            payload={"point": [float(x) + 200.0, float(y), float(z)]},
            reason="模拟预测：你可能想让它往右一点",
            confidence=self.confidence, created_at=now)
        self.last = now
        self.submit(command)
        return command

    def run(self, stop_event):
        while not stop_event.is_set():
            try:
                self.tick()
            except Exception as e:  # 预测不能把主程序带崩
                print("[station] predictor:", e)
            stop_event.wait(1.0)

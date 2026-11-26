"""JSONL 命令历史。"""
import json
import threading
from pathlib import Path


class History:
    def __init__(self, path, limit=500):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.limit = int(limit)
        self._lock = threading.Lock()

    def append(self, entry):
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line)

    def recent(self, n=50):
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-max(1, int(n)):]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

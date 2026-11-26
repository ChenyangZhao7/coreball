"""Command 模型、来源优先级、TTL、仲裁。"""
import copy
import math
import time
import uuid
from dataclasses import asdict, dataclass, field

from . import config

KINDS = ("goto", "jog", "stop", "expression", "preset")
MOTION = ("goto", "jog", "preset")


class BadCommand(ValueError):
    """命令字段不合法。"""


@dataclass
class Command:
    source: str
    kind: str
    payload: dict
    reason: str = ""
    ttl_s: float | None = None
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: "cmd_" + uuid.uuid4().hex[:10])
    priority: int = 0
    status: str = "accepted"
    sent_at: float | None = None
    requested: dict | None = None

    def to_dict(self):
        return asdict(self)


def _to_intent(command):
    source = "station/" + command.source
    kind = command.kind
    if kind == "goto":
        out = {"intent": "goto", "point": list(command.payload["point"]),
               "src": source}
    elif kind == "jog":
        out = {"intent": "jog", "v": list(command.payload["v"]), "src": source}
    elif kind == "stop":
        out = {"intent": "stop", "src": source}
    elif kind == "expression":
        out = {"intent": "expression", "name": command.payload["name"],
               "src": source}
    elif kind == "preset":
        out = {"intent": command.payload["name"], "src": source}
    else:  # pragma: no cover - validation prevents this
        raise BadCommand("unknown kind: %s" % kind)
    if command.reason:
        out["reason"] = command.reason
    return out


to_intent = _to_intent


class Arbiter:
    def __init__(self, now=time.time):
        self.now = now
        self.mode = "manual"
        self.prediction_auto = False
        self.active = None
        self.suggestions = []
        self.last_manual_at = -1e9
        self.last_nonmanual_at = -1e9

    def set_mode(self, mode):
        if mode not in ("manual", "auto"):
            raise BadCommand("mode 必须是 manual 或 auto")
        self.mode = mode

    def set_prediction_auto(self, flag):
        self.prediction_auto = bool(flag)

    # ---------------- 校验 ----------------
    def _validate(self, command):
        if command.source not in config.PRIORITIES:
            raise BadCommand("未知 source: %s" % command.source)
        if command.kind not in KINDS:
            raise BadCommand("未知 kind: %s" % command.kind)
        if not isinstance(command.payload, dict):
            raise BadCommand("payload 必须是对象")
        if command.kind == "stop":
            return
        if command.kind == "goto":
            point = command.payload.get("point")
            if not isinstance(point, (list, tuple)) or len(point) != 3:
                raise BadCommand("goto 需要 point[x,y,z]")
            try:
                point = [float(v) for v in point]
            except (TypeError, ValueError):
                raise BadCommand("goto point 不是数字")
            if not all(math.isfinite(v) for v in point):
                raise BadCommand("goto point 不是有限数")
            command.requested = {"point": list(point)}
            command.payload["point"] = [
                point[0], point[1],
                min(max(point[2], config.Z_MIN), config.Z_MAX)]
            return
        if command.kind == "jog":
            if command.source != "manual":
                raise BadCommand("只有 manual 可以 jog")
            v = command.payload.get("v")
            if not isinstance(v, (list, tuple)) or len(v) != 3:
                raise BadCommand("jog 需要 v[x,y,z]")
            try:
                v = [float(x) for x in v]
            except (TypeError, ValueError):
                raise BadCommand("jog v 不是数字")
            if not all(math.isfinite(x) for x in v):
                raise BadCommand("jog v 不是有限数")
            if math.sqrt(sum(x * x for x in v)) > config.MAX_JOG:
                raise BadCommand("jog 速度超过上限")
            command.payload["v"] = v
            return
        if command.kind == "expression":
            if command.payload.get("name") not in config.EXPRESSIONS:
                raise BadCommand("未知表情")
            return
        if command.kind == "preset":
            if command.payload.get("name") not in config.PRESETS:
                raise BadCommand("未知预设")

    # ---------------- 提交 ----------------
    def submit(self, command):
        self._validate(command)
        command.priority = (1000 if command.kind == "stop"
                            else config.PRIORITIES[command.source])

        ttl = command.ttl_s
        if ttl is None:
            ttl = config.DEFAULT_TTL.get(command.kind, 5.0)
        now = self.now()
        if ttl and now - command.created_at >= ttl:
            command.status = "expired"
            return "expired"

        if command.kind == "stop":
            command.status = "accepted"
            self.mode = "manual"
            self.active = None
            self.suggestions.clear()
            self.last_manual_at = now
            return "accepted"

        if self.mode == "manual" and command.source != "manual":
            return self._suggest(command)

        if command.source == "prediction":
            idle = (now - self.last_manual_at >= config.PREDICTION_IDLE_S
                    and now - self.last_nonmanual_at >= config.PREDICTION_IDLE_S)
            if (not self.prediction_auto
                    or command.confidence < config.PREDICTION_AUTO_MIN
                    or not idle):
                return self._suggest(command)

        if command.source != "manual" and self.active is not None:
            active = self.active
            if (active["kind"] in MOTION
                    and active.get("sent_at") is not None
                    and now - active["sent_at"] < config.HOLD_S
                    and command.priority < active["priority"]):
                command.status = "rejected"
                return "rejected"

        command.status = "accepted"
        command.sent_at = now
        if command.kind in MOTION:
            self.active = command.to_dict()
        if command.source == "manual":
            self.mode = "manual"
            self.last_manual_at = now
            self.suggestions.clear()
        else:
            self.last_nonmanual_at = now
        return "accepted"

    def _suggest(self, command):
        command.status = "suggested"
        self.suggestions = [c for c in self.suggestions if c.id != command.id]
        self.suggestions.append(command)
        self.suggestions = self.suggestions[-20:]
        return "suggested"

    def accept(self, sid):
        found = next((c for c in self.suggestions if c.id == sid), None)
        if found is None:
            raise KeyError(sid)
        self.suggestions = [c for c in self.suggestions if c.id != sid]
        command = Command(source="manual", kind=found.kind,
                          payload=copy.deepcopy(found.payload),
                          reason=found.reason or "接受建议",
                          ttl_s=0.0, created_at=self.now())
        status = self.submit(command)
        return command if status == "accepted" else None

    def reject(self, sid):
        before = len(self.suggestions)
        self.suggestions = [c for c in self.suggestions if c.id != sid]
        if len(self.suggestions) == before:
            raise KeyError(sid)

    def status(self):
        active = self.active
        suggestions = [c.to_dict() for c in self.suggestions]
        queue = ([active] if active is not None else []) + suggestions
        return {
            "mode": self.mode,
            "prediction_auto": self.prediction_auto,
            "active": active,
            "current_source": active["source"] if active else None,
            "suggestions": suggestions,
            "queue": queue,
        }

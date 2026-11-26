# CoreBall 独立控制台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做一个独立的本地控制台：手动把球送到任意点，语音/行为/预测走同一个命令入口，由仲裁器决定谁真正控制；先驱动 Blender 建模，以后换硬件只换 transport。

**Architecture:** `station/` 是一个标准库 HTTP 进程：`commands` 管 Command/来源/优先级/TTL，`link` 管 UDP 4590/4591，`app` 暴露 `/api/*` 和静态页，`predictor` 产生模拟预测建议；浏览器 UI 用 2D 地图 + x/y/z + 3D `viewer.html` 实时预览。安全夹紧以 `cmd_runtime` 为最终权威，station 只额外夹 z。

**Tech Stack:** Python 3.11、标准库（`http.server`、`socket`、`json`、`unittest`）、原生 HTML/JS；不新增依赖；复用 `web/viewer.html`、`rig.glb`、`params.json`。

**Spec:** `docs/superpowers/specs/2026-11-26-control-station-design.md`

## Global Constraints

- 只绑定 `127.0.0.1`；HTTP 默认 `8030`；UDP 发送 `4590`、接收 `4591`。
- **station 独占 4591**；运行它时不要再开 `tools/control_server.py`（`control.html` 的旧桥）；被占用时启动失败并打印明确提示。
- 手动模式默认；`stop` 永远最高；接管 = stop + manual，**不回默认位**。
- v1 只控制 winch；`telem.body != "winch"` 时只读、禁用 goto/高度/预设。
- 手动动作切回 manual；非手动命令在 manual 下只记 `suggested`，HTTP 返回 `200`。
- 非手动 `jog`、非法 source/kind、缺 payload 才返回 `409`；参数类型错返回 `400`。
- 优先级：stop 1000、manual 100、voice 60、behavior 50、prediction 20；不做等待队列，低优先级在 2 s 内 `rejected`。
- `z` 由 station 夹到 `900–1500 mm`；x/y 原样发，由 `cmd_runtime.clamp_ball` 夹；UI 显示 `requested`/实际。
- 预测：固定 `ball + (200,0,0)`，confidence `0.75`，自动阈值 `0.7`，`prediction_auto` 默认关。
- 历史写 `station/data/history.jsonl`（不进 git）；`/shared/*` 只映射仓库 `web/*`。
- 所有 UI 文案中文；所有抓来的内容用 `textContent`，不拼 `innerHTML`。
- 执行测试用主仓库 venv：`Z:\Projects\coreball\.venv\Scripts\python.exe`（worktree 没有 `.venv`）。

## Review Focus

- **4591 冲突**：station 启动时 4591 被 `control_server.py` 占用 → 必须失败并提示停旧桥，而不是静默没遥测。Task 2 测绑定失败/提示。
- **z 越界**：`cmd_runtime` 不夹 z；数值输入 `z=5000` 必须被 station 夹到 1500，且 `requested` 保留原值。Task 1 测。
- **优先级抢占**：voice 正在走，behavior 1 s 内发 goto 必须 `rejected`，不能悄悄覆盖；manual 必须立刻抢占。Task 1 测。
- **manual 下 voice**：必须是 `200 suggested`，不能 409；409 只给非法请求。Task 3 测。
- **预测自动是活的**：模拟置信度 0.75 > 阈值 0.7，`prediction_auto=True` 且空闲时必须真的执行，不是死路径。Task 4 测。

---

### Task 1: 命令模型、仲裁与历史

**Files:**
- Create: `station/__init__.py`
- Create: `station/config.py`
- Create: `station/commands.py`
- Create: `station/history.py`
- Create: `station/tests/__init__.py`
- Create: `station/tests/test_commands.py`
- Modify: `.gitignore`（追加 `station/data/`）

**Interfaces:**
- Produces: `config.HOST/PORT/INTENT_ADDR/TELEMETRY_ADDR/PRIORITIES/DEFAULT_TTL/HOLD_S/Z_MIN/Z_MAX/PREDICTION_*`。
- Produces: `commands.BadCommand(ValueError)`；`commands.Command`（dataclass，`to_dict()`）；`commands.to_intent(cmd) -> dict`。
- Produces: `commands.Arbiter(now=time.time)`：`submit(cmd) -> str`（`accepted/suggested/rejected/expired`，非法抛 `BadCommand`）、`accept(sid) -> Command`、`reject(sid)`、`set_mode(mode)`、`set_prediction_auto(flag)`、`status() -> dict`。
- Produces: `history.History(path, limit=500)`：`append(entry)`、`recent(n=50)`。

- [ ] **Step 1: 写失败测试**

`station/tests/test_commands.py`：

```python
import tempfile
import unittest
from pathlib import Path

from station import commands as C
from station.history import History

NOW = 1000.0


def cmd(source="manual", kind="goto", payload=None, **kw):
    return C.Command(source=source, kind=kind,
                     payload=payload or {"point": [-380.0, 520.0, 1300.0]},
                     created_at=NOW, **kw)


class ArbiterTest(unittest.TestCase):
    def setUp(self):
        self.a = C.Arbiter(now=lambda: NOW)

    def test_manual_voice_is_suggested(self):
        self.assertEqual(self.a.submit(cmd(source="voice")), "suggested")
        self.assertEqual(self.a.status()["mode"], "manual")
        self.assertIsNone(self.a.status()["active"])

    def test_manual_goto_accepted_and_z_clamped(self):
        c = cmd(payload={"point": [-380.0, 520.0, 5000.0]})
        self.assertEqual(self.a.submit(c), "accepted")
        self.assertEqual(c.payload["point"][2], 1500.0)
        self.assertEqual(c.requested["point"][2], 5000.0)

    def test_auto_voice_accepted(self):
        self.a.set_mode("auto")
        self.assertEqual(self.a.submit(cmd(source="voice")), "accepted")
        self.assertEqual(self.a.status()["current_source"], "voice")

    def test_lower_priority_rejected_during_hold(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="voice"))
        self.assertEqual(self.a.submit(cmd(source="behavior")), "rejected")

    def test_lower_priority_after_hold_accepted(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="voice"))
        self.a.now = lambda: NOW + 2.1
        self.assertEqual(self.a.submit(cmd(source="behavior")), "accepted")

    def test_manual_preempts_voice(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="voice"))
        self.assertEqual(self.a.submit(cmd(source="manual")), "accepted")
        self.assertEqual(self.a.status()["mode"], "manual")

    def test_stop_clears_and_manual(self):
        self.a.set_mode("auto")
        self.a.submit(cmd(source="voice"))
        self.assertEqual(self.a.submit(cmd(source="voice", kind="stop",
                                          payload={})), "accepted")
        s = self.a.status()
        self.assertEqual(s["mode"], "manual")
        self.assertIsNone(s["active"])

    def test_bad_command(self):
        with self.assertRaises(C.BadCommand):
            self.a.submit(cmd(kind="nope"))
        with self.assertRaises(C.BadCommand):
            self.a.submit(cmd(source="nope"))
        with self.assertRaises(C.BadCommand):
            self.a.submit(cmd(payload={"point": [float("nan"), 0, 1300]}))
        with self.assertRaises(C.BadCommand):
            self.a.submit(cmd(source="voice", kind="jog",
                              payload={"v": [10, 0, 0]}))

    def test_ttl_expired(self):
        old = cmd()
        old.created_at = NOW - 10
        self.assertEqual(self.a.submit(old), "expired")

    def test_prediction_suggested_by_default(self):
        self.a.set_mode("auto")
        self.assertEqual(self.a.submit(cmd(source="prediction")), "suggested")

    def test_prediction_auto_runs_when_idle(self):
        self.a.set_mode("auto")
        self.a.set_prediction_auto(True)
        self.assertEqual(self.a.submit(cmd(source="prediction")), "accepted")

    def test_prediction_auto_blocked_by_recent_manual(self):
        self.a.set_prediction_auto(True)
        self.a.submit(cmd(source="manual"))
        self.a.set_mode("auto")
        self.assertEqual(self.a.submit(cmd(source="prediction")), "suggested")

    def test_accept_suggestion_becomes_manual(self):
        self.a.submit(cmd(source="voice"))
        sid = self.a.status()["suggestions"][0]["id"]
        self.a.accept(sid)
        s = self.a.status()
        self.assertEqual(s["mode"], "manual")
        self.assertEqual(s["current_source"], "manual")

    def test_history(self):
        self.a.submit(cmd())
        self.a.submit(cmd(source="voice"))
        self.assertEqual(len(self.a.status()["suggestions"]), 1)


class HistoryTest(unittest.TestCase):
    def test_append_recent(self):
        with tempfile.TemporaryDirectory() as d:
            h = History(Path(d) / "history.jsonl")
            h.append({"id": "1", "source": "manual"})
            h.append({"id": "2", "source": "voice"})
            self.assertEqual([x["id"] for x in h.recent(10)], ["1", "2"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest station.tests.test_commands -v`
Expected: `ModuleNotFoundError: No module named 'station'`

- [ ] **Step 3: 实现 config/commands/history**

`station/config.py`：常量按 Global Constraints；`PRESETS = ("come","back","look","up","down","left","right")`；`EXPRESSIONS=("idle","listening","acting")`。

`station/commands.py`：
- dataclass 字段：`source, kind, payload, reason="", ttl_s=None, confidence=1.0, created_at, id, priority=0, status="accepted", sent_at=None, requested=None`；`to_dict()` 用 `asdict`。
- `to_intent(cmd)`：
  - `goto` → `{"intent":"goto","point":list(point),"src":"station/"+source,"reason":...}`
  - `jog` → `{"intent":"jog","v":list(v),"src":...}`
  - `stop` → `{"intent":"stop","src":...}`
  - `expression` → `{"intent":"expression","name":...}`
  - `preset` → `{"intent":name}`
- `Arbiter`：
  - `_validate`：source/kind；goto point 3 个有限数；z 夹 900–1500，保留 `requested`；jog 只允许 manual，v 3 个数且 ≤400；expression/preset 名称白名单。
  - TTL：`ttl_s` 缺省按 kind；`ttl_s <=0` 不过期；`created_at + ttl < now` → `expired`。
  - `stop`：accepted，`mode=manual`，`active=None`，清空 suggestions。
  - manual：accepted，mode manual，active=cmd，`last_manual_at=now`，清空 suggestions。
  - manual 模式下非 manual：suggested，加入 suggestions。
  - auto 下 prediction：若 `prediction_auto` 为假、`confidence<0.7`、或近 2 s 有 manual/非 manual 命令 → suggested；否则 accepted。
  - auto 下其他非 manual：若有 active 运动且 `now - active.sent_at < 2.0` 且 `priority < active.priority` → rejected；否则 accepted 并更新 active。
  - 接受的运动命令设置 `sent_at=now`；`last_nonmanual_at`。
  - `accept(sid)` 取 suggestion，构造 manual goto 再 submit；`reject(sid)` 删除。
  - `status()` 返回 `mode/current_source/active/suggestions/queue/prediction_auto`；`queue` 为 active+suggestions。
- `station/history.py`：追加 JSONL，父目录创建；`recent` 读最后 n 条，坏行跳过。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest station.tests.test_commands -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add station .gitignore
git commit -m "feat: add station command model and arbiter"
```

---

### Task 2: UDP link 与协议

**Files:**
- Create: `station/link.py`
- Create: `station/tests/test_link.py`

**Interfaces:**
- Consumes: `commands.to_intent`。
- Produces: `link.Link(intent_addr=..., telemetry_addr=..., sock=None, now=time.monotonic)`：`start()`、`stop()`、`send(intent: dict)`、`put_telemetry(raw: bytes, now=None)`、`latest() -> dict|None`、`connected(max_age=1.0) -> bool`、`age_ms() -> int|None`。
- `start()` 绑定 4591 失败抛 `OSError`；错误信息包含「4591」和「control_server」。

- [ ] **Step 1: 写失败测试**

`station/tests/test_link.py`：

```python
import json
import socket
import unittest

from station import commands as C
from station.link import Link


class FakeSock:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


class LinkTest(unittest.TestCase):
    def test_intent_shapes(self):
        c = C.Command("manual", "goto", {"point": [1, 2, 1300]}, created_at=0)
        i = C.to_intent(c)
        self.assertEqual(i["intent"], "goto")
        self.assertEqual(i["src"], "station/manual")
        self.assertEqual(i["point"], [1, 2, 1300])

    def test_send(self):
        sock = FakeSock()
        link = Link(sock=sock)
        link.send({"intent": "stop"})
        raw, addr = sock.sent[0]
        self.assertEqual(json.loads(raw), {"intent": "stop"})
        self.assertEqual(addr, ("127.0.0.1", 4590))

    def test_telemetry_age(self):
        link = Link(now=lambda: 100.0)
        raw = json.dumps({"ball": [0, 0, 1300], "hub": [0, 0, 1460]}).encode()
        link.put_telemetry(raw, now=99.0)
        snap = link.latest()
        self.assertEqual(snap["ball"], [0, 0, 1300])
        self.assertEqual(snap["age_ms"], 1000)
        self.assertTrue(snap["stale"])
        self.assertFalse(link.connected(max_age=0.5))

    def test_bind_conflict(self):
        holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        try:
            with self.assertRaises(OSError):
                Link(telemetry_addr=("127.0.0.1", port)).start()
        finally:
            holder.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest station.tests.test_link -v`
Expected: `ModuleNotFoundError: No module named 'station.link'`

- [ ] **Step 3: 实现 Link**

- `__init__` 存地址、socket（缺省 UDP）、`now`；`latest` 初始 None。
- `start()`：`socket(AF_INET, SOCK_DGRAM).bind(telemetry_addr)`；失败时抛 `OSError("遥测端口 4591 被占用；先停掉 tools/control_server.py")`；后台线程 `recvfrom` → `put_telemetry`；`stop` 关 socket。
- `send(intent)`：JSON UTF-8 发到 intent_addr；异常向上抛。
- `put_telemetry`：JSON 解析，必须是 dict；存 `self._snap`、`self._at`。
- `latest`：复制快照，加 `age_ms`、`stale`（>1000ms）。
- `connected(max_age)`：age ≤ max_age*1000。
- 测试可只构造不 `start`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest station.tests.test_link -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add station/link.py station/tests/test_link.py
git commit -m "feat: add station udp link"
```

---

### Task 3: App、HTTP API 与静态页

**Files:**
- Create: `station/app.py`
- Create: `station/tests/test_app.py`
- Create: `station/web/index.html`（先放最小占位，Task 5 完整页面）

**Interfaces:**
- Consumes: `Arbiter`、`History`、`Link`。
- Produces: `app.App(config=None, link=None, history=None, now=time.time)`：`submit(source, kind, payload, ...) -> (status_code, dict)`、`submit_command(cmd) -> (status_code, dict)`（HTTP 和 predictor 共用）、`state()`、`set_mode(mode)`、`accept(sid)`、`reject(sid)`、`settings(prediction_auto)`、`recent_history(n)`。
- Produces: `app.create_server(host, port, app) -> ThreadingHTTPServer`；`app.main(argv=None) -> int`。

HTTP 契约：

```text
GET  /api/state                 200
POST /api/command               {source, kind, payload, reason?, ttl_s?, confidence?}
                                200 accepted/suggested/rejected
                                400 bad payload; 409 illegal kind/source/non-manual jog
POST /api/mode                  {mode:"manual"|"auto"} 200
POST /api/suggestion/accept     {id} 200 | 404
POST /api/suggestion/reject     {id} 204 | 404
POST /api/settings              {prediction_auto: bool} 200
GET  /api/history?limit=50      200
GET  /                          控制台 HTML
GET  /shared/*                  仓库 web/*（viewer/models/params）
```

- [ ] **Step 1: 写失败测试**

`station/tests/test_app.py`：

```python
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from station.app import App, create_server
from station.history import History


class FakeLink:
    def __init__(self):
        self.sent = []
        self.snap = None

    def send(self, intent):
        self.sent.append(intent)

    def latest(self):
        return self.snap


def req(url, data=None):
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(url, data=body,
                               method="GET" if data is None else "POST",
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=3) as x:
            raw = x.read()
            return x.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else None)


class AppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.link = FakeLink()
        self.app = App(link=self.link,
                       history=History(Path(self.tmp.name) / "h.jsonl"))
        self.httpd = create_server("127.0.0.1", 0, self.app)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_state_and_manual_goto(self):
        self.assertEqual(req(self.base + "/api/state")[1]["mode"], "manual")
        st, body = req(self.base + "/api/command",
                       {"source": "manual", "kind": "goto",
                        "payload": {"point": [-380, 520, 2000]}})
        self.assertEqual(st, 200)
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(self.link.sent[0]["intent"], "goto")
        self.assertEqual(self.link.sent[0]["point"][2], 1500.0)

    def test_manual_voice_is_suggested(self):
        st, body = req(self.base + "/api/command",
                       {"source": "voice", "kind": "goto",
                        "payload": {"point": [0, 500, 1300]}})
        self.assertEqual(st, 200)
        self.assertEqual(body["status"], "suggested")
        self.assertEqual(self.link.sent, [])

    def test_mode_and_voice(self):
        req(self.base + "/api/mode", {"mode": "auto"})
        st, body = req(self.base + "/api/command",
                       {"source": "voice", "kind": "goto",
                        "payload": {"point": [0, 500, 1300]}})
        self.assertEqual(st, 200)
        self.assertEqual(body["status"], "accepted")
        self.assertEqual(self.link.sent[0]["src"], "station/voice")

    def test_accept_suggestion(self):
        req(self.base + "/api/command",
            {"source": "voice", "kind": "goto", "payload": {"point": [0, 500, 1300]}})
        sid = req(self.base + "/api/state")[1]["suggestions"][0]["id"]
        st, _ = req(self.base + "/api/suggestion/accept", {"id": sid})
        self.assertEqual(st, 200)
        self.assertEqual(req(self.base + "/api/state")[1]["mode"], "manual")

    def test_bad_and_illegal(self):
        self.assertEqual(req(self.base + "/api/command", {})[0], 400)
        self.assertEqual(req(self.base + "/api/command",
                             {"source": "voice", "kind": "jog",
                              "payload": {"v": [1, 0, 0]}})[0], 409)
        self.assertEqual(req(self.base + "/api/command",
                             {"source": "nope", "kind": "goto",
                              "payload": {"point": [0, 0, 1300]}})[0], 409)

    def test_shared_and_index(self):
        with urllib.request.urlopen(self.base + "/shared/params.json", timeout=3) as r:
            self.assertEqual(r.status, 200)
        with urllib.request.urlopen(self.base + "/", timeout=3) as r:
            html = r.read().decode("utf-8")
        self.assertIn("/api/state", html)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest station.tests.test_app -v`
Expected: `ModuleNotFoundError: No module named 'station.app'`

- [ ] **Step 3: 实现 App 与 Handler**

- `App.submit_command`: `Arbiter.submit`；若 accepted 调 `link.send(to_intent(cmd))`；写 History；返回 `(200, {status,id,reason,command})`。`App.submit(source,kind,payload,...)` 只构造 `Command` 再调它；predictor 也调 `submit_command`。
- `BadCommand` → 400/409：source/kind 不合法 → 409；payload 数值/缺字段 → 400；非 manual jog → 409。
- `state`: arbiter.status + `link.latest()` + `prediction_auto` + `history` 最近 50。
- `set_mode/accept/reject/settings` 对应。
- `Handler`：`GET /` → `station/web/index.html`；`/api/state`、`/api/history`；`/shared/*` 映射仓库 `web/*`（阻止 `..`）；其他静态从 `station/web`；`POST` 读 ≤8192 字节。`create_server` 同 `control_server.py` 的 BoundHandler 模式。
- `main`: `--port`、`--no-prediction`；`Link.start()` 失败打印「4591 被占用…」返回 2；起 server；打印 URL；KeyboardInterrupt 退出。Task 5 之前不启动 predictor（Task 4 加）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest station.tests.test_app -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add station/app.py station/web/index.html station/tests/test_app.py
git commit -m "feat: add station http api"
```

---

### Task 4: 预测源与自动执行

**Files:**
- Create: `station/predictor.py`
- Modify: `station/app.py`（启动 predictor 线程）
- Create: `station/tests/test_predictor.py`

**Interfaces:**
- Consumes: `App.submit`、`Link.latest`。
- Produces: `predictor.Predictor(submit, latest, now=time.time, interval=8.0, confidence=0.75)`：`tick(now) -> Command|None`；`run(stop_event)`。
- `submit` 是 `App` 的回调：`submit(source, kind, payload, reason, ...)`。

- [ ] **Step 1: 写失败测试**

`station/tests/test_predictor.py`：

```python
import unittest

from station.predictor import Predictor


class PredictorTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.ball = [-380.0, 520.0, 1300.0]

    def submit(self, cmd):
        self.sent.append(cmd)

    def latest(self):
        return {"ball": self.ball}

    def test_tick_builds_suggestion(self):
        p = Predictor(self.submit, self.latest, now=lambda: 100.0)
        c = p.tick(100.0)
        self.assertEqual(c.source, "prediction")
        self.assertEqual(c.payload["point"], [-180.0, 520.0, 1300.0])
        self.assertEqual(c.confidence, 0.75)
        self.assertEqual(self.sent[0].source, "prediction")

    def test_interval_and_no_ball(self):
        p = Predictor(self.submit, lambda: None, now=lambda: 100.0)
        self.assertIsNone(p.tick(100.0))
        self.ball = None
        p2 = Predictor(self.submit, self.latest, now=lambda: 100.0)
        self.assertIsNone(p2.tick(100.0))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest station.tests.test_predictor -v`
Expected: `ModuleNotFoundError: No module named 'station.predictor'`

- [ ] **Step 3: 实现 Predictor 与接线**

- `tick(now)`：若 `latest()` 无 `ball` 返回 None；距上次 < interval 返回 None；否则构造 `Command(source="prediction", kind="goto", payload={"point":[x+200,y,z]}, reason="模拟预测：你可能想让它往右一点", confidence=0.75, created_at=now)`，调用 `submit(cmd)`，更新 last，返回 cmd。
- `run(stop_event)`：每 1 s tick；异常吞掉并打印。
- `app.main`：除非 `--no-prediction`，起 `Predictor(self.submit_prediction, link.latest)` 的 daemon 线程；`submit_prediction` 调 `App.submit` 并在 accepted 时已发 UDP。
- `App.submit` 需要支持 Command 输入（或 `submit_command`），避免重复构造；Task 3 的 HTTP 路径调用同一方法。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest station.tests.test_predictor -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add station/predictor.py station/app.py station/tests/test_predictor.py
git commit -m "feat: add station prediction source"
```

---

### Task 5: 控制台 UI

**Files:**
- Replace: `station/web/index.html`
- Modify: `station/tests/test_app.py`（只加页面元素断言）

**Interfaces:**
- Consumes: HTTP API；`/shared/viewer.html?embed=1&debug=rig`；`/shared/params.json`。
- Produces: 一个可用的手动控制台（2D 地图 + 3D 工位 + 目标 + 状态 + 建议 + 历史）。

- [ ] **Step 1: 页面结构**

- 顶栏：标题、连接状态、模式徽标（手动/自动）、当前来源、「接管」「停止」「2D/3D」。
- 左栏：2D canvas（8 锚点、脖子禁区、球/吊点/目标、球→目标虚线）；点击设 x/y；z 滑杆 900–1500；x/y/z 数值；「发送」；预设/表情按钮；3D iframe。
- 右栏：球/吊点/目标/安全修正/遥测 age/最后指令；支撑/四根张力/最松/力封闭；建议卡片（接受/忽略）；历史最近 20。
- 每 100 ms `fetch('/api/state')`；把 `telemetry` 以 10 Hz `postMessage({type:'telemetry',data})` 给 3D iframe；文本全用 `textContent`。
- 目标/建议/模式/停止都走 `/api/*`；错误显示 toast。
- `telem.body != "winch"` 时只读横幅，禁用 goto/z/presets。

- [ ] **Step 2: 加页面断言**

`test_app.py` 追加：`GET /` 含「接管」「预测」「/api/state」；`GET /shared/params.json` 200。

- [ ] **Step 3: 目测**

Run: `python station/app.py`（Blender 指挥场景已开）
Expected: 页面加载；2D 地图和 3D 工位可见；点击地图/发送后 Blender 里的球移动；张力/支撑/遥测更新；切自动后模拟预测建议出现；接受后球移动；停止立刻停。

- [ ] **Step 4: 提交**

```bash
git add station/web/index.html station/tests/test_app.py
git commit -m "feat: add station control ui"
```

---

### Task 6: README、联调与文档

**Files:**
- Create: `station/README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/07-开发日志.md`
- Modify: `docs/08-技术报告.md`

- [ ] **Step 1: 写 `station/README.md`**

内容：运行顺序（Blender 指挥场景 → `python station/app.py`；不要同时开 `control_server.py`）；4591 独占；API 示例（curl/PowerShell）；来源优先级；手动/自动/接管；预测是模拟；历史路径；测试命令；换硬件只换 `link.py`。

- [ ] **Step 2: 同步文档**

- `README.zh-CN.md` 目录树加 `station/` 四行；加一节「独立控制台」。
- `docs/07` 追加 2026-11-26 station 条目：做了什么/为什么/验证。
- `docs/08` §1.2 加「独立控制台」状态；§10 下一步加「语音/行为接 station API」。

- [ ] **Step 3: 全量测试**

Run: `python -m unittest discover -s station/tests -t . -v`
Expected: 全部 PASS

- [ ] **Step 4: 端到端清单**

- [ ] Blender 指挥场景打开；`station/app.py` 启动无 4591 冲突。
- [ ] 2D 点选/数值发送 → 球到目标；3D 工位同步。
- [ ] 手动模式 voice POST → 200 suggested，球不动。
- [ ] 自动模式 voice POST → 球动；behavior 1 s 内被 rejected；2 s 后可接管。
- [ ] 预测建议出现；接受 → 切 manual 并执行；忽略 → 消失。
- [ ] 停止/接管 → 立刻停；5 秒内无漂移。
- [ ] rover 身体 → 只读横幅，goto 禁用。
- [ ] 4591 被 `control_server.py` 占用 → station 启动失败并提示。

- [ ] **Step 5: 提交**

```bash
git add station/README.md README.zh-CN.md docs/07-开发日志.md docs/08-技术报告.md
git commit -m "docs: document standalone control station"
```

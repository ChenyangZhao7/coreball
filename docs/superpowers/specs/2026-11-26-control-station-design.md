# CoreBall 独立控制台 `station/` 设计

> 2026-11-26 · 状态：待批准 · 类型：独立控制程序（新子系统）
> 先控制 Blender 建模；以后语音、行为、预测都通过同一个命令入口驱动。

---

## 1. 一句话

写一个独立的本地控制台：左手 2D/3D 看球和工位，右手把球送到任意点；手动、语音、行为、预测都往同一个 `Command` 入口投命令，由一个仲裁器决定谁真正控制球，你随时能接管。

它不替代 Blender，也不替代现有 `control.html`；它只负责**命令、仲裁、安全显示、遥测和历史**，把 `goto / jog / stop / expression` 通过现有 UDP 协议发给 Blender。

## 2. 为什么

- 现有 `web/control.html` 是调试台：手动够用，但没有“谁在控制、为什么、下一步建议去哪”的状态。
- 语音（`brain.py`）、行为（十二个时刻）、预测都还没有统一入口；如果各自直接发 UDP，会互相打架，也没法追责。
- 需要一个独立的、可以长期演进的程序：先手动，再自动，再预测；换硬件时只换 transport。

## 3. 目标 / 非目标 / 反目标

**目标**

- 独立进程 `station/`，本地浏览器 UI，默认 `127.0.0.1:8030`。
- 任意目标：2D 地图点选 + x/y/z 数值 + 高度滑杆；显示目标、实际球位、安全修正。
- 3D 工位实时预览：复用 `web/viewer.html?embed=1&debug=rig` 和 `rig.glb`。
- 统一命令 API：`manual / voice / behavior / prediction`，带来源、优先级、TTL、理由。
- 手动接管：任何手动动作立即生效；非手动命令在手动模式下只作为建议。
- 模拟预测源：每 8 秒给一个“下一步建议”，UI 可接受/忽略；可选自动执行。
- 遥测、绳张力、支撑组、连接状态、历史（JSONL）。
- 现有 `cmd_runtime` 的安全层仍是最终权威；控制台不复制、不绕过。

**非目标**

- 不做语音识别/TTS（`brain.py` 以后接 API）。
- 不做行为/预测算法（只留接口 + 一个模拟预测源）。
- 不做 3D 点选/拖拽目标（v1 用 2D + 高度；3D 拾取 v2）。
- 不做 A* 路径规划（v1 画直线 + 安全修正提示；A* v2）。
- 不做硬件串口/协议（transport 抽象，以后换）。
- 不做多用户、远程访问、账号。

**反目标**

- ❌ 让语音/预测绕过手动接管。
- ❌ 在控制台里再写一套安全边界，和 Blender 不一致。
- ❌ 为了“自动”把停止按钮藏起来。
- ❌ 没有遥测还假装在线。

## 4. 方案选择

| 方案 | 内容 | 结论 |
|---|---|---|
| **A. 本地 Web 控制台** | Python 标准库 HTTP + 浏览器 UI；复用 `web/viewer.html` 和 UDP 协议 | **选它** |
| B. 桌面窗口 | Tkinter/PyQt + 自绘 3D | 3D 资产生态都在浏览器，重；不选 |
| C. 无头命令服务 | 只提供 API，不做操作台 | 适合做 A 的后端，不单独交付 |

A 的理由：仓库的 3D（`rig.glb`、`viewer.html`）和遥测都在浏览器侧；标准库 HTTP 不引入新依赖；控制台和 Blender 解耦。

## 5. 总体结构

```
station/
  __init__.py
  app.py            入口：起 UDP 接收、预测线程、HTTP 服务
  config.py         HOST/PORT/优先级/TTL/预测参数/共享 web 路径
  commands.py       Command 模型、来源、模式、仲裁、TTL、历史记录
  link.py           UDP 4590 发送、4591 接收、遥测缓存、连接状态
  predictor.py      模拟预测源（可关）
  history.py        JSONL 历史
  web/index.html    控制台 UI（2D 地图 + 3D iframe + 目标/命令/状态）
  tests/test_commands.py
  tests/test_link.py
  tests/test_app.py
  README.md
```

- 进程内三个线程：HTTP、UDP 接收、预测。共享状态用 `RLock`；不引入 asyncio。
- `/shared/*` 静态映射到仓库 `web/*`（`viewer.html`、`models/rig.glb`、`params.json`）；`/` 映射到 `station/web`。
- 运行：`python station\app.py`，打开 `http://127.0.0.1:8030/`。

## 6. 命令模型

```python
Command = {
  "id": "cmd_...",          # 控制台生成
  "source": "manual|voice|behavior|prediction",
  "kind": "goto|jog|stop|expression|preset",
  "payload": {...},          # goto: {"point":[x,y,z] mm}; jog: {"v":[vx,vy,vz]};
                             # expression: {"name": "listening"}; preset: {"name":"come"}
  "priority": 100,           # 仲裁用；由来源决定，API 不能伪造更高优先级
  "ttl_s": 5.0,              # 过期不执行
  "reason": "用户点击地图",
  "confidence": 1.0,         # prediction 用
  "created_at": 1700000000.0,
  "status": "accepted|suggested|rejected|expired|sent"
}
```

固定优先级：`stop 1000`、`manual 100`、`voice 60`、`behavior 50`、`prediction 20`。API 传 `priority` 时忽略，按 source 查表。

**模式**

- `manual`（默认）：只有 `manual` 和 `stop` 会真正发；`voice/behavior/prediction` 记为 `suggested`，UI 显示，不执行。点「接管」= 发 stop + 切 manual。
- `auto`：`voice`/`behavior` 按优先级执行；`prediction` 默认仍是建议；`manual` 动作立即抢占并切回 `manual`。
- `stop` 任何模式都立即发，清空活动命令，切 `manual`。

**TTL**：默认 goto 5 s、jog 1 s、expression 5 s；超时命令标 `expired`，不发送。UI 手动 goto 的 TTL 可以为 0（立即发一次）。

**优先级与排队（v1）**

- 立即派发；**v1 不做 pending motion scheduler**，避免猜 Blender 什么时候走完。
- 手动任何动作抢占并切回 `manual`；`stop` 永远最高。
- `auto` 下，非手动新命令只有在「优先级 ≥ 当前活动来源」或「当前命令已发出超过 2 s」时才能接管；否则标 `rejected`，原因写「higher-priority active」，不排队。
- `queue` 只显示 active + suggestions，不是等待队列；TTL 在派发前判断。
- `jog` 只在手动下发送；非手动 jog 直接 409。

## 7. 传输与协议

沿用 `blender/cmd_runtime.py`：

- 发送：UDP `127.0.0.1:4590`
  - `{"intent":"goto","point":[x,y,z],"src":"station/manual","reason":"..."}`
  - `{"intent":"jog","v":[vx,vy,vz],"src":"station/manual"}`
  - `{"intent":"stop","src":"station/manual"}`
  - `{"intent":"expression","name":"listening"}`
  - `{"intent":"come"}` 等预设
- 接收：UDP `127.0.0.1:4591`，使用 `telemetry.snapshot` 的字段：`ball/hub/support/tensions/margin/blocked/requested/last/expr/body/anchors/t`。

**4591 归属**：station 自己 bind `4591`；必须停掉 `tools/control_server.py`（它和 `control.html` 是旧的桥）。4591 被占用时 station 启动失败并打印明确提示；两者不能同时接收遥测。运行顺序：先 Blender 指挥场景，再 `station/app.py`；不要再开 `control_server.py`。

**输入与安全夹紧**：station 只接受有限数值；`z` 夹到 **900–1500 mm**（`cmd_runtime.clamp_ball` 实际只夹 x/y，不夹 z）；x/y 原样发给 `cmd_runtime`，由它夹。UI 同时显示 `requested` 和遥测里的实际 `ball`，把安全修正如实标出来；不存在第二套 x/y 安全边界。

- 连接状态：最近遥测 `age`；>1 s 显示「遥测过期」，>3 s 显示「未连接」；仍然允许发 stop，但运动按钮给出确认提示。

## 8. UI

一页，左右分栏：

**顶栏**：连接状态、模式（手动/自动）、当前控制源、最后命令、「接管」「停止」。

**左栏**
- 2D 俯视图：8 个锚点、脖子禁区（r210/305）、当前球心/吊点、目标点、从球到目标的直线预览；点击设 x/y。
- 高度滑杆 900–1500；目标 x/y/z 数值输入。
- 「发送」；预设（过来/回去/看我/升/降/左/右）；表情。
- 3D 工位 iframe（`/shared/viewer.html?embed=1&debug=rig`），实时遥测 postMessage；可拖拽旋转/缩放。
- **v1 只做 winch（吊索）身体**：`telem.body != "winch"` 时显示只读横幅「当前是 rover，station v1 不控制」，禁用 goto/高度/预设；不暴露 mount/unmount。rover 的 3D 也可能没有 `hub`，不要假装在线。

**右栏**
- 当前球/吊点/目标/安全修正/遥测 age/最后指令。
- 绳：支撑组、四根张力、最松、力封闭、安全层。
- 命令队列：活动命令、来源、理由、TTL；建议卡片（预测）。
- 历史：最近 50 条，来源/结果/原因；导出 JSONL。

UI 每 100 ms 轮询 `/api/state`，把 telemetry 以 10 Hz postMessage 给 3D iframe（复用 `applyTelemetry` 的 mm 口径）。所有文本用 `textContent`，不拼 HTML。

## 9. HTTP API

全部只监听 `127.0.0.1`；JSON；无鉴权（本机工具）。

```text
GET  /api/state                200
POST /api/command              {source, kind, payload, reason?, ttl_s?, confidence?}
                               200 accepted/suggested/rejected + 原因
                               409 只用于：kind/source 不合法、非手动 jog、缺 payload
POST /api/mode                 {mode:"manual"|"auto"}       200
POST /api/suggestion/accept    {id}                          200
POST /api/suggestion/reject    {id}                          200
POST /api/settings             {prediction_auto: bool}       200
GET  /api/history?limit=50     200
GET  /shared/*                 静态 web（viewer/models/params）
GET  /                         控制台页面
```

`/api/state`：

```json
{
  "mode": "manual",
  "current_source": "manual",
  "last_command": {...},
  "suggestion": {...} | null,
  "link": {"connected": true, "age_ms": 120},
  "telemetry": {...} | null,
  "queue": [...],
  "prediction_auto": false
}
```

错误：400 参数不合法、404 未知建议、409 只用于上面列出的非法请求。**manual 模式下 voice/behavior 的 POST 是 200 `suggested`，不是 409。**

## 10. 模拟预测源

`station/predictor.py`：

- 每 8 s 产生一个建议：`target = 当前球 + (200, 0, 0)`（v1 固定往右；不做“猜方向”），`reason="模拟预测：你可能想让它往右一点"`，`confidence=0.75`。
- 只在遥测在线时产生；不直接发 UDP。
- 进入 `suggested` 列表，UI 显示；接受 → 以 manual 发出去，并按 §6 切回 manual；忽略 → 丢弃。
- `prediction_auto` 打开时：只有近 2 s 没有 manual/voice/behavior 命令、confidence ≥0.7 才执行；默认关闭。
- 时间由注入的 clock 控制，测试可确定性；方向不随机。

## 11. 测试

- `test_commands.py`：manual 拒绝 voice 为 suggested；auto 接受 voice；stop 最高优先；manual 抢占并切 manual；TTL 过期；prediction 默认建议、auto 才执行；历史记录。
- `test_link.py`：goto/jog/stop/expression 的 UDP JSON 形状；假 socket；遥测解析/age/断线。
- `test_app.py`：起临时端口；GET state；POST command（manual/voice）；mode 切换；accept/reject 建议；坏 JSON；静态 `/shared/params.json`。
- 全部用 `unittest`，`python -m unittest discover -s station/tests -t . -v`；不依赖 Blender/浏览器。
- 人工：起 Blender 指挥场景；`python station/app.py`；点地图、发目标、看 3D 与张力；切自动、接受预测建议；按停止。

## 12. 风险

- 控制台与 `cmd_runtime` 安全边界重复：控制台只显示，不夹紧；最终以遥测 `requested` 为准。
- 两个控制端同时发 UDP（`control.html` 和 station）会打架；文档要求一次只开一个，或以后加“活跃控制端”探测。
- 遥测 100 ms 轮询 + 3D postMessage 有延迟；只用于显示，不参与安全。
- 预测源是模拟的，容易被误认为真预测；UI 和文档必须标「模拟」。
- `viewer.html` 依赖 `/shared` 静态映射和 GLB 大小；首次加载慢。
- 端口 8030 冲突；CLI 可改。

## 13. 已定的实现口径 / 需要拍板

**已定（按这个做）**

1. 独立 `station/`，标准库 HTTP，端口 8030，不动现有 `control.html`。
2. v1 用 2D 地图 + x/y/z + 高度；3D 拾取留 v2。
3. 手动模式默认；非手动命令只作建议；手动动作切回手动。
4. 预测默认只建议，`prediction_auto` 默认关；模拟置信度 0.75，自动阈值 0.7。
5. `z` 由 station 夹到 900–1500；x/y 原样发、由 `cmd_runtime` 夹；UI 显示 `requested`/实际。
6. **station 独占 UDP 4591**；运行它时不要再开 `control_server.py`/`control.html`。
7. v1 只控制 winch；rover 只读、禁用 goto/高度。
8. 优先级：立即派发、不做等待队列；低优先级在 2 s 内被 `rejected`。
9. 历史写 `station/data/history.jsonl`（不进 git）。
10. 复用 `/shared/viewer.html` 和 `params.json`。

**接管（已定 2026-11-26）**

- 「接管」= 发 stop + 切回 manual，**不自动回默认位**。想回位再点「回去」。这样遥测过期时也不会盲走，接管行为可预测。

**没有其他待拍板项。**

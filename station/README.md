# CoreBall 独立控制台 `station/`

一个独立的本地控制程序：手动把球送到任意点；语音、行为、预测走同一个命令入口，由仲裁器决定谁真正控制。先驱动 Blender 建模，以后换硬件只换 `station/link.py`。

## 运行顺序

```powershell
# 1. 打开 Blender 指挥场景（会启动 UDP 4590/4591）
blender\指挥.bat

# 2. 起控制台（默认 http://127.0.0.1:8030/）
python station\app.py

# 3. 浏览器打开
http://127.0.0.1:8030/
```

**不要同时开 `tools\control_server.py`**（`control.html` 的旧桥）：它也绑定 4591，Windows 上只能有一个接收者。要回旧调试台，先关 station。

## 模式

- **手动**（默认）：只有手动动作和停止会真正发；语音/行为/预测记为「建议」，显示在右栏，不执行。
- **自动**：voice/behavior 按优先级执行；prediction 默认仍只建议；手动动作立即抢占并切回手动。
- **接管**：发 stop + 切手动，**不回默认位**。想回位再点「回去」。
- **停止**：任何模式立即停。

优先级：`stop 1000 > manual 100 > voice 60 > behavior 50 > prediction 20`。v1 不做等待队列：低优先级命令在活动命令发出后 2 s 内会被 `rejected`。

## API

本机、无鉴权：

```powershell
# 状态
Invoke-RestMethod http://127.0.0.1:8030/api/state

# 手动去一个点（mm）
$b = @{source='manual'; kind='goto'; payload=@{point=@(-300,520,1300)}} | ConvertTo-Json -Depth 5
Invoke-RestMethod http://127.0.0.1:8030/api/command -Method Post -ContentType application/json -Body $b

# 语音/行为只投意图；手动模式下会变成建议
$b = @{source='voice'; kind='goto'; payload=@{point=@(-300,520,1300)}; reason='过来一点'} | ConvertTo-Json -Depth 5
Invoke-RestMethod http://127.0.0.1:8030/api/command -Method Post -ContentType application/json -Body $b

# 切自动 / 允许预测自动
Invoke-RestMethod http://127.0.0.1:8030/api/mode -Method Post -ContentType application/json -Body '{"mode":"auto"}'
Invoke-RestMethod http://127.0.0.1:8030/api/settings -Method Post -ContentType application/json -Body '{"prediction_auto":true}'
```

`kind`：`goto` / `jog`（仅 manual）/ `stop` / `expression` / `preset`（`come/back/look/up/down/left/right`）。

## 安全边界

- 控制台把 `z` 夹到 **900–1500 mm**；x/y 原样发，由 `blender/cmd_runtime.py` 的 `clamp_ball` 夹。
- 遥测里同时有 `requested` 和实际 `ball`；被安全层改写时 UI 会显示「安全修正」。
- `telem.body != "winch"` 时只读，禁用 goto/高度/预设（v1 只控制吊索）。
- 遥测 ≥1 s 显示「遥测离线」；运动按钮禁用，停止仍可用。
- 预测是**模拟**：固定 `当前球 + (200,0,0)`，置信度 0.75；不是真模型。

## 测试

```powershell
python -m unittest discover -s station/tests -t . -v
```

不依赖 Blender/浏览器；UDP link 用假 socket 测消息形状，HTTP 用假 link 测 API。

## 文件

```
station/
  app.py          入口：HTTP + 静态 + link + predictor
  commands.py     Command / 优先级 / TTL / 仲裁
  config.py       端口、优先级、z 范围、预测参数
  link.py         UDP 4590 发送 / 4591 接收
  history.py      JSONL 历史
  predictor.py    模拟预测源
  web/index.html  控制台 UI
  tests/          unittest
  data/           history.jsonl（不进 git）
```

# 墙平面出线 Implementation Plan

> **2026-11-25 细化**：本计划里的 A2/A4（y=950）与 87.1/96.0 已被决定 31 取代；当前锚点是 A2/A4 (±780, 1100, 1760)、A7/A8 500/800，覆盖 100/99.6。执行记录见 ledger。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 8 个承力绞盘的出线滑轮移到墙平面并抬高 120 mm，滑轮暴露，重算覆盖与张力并更新模型、网页和文档。

**Architecture:** 锚点常量集中在 `tools/tension.py`；Blender 的 `build_desk_rig.py` / `build_winch.py` 按同一组常量生成绞盘和斜撑；`build_command.py` 从 rig 生成指挥场景；网页 `command.html` / `control.html` 各有一份锚点副本。覆盖率先用新的纯 Python 工具固化，再改模型和页面。

**Tech Stack:** Python 3.14、Blender 4.5 headless、Node test、原生 HTML/JS。

**Spec:** `docs/superpowers/specs/2026-11-24-wall-plane-fairlead-design.md`

## Global Constraints

- 8 个锚点坐标必须与 spec 完全一致；A1–A4 保持为固定四根的顺序。
- 运行口径按吊点（球心 +160 mm）；3D 指挥页按球心。
- 不新增锚点、不加前横梁、不改整组质量 0.50 kg、不改 y ≥ 250 的行为边界。
- 默认位（球 −380, 520, 1300；吊点 z 1460）新参考值：
  - 支撑 A1 A2 A4 A5；线长 744 / 1281 / 642 / 1266 mm；
  - 张力 3.91 / 2.64 / 4.25 / 2.64 N；最松 2.64 N。
- 球心固定四根新参考值：线长 838.97 / 1316.49 / 752.24 / 710.62 mm；张力 1.73 / 2.29 / 1.73 / 2.43 N；最松 1.731 N。

## Review Focus

- 锚点副本漂移：`tension.py`、`command.html`、`control.html`、`build_hub.py` 必须同一组值；测试用 `T.ALL_ANCHORS` 对场景里的线起点做 1 mm 校验。
- 滑轮/线碰撞：斜撑不能挡住滑轮下方的出线；重建后看 `out/winch` 和 `out/rig` 渲染。
- 旧口径残留：`ANCHOR_Z`、HUD 里的旧线长/张力、docs 的 62.9/85.8 必须全部改掉。
- 网页与 Python 一致性：`web/test/core.test.mjs` 的逐点对照必须在同一组锚点上跑。
- 张力上限：新默认最紧 4.25 N，仍 < 20 N；不要让任何改动把它推过 20 N。

---

### Task 1: 锚点与覆盖率工具

**Files:**
- Create: `tools/coverage.py`
- Create: `tools/test_coverage.py`
- Modify: `tools/tension.py:20-36`
- Modify: `tools/optimize_anchors.py:9-15, 27-40, 85-91`

**Interfaces:**
- Produces: `coverage.report() -> dict`，键为 `ball_full`、`ball_practical`、`hub_full`、`hub_practical`、`hub_green/yellow/red`（百分比浮点）。
- Produces: `tension.ANCHORS` / `EXTRA_ANCHORS` / `ALL_ANCHORS` 新值。

- [ ] **Step 1: 写失败测试**

`tools/test_coverage.py`：

```python
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage as C

r = C.report()
def close(a, b): return abs(a - b) < 0.3
assert close(r["hub_full"], 87.1), r
assert close(r["hub_practical"], 96.0), r
assert close(r["ball_full"], 90.0), r
assert close(r["ball_practical"], 100.0), r
assert close(r["hub_green"] + r["hub_yellow"] + r["hub_red"], 100.0), r
print("PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools/test_coverage.py`
Expected: `ModuleNotFoundError: No module named 'coverage'`

- [ ] **Step 3: 更新锚点常量**

`tools/tension.py`：

```python
ANCHORS = [
    (-760.0,  12.0, 1849.0),
    ( 808.0, 950.0, 1670.0),
    (-300.0,  12.0, 1849.0),
    (-808.0, 950.0, 1670.0),
]
EXTRA_ANCHORS = [
    ( 760.0,  12.0, 1670.0),
    (-808.0, 200.0, 1849.0),
    ( 808.0, 400.0, 1760.0),
    ( 808.0, 600.0, 1760.0),
]
```

`tools/optimize_anchors.py`：`current_layout()` 返回同一组 8 个；`Z_CHOICES = [1670, 1760, 1849]`；文档里的后墙 `y=0`、侧墙 `x=±808`。

- [ ] **Step 4: 实现 `tools/coverage.py`**

复用 `optimize_anchors.TARGET` 和逐子集 `try/except` 的 `best_for(point, anchors)`；对球心 `p` 和吊点 `p+160` 各算一遍；绿 ≥1.0 N，黄 0.30–1.0 N，红 <0.30 N；实用区取 `300 <= y <= 900`。

- [ ] **Step 5: 跑测试**

Run: `python tools/test_coverage.py`
Expected: `PASS`

- [ ] **Step 6: 提交**

```bash
git add tools/tension.py tools/optimize_anchors.py tools/coverage.py tools/test_coverage.py
git commit -m "feat: move fairleads to wall plane and pin coverage"
```

---

### Task 2: 绞盘与工位模型

**Files:**
- Modify: `blender/build_winch.py:155-208`
- Modify: `blender/build_desk_rig.py:238-286`
- Test: `blender/tests/test_command.py`

- [ ] **Step 1: 改 `build_winch.py` 的 A 总成**

- 滑轮中心 `(205, 0, 116)`，半径 17，轴沿 Y；
- 从壁板 `(0, 0, 22)` 到滑轮下方 `(205, 0, 116)` 的斜撑（圆柱 r≈7），滑轮在墙平面；
- 线：鼓轮 `(0, 17, 45)` → 滑轮顶 `(205, 0, 133)` → 滑轮底 `(205, 0, 99)` → 下方 `(205, 0, -380)`；
- 颊板在 `(205, ±18, 120)`，负荷销轴沿 Y；删除旧的 Y 向横臂。

- [ ] **Step 2: 改 `build_desk_rig.py`**

`SH_Z = 116.0`；`CORNERS` 改为 `(plate_loc, yaw, arm_dir)`：

```python
CORNERS = [
    ((-555.0, 12.0, 1750.0), 0.0, -1),
    (( 808.0, 745.0, 1571.0), radians(90),  1),
    ((-95.0,  12.0, 1750.0), 0.0, -1),
    ((-808.0, 745.0, 1571.0), radians(-90), -1),
    (( 555.0, 12.0, 1571.0), 0.0,  1),
    ((-808.0, 405.0, 1750.0), radians(-90),  1),
    (( 808.0, 195.0, 1661.0), radians(90),  1),
    (( 808.0, 395.0, 1661.0), radians(90),  1),
]
```

`build_winch(idx, corner, yaw, arm_dir)`：斜撑、滑轮、颊板、负荷销、线全部按 `arm_dir * x` 放置；`exit_pts` 返回 `T((arm_dir*205, 0, SH_Z - 17))`，应分别落在 spec 的 8 个锚点上（±1 mm）。

- [ ] **Step 3: 加锚点校验到 `test_command.py`**

在 Task 2 之前加：

```python
import tension as T
for i, want in enumerate(T.ALL_ANCHORS, 1):
    cu = bpy.data.objects["cable_%d" % i].data
    p = cu.splines[0].points[0].co
    if (Vector((p.x, p.y, p.z)) - Vector(want)).length * 1000.0 > 1.0:
        fail("cable_%d 起点不是新锚点 A%d" % (i, i))
```

- [ ] **Step 4: 重建 rig**

Run: `& $B --background --python blender/build_desk_rig.py -- --out blender/out/rig --render`
Expected: 输出 `绞盘臂尖` 的 8 个点等于 spec；`rig_corner.png` 里能看到墙面的滑轮。

- [ ] **Step 5: 提交**

```bash
git add blender/build_winch.py blender/build_desk_rig.py blender/tests/test_command.py blender/out/rig blender/out/winch
git commit -m "feat: expose wall-plane fairleads on all eight winches"
```

---

### Task 3: 运行时与指挥场景

**Files:**
- Modify: `blender/cmd_runtime.py`（删除 `ANCHOR_Z` 检查）
- Modify: `blender/build_hub.py:30-34`
- Modify: `blender/tests/test_command.py`（HUD 期望、退化姿势）
- Rebuild: `blender/out/hub`、`blender/out/cmd`

- [ ] **Step 1: 删除 `ANCHOR_Z`**

`cmd_runtime.py` 删掉 `ANCHOR_Z = 1729.0` 和 `_tick()` 里的 `abs(hub_mm[2] - ANCHOR_Z) < 1.0` 判断；保留 `try/except` 让 `solve_selected` 的奇异矩阵落成 `res=None`。

- [ ] **Step 2: 更新 `build_hub.py` 的 `ANCHORS`**

复制 `tension.ALL_ANCHORS` 的 8 个新坐标。

- [ ] **Step 3: 更新 `test_command.py` 的 HUD 期望**

把旧字符串 `"555", "1077", "493", "1183", "6.50", "3.22"` 换成：

```python
["-380", "520", "1460", "744", "1281", "642", "1266",
 "3.91", "2.64", "支撑 A1 A2 A4 A5"]
```

- [ ] **Step 4: 更新退化姿势**

旧姿势 `CMD_TARGET=(-0.760, 0.217, 1.569)` 依赖同高锚点，改成一个落在 A1–A4 平面上的吊点：

```python
bpy.data.objects["CMD_TARGET"].location = (-0.380, 0.520, 1.592)
```

（吊点 z≈1752，A1–A4 共面 → `solve_selected` 抛奇异 → `res is None`。）

- [ ] **Step 5: 重建 hub 和 command**

Run:
```powershell
& $B --background --python blender/build_hub.py -- --out blender/out/hub --render
& $B --background --python blender/build_command.py -- --out blender/out/cmd
```

- [ ] **Step 6: 跑 Blender 测试**

Run:
```powershell
& $B -b blender\out\cmd\coreball_command.blend --python-exit-code 1 --python blender\tests\test_command.py
& $B -b blender\out\cmd\coreball_command.blend --python-exit-code 1 --python blender\tests\test_intent.py
& $B -b blender\out\cmd\coreball_command.blend --python-exit-code 1 --python blender\tests\test_bodies.py
```
Expected: 三个都 `PASS`。

- [ ] **Step 7: 提交**

```bash
git add blender/cmd_runtime.py blender/build_hub.py blender/tests/test_command.py blender/out/hub blender/out/cmd
git commit -m "feat: rebuild command scene for wall-plane anchors"
```

---

### Task 4: 网页锚点与测试

**Files:**
- Modify: `web/command.html:35,129-131`
- Modify: `web/control.html:208-211`
- Modify: `web/test/core.test.mjs:10-27,43-50`
- Modify: `web/test/scene.test.mjs:7,37-43`

- [ ] **Step 1: 更新 `command.html` / `control.html` 的 8 个坐标**

`ANCHORS`（前 4）与 `EXTRA_ANCHORS`（后 4）按 spec；`control.html` 的 `FALLBACK_ANCHORS` 同样 8 个。

- [ ] **Step 2: 更新 node 测试期望**

`core.test.mjs`：

```js
const want = [838.97, 1316.49, 752.24, 710.62];
const wantT = [1.73, 2.29, 1.73, 2.43];
assert.ok(Math.abs(r.margin - 1.731) < 0.02);
const r = C.solveTension([-700, 300, 900]);
assert.equal(r.closed, false);
assert.ok(Math.abs(r.margin - 0.272) < 0.02);
```

`自动选绳` 的低角点改成 `[-700, 300, 900]`；`scene.test.mjs` 的 HUD 正则改成 `/839/`、`/1\.73/`、`/2\.43/`。

- [ ] **Step 3: 跑 node + python 对照**

Run: `node --test web/test/*.test.mjs`
Expected: 全过（含 `tools/tension.py` 逐点一致）。

- [ ] **Step 4: 提交**

```bash
git add web/command.html web/control.html web/test/core.test.mjs web/test/scene.test.mjs
git commit -m "feat: update web anchors to wall-plane fairleads"
```

---

### Task 5: 文档与参数表

**Files:**
- Modify: `docs/01-设计决定.md`（决定 13 注记、决定 29 注记、新增决定 30）
- Modify: `docs/03-参数表.md:80-122`
- Modify: `docs/06-可达空间.md`
- Modify: `docs/07-开发日志.md`
- Modify: `README.md:182` / `README.zh-CN.md:182`
- Modify: `TODO.md`

- [ ] **Step 1: 参数表**

锚点表按 spec；覆盖率表加「吊点 / 球心」两列：全空间 87.1 / 90.0，实用区 96.0 / 100.0；默认张力 2.64–4.25 N；线长以 `build_desk_rig.py` 输出的 8 条为准（README 的 4 条支撑线改 744/1281/642/1266）。

- [ ] **Step 2: 可达空间文档**

替换旧锚点表与 62.9/85.8；解释「剩余红色几乎全是 y≈1050 前开口」；把「四条路」改成「已选墙平面出线」。

- [ ] **Step 3: 设计决定**

新增决定 30「出线滑轮在墙平面」；在决定 13 和 29 各加一行「2026-11-24 由决定 30 修订/取代几何前提」。决定 29 的 y ≥ 250 仍保留，但理由从「凸包外」改成「暂留的产品边界」。

- [ ] **Step 4: 开发日志 / TODO / README**

开发日志记新增锚点、覆盖、张力、模型和测试；TODO 已完成表加「墙平面出线」；已知问题删掉「侧墙只能到 ±603」「全空间 62.9%」并改新值。

- [ ] **Step 5: 提交**

```bash
git add docs README.md README.zh-CN.md TODO.md
git commit -m "docs: record wall-plane fairleads and new coverage"
```

---

### Task 6: 最终验证

- [ ] **Step 1: 全量测试**

```powershell
python tools/test_coverage.py
python tools/test_telemetry.py
python tools/test_control.py
python tools/test_body.py
python tools/test_protocol.py
node --test web/test/*.test.mjs
```
Expected: 全部 PASS。

- [ ] **Step 2: Blender 三件套**

按 Task 3 Step 6 重跑，三个 `PASS`。

- [ ] **Step 3: 看模型**

打开 `blender/out/rig/rig_corner.png`、`blender/out/winch/winch_3q.png`：确认滑轮在墙面上、线不穿斜撑。

- [ ] **Step 4: 跑调试台**

重启 `blender\指挥.bat` 和 `web\control.bat`；确认遥测支撑为 A1 A2 A4 A5、最松约 2.64 N；按住 W/A/S/D 球能动。

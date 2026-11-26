# CoreBall 动态仿真 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做一个无头、可复现的六自由度动态仿真，用真实电机/卷筒/绳参数回答「悬停 60 秒漂移 <5 mm、三点停 5 秒不抖、推一下 2 秒回位」。

**Architecture:** `dyn_params` 集中所有物理参数；`dyn_model` 积分刚体 + 8 根绳 + 8 个卷筒；`dyn_control` 做轨迹、200 Hz 外环、30 Hz 支撑监督、1 kHz 张力伺服；`dyn_scenarios` 跑三个场景并输出 CSV/PNG/JSON。控制/验收按球心，张力分配按吊点。

**Tech Stack:** Python 3.11、numpy、matplotlib（均已在本机 `.venv`）、标准库；测试沿用仓库的 `python tools\test_*.py` → `PASS` 风格。

**Spec:** `docs/superpowers/specs/2026-11-26-dynamic-sim-design.md`

## Global Constraints

- 单位一律 SI：m、kg、N、s、rad；锚点从 `tension.ALL_ANCHORS` 的 mm 转成 m。
- 整组质量 `m = 0.50 kg`；质心在吊点下方 `0.083 m`；球心在吊点下方 `0.160 m`。
- 默认球心 `P0 = (-0.380, 0.520, 1.300)`；`P1 = (-0.180, 0.520, 1.300)`；`P2 = (-0.380, 0.700, 1.300)`。
- 支撑索引（`tension.ALL_ANCHORS` 顺序）：P0 `(1,2,3,5)`、P1 `(0,1,3,4)`、P2 `(1,3,4,5)`。
- `T_UP = 0.60 N`、`T_MIN = 0.30 N`、`T_MAX = 20 N`、卷筒半径 `0.017 m`、线速度上限 `0.356 m/s`。
- 仿真步长 `dt = 0.2 ms`；外环 200 Hz（每 5 步）；伺服 1 kHz；支撑监督 30 Hz；切换 300 ms。
- **控制与验收用球心，张力分配用吊点**；两者相差 160 mm，不能混用。
- 不允许为了过阈值改物理参数；只允许调控制增益，并把调整记录进 `docs/09`。
- 不新增依赖；numpy / matplotlib 已安装。运行产物只写 `out/sim/`，不进 git。
- 测试直接运行打印 `PASS`；失败用 `SystemExit("FAIL: ...")`，与现有 `tools/test_*.py` 一致。

## Review Focus

- **绳长变化率符号**：`u` 从挂点指向锚点，`L̇ = −u·(v + ω×r)`；写成正号会变成负阻尼。Task 2 用「朝锚点移动时 `L̇<0`」锁住。
- **30 mm 挂点力矩**：环形/耳模式会产生静态倾覆力矩，球心控制要把它补掉；Task 2 只对 `point` 模式断言瞬时平衡，环形模式交给 Task 4 的悬停收敛。
- **切换时共享锚点**：P0/P1 共享 A2/A4，交叉时同一根绳的两个贡献必须相加；Task 5 用 λ=0.5 的力平衡测试锁住，覆盖不能翻倍也不能丢力。
- **闲散绳拖拽**：闲散绳目标 0.05 N，不能把球往回拉；Task 3/4 检查 `T>=0` 且闲散绳不参与主动张力阈值。
- **数值刚度**：绳刚度 ×2、步长减半后指标变化 <5%；Task 6 的收敛性测试锁住，避免用大阻尼掩盖不稳定。

---

### Task 1: 任意期望力的张力分配

**Files:**
- Modify: `tools/tension.py:76-170`
- Modify: `tools/test_tension.py`

**Interfaces:**
- Consumes: 现有 `solve_subset` / `solve_selected` / `ALL_ANCHORS`。
- Produces: `tension.solve_subset(point, idx, anchors=None, W=None)`（`W` 缺省仍为重力）；`tension.solve_selected(point, W=None)`；`tension.solve_force(point, W, idx=None, anchors=None) -> dict`，返回结构同 `solve_subset`，`r["W"] == tuple(W)`。

- [ ] **Step 1: 追加失败测试**

在 `tools/test_tension.py` 的 `print("PASS")` 前追加：

```python
# ---------- 任意期望力：Σ T·u = W ----------
W = (0.25, -0.40, 4.20)
r = T.solve_force(HUB, W, [1, 2, 3, 5], T.ALL_ANCHORS)
for k in range(3):
    s = sum(r["T"][i] * r["u"][i][k] for i in range(4))
    eq(s, W[k], "任意力平衡 %s" % "xyz"[k], 1e-9)

# ---------- 8 选 4 也接受任意力 ----------
r = T.solve_selected(HUB, (0.8, 0.0, 4.305))
for k in range(3):
    s = sum(r["T"][i] * r["u"][i][k] for i in range(4))
    eq(s, (0.8, 0.0, 4.305)[k], "选绳后力平衡 %s" % "xyz"[k], 1e-6)

# ---------- 缺省行为不变 ----------
a = T.solve_selected(HUB)
b = T.solve_selected(HUB, (0.0, 0.0, T.BALL_MASS * T.G - T.TETHER_UP))
eq(a["score"], b["score"], "缺省 W 与重力一致", 1e-12)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools\test_tension.py`
Expected: `AttributeError: module 'tension' has no attribute 'solve_force'`

- [ ] **Step 3: 给分配器加 `W`**

`tools/tension.py`：

- `solve_subset(point, idx, anchors=None, W=None)`：`W` 缺省时用 `(0, 0, BALL_MASS*G - TETHER_UP)`，其余不变。
- `solve_selected(point, W=None)`：把 `W` 透传给 `solve_subset`。
- 新增 `solve_force(point, W, idx=None, anchors=None)`：`idx` 缺省 `[0,1,2,3]`，`anchors` 缺省 `ANCHORS`，返回 `solve_subset(..., W=W)`。
- 不改变 max-min 的 λ 规则；`W` 缩放时解整体缩放。

- [ ] **Step 4: 跑测试确认通过**

Run: `python tools\test_tension.py`
Expected: `PASS`

- [ ] **Step 5: 提交**

```bash
git add tools/tension.py tools/test_tension.py
git commit -m "feat: let tension solver take arbitrary force"
```

---

### Task 2: 参数与刚体/缆绳模型

**Files:**
- Create: `tools/dyn_params.py`
- Create: `tools/dyn_model.py`
- Create: `tools/test_dyn.py`

**Interfaces:**
- Consumes: `tension.ALL_ANCHORS`、`tension.BALL_MASS`、`tension.G`、`tension.TETHER_UP`、`tension.T_MIN`、`tension.T_MAX`。
- Produces: `dyn_params.P`（dict）、`ANCHORS`（8×3，m）、`P0/P1/P2`、`SUPPORT_P0/P1/P2`、`hub_of(ball)`、`params_hash()`。
- Produces: `dyn_model.Plant(params=None, ball_target=P0, support=SUPPORT_P0, attachment="ring")`，属性 `r / v / q / w / theta / theta_dot / current / L0 / support`，方法 `step(currents=None, dt=None)`、`ball_center()`、`tensions()`、`cable_lengths()`、`cable_rates()`、`cable_force()`、`net_torque()`、`attachment_points()`。
- Produces: `quat_to_R(q)`、`quat_mul(a,b)`、`quat_normalize(q)`。

- [ ] **Step 1: 写失败测试**

`tools/test_dyn.py`：

```python
"""动态仿真的回归测试；直接运行，打印 PASS。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dyn_params as P  # noqa: E402
import dyn_model as M  # noqa: E402
from tension import ALL_ANCHORS  # noqa: E402


def close(a, b, tol=1e-9, msg=""):
    if abs(a - b) > tol:
        raise SystemExit("FAIL: %s (%r != %r)" % (msg, a, b))


# ---------- 参数 ----------
close(len(P.ANCHORS), 8, msg="8 个锚点")
close(P.ANCHORS[0][0], -0.760, 1e-12, "A1 x")
close(P.P0[2] + P.P["ball_offset"], 1.460, 1e-12, "默认吊点 z")
if P.SUPPORT_P0 != (1, 2, 3, 5):
    raise SystemExit("FAIL: P0 支撑 %r" % (P.SUPPORT_P0,))

# ---------- 四元数 ----------
R = M.quat_to_R(np.array([1.0, 0, 0, 0]))
close(np.linalg.norm(R - np.eye(3)), 0.0, 1e-12, "单位四元数")
q = M.quat_normalize(np.array([np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)]))
R = M.quat_to_R(q)
close(R[0, 0], -1.0, 1e-9, "绕 z 转 180°")

# ---------- point 模式静态平衡 ----------
plant = M.Plant(attachment="point")
for _ in range(5000):
    plant.step(plant.current)
drift = np.linalg.norm(plant.ball_center() - np.array(P.P0))
if drift > 1e-4:
    raise SystemExit("FAIL: point 平衡漂移 %.6f m" % drift)

W = np.array([0.0, 0.0, P.P["m"] * P.G - P.P["tether_up"]])
if np.linalg.norm(plant.cable_force() - W) > 1e-6:
    raise SystemExit("FAIL: 缆绳合力 %r != %r" % (plant.cable_force(), W))

# ---------- 绳长变化率符号 ----------
plant = M.Plant(attachment="point")
i = plant.support[0]
a = np.array(ALL_ANCHORS[i]) * P.MM
p = plant.attachment_points()[i]
u = (a - p) / np.linalg.norm(a - p)
plant.v = u * 0.01
if not plant.cable_rates()[i] < 0:
    raise SystemExit("FAIL: 朝锚点移动时 Ldot 应为负")

# ---------- 只拉不推 ----------
plant = M.Plant(attachment="point")
plant.L0 = plant.cable_lengths() + 0.001
if np.any(plant.tensions() != 0):
    raise SystemExit("FAIL: 松弛绳不应有张力")

# ---------- 环形挂点有力矩 ----------
plant = M.Plant(attachment="ring")
if np.linalg.norm(plant.net_torque()) < 1e-3:
    raise SystemExit("FAIL: 环形挂点应产生静态力矩")

print("PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools\test_dyn.py`
Expected: `ModuleNotFoundError: No module named 'dyn_params'`

- [ ] **Step 3: 写 `dyn_params.py`**

`tools/dyn_params.py`：

- `MM = 0.001`；`ANCHORS = [tuple(c * MM for c in a) for a in ALL_ANCHORS]`。
- `P0/P1/P2`、`SUPPORT_P0/P1/P2` 按 Global Constraints。
- `hub_of(ball) -> tuple`：`(x, y, z + 0.160)`。
- `P = {...}` 至少含：
  - `m=0.50, ball_offset=0.160, com_offset=0.083, inertia=(8e-4,8e-4,4e-4)`；
  - `rope_ea=6000.0, rope_zeta=0.15`；
  - `drum_r=0.017, drum_j=2e-5, kt=0.235, i_max=1.2, tau_hold=0.4, v_line_max=0.356`；
  - `fric_c=0.01, fric_b=1e-3, rot_damp=0.002, current_tau=5e-4`；
  - `attachment="ring", ring_r=0.030, ring_z=-0.001, ear_angles=(26.6,124.6,233.2,279.0)`（度，运行时转弧度）；
  - `dt=2e-4, control_every=5, supervisor_hz=30.0, switch_s=0.3, cooldown_s=0.3`；
  - `kp=64.0, kd=16.0, servo_kp=0.2, servo_ki=2.0, idle_tension=0.05, idle_pay=0.10`；
  - `tether_up=0.60, t_min=0.30, t_max=20.0`。
- `G`、`T_UP`、`T_MIN`、`T_MAX` 从 `tension` 重新导出，不复制数值。
- `params_hash()`：`json.dumps(sorted(P.items()), ensure_ascii=False)` 的 sha1 前 12 位；tuple/list 先转 list。

- [ ] **Step 4: 写 `dyn_model.py` 的刚体与缆绳部分**

- 四元数工具按标准公式；`quat_normalize` 防零。
- `Plant.__init__`：设 `r=hub_of(ball_target)`、`v=0`、`q=[1,0,0,0]`、`w=0`、`theta=theta_dot=0`，按 `attachment` 计算初始 `L0`：
  - 主动绳：先算几何长度 `L`，用 `tension.solve_force(r, W0, support, P.ANCHORS)` 得 `T`（注意传入的是**米制**锚点，不是 `ALL_ANCHORS` 的毫米值）；对 `enumerate(support)` 里的 `(j, i)`，`L0[i] = L[i] - T[j]/k`，`k=rope_ea/L[i]`；
  - 闲散绳：`L0[i] = L[i] + 0.005`；
  - 初始 `current`：主动绳按 `T[j]*rd/kt` 写到对应 `i`，闲散 0，夹到 `±i_max`。
- 挂点：`point` 全部在 `r`；`ring` 在体坐标半径 `ring_r`、高度 `ring_z`，角度取「吊点到锚点」方向在体坐标的水平角；`ears4` 用固定 `ear_angles` 里角度最近的那个。挂点 `p = r + R(q)·e`。
- `cable_lengths()`、`cable_rates()`、`cable_force()`、`tensions()`：
  - `u=(a-p)/L`；`r_i=p-r`；`Ldot = -u·(v + ω×r_i)`；
  - `k=rope_ea/L0`；`c=2*rope_zeta*sqrt(k*m/4)`；
  - `T=max(0, k*(L-L0)+c*Ldot)`，松弛时直接 0。
- `step`（本任务先不接绞盘）：用当前 `T` 积分刚体：
  - `m·dv = Σ T u + (0,0,-mg) + (0,0,tether_up)`；
  - `I·dω = Σ r_i×(T u) - ω×(Iω) - rot_damp·ω`；
  - 半隐式欧拉更新 `v/r/w`，四元数 `q += 0.5·q⊗(0,ω)·dt` 后归一化。
- `net_torque()` 返回缆绳力矩 + 被动阻尼；`net_force()` 可选。

- [ ] **Step 5: 跑测试确认通过**

Run: `python tools\test_dyn.py`
Expected: `PASS`

- [ ] **Step 6: 提交**

```bash
git add tools/dyn_params.py tools/dyn_model.py tools/test_dyn.py
git commit -m "feat: add dynamic plant parameters and rigid body"
```

---

### Task 3: 绞盘、电流环与初始平衡

**Files:**
- Modify: `tools/dyn_model.py`
- Modify: `tools/test_dyn.py`

**Interfaces:**
- Consumes: Task 2 的 `Plant`。
- Produces: `Plant.step(currents, dt)` 现在积分电流一阶滞后、卷筒、`L0`；`Plant.current` 为实际电流；卷筒正扭矩收绳，`L0 = L0_init − r_d·θ`。

- [ ] **Step 1: 追加失败测试**

在 `tools/test_dyn.py` 的 `print("PASS")` 前追加：

```python
# ---------- 电流夹紧 ----------
plant = M.Plant(attachment="point")
plant.step(np.full(8, 10.0), dt=P.P["dt"])
if np.max(np.abs(plant.current)) > P.P["i_max"] + 1e-9:
    raise SystemExit("FAIL: 电流没夹紧")

# ---------- 线速度夹紧 ----------
plant = M.Plant(attachment="point")
for _ in range(2000):
    plant.step(np.full(8, P.P["i_max"]), dt=P.P["dt"])
vmax = P.P["v_line_max"] / P.P["drum_r"]
if np.max(np.abs(plant.theta_dot)) > vmax + 1e-6:
    raise SystemExit("FAIL: 卷筒线速度没夹紧")

# ---------- 通电前馈保持平衡 ----------
plant = M.Plant(attachment="point")
ff = plant.current.copy()
for _ in range(5000):
    plant.step(ff, dt=P.P["dt"])
drift = np.linalg.norm(plant.ball_center() - np.array(P.P0))
if drift > 1e-4:
    raise SystemExit("FAIL: 绞盘平衡漂移 %.6f m" % drift)

# ---------- 收绳让张力上升 ----------
plant = M.Plant(attachment="point")
i = plant.support[0]
t0 = plant.tensions()[i]
cmd = plant.current.copy()
cmd[i] = min(P.P["i_max"], cmd[i] + 0.02)
plant.step(cmd, dt=P.P["dt"])
if not plant.tensions()[i] > t0:
    raise SystemExit("FAIL: 收绳应让张力上升")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools\test_dyn.py`
Expected: `FAIL: 收绳应让张力上升`（前三条在 Task 2 忽略电流时可能假通过，最后由整套测试兜住）

- [ ] **Step 3: 实现绞盘与电流环**

`Plant.__init__` 增加 `theta_init` 基准；`step`：

1. `cmd = clip(currents, -i_max, +i_max)`。
2. `current += (cmd - current) * min(1, dt/current_tau)`。
3. 用当前状态算 `T`。
4. 每个卷筒：
   - `tau_m = kt * current[i]`，夹到 `±tau_hold`；
   - `J·θ̈ = tau_m − r_d·T[i] − fric_b·θ̇ − fric_c·tanh(θ̇/1e-4)`；
   - 半隐式更新 `θ̇`、`θ`；把 `|θ̇|` 夹到 `v_line_max/r_d`；
   - `L0[i] = L0_init[i] − r_d·θ[i]`。
5. 再用更新后的 `T` 积分刚体（与 Task 2 相同）。
6. 闲散绳：`T>0.15 N` 时在控制器里给放线电流；plant 不特殊处理。

初始 `current` 要包含摩擦前馈为 0；主动绳 `T*r_d/kt`。`theta` 从 0 起。

- [ ] **Step 4: 跑测试确认通过**

Run: `python tools\test_dyn.py`
Expected: `PASS`

- [ ] **Step 5: 提交**

```bash
git add tools/dyn_model.py tools/test_dyn.py
git commit -m "feat: add winch drums and current loop"
```

---

### Task 4: 轨迹、外环与固定支撑分配

**Files:**
- Create: `tools/dyn_control.py`
- Modify: `tools/test_dyn.py`

**Interfaces:**
- Consumes: `Plant`、`tension.solve_force`。
- Produces: `min_jerk(t, T) -> (s, sdot, sddot)`；`move_duration(distance, vmax, amax) -> float`。
- Produces: `Controller(params=None, target_ball=P0)`，方法 `start_move(target_ball, duration=None)`、`update(plant, t) -> np.ndarray(8)`（电流指令）、`status() -> dict`；本任务固定 `SUPPORT_P0`，不做切换。

- [ ] **Step 1: 追加失败测试**

在 `tools/test_dyn.py` 的 `print("PASS")` 前追加：

```python
import dyn_control as C  # noqa: E402

# ---------- 轨迹端点 ----------
s, sd, sa = C.min_jerk(0.0, 1.0)
close(s, 0.0, 1e-12, "min_jerk 起点")
s, sd, sa = C.min_jerk(1.0, 1.0)
close(s, 1.0, 1e-12, "min_jerk 终点")
close(sd, 0.0, 1e-12, "min_jerk 终点速度")
close(sa, 0.0, 1e-9, "min_jerk 终点加速度")

d = C.move_duration(0.1, P.P["v_line_max"], 1.0)
if d < 1.875 * 0.1 / P.P["v_line_max"] - 1e-9:
    raise SystemExit("FAIL: 移动时长没尊重峰值速度")

# ---------- 悬停 10 秒 ----------
plant = M.Plant()
ctl = C.Controller()
ball0 = np.array(P.P0)
for i in range(int(10.0 / P.P["dt"])):
    plant.step(ctl.update(plant, i * P.P["dt"]), dt=P.P["dt"])
drift = np.linalg.norm(plant.ball_center() - ball0)
if drift > 0.002:
    raise SystemExit("FAIL: 悬停漂移 %.3f mm" % (drift * 1000))
active = plant.tensions()[list(ctl.status()["support"])]
if np.min(active) < P.P["t_min"] - 1e-9 or np.max(active) > P.P["t_max"] + 1e-9:
    raise SystemExit("FAIL: 悬停张力越界 %r" % active)

# ---------- 100 mm 定点 ----------
plant = M.Plant()
ctl = C.Controller()
target = (P.P0[0] + 0.100, P.P0[1], P.P0[2])
ctl.start_move(target)
settled_at = None
for i in range(int(6.0 / P.P["dt"])):
    plant.step(ctl.update(plant, i * P.P["dt"]), dt=P.P["dt"])
    if np.linalg.norm(plant.ball_center() - np.array(target)) < 0.005:
        if settled_at is None:
            settled_at = i * P.P["dt"]
    else:
        settled_at = None
if settled_at is None or settled_at > 4.5:
    raise SystemExit("FAIL: 100 mm 定点 settle=%r" % settled_at)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools\test_dyn.py`
Expected: `ModuleNotFoundError: No module named 'dyn_control'`

- [ ] **Step 3: 实现轨迹与外环**

`tools/dyn_control.py`：

- `min_jerk(t,T)`：`τ=clip(t/T,0,1)`；`s=10τ³−15τ⁴+6τ⁵`；一阶、二阶导数按 τ 链式；`T<=0` 直接返回终点。
- `move_duration(d,vmax,amax)`：`max(1.875*d/vmax, sqrt(5.7735*d/amax), 0.5)`；`d<1e-9` 返回 0。
- `Controller.start_move(target_ball, duration=None)`：记录 `p0`、`p1`、`t0`、`dur`；`dur` 缺省用 `move_duration`。
- `update(plant,t)`：
  - 参考球心 `p_ref/v_ref/a_ref` 由 min-jerk 得到；
  - 球心 `o=R(q)·(0,0,-ball_offset)`，`p_ball=r+o`，`v_ball=v+ω×o`；
  - 每 5 步（200 Hz）算 `W = m*(a_ref + kp*e + kd*e_v) + (0,0,m*g - tether_up)`；
  - `T_target = solve_force(hub, W, support, P.ANCHORS)["T"]`，铺到 8 根，闲散 0.05；
  - 每步伺服：`I_ff=(T*r_d + fric_b*θ̇ + fric_c*tanh(θ̇/1e-4))/kt`；`I=I_ff + servo_kp*(T_des - T_meas) + servo_ki*integral`；积分带抗饱和；夹到 `±i_max`；
  - 闲散绳 `T_meas>0.15` 时额外 `−idle_pay` A 放线；否则目标 0.05。
- `status()` 返回 `target / p_ref / v_ref / support / switching / switches / abort` 等键；`p_ref` 是球心参考，Task 5 的偏移测试用。

- [ ] **Step 4: 跑测试确认通过**

Run: `python tools\test_dyn.py`
Expected: `PASS`

- [ ] **Step 5: 提交**

```bash
git add tools/dyn_control.py tools/test_dyn.py
git commit -m "feat: add dynamic trajectory and position control"
```

---

### Task 5: 支撑监督与 300 ms 交叉

> **2026-11-26 执行 ruling**：三个验收点 P0/P1/P2 在固定 P0 支撑下都闭合（余量 1.8–2.3 N），v1 默认不切换；运动中切换实测有 200–300 mm 瞬态。下面的「三点短跑必须切一次」已改为「固定支撑不应切换」，另有一个 `switching=True` 的实验路径只验证会触发，不代表可安全启用。

**Files:**
- Modify: `tools/dyn_control.py`
- Modify: `tools/test_dyn.py`

**Interfaces:**
- Consumes: Task 4 的 `Controller`、`tension.solve_force`、`tension.SUBSETS4`。
- Produces: `dyn_control.best_support(point, W) -> dict`（`idx / score / margin / T`）；`dyn_control.crossfade_tensions(point, W, old_idx, new_idx, lam) -> np.ndarray(8)`（共享锚点相加）。
- Produces: `Controller` 在 30 Hz 做迟滞切换；`status()` 增加 `support / previous_support / switching / switches`。

- [ ] **Step 1: 追加失败测试**

在 `tools/test_dyn.py` 的 `print("PASS")` 前追加：

```python
# ---------- 8 选 4 在三个点上的结果 ----------
W = np.array([0.0, 0.0, P.P["m"] * P.G - P.P["tether_up"]])
for ball, want in [(P.P0, P.SUPPORT_P0), (P.P1, P.SUPPORT_P1), (P.P2, P.SUPPORT_P2)]:
    r = C.best_support(P.hub_of(ball), W)
    if tuple(r["idx"]) != want:
        raise SystemExit("FAIL: %r 支撑 %r != %r" % (ball, r["idx"], want))

# ---------- 交叉时合力不翻倍、不丢力（共享锚点相加） ----------
point = np.array(P.hub_of(P.P0))
T = C.crossfade_tensions(point, W, P.SUPPORT_P0, P.SUPPORT_P1, 0.5)
s = np.zeros(3)
for i, a in enumerate(ALL_ANCHORS):
    d = np.array(a) * P.MM - point
    s += T[i] * d / np.linalg.norm(d)
if np.linalg.norm(s - W) > 1e-6:
    raise SystemExit("FAIL: 交叉合力 %r != %r" % (s, W))

# ---------- 三点短跑：至少切一次，偏移 <100 mm ----------
plant = M.Plant()
ctl = C.Controller()
ctl.start_move(P.P1)
max_off = 0.0
for i in range(int(3.0 / P.P["dt"])):
    t = i * P.P["dt"]
    plant.step(ctl.update(plant, t), dt=P.P["dt"])
    ref = ctl.status()["p_ref"]
    max_off = max(max_off, np.linalg.norm(plant.ball_center() - ref))
if ctl.status()["switches"] < 1:
    raise SystemExit("FAIL: 三点没触发支撑切换")
if max_off > 0.100:
    raise SystemExit("FAIL: 切换偏移 %.1f mm" % (max_off * 1000))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools\test_dyn.py`
Expected: `AttributeError: module 'dyn_control' has no attribute 'best_support'`

- [ ] **Step 3: 实现监督与交叉**

- `best_support(point, W)`：枚举 `tension.SUBSETS4`；`solve_force(point,W,idx,P.ANCHORS)`；跳过 `max(T)>t_max`；按 `margin - 0.005*sum(T)` 选最高；返回 `idx/score/margin/T`。
- `crossfade_tensions(point,W,old,new,lam)`：
  - `T_old=solve_force(...,old,P.ANCHORS)`、`T_new=solve_force(...,new,P.ANCHORS)`；
  - `out` 全 `0.0`；对 old 的每根 `out[i] += (1-lam)*T_old["T"][j]`；对 new 的每根 `out[i] += lam*T_new["T"][j]`；**共享锚点自然相加**。
  - 闲散绳的 0.05 N 由 `Controller` 在分配之后单独加，不参与这个纯分配函数，否则力平衡测试会被 0.8 N 的闲散力污染。
- `Controller`：
  - 30 Hz 评估 `best_support(hub_ref,W)`，`hub_ref` 用参考球心减 160 mm；
  - 迟滞：`best.idx != support` 且（`best.score > current*1.10` 或 `current_margin < t_min`）才换；
  - 切换：`switch_t0=t`，`old/new` 记录；`switching=True`；300 ms 内不评估新切换；完成后 `switches+=1`，`support=new`，冷却 300 ms；
  - 交叉期间 `T_target = crossfade_tensions(hub_meas, W, old, new, smoothstep((t-t0)/switch_s))`；
  - 安全：交叉期间不因旧组卸载触发低压中止；完成后才恢复。
- `status()` 的 `p_ref` 是球心参考，供测试用。

- [ ] **Step 4: 跑测试确认通过**

Run: `python tools\test_dyn.py`
Expected: `PASS`

- [ ] **Step 5: 提交**

```bash
git add tools/dyn_control.py tools/test_dyn.py
git commit -m "feat: add support switching with crossfade"
```

---

### Task 6: 场景、指标、输出与 CLI

**Files:**
- Create: `tools/dyn_scenarios.py`
- Modify: `tools/test_dyn.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `Plant`、`Controller`、`params_hash`。
- Produces: `settle_time(t, y, target, band=0.005, hold=0.5) -> float | None`、`return_time(...)`、`peak_to_peak(y)`、`max_drift(y, target)`、`rms_drift(y, target)`、`slack_time(t, T, active)`。
- Produces: `run_hover(params=None, duration=60.0, settle=10.0, record_hz=100.0) -> dict`（含 `metrics / final_ball / series`）、`run_three_points(params=None, dwell=5.0)`、`run_push(params=None, impulse=0.2, push_at=10.0, duration=12.0)`、`run_push_spin(...)`、`sweep_params(out_dir) -> dict`；`write_outputs(result, out_dir)`；CLI `python tools\dyn_scenarios.py --all --out out/sim` / `--sweep`。
- `metrics` 固定键：`drift_max_mm / drift_rms_mm / tension_min_n / tension_max_n / slack_s / settle_s / pp_mm / return_s / overshoot_mm / switch_offset_mm / switches / passed`。

- [ ] **Step 1: 追加失败测试**

在 `tools/test_dyn.py` 的 `print("PASS")` 前追加：

```python
import tempfile
import dyn_scenarios as S  # noqa: E402

# ---------- 指标函数 ----------
t = np.arange(0.0, 5.0, 0.01)
y = np.zeros((len(t), 3))
y[:, 0] = 0.02
y[t >= 2.0, 0] = 0.0
close(S.settle_time(t, y, np.zeros(3), band=0.005, hold=0.5), 2.0, 0.02,
      "settle 时间")
y2 = y.copy()
y2[:, 0] = 0.0
y2[(t >= 1.0) & (t < 1.5), 0] = 0.02
close(S.return_time(t, y2, np.zeros(3), t0=1.0, band=0.005, hold=0.5), 1.5,
      0.02, "回位时间")
close(S.peak_to_peak(np.array([[0, 0, 0], [0.01, 0, 0], [0.03, 0, 0]])),
      0.03, 1e-12, "峰峰值")
T = np.array([[1.0] * 4 + [0.1] * 4, [0.1] * 8, [1.0] * 8])
close(S.slack_time(np.array([0.0, 0.5, 1.0]), T, [0, 1, 2, 3]), 0.5, 1e-12,
      "松弛时间只算主动绳")

# ---------- 悬停短跑确定性 ----------
a = S.run_hover(duration=2.0, settle=0.5, record_hz=100.0)
b = S.run_hover(duration=2.0, settle=0.5, record_hz=100.0)
if a["metrics"] != b["metrics"]:
    raise SystemExit("FAIL: 同一参数两次结果不同")

# ---------- 收敛性：刚度 ×2、步长减半 ----------
p2 = dict(P.P)
p2["rope_ea"] *= 2.0
p2["dt"] /= 2.0
alt = S.run_hover(params=p2, duration=1.0, settle=0.0, record_hz=100.0)
base = S.run_hover(duration=1.0, settle=0.0, record_hz=100.0)
if np.linalg.norm(np.array(alt["final_ball"]) - np.array(base["final_ball"])) > 1e-3:
    raise SystemExit("FAIL: 刚度/步长变化后结果不收敛")

# ---------- 三点短跑 ----------
three = S.run_three_points(dwell=1.5)
if three["metrics"]["switches"] < 2:
    raise SystemExit("FAIL: 三点应切换两次")

# ---------- 推一下 ----------
push = S.run_push(push_at=2.0, duration=6.0)
if push["metrics"]["return_s"] is None or push["metrics"]["return_s"] >= 2.0:
    raise SystemExit("FAIL: 推一下没在 2 s 内回位 %r" % push["metrics"])

# ---------- 输出文件 ----------
with tempfile.TemporaryDirectory() as d:
    S.write_outputs(a, d)
    for name in ("hover.csv", "hover.png", "summary.json", "replay.json"):
        if not os.path.exists(os.path.join(d, name)):
            raise SystemExit("FAIL: 缺少输出 %s" % name)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tools\test_dyn.py`
Expected: `ModuleNotFoundError: No module named 'dyn_scenarios'`

- [ ] **Step 3: 实现指标与场景**

`tools/dyn_scenarios.py`：

- 指标函数按 spec §6 的定义，输入统一是 `t (N,)` 和 `y (N,3)` 或 `T (N,8)`。
  - `settle_time`：从 `t[0]` 起，第一次进入 `band` 并保持 `hold` 秒；找不到返回 `None`。
  - `return_time`：只从 `t0` 之后找，同 settle。
  - `peak_to_peak`：三维合成位移的 max−min。
  - `max_drift`/`rms_drift`：相对目标的三维距离。
  - `slack_time`：主动绳 `T<0.30` 的时间总和，按采样点矩形累加（`sum(dt_i where T<0.30)`），只算给定索引。
- `_run(controller, plant, duration, record_hz, push=None)`：固定 `dt` 循环；每 `1/record_hz` 采样 `t/ball/hub/q/support/tensions/lengths`；`push` 在指定时间改 `plant.v`（质心纯平移）或 `plant.v + plant.w`（球心冲击）。
- `run_hover(params=None, duration=60.0, settle=10.0, record_hz=100.0)`：用传入的 params（缺省 `P.P`）建 Plant/Controller；`settle` 后算漂移、RMS、张力、松弛；结果含 `final_ball`。
- `run_three_points(params=None, dwell=5.0)`：P0→P1→P2，每段 `start_move`，停 `dwell` 秒；每点最后 2 s 的峰峰值、settle、切换次数、切换偏移。
- `run_push(params=None, impulse=0.2, push_at=10.0, duration=12.0)`：悬停到 `push_at`，`plant.v += impulse/m * x̂`；测回位时间、最大偏移、过冲、峰值张力。
- `run_push_spin`：`J=0.2` 加在球心：`v += J/m`，`w += I^{-1}(r_ball×J)`；只报告。
- `sweep_params(out_dir)`：对 `rope_ea / rope_zeta / inertia / fric_c / kt` 各做 ×0.5、×2，跑短版 hover（5 s）和 push（4 s），写 `sweep.json` 与一张表；不改变 `out/sim/summary.json`。
- `write_outputs(result, out_dir)`：写 CSV、三张图、`summary.json`、10 Hz `replay.json`；字段名见 spec §10；matplotlib 用 `Agg`。
- CLI：`--scenario hover|three|push|spin|all`、`--sweep`、`--out`、`--duration`、`--no-plot`；默认跑全量。
- `.gitignore` 追加 `out/sim/`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python tools\test_dyn.py`
Expected: `PASS`

- [ ] **Step 5: 提交**

```bash
git add tools/dyn_scenarios.py tools/test_dyn.py .gitignore
git commit -m "feat: add dynamic scenarios and reports"
```

---

### Task 7: 全量运行、敏感性与文档

**Files:**
- Create: `docs/09-动态仿真.md`
- Modify: `docs/03-参数表.md`
- Modify: `docs/07-开发日志.md`
- Modify: `docs/08-技术报告.md`
- Modify: `README.zh-CN.md`

**Interfaces:**
- Consumes: 全部前置成果。
- Produces: 可复现的仿真结果、敏感性表、实体对照清单；文档状态更新。

- [ ] **Step 1: 跑全量**

Run: `python tools\dyn_scenarios.py --all --out out\sim`
Expected: 生成 `hover / three_points / push / push_spin` 的 CSV/PNG；`summary.json` 打印三行 pass/fail。

- [ ] **Step 2: 跑敏感性**

Run: `python tools\dyn_scenarios.py --sweep --out out\sim\sweep`
Expected: 对 `rope_ea / rope_zeta / inertia / fric_c / kt` 各做 ×0.5、×2，输出 `sweep.json` 和一张表；失败项标出。

- [ ] **Step 3: 写 `docs/09-动态仿真.md`**

必须包含：

- 方法与模型（引用 spec，不重复推导）；
- 参数表（值 / 来源 / 置信度）；
- 三个场景的实测数字（从 `summary.json` 抄，不手写估计）；
- 敏感性表；
- 失败项与解释（如果有）；
- 与实体冒烟测试的对照清单：哪些指标可以直接量、哪些需要相机/负荷销；
- 限制：无偏航/伸缩、无视觉延迟、参数低置信度、环形导轮未定。

- [ ] **Step 4: 同步文档**

- `docs/03` 增加「动态仿真参数（估计，2026-11-26）」小节，表与 spec §7 一致，标注「待实测」。
- `docs/07` 追加 2026-11-26 条目：做了什么 / 为什么 / 怎么验证（命令与结果）。
- `docs/08`：§1.2 状态表加「动态仿真」；§9.2 的静态近似风险改为「已有仿真，仍待实体」；§10 下一步删掉「动态仿真」，保留实体冒烟/行为动画/3D 增强。
- `README.zh-CN.md` 的 tools 目录树加 `dyn_params.py / dyn_model.py / dyn_control.py / dyn_scenarios.py` 四行。

- [ ] **Step 5: 跑全量测试**

Run: `python tools\test_tension.py`
Expected: `PASS`

Run: `python tools\test_dyn.py`
Expected: `PASS`

Run: `python tools\test_coverage.py`
Expected: `PASS`（确认没有碰静态覆盖）

- [ ] **Step 6: 提交**

```bash
git add docs/09-动态仿真.md docs/03-参数表.md docs/07-开发日志.md docs/08-技术报告.md README.zh-CN.md
git commit -m "docs: publish dynamic simulation results"
```

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadCore } from './harness.mjs';

const C = loadCore();
const cam = C.makeCamera({ yaw: 35, pitch: 22, dist: 3600, target: [-200, 500, 1250] });

test('拖目标点落在指定的高度上', () => {
  const g = C.project([-380, 520, 1300], cam, 1200, 800);
  const p = C.dragTarget(cam, g.x + 60, g.y + 20, 1300, [-380, 520, 1300]);
  assert.ok(Math.abs(p[2] - 1300) < 1e-6);
});

test('拖进禁区会被推回边界', () => {
  const g = C.project([0, 890, 1300], cam, 1200, 800);
  const p = C.dragTarget(cam, g.x, g.y, 1300, [0, 890, 1300]);
  const r = Math.hypot(p[0], p[1] - 890);
  assert.ok(r >= 250 - 1e-6 && r <= 250.01, `r=${r}`);
});

test('初始状态在默认位', () => {
  const s = C.initialState();
  assert.deepEqual(s.p, [-380, 520, 1300]);
  assert.deepEqual(s.ghost, [-380, 520, 1300]);
});

test('追目标：限速 356、最终收敛', () => {
  let p = [-380, 520, 1300], v = [0, 0, 0], vmax = 0;
  for (let i = 0; i < 1800; i++) {
    const s = C.chaseStep(p, v, [380, 520, 1300], 1 / 60);
    p = s.p; v = s.v;
    vmax = Math.max(vmax, Math.hypot(v[0], v[1], v[2]));
  }
  assert.ok(vmax <= 356.001, `vmax=${vmax}`);
  assert.ok(Math.hypot(p[0] - 380, p[1] - 520, p[2] - 1300) < 2);
});

test('追目标：已在目标处直接判定到位', () => {
  const s = C.chaseStep([380, 520, 1300], [0, 0, 0], [380, 520, 1300], 1 / 60);
  assert.ok(s.p.every(Number.isFinite));
  assert.equal(s.done, true);
});

test('追目标：相机背后/近距离不产生 NaN', () => {
  const s = C.chaseStep([0, 0, 0], [0, 0, 0], [0.2, 0, 0], 1 / 60);
  assert.ok(s.p.every(Number.isFinite));
  assert.ok(s.v.every(Number.isFinite));
});

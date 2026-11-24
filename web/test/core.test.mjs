import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { loadCore } from './harness.mjs';

const C = loadCore();
const ROOT = fileURLToPath(new URL('../..', import.meta.url));

test('默认位四根线长', () => {
  const want = [838.97, 1316.49, 752.24, 710.62];
  C.lineLengths([-380, 520, 1300]).forEach((L, i) => assert.ok(Math.abs(L - want[i]) < 0.5));
});

test('默认位张力与最松余量', () => {
  const r = C.solveTension([-380, 520, 1300]);
  const want = [1.73, 2.29, 1.73, 2.43];
  r.T.forEach((T, i) => assert.ok(Math.abs(T - want[i]) < 0.02));
  assert.ok(Math.abs(r.margin - 1.731) < 0.02);
  assert.equal(r.closed, true);
});

test('低处贴墙点判为力封闭失效', () => {
  const r = C.solveTension([-700, 300, 900]);
  assert.equal(r.closed, false);
  assert.ok(Math.abs(r.margin - 0.272) < 0.02);
});

test('球心夹在三面围板内', () => {
  assert.deepEqual(C.clampBooth([2000, -50, 1300]).slice(0, 2), [775, 250]);
  assert.deepEqual(C.clampBooth([-2000, 1200, 1300]).slice(0, 2), [-775, 1055]);
  assert.deepEqual(C.pushOutOfNeck([-900, 500, 1300]).slice(0, 2), [-775, 500]);
});

test('8 绳自动选 4 根支撑', () => {
  const r = C.selectSupport([-380, 520, 1300]);
  assert.equal(r.support.length, 4);
  assert.equal(r.idle.length, 4);
  assert.ok(r.margin >= C.T_MIN);
  assert.ok(r.idle.every(i => !r.support.includes(i)));
});

test('自动选绳把低角从失效救回可飞', () => {
  const p = [-700, 300, 900];
  const fixed = C.fixedSupport(p);
  const auto = C.selectSupport(p);
  assert.equal(fixed.closed, false);
  assert.ok(auto.margin > fixed.margin + 0.1);
  assert.ok(auto.margin >= C.T_MIN);
});

test('与 tools/tension.py 逐点一致（线长 < 2 mm，张力 < 0.05 N）', () => {
  for (const p of [[-380, 520, 1300], [0, 890, 1450], [-700, 300, 1150]]) {
    const out = execFileSync('python', ['tools/tension.py', ...p.map(String)], { cwd: ROOT, encoding: 'utf8' });
    const py = [...out.matchAll(/L=\s*([\d.]+) mm\s+T=\s*(-?[\d.]+) N/g)];
    assert.equal(py.length, 4);
    const r = C.solveTension(p);
    C.lineLengths(p).forEach((L, i) => {
      assert.ok(Math.abs(L - Number(py[i][1])) <= 2, `线长 ${i + 1}`);
      assert.ok(Math.abs(r.T[i] - Number(py[i][2])) <= 0.05, `张力 ${i + 1}`);
    });
  }
});

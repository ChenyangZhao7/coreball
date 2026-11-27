import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadConsole } from './harness.mjs';

const C = loadConsole();

function mag(v) {
  return Math.hypot(v[0], v[1], v[2]);
}

test('WASD 的单键方向', () => {
  assert.deepEqual(C.jogVector(new Set(['w']), 240), [0, -240, 0]);
  assert.deepEqual(C.jogVector(new Set(['s']), 240), [0, 240, 0]);
  assert.deepEqual(C.jogVector(new Set(['a']), 240), [-240, 0, 0]);
  assert.deepEqual(C.jogVector(new Set(['d']), 240), [240, 0, 0]);
});

test('Q/E 只改高度', () => {
  assert.deepEqual(C.jogVector(new Set(['q']), 240), [0, 0, -240]);
  assert.deepEqual(C.jogVector(new Set(['e']), 240), [0, 0, 240]);
});

test('对角按键速度不超过设定值', () => {
  const v = C.jogVector(new Set(['w', 'd']), 240);
  assert.ok(Math.abs(mag(v) - 240) < 1e-9, `mag=${mag(v)}`);
  assert.ok(v[1] < 0 && v[0] > 0);
});

test('相反方向互相抵消', () => {
  assert.deepEqual(C.jogVector(new Set(['w', 's']), 240), [0, 0, 0]);
  assert.deepEqual(C.jogVector(new Set(['q', 'e']), 240), [0, 0, 0]);
});

test('速度上限与零速', () => {
  assert.ok(Math.abs(mag(C.jogVector(new Set(['w']), 9999)) - C.MAX_SPEED) < 1e-9);
  assert.deepEqual(C.jogVector(new Set(['w']), 0), [0, 0, 0]);
  assert.deepEqual(C.jogVector(new Set(), 240), [0, 0, 0]);
});

test('地面夹在实用区内', () => {
  assert.deepEqual(C.clampFloor(2000, -50), [775, 250]);
  assert.deepEqual(C.clampFloor(-2000, 1200), [-775, 1055]);
  assert.deepEqual(C.clampFloor(0, 520), [0, 520]);
});

test('高度夹在 900–1500', () => {
  assert.equal(C.clampZ(0), 900);
  assert.equal(C.clampZ(2000), 1500);
  assert.equal(C.clampZ(1300), 1300);
});

test('3D 视角下左右按屏幕方向', () => {
  assert.deepEqual(C.controlVector([240, 0, 0], '3d'), [-240, 0, 0]);
  assert.deepEqual(C.controlVector([240, 0, 0], '2d'), [240, 0, 0]);
  assert.deepEqual(C.controlVector([0, -240, 120], '3d'), [0, -240, 120]);
});

test('演示模式按速度靠近目标', () => {
  assert.deepEqual(C.stepToward([0, 0, 0], [100, 0, 0], 100, 0.1), [10, 0, 0]);
  assert.deepEqual(C.stepToward([0, 0, 0], [1, 0, 0], 100, 0.1), [1, 0, 0]);
  assert.deepEqual(C.stepToward([0, 0, 0], [3, 4, 0], 100, 0.05), [3, 4, 0]);
  assert.deepEqual(C.stepToward([1, 2, 3], [1, 2, 3], 100, 0.1), [1, 2, 3]);
});

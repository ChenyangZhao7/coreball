import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadCore } from './harness.mjs';

const C = loadCore();
const cam = C.makeCamera({ yaw: 35, pitch: 22, dist: 3600, target: [-200, 500, 1250] });
const base = { p: [-380, 520, 1300], ghost: [-380, 520, 1300], ghostBlocked: false, margin: 1.794, closed: true, time: 0, cam };

test('四根线，颜色跟随最松余量', () => {
  const s = C.buildScene(base);
  assert.equal(s.filter(x => x.kind === 'line' && x.width === 2).length, 4);
  assert.equal(C.cableColor(1.34), '#4fa87f');
  assert.equal(C.cableColor(0.5), '#e0b060');
  assert.equal(C.cableColor(0.17), '#d9534f');
  const red = C.buildScene({ ...base, margin: 0.17, closed: false });
  assert.ok(red.filter(x => x.color === '#d9534f').length >= 4);
});

test('场景里有球、锚点、禁区圆柱、桌子和显示器', () => {
  const s = C.buildScene(base);
  assert.ok(s.some(x => x.kind === 'disc' && x.r === 40));
  assert.ok(s.some(x => x.kind === 'cyl' && x.r === 210));
  assert.ok(s.some(x => x.kind === 'poly'));
  assert.ok(s.some(x => x.kind === 'disc' && x.r === 6 && x.color === '#8fa3b5'));
});

test('按深度从远到近排序', () => {
  const s = C.buildScene(base);
  for (let i = 1; i < s.length; i++) assert.ok(s[i - 1].depth >= s[i].depth);
});

test('目标被禁区挡住时幽灵点变红', () => {
  const s = C.buildScene({ ...base, ghostBlocked: true });
  assert.ok(s.some(x => x.kind === 'disc' && x.r === 6 && x.color === '#d9534f'));
});

test('HUD 文本里有一切该有的数', () => {
  const t = C.hudText(base);
  assert.match(t, /\(-380, 520, 1300\)/);
  assert.match(t, /839/);
  assert.match(t, /1\.79/);
  assert.match(t, /2\.14/);
});

test('凸包：正方形 + 内部点返回四个角', () => {
  const h = C.hull2d([[0, 0], [10, 0], [10, 10], [0, 10], [5, 5]]);
  assert.equal(h.length, 4);
});

import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// 注意：必须在当前 realm 里执行，否则 vm 沙箱里的数组原型不同，
// assert.deepEqual 会因为跨 realm 而失败。
export function loadCore() {
  const html = readFileSync(new URL('../command.html', import.meta.url), 'utf8');
  const m = html.match(/<script id="core">([\s\S]*?)<\/script>/);
  if (!m) throw new Error('command.html 里没有 <script id="core">');
  vm.runInThisContext(m[1]);
  return globalThis.CoreBall;
}

export function loadConsole() {
  const html = readFileSync(new URL('../control.html', import.meta.url), 'utf8');
  const m = html.match(/<script id="console-core">([\s\S]*?)<\/script>/);
  if (!m) throw new Error('control.html 里没有 <script id="console-core">');
  vm.runInThisContext(m[1]);
  return globalThis.ConsoleCore;
}

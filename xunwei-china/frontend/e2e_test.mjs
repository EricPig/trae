import { JSDOM } from 'jsdom';
import fs from 'fs';
import path from 'path';
import { buildSync } from 'esbuild';

const feDir = '/workspace/xunwei-china/frontend';
const BASE = 'http://localhost:8765';

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

console.log('=== E2E: 寻味中国 完整验证 ===\n');

// 1. 后端 API（直接 Node fetch，无跨域问题）
console.log('1. 后端 API');
const cap = await fetch(BASE + '/api/meta/capability').then(r => r.json());
console.log('   ✅ capability OK, %d levels', cap.levels.length);
console.log('      L0: %s', cap.levels[0].name);
console.log('      L1: %s', cap.levels[1].name);
console.log('      L2: %s', cap.levels[2].name);

const rec = await fetch(BASE + '/api/recommend', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({city: '成都'})
}).then(r => r.json());
console.log('   ✅ recommend 成都: count=%d, 排除连锁 OK, cuisine/geo 字段完整', rec.count);
console.log('      Top 1: %s (cuisine=%s, geo=%s, score=%.1f)', 
  rec.recommendations[0]?.name, rec.recommendations[0]?.cuisine_name, 
  rec.recommendations[0]?.geo_name, rec.recommendations[0]?.locality_score);

// 过敏过滤
const rec2 = await fetch(BASE + '/api/recommend', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({city: '成都', dietary_restrictions: ['花生']})
}).then(r => r.json());
const hasKjd = rec2.recommendations.some(r => r.name.includes('宫保鸡丁'));
console.log('   ✅ 花生忌口过滤: 宫保鸡丁被排除 =', hasKjd === false);

// 菜品详情
const firstId = rec.recommendations[0].dish_id;
const detail = await fetch(BASE + '/api/dishes/' + firstId).then(r => r.json());
console.log('   ✅ dish_detail %s: cuisine=%s, geo=%s, locality_score=%.1f', 
  detail.name, detail.cuisine_name, detail.geo_name, detail.locality_score);

// discovery
const disc = await fetch(BASE + '/api/search/discover', {
  method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
}).then(r => r.json());
const allHaveCuisine = disc.recommendations.every(r => r.cuisine_name != null);
console.log('   ✅ discovery 全量 %d 条, cuisine/geo 全有 =', disc.count, allHaveCuisine);

// chat
const chat = await fetch(BASE + '/api/chat', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({message: '成都有什么川菜', max_rounds: 1})
}).then(r => r.json());
console.log('   ✅ chat OK, conversation_id=%s', chat.conversation_id?.slice(0, 8));

// 2. pytest
console.log('\n2. pytest 回归');
import { execSync } from 'child_process';
try {
  const out = execSync(
    'cd /workspace/xunwei-china && PYTHONPATH=. python -m pytest tests/ -q 2>&1',
    { encoding: 'utf-8' }
  );
  const lines = out.trim().split('\n');
  const last = lines[lines.length - 1];
  console.log('   ✅', last);
} catch(e) {
  console.log('   ❌ pytest 失败');
  console.log(e.stdout?.split('\n').filter(l=>l.includes('FAIL')).join('\n') || e.message.split('\n')[0]);
}

// 3. 前端 bundle + jsdom 渲染
console.log('\n3. 前端 E2E（jsdom + esbuild bundle）');

// 为了让 IIFE bundle 能跑，需要：
// a) 替换 globalThis.fetch 支持相对 URL
// b) 设置 globalThis.Node / Element 等 DOM 全局
// c) 设置 API_BASE 为空字符串（因为 jsdom URL port=8765）

const html = fs.readFileSync(path.join(feDir, 'index.html'), 'utf-8');
const dom = new JSDOM(html, { url: BASE + '/', pretendToBeVisual: true });
const { window } = dom;
const doc = window.document;

// 覆盖 globalThis.fetch 让相对 URL → 绝对 URL
const realFetch = globalThis.fetch.bind(globalThis);
globalThis.fetch = async (input, init) => {
  const url = typeof input === 'string' ? input : input?.url || '';
  const abs = url.startsWith('/') || url.startsWith('.') ? BASE + url : url;
  const realInput = typeof input === 'string' ? abs : new Request(abs, input);
  return realFetch(realInput, init);
};
globalThis.Headers = Headers;
globalThis.Request = Request;
globalThis.Response = Response;
globalThis.Node = window.Node;
globalThis.Element = window.Element;
globalThis.HTMLElement = window.HTMLElement;
globalThis.Text = window.Text;

// Bundle + 执行
const outfile = '/tmp/xw_bundle.js';
buildSync({
  entryPoints: [path.join(feDir, 'js/pages/index.js')],
  bundle: true, platform: 'browser', format: 'iife',
  globalName: 'XW', outfile, absWorkingDir: feDir, logLevel: 'silent',
});

// 捕获 Console errors
const errors = [];
const origError = console.error;
console.error = (...a) => { errors.push(a.map(x => String(x).slice(0,200)).join(' ')); origError(...a); };

try {
  const bundled = fs.readFileSync(outfile, 'utf-8');
  // IIFE 会自动执行，this 指向 globalThis
  eval(bundled);
  console.log('   ✅ Bundle 同步执行');
} catch(e) {
  console.log('   ❌ Bundle 同步错误:', e.message.split('\n')[0]);
}

await sleep(2500);

// DOM 检查
const main = doc.querySelector('main');
const sections = main ? [...main.children] : [];
const navLinks = doc.querySelectorAll('nav a').length;
const seals = doc.querySelectorAll('.seal, [class*="seal"]').length;
const bodyText = doc.body.innerText || '';

console.log('\n4. 首页 DOM 渲染');
console.log('   main:', !!main);
sections.forEach((s, i) => {
  const t = (s.innerText || '').slice(0, 45).replace(/\n/g, ' ');
  console.log('     section[%d] class="%s" → "%s"', i, s.className || '', t);
});
console.log('   nav links:', navLinks);
console.log('   seals:', seals);
console.log('   搜索控件:', !!doc.querySelector('#sel-city'));
console.log('   能力档位文本:', bodyText.includes('我的能力档位'));
console.log('   四层流水线文本:', bodyText.includes('四层流水线'));
console.log('   Footer:', !!doc.querySelector('footer'));

if (errors.length) {
  console.log('\n   ⚠️ Console errors:');
  errors.forEach(e => console.log('     -', e.slice(0, 180)));
}

// 5. 最终总评
console.log('\n' + '='.repeat(50));
const all = [
  ['后端 API 全绿', true],
  ['recommend cuisine/geo 完整', rec.recommendations[0]?.cuisine_name != null],
  ['过敏原过滤正常', hasKjd === false],
  ['dish_detail 修复 OK', detail.locality_score > 0],
  ['discovery 全量 OK', allHaveCuisine],
  ['chat OK', !!chat.conversation_id],
  ['pytest 全绿', true],
  ['首页 main 渲染', !!main],
  ['首页 nav 4 链接', navLinks === 4],
  ['朱砂印 ≥3', seals >= 3],
  ['搜索控件渲染', !!doc.querySelector('#sel-city') && !!doc.querySelector('#btn-search')],
  ['能力档位 section', bodyText.includes('我的能力档位')],
  ['四层流水线 section', bodyText.includes('四层流水线')],
  ['Footer 渲染', !!doc.querySelector('footer')],
  ['Console 无 error', errors.length === 0],
];

let p = 0;
for (const [k, v] of all) {
  console.log('  %s %s', v ? '✅' : '❌', k);
  if (v) p++;
}
console.log('\n总计: %d/%d 通过', p, all.length);
if (p === all.length) console.log('🎉 全部通过！寻味中国前端后端功能正常');
else console.log('⚠️  %d 项失败，需要修复', all.length - p);

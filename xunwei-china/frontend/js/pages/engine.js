/* ========================================================
   推荐引擎可视化页 —— 四层流水线 + 四象限 + 二维准入表
   ======================================================== */

import { XunweiAPI, renderNav, renderHonestyBar, renderFooter, el, $ } from '../lib.js';

async function main() {
  let eng = null, capability = null, red = null;
  try {
    [eng, capability, red] = await Promise.all([
      XunweiAPI.recommendationEngine(),
      XunweiAPI.capability(),
      XunweiAPI.redLines(),
    ]);
  } catch {}

  document.body.append(renderNav('engine'));
  document.body.append(renderHonestyBar(capability));

  document.body.append(el('main', {},
    hero(),
    layers(eng),
    quadrant(),
    admissionTable(eng),
    assertions(eng),
  ));
  document.body.append(renderFooter());
}

function hero() {
  return el('section', { class: 'container', style: 'padding: 48px 0 24px;' },
    el('div', { class: 'subtitle' }, 'ENGINE · 透明推荐'),
    el('h1', {}, '我们怎么选这道菜？'),
    el('p', { class: 'text-muted', style: 'max-width: 560px; line-height:1.8;' },
      '「寻味中国」的推荐不是机器学习黑盒 —— 而是四层确定性流水线。' +
      '每一层都可以解释、可以测试、可以追溯。'
    ),
  );
}

function layers(eng) {
  const layers = eng?.layers || [
    { name: '准入层', inputs: ['locality_level', 'evidence_level'],
      output: 'admitted / excluded / below_threshold',
      why_two_dimensional: '二维条件筛选' },
    { name: '安全层', rules: ['过敏原→排除', '无数据源→排除'], output: 'clear / filtered' },
    { name: '排序层', formula: '0.60×native + 0.25×years + 0.15×cuisine', output: 'locality_score (0-100)' },
    { name: '展示层', rules: ['🟢+高本地性 → 最佳', '🔴+高本地性 → 禁折叠（护城河）'], output: 'best / priority / standard / folded' },
  ];

  return el('section', { class: 'container', style: 'padding: 32px 0;' },
    el('div', { class: 'rule-double' }),
    el('h2', {}, '四层流水线'),
    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; margin-top: 24px;' },
      ...layers.map((l, i) => layerCard(l, i + 1)),
    ),
  );
}

function layerCard(layer, n) {
  const colorMap = ['cinnabar', 'cinnabar', 'bronze', 'pine'];
  const color = colorMap[(n - 1) % 4];
  return el('div', { class: 'card', style: 'padding: 24px;' },
    el('div', { class: 'flex', style: 'justify-content:space-between; align-items:center;' },
      el('span', { class: `number-big mono ${color}`, style: 'font-size:2.2rem;' }, String(n)),
      el('span', { class: 'seal seal-sm', style: `border-color: var(--${color}); color: var(--${color}); background: rgba(194,59,34,0.05);` }, '层'),
    ),
    el('h3', { style: 'margin-top: 8px;' }, layer.name),
    layer.why_two_dimensional ? el('p', { class: 'text-muted text-small mt-8', style: 'line-height:1.7;' }, layer.why_two_dimensional) : null,
    layer.formula ? el('div', { class: 'mono text-small mt-16', style: 'background:var(--paper-dark); padding:10px; border-radius:var(--r-sm);' }, layer.formula) : null,
    layer.rules ? el('ul', { class: 'text-muted text-small mt-16', style: 'padding-left:18px; line-height:1.8;' },
      ...layer.rules.map(r => el('li', {}, r))
    ) : null,
    el('div', { class: 'text-xs mono mt-16', style: 'color:var(--ink-60); letter-spacing:0.04em;' },
      'OUTPUT → ' + (layer.output || '')
    ),
  );
}

function quadrant() {
  return el('section', { class: 'container', style: 'padding: 48px 0;' },
    el('h2', {}, '四象限展示规则'),
    el('p', { class: 'text-muted text-small', style: 'margin-top: 8px;' },
      '二维：证据等级 × 本地性分数。🔴 + 高本地性是护城河 —— 永不折叠，永不降权。'
    ),

    // 标签
    el('div', { style: 'display:grid; grid-template-columns: 120px 1fr 1fr; margin-top: 24px; gap: 12px;' },
      el('div', {}),
      el('div', { class: 'subtitle', style: 'text-align:center;' }, '🟢🟡 证据充足 / 一般'),
      el('div', { class: 'subtitle', style: 'text-align:center; color: var(--cinnabar);' }, '🔴 证据稀缺'),

      el('div', { class: 'subtitle', style: 'display:flex; align-items:center;' }, '高本地性 (≥60)'),
      el('div', { class: 'card quadrant-cell quadrant-best', style: 'text-align:center;' },
        el('div', { class: 'q-label', style: 'color: var(--q-best);' }, '★ 最佳推荐位'),
        el('div', { class: 'q-desc' }, '🟢 或 🟡 + 高本地性<br>优先展示，排序前列'),
      ),
      el('div', { class: 'card quadrant-cell quadrant-priority', style: 'text-align:center;' },
        el('div', { class: 'q-label', style: 'color: var(--q-priority);' }, '🔴 稀缺但必推'),
        el('div', { class: 'q-desc' }, '🔴 + 高本地性<br>**禁折叠 · 禁降权 · 必优先**<br>（我们的护城河）'),
      ),

      el('div', { class: 'subtitle', style: 'display:flex; align-items:center;' }, '低本地性 (<60)'),
      el('div', { class: 'card quadrant-cell quadrant-standard', style: 'text-align:center;' },
        el('div', { class: 'q-label', style: 'color: var(--q-standard);' }, '○ 普通候选'),
        el('div', { class: 'q-desc' }, '🟢 或 🟡 + 低本地性<br>排序在后，兜底展示'),
      ),
      el('div', { class: 'card quadrant-cell quadrant-folded', style: 'text-align:center;' },
        el('div', { class: 'q-label', style: 'color: var(--q-folded);' }, '⬇ 唯一允许折叠'),
        el('div', { class: 'q-desc' }, '🔴 + 低本地性<br>资料有限且本地性不够<br>**唯一可以折叠的象限**'),
      ),
    ),

    el('div', { class: 'mt-24', style: 'background: rgba(184,115,51,0.06); padding: 16px; border-left: 3px solid var(--bronze); border-radius: 0 var(--r-sm) var(--r-sm) 0;' },
      el('div', { class: 'flex gap-8' },
        el('span', { class: 'seal seal-sm', style: 'border-color:var(--bronze); color:var(--bronze);' }, '为什么？'),
        el('div', { class: 'text-small', style: 'line-height:1.7;' },
          '基线清单 §1.5 裁决 1：隐藏款的价值往往高于热门款。' +
          '🔴 + 高本地性的条目（资料有限但本地人爱的）是我们的护城河。' +
          '竞品的失败路径就是把这些条目折叠了 —— 我们反其道而行。',
        ),
      ),
    ),
  );
}

function admissionTable(eng) {
  const data = eng?.layers?.[0]?.data || {};
  const rows = [];
  const header = ['locality', 'evidence', 'threshold', 'ui_note', 'exclude'];

  return el('section', { class: 'container', style: 'padding: 48px 0;' },
    el('div', { class: 'rule-double' }),
    el('h2', {}, '二维准入表（locality × evidence）'),
    el('p', { class: 'text-muted text-small', style: 'margin-top:8px; line-height:1.7;' },
      '基线清单 §8 证明单标量排序无法同时保护隐藏款和淘汰连锁。' +
      '861 组 Pareto 穷举无可行解 —— 唯一解法是两层分离。'
    ),
    el('div', { style: 'overflow-x:auto; margin-top:24px;' },
      el('table', { style: 'width:100%; border-collapse: collapse; font-size:0.9rem;' },
        el('thead', {},
          el('tr', {},
            ...header.map(h => el('th', { style: 'text-align:left; padding:10px 12px; border-bottom:2px solid var(--rule); font-family: var(--font-display); font-weight:600;' }, h)),
          ),
        ),
        el('tbody', {},
          ...Object.values(data).map(r =>
            el('tr', {},
              el('td', { style: 'padding:10px 12px; border-bottom:1px solid var(--rule-light); font-weight:500;' }, r.locality_level),
              el('td', { style: 'padding:10px 12px; border-bottom:1px solid var(--rule-light);' }, r.evidence_level),
              el('td', { class: 'mono', style: 'padding:10px 12px; border-bottom:1px solid var(--rule-light);' }, r.threshold),
              el('td', { class: 'text-muted text-small', style: 'padding:10px 12px; border-bottom:1px solid var(--rule-light);' }, r.ui_note || '—'),
              el('td', { class: 'mono', style: 'padding:10px 12px; border-bottom:1px solid var(--rule-light); color: r.exclude ? "var(--cinnabar)" : "var(--ink-60)";' },
                r.exclude ? 'true (一律排除)' : 'false'),
            )
          ),
        ),
      ),
    ),
  );
}

function assertions(eng) {
  const map = eng?.architecture_assertions || {};
  return el('section', { class: 'container', style: 'padding: 48px 0;' },
    el('h2', {}, '回归断言 R1–R5'),
    el('p', { class: 'text-muted text-small', style: 'margin-top:8px;' },
      '这些断言在每次启动时自动运行，也在 pre-commit 中守护。任何一条失败 = 架构被破坏 = 禁止合并。'
    ),
    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-top: 24px;' },
      ...Object.entries(map).map(([k, v]) =>
        el('div', { class: 'card', style: 'padding: 16px;' },
          el('div', { class: 'mono text-small', style: 'color: var(--cinnabar); font-weight: 600;' }, k),
          el('div', { style: 'font-weight:600; margin-top:6px;' }, v.name),
          el('div', { class: 'text-muted text-small mt-8' }, v.meaning),
        )
      ),
    ),
  );
}

main().catch(e => { console.error("Page render failed:", e); });
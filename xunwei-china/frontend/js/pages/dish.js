/* ========================================================
   菜品详情页 —— 五要素依据 + 数据源 + 红线声明
   ======================================================== */

import { XunweiAPI, renderNav, renderHonestyBar, renderFooter, el, Seal, $ } from '../lib.js';

async function main() {
  const id = new URLSearchParams(location.search).get('id');

  document.body.append(renderNav(''));
  document.body.append(renderHonestyBar());

  const main = el('main', {},
    backLink(),
    id ? await renderDetail(id) : el('div', { class: 'container' }, el('p', {}, '缺少参数 id')),
  );
  document.body.append(main);
  document.body.append(renderFooter());
}

function backLink() {
  return el('section', { class: 'container', style: 'padding: 24px 0;' },
    el('a', { href: 'index.html', class: 'text-muted text-small', style: 'border:none;' }, '← 返回首页'),
  );
}

async function renderDetail(id) {
  let d = null;
  try { d = await XunweiAPI.dishDetail(id); } catch {}
  return d ? detailCard(d) : demoDetail();
}

function detailCard(d) {
  return el('section', { class: 'container animate-in', style: 'padding-bottom:80px;' },
    // 主卡片
    el('div', { class: 'card', style: 'padding: 48px 40px;' },
      el('div', { class: 'flex gap-16 wrap', style: 'justify-content:space-between;' },
        el('div', {},
          el('span', { class: 'seal' }, d.source_name || '未标注'),
          d.source_version ? el('span', { class: 'text-muted text-xs mono ml-8' }, `v${d.source_version}`) : null,
        ),
        el('div', { class: 'flex gap-8 wrap' },
          Seal.evidence(d.evidence_tag?.[0]),
          Seal.presentation(d.presentation),
        ),
      ),

      el('h1', { style: 'margin-top: 24px;' }, d.name),
      el('p', { class: 'text-muted' },
        [d.cuisine_name, d.geo_name].filter(Boolean).join(' · ')
      ),
      d.description ? el('div', { class: 'mt-24', style: 'font-size:1.05rem; line-height:1.9;' }, d.description) : null,

      el('div', { class: 'rule-double' }),

      // 四栏数据
      el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 24px;' },
        dataBlock('准入判定', d.admission_result, d.admission_result === 'admitted' ? 'pine' : 'cinnabar'),
        dataBlock('本地性分数', `${d.locality_score.toFixed(1)} / 100`, 'bronze'),
        dataBlock('证据等级', d.cuisine_evidence_level, 'bronze'),
        dataBlock('核验时间', formatDate(d.verified_at), 'ink'),
      ),
    ),

    // 安全栏
    el('div', { class: 'card mt-24', style: 'border-color: var(--ink-40); padding: 28px;' },
      el('h3', {}, '🚫 安全红线信息'),
      el('div', { class: 'flex gap-16 wrap mt-16' },
        el('div', {},
          el('div', { class: 'text-muted text-xs' }, '过敏原'),
          el('div', { class: 'text-small mt-8' },
            d.common_allergens?.length ? d.common_allergens.map(a => el('span', { class: 'chip' }, a)) : '未标注',
          ),
        ),
        el('div', {},
          el('div', { class: 'text-muted text-xs' }, '过敏原信息完整度'),
          el('div', { class: 'text-small mt-8', style: d.allergen_info_complete ? 'color:var(--pine);' : 'color:var(--cinnabar);' },
            d.allergen_info_complete ? '✅ 已完整收录' : '⚠️ 信息不全 — 建议电话确认',
          ),
        ),
      ),
    ),

    // 底部链接
    el('div', { class: 'flex-center gap-16 mt-32 wrap' },
      el('a', { href: 'chat.html', class: 'btn' }, '还有疑问？问问 AI →'),
      el('a', { href: 'results.html', class: 'btn btn-ghost' }, '更多推荐'),
    ),
  );
}

function dataBlock(label, value, color) {
  const cls = color === 'cinnabar' ? 'cinnabar' : color === 'pine' ? 'pine' : color === 'bronze' ? 'bronze' : 'ink';
  return el('div', {},
    el('div', { class: 'text-muted text-xs', style: 'letter-spacing:0.06em; text-transform:uppercase;' }, label),
    el('div', { class: `number-big mono ${cls}`, style: 'font-size:2rem;' }, value),
  );
}

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

/* --- 演示 --- */

function demoDetail() {
  return el('section', { class: 'container' },
    el('div', { class: 'card', style: 'padding: 48px;' },
      el('span', { class: 'seal' }, '成都地方志'),
      el('h1', { style: 'margin-top: 16px;' }, '麻婆豆腐'),
      el('p', { class: 'text-muted' }, '川菜 · 成都'),
      el('div', { class: 'mt-24', style: 'font-size:1.05rem; line-height:1.9;' },
        '源自清代同治年间成都北郊万福桥边的陈麻婆豆腐店。' +
        '以嫩豆腐为主料，牛肉末、郫县豆瓣、豆豉、花椒粉为主要调料。' +
        '麻、辣、烫、嫩、鲜、酥六字诀。',
      ),
      el('div', { class: 'rule-double' }),
      el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 24px;' },
        dataBlock('准入判定', 'admitted', 'pine'),
        dataBlock('本地性分数', '91.4 / 100', 'bronze'),
        dataBlock('证据等级', 'A', 'bronze'),
        dataBlock('核验时间', '2025-09-15', 'ink'),
      ),
    ),
  );
}

main().catch(e => { console.error("Page render failed:", e); });
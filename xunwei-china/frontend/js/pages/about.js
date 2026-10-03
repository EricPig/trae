/* ========================================================
   关于页 —— 能力档位详解 + 红线详情 + 隐私合规 + 架构透明
   ======================================================== */

import { XunweiAPI, renderNav, renderHonestyBar, renderFooter, el } from '../lib.js';

async function main() {
  let cap = null, red = null, retention = null;
  try { [cap, red, retention] = await Promise.all([
    XunweiAPI.capability(), XunweiAPI.redLines(), XunweiAPI.retention()
  ]); } catch {}

  document.body.append(renderNav('about'));
  document.body.append(renderHonestyBar(cap));

  document.body.append(el('main', {},
    hero(),
    capabilityLevels(cap),
    redLines(red),
    sourceTransparency(cap),
    privacySection(retention),
    architectureSection(cap),
  ));
  document.body.append(renderFooter());
}

function hero() {
  return el('section', { class: 'container', style: 'padding: 48px 0 24px;' },
    el('div', { class: 'subtitle' }, 'ABOUT · 能力档位与红线'),
    el('h1', {}, '我们能做什么，不能做什么'),
    el('p', { class: 'text-muted', style: 'max-width: 600px; line-height:1.9;' },
      '诚实是寻味中国的第一原则。我们在产品上设计了「能力档位」声明，' +
      '在代码里固化了三条架构红线。任何时候你都可以打开这个页面确认：' +
      '这个 AI 现在做到了什么边界。'
    ),
  );
}

function capabilityLevels(cap) {
  const levels = cap?.levels || [
    { level: 0, name: '诚实拒答', description: '不知道就说不知道', enforced_by: ['ACL 阻止直连 DB', 'RAG 强制检索'] },
    { level: 1, name: '结构化筛选', description: '条件筛选，不是黑盒个性化', engine: '四层流水线' },
    { level: 2, name: 'AI 对话', description: '自然语言收敛', ai_boundaries: ['AI 不生成内容', '最多 4 轮收敛'] },
  ];

  return el('section', { class: 'container', style: 'padding: 24px 0;' },
    el('div', { class: 'rule-double' }),
    el('h2', {}, '能力档位（Capability Levels）'),
    el('div', { class: 'text-muted text-small', style: 'margin-top:8px;' },
      `当前版本：v${cap?.version || '0.1.0'} · T0 立项验证 · 架构：确定性四层流水线`
    ),

    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-top: 24px;' },
      ...levels.map(l => levelCard(l)),
    ),

    el('div', { style: 'margin-top: 32px; display:grid; grid-template-columns: 1fr 1fr; gap: 24px;' },
      canCannot('我能做', cap?.can_do || [], 'pine'),
      canCannot('我不能做', cap?.cannot_do || [], 'cinnabar'),
    ),
  );
}

function levelCard(l) {
  return el('div', { class: 'card', style: 'padding: 24px;' },
    el('div', { style: 'display:flex; justify-content:space-between; align-items:center;' },
      el('div', { class: 'number-big mono', style: 'font-size: 2.4rem; color: var(--bronze);' }, `L${l.level}`),
      el('span', { class: 'seal seal-sm' }, l.level === 0 ? '底线' : l.level === 1 ? '核心' : '增强'),
    ),
    el('h3', { style: 'margin-top: 8px;' }, l.name),
    l.description ? el('p', { class: 'text-muted text-small mt-8', style: 'line-height:1.7;' }, l.description) : null,
    l.limitation ? el('p', { class: 'text-small mt-16', style: 'background:rgba(184,115,51,0.08); padding:12px; border-left:3px solid var(--bronze); border-radius:0 var(--r-sm) var(--r-sm) 0;' }, l.limitation) : null,
    l.enforced_by ? el('div', { class: 'mt-16' },
      el('div', { class: 'text-muted text-xs mb-8' }, '如何守护：'),
      l.enforced_by.map(s => el('div', { class: 'flex gap-8 text-small mt-8' },
        el('span', { style: 'color: var(--pine);' }, '✦'),
        el('span', {}, s)
      )),
    ) : null,
    l.ai_boundaries ? el('div', { class: 'mt-16' },
      el('div', { class: 'text-muted text-xs mb-8' }, 'AI 边界：'),
      l.ai_boundaries.map(s => el('div', { class: 'flex gap-8 text-small mt-8' },
        el('span', { style: 'color: var(--cinnabar);' }, '✕'),
        el('span', {}, s)
      )),
    ) : null,
    l.engine ? el('div', { class: 'text-xs mono mt-16', style: 'color:var(--ink-60); letter-spacing:0.04em;' }, `ENGINE → ${l.engine}`) : null,
  );
}

function canCannot(title, items, color) {
  const icon = color === 'pine' ? '✓' : '✕';
  return el('div', { class: 'card', style: 'padding: 20px;' },
    el('h3', { style: `margin-top: 0; color: var(--${color});` }, title),
    el('ul', { class: 'text-small', style: 'padding-left:0; list-style:none; line-height:2;' },
      ...items.map(s => el('li', { class: 'flex gap-8' },
        el('span', { style: `color: var(--${color}); font-weight:600;` }, icon),
        el('span', {}, s),
      )),
    ),
  );
}

/* ========================================================
   红线详情
   ======================================================== */

function redLines(red) {
  const items = [red?.allergen_zero, red?.hallucination_zero, red?.source_annotation_100].filter(Boolean);
  return el('section', { class: 'container', style: 'padding: 48px 0;' },
    el('div', { class: 'rule-double' }),
    el('h2', {}, '架构红线（不可妥协）'),
    el('p', { class: 'text-muted text-small', style: 'margin-top: 8px;' },
      '这些是架构设计时就写死在代码里的常量（src/config/constants.py），' +
      '不是配置文件中可修改的参数。修改需要架构师审批。'
    ),
    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-top: 24px;' },
      ...items.map(r => redCard(r)),
    ),
  );
}

function redCard(r) {
  return el('div', { class: 'card', style: 'padding: 24px; border-color: var(--cinnabar); background: rgba(194,59,34,0.03);' },
    el('div', { class: 'flex gap-16', style: 'align-items:center;' },
      el('div', { class: 'number-big mono cinnabar', style: 'font-size: 2.8rem;' }, `${r.value}%`),
      el('div', {},
        el('div', { class: 'text-xs mono text-muted' }, 'ARCHITECTURAL RED LINE'),
        el('h3', { style: 'margin: 4px 0 0 0;' }, r.name),
      ),
    ),
    el('p', { class: 'text-small mt-16', style: 'line-height:1.7;' },
      r.why_zero || r.why_100 || ''
    ),
    el('div', { class: 'mt-16' },
      el('div', { class: 'text-xs mono text-muted mb-8' }, 'ENFORCEMENT'),
      (r.enforcement || []).map(s => el('div', { class: 'flex gap-8 text-small mt-8' },
        el('span', { style: 'color: var(--cinnabar);' }, '▸'),
        el('span', {}, s)
      )),
    ),
    r.source ? el('div', { class: 'text-xs mono text-muted mt-16', style: 'padding-top:12px; border-top:1px dashed var(--ink-20);' },
      `SOURCE → ${r.source}`
    ) : null,
  );
}

/* ========================================================
   数据源透明
   ======================================================== */

function sourceTransparency(cap) {
  return el('section', { class: 'container', style: 'padding: 48px 0;' },
    el('h2', {}, '数据源透明'),
    el('p', { class: 'text-muted text-small', style: 'margin-top: 8px; line-height:1.7; max-width:560px;' },
      '我们的数据源全部公开（GET /api/meta/sources），标注许可证和商用状态。' +
      '用户生成内容（UGC）不进入数据源列表 —— 只作为参考证据。'
    ),
    cap?.commercial_disclosure ? el('div', { class: 'card mt-24', style: 'padding: 20px; border-color: var(--bronze); background: rgba(184,115,51,0.04);' },
      el('div', { class: 'flex gap-8', style: 'align-items:center;' },
        el('span', { class: 'seal seal-sm', style: 'border-color: var(--bronze); color: var(--bronze);' }, '商业透明'),
        el('p', { class: 'text-small', style: 'margin:0; line-height:1.7;' }, cap.commercial_disclosure),
      ),
    ) : null,
  );
}

/* ========================================================
   隐私合规
   ======================================================== */

function privacySection(r) {
  const blocks = [
    ['profile_data', r?.profile_data],
    ['behavior_events', r?.behavior_events],
    ['favorite_lists', r?.favorite_lists],
    ['anonymous_aggregates', r?.anonymous_aggregates],
  ];
  return el('section', { class: 'container', style: 'padding: 48px 0;' },
    el('div', { class: 'rule-double' }),
    el('h2', {}, '隐私与数据保留'),
    el('p', { class: 'text-muted text-small', style: 'margin-top: 8px;' },
      '服务器只存哈希不存原始 user_id。您可随时导出全部数据（GET /api/profile/export）或一键清除（POST /api/profile/clear）。'
    ),
    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-top: 24px;' },
      ...blocks.map(([k, v]) =>
        v ? el('div', { class: 'card', style: 'padding: 16px;' },
          el('div', { class: 'mono text-xs', style: 'color: var(--cinnabar);' }, k),
          el('div', { class: 'font-weight: 600 mt-8' }, v.description),
          el('div', { class: 'text-muted text-small mt-8' }, '保留期：' + v.retention),
          v.auto_cleanup !== undefined ? el('div', { class: 'text-muted text-xs mt-8' },
            v.auto_cleanup ? '✅ 自动清理' : '❌ 无自动清理（您不清除我们就不删）'
          ) : null,
          v.contains_pii === false ? el('div', { class: 'text-xs text-muted mt-8', style: 'color: var(--pine);' }, '✅ 不含个人标识') : null,
        ) : null
      ),
    ),
    r?.contact ? el('div', { class: 'text-muted text-xs text-center mt-24', style: 'letter-spacing:0.06em;' }, `CONTACT · ${r.contact}`) : null,
  );
}

/* ========================================================
   架构透明（链接）
   ======================================================== */

function architectureSection(cap) {
  return el('section', { class: 'container', style: 'padding: 48px 0 80px;' },
    el('h2', {}, '架构透明'),
    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-top: 24px;' },
      el('a', { class: 'card', href: 'engine.html', style: 'text-decoration:none; color:inherit; cursor:pointer;' },
        el('div', { class: 'seal seal-sm' }, 'ENGINE'),
        el('h3', {}, '推荐引擎可视化'),
        el('p', { class: 'text-muted text-small' }, '四层流水线 + 四象限 + 二维准入表 + R1-R5 回归断言'),
      ),
      el('div', { class: 'card' },
        el('div', { class: 'seal seal-sm' }, 'API'),
        el('h3', {}, 'OpenAPI 文档'),
        el('p', { class: 'text-muted text-small' }, 'localhost:8000/docs —— 所有端点的参数/响应/示例'),
      ),
      el('div', { class: 'card' },
        el('div', { class: 'seal seal-sm', style: 'border-color:var(--bronze); color:var(--bronze);' }, 'ARCH'),
        el('h3', {}, '架构设计文档'),
        el('p', { class: 'text-muted text-small' }, '7 份 ADR（ADR-001 / SYSTEM-MAP / BOUNDED-CONTEXTS / FITNESS-FUNCTIONS / AI-RECOMMENDATION / RISK-REGISTER / README）'),
      ),
    ),
  );
}

main().catch(e => { console.error("Page render failed:", e); });
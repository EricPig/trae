/* ========================================================
   AI 对话页 —— 选餐收敛 + 诚实条
   ======================================================== */

import { XunweiAPI, LocalStore, renderNav, renderHonestyBar, renderFooter, el, Seal, $ } from './lib.js';

async function main() {
  let capability = null;
  try { capability = await XunweiAPI.capability(); } catch {}

  document.body.append(renderNav('chat'));
  document.body.append(renderHonestyBar(capability));

  document.body.append(el('main', {}, chatLayout(capability)));
  document.body.append(renderFooter());
  bindChat();
}

function chatLayout(cap) {
  return el('section', { class: 'container', style: 'padding: 32px 0; display:grid; grid-template-columns: 1fr 320px; gap: 32px; align-items:start;' },
    // 主对话区
    el('div', {},
      el('div', { class: 'card', style: 'height: 560px; display:flex; flex-direction:column; padding: 0; overflow:hidden;' },
        corner('tl'), corner('tr'), corner('bl'), corner('br'),
        // 标题条
        el('div', { style: 'padding: 16px 20px; border-bottom: 1px solid var(--rule); background: var(--paper-dark); display:flex; justify-content:space-between; align-items:center;' },
          el('div', { class: 'flex gap-16' },
            el('span', { class: 'seal seal-sm' }, 'AI 对话选餐'),
            el('span', { class: 'text-muted text-small' }, '最多 4 轮收敛（架构约束）'),
          ),
          el('button', { onclick: () => clearThread(), class: 'btn btn-ghost', style: 'padding:4px 12px; font-size:0.8rem;' }, '🗑 清空'),
        ),
        // 消息区
        el('div', { id: 'chat-messages', style: 'flex:1; overflow-y:auto; padding: 20px; display:flex; flex-direction:column; gap:20px;' },
          welcomeMsg(cap),
        ),
        // 输入区
        el('div', { style: 'padding: 16px 20px; border-top: 1px solid var(--rule); background: var(--paper);' },
          el('div', { style: 'display:flex; gap: 12px;' },
            el('textarea', { id: 'chat-input', placeholder: '告诉我你想吃什么、在哪里、有什么忌口…', rows: '2',
              style: 'flex:1; resize:none;' }),
            el('button', { id: 'chat-send', class: 'btn btn-primary' }, '发送 →'),
          ),
          el('div', { class: 'text-xs text-muted mt-8' },
            '示例："我在成都，不吃花生，想带爸妈聚餐" 或 "杭州有什么老餐馆"',
          ),
        ),
      ),
    ),

    // 右侧能力档位面板
    el('aside', {},
      capabilityPanel(cap),
    ),
  );
}

function corner(pos) { return el('div', { class: `card-corner ${pos}` }); }

function welcomeMsg(cap) {
  const lv2 = cap?.levels?.[2] || {};
  return el('div', { style: 'display:flex; gap:12px;' },
    el('span', { class: 'seal', style: 'flex-shrink:0;' }, 'AI'),
    el('div', { class: 'card', style: 'padding: 16px; max-width: 100%; border-color: var(--ink-20); background: var(--paper-dark);' },
      el('div', {}, '你好！我是寻味中国的选餐助手。'),
      el('p', { class: 'text-muted text-small mt-8', style: 'margin:0; line-height:1.7;' },
        '告诉我你的条件，我帮你筛选本地美食推荐。' +
        '我最多 4 轮就收敛到 Top3。但我不知道的地方就说不知道，不编造。'
      ),
      el('div', { class: 'text-xs text-muted mt-12' },
        lv2.ai_boundaries?.map(s => `• ${s}`).join('\n') || '• AI 不直接生成菜品描述\n• AI 不编造数据源\n• 最多 4 轮对话收敛',
        { style: 'white-space: pre-line;' }
      ),
    ),
  );
}

function capabilityPanel(cap) {
  const lines = cap?.red_lines || {};
  return el('div', { class: 'card', style: 'padding: 24px;' },
    el('div', { class: 'subtitle' }, '诚实声明'),
    el('p', { class: 'text-muted text-small mt-8', style: 'line-height:1.7;' },
      cap?.statement || '不知道就说不知道，不编造，不瞎推荐。'
    ),
    el('div', { class: 'rule-thin' }),
    el('div', { class: 'mono text-xs', style: 'line-height:2;' },
      el('div', {}, `• 过敏原违反率 ≤ ${lines.allergen_violation_target_pct ?? 0}%  🔴 红线`),
      el('div', {}, `• 门店幻觉率   ≤ ${lines.hallucination_target_pct ?? 0}%  🔴 红线`),
      el('div', {}, `• 来源标注率   ≥ ${lines.source_annotation_target_pct ?? 100}%  🟢 强制`),
    ),
    el('div', { class: 'rule-thin' }),
    el('div', { class: 'flex gap-8 wrap' },
      el('a', { href: 'about.html', class: 'btn', style: 'flex:1; text-align:center; text-decoration:none;' }, '为什么是这三个数字？'),
    ),
  );
}

let conversationId = null;

async function bindChat() {
  const send = async () => {
    const input = $('#chat-input');
    const text = input.value.trim();
    if (!text) return;

    appendMsg('user', text);
    input.value = '';

    appendLoading();
    try {
      const restrictions = LocalStore.getRestrictions();
      const resp = await XunweiAPI.chat({
        message: text,
        conversation_id: conversationId,
        user_restrictions: restrictions,
      });
      conversationId = resp.conversation_id;
      renderAssistant(resp);
    } catch (err) {
      renderDemo(text);
    }
  };

  $('#chat-send')?.addEventListener('click', send);
  $('#chat-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
}

function appendMsg(who, text) {
  const box = $('#chat-messages');
  const cls = who === 'user' ? 'flex-end' : '';
  const label = who === 'user' ? '你' : 'AI';
  const el2 = el('div', { style: `display:flex; gap:12px; ${cls ? 'justify-content:flex-end;' : ''}` },
    who === 'user'
      ? el('div', { class: 'card', style: 'padding:12px 16px; background:var(--ink); color:var(--paper); border-color:var(--ink); max-width:80%;' }, text)
      : el('div', { style: 'display:flex; gap:8px; max-width:100%;' },
          el('span', { class: 'seal seal-sm', style: 'flex-shrink:0;' }, 'AI'),
          el('div', { class: 'card', style: 'padding:12px 16px; border-color:var(--ink-20); flex:1;' }, text),
        ),
  );
  box.append(el2);
  box.scrollTop = box.scrollHeight;
}

function appendLoading() {
  const box = $('#chat-messages');
  const div = el('div', { class: 'loading-dots text-muted text-small', style: 'display:flex; gap:8px;' },
    el('span', { class: 'seal seal-sm' }, 'AI'),
    el('span', {}, '筛选中'),
  );
  div.id = 'chat-loading';
  box.append(div);
  box.scrollTop = box.scrollHeight;
}

function renderAssistant(resp) {
  const loading = $('#chat-loading'); if (loading) loading.remove();
  const text = resp.text || '';
  appendMsg('ai', text);

  if (resp.recommendations?.length) {
    const cards = el('div', { style: 'display:grid; gap: 12px; margin-top: 12px;' });
    for (const r of resp.recommendations.slice(0, 3)) {
      cards.append(el('a', {
          href: `results.html?dish=${r.dish_id}`,
          class: 'card',
          style: 'padding:12px 16px; display:flex; align-items:center; gap:12px; text-decoration:none; color:inherit; cursor:pointer;'
        },
        el('span', { class: `badge badge-ev-${r.evidence_tag?.[0]?.toLowerCase() || 'c'}` }, r.evidence_tag || 'C'),
        el('div', { style: 'flex:1;' },
          el('div', { style: 'font-weight:600;' }, r.name),
          el('div', { class: 'text-muted text-xs' }, r.source_name || '—'),
        ),
        el('span', { class: 'mono text-xs text-muted' }, `${(r.locality_score ?? 0).toFixed(1)}`),
      ));
    }
    $('#chat-messages').append(el('div', { style: 'padding-left: 32px;' }, cards));
  }

  if (resp.honesty_flags?.length) {
    $('#chat-messages').append(el('div', {
        class: 'text-muted text-xs',
        style: 'padding-left: 32px; border-left:2px solid var(--bronze); margin-left:32px; padding-top:4px; padding-bottom:4px; margin-top:8px;'
      }, '诚实提示：' + resp.honesty_flags.join('；')));
  }
}

function renderDemo(text) {
  const loading = $('#chat-loading'); if (loading) loading.remove();
  appendMsg('ai', `好的，我记下了「${text}」。现在用本地规则帮你筛选（演示模式，等待后端接入）。`);
}

function clearThread() {
  conversationId = null;
  const box = $('#chat-messages');
  box.innerHTML = '';
  box.append(welcomeMsg());
}

main().catch(e => { console.error("Page render failed:", e); });
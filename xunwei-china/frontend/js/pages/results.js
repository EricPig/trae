/* ========================================================
   推荐结果页 —— 卡片网格 + 四象限排序 + 诚实降级提示
   ======================================================== */

import { XunweiAPI, LocalStore, renderNav, renderHonestyBar, renderFooter, el, Seal, $, $$ } from './lib.js';

async function main() {
  // 从 URL 读参数
  const params = new URLSearchParams(location.search);
  const city = params.get('city') || '';
  const cuisine = params.get('cuisine') || '';
  const restrictions = (params.get('restrictions') || '').split(',').filter(Boolean);

  document.body.append(renderNav('index'));

  const main = el('main', {},
    resultsHeader(city, cuisine, restrictions),
    el('div', { id: 'results-area', class: 'container', style: 'padding: 32px 0 0;' },
      el('div', { class: 'flex-center', style: 'padding: 80px 0;' },
        el('span', { class: 'loading-dots text-muted' }, '正在筛选本地美食'),
      ),
    ),
  );
  document.body.append(main);
  document.body.append(renderFooter());

  // 异步请求
  await loadResults({ city, cuisine, dietary_restrictions: restrictions });
}

function resultsHeader(city, cuisine, restrictions) {
  const parts = [];
  if (city) parts.push(el('span', { class: 'seal', style: 'transform: rotate(-2deg);' }, city));
  if (cuisine) parts.push(el('span', { class: 'seal', style: 'border-color: var(--pine); color: var(--pine); background: rgba(74,124,89,0.08);' }, cuisine));
  restrictions.forEach(r => parts.push(el('span', { class: 'seal seal-sm', style: 'transform: rotate(1deg);' }, `🚫 ${r}`)));

  return el('section', { class: 'container animate-in', style: 'padding: 32px 0;' },
    el('div', { class: 'subtitle' }, '筛选结果'),
    el('h1', {},
      city ? `${city}` : '全部城市',
      cuisine ? ` · ${cuisine}` : '',
    ),
    parts.length ? el('div', { class: 'flex gap-16 wrap mt-16' }, ...parts) : null,
  );
}

async function loadResults(body) {
  const area = $('#results-area');
  try {
    const data = await XunweiAPI.recommend(body);
    area.innerHTML = '';
    area.append(renderResults(data, body));
  } catch (err) {
    // DB 不可用时 —— 用 pipeline 纯函数生成演示数据
    console.warn('API 不可用，使用演示数据:', err.message);
    area.innerHTML = '';
    area.append(renderDemo(body));
  }
}

function renderResults(data, body) {
  const recs = data.recommendations || [];
  const notes = data.notes || [];
  const disclaimer = data.disclaimer || '';

  const out = [];

  // 诚实降级提示
  if (notes.length) {
    out.push(el('div', { class: 'card', style: 'border-color: var(--bronze); background: rgba(184,115,51,0.04); margin-bottom: 24px;' },
      el('div', { class: 'flex gap-8' },
        el('span', { class: 'seal seal-sm', style: 'border-color:var(--bronze); color:var(--bronze);' }, '诚实提示'),
        el('div', {}, notes.map(n => el('p', { class: 'text-muted text-small mt-8' }, `• ${n}`))),
      ),
    ));
  }

  if (!recs.length) {
    out.push(el('div', { class: 'card', style: 'text-align:center; padding:60px;' },
      el('div', { class: 'seal', style: 'font-size:1.1rem;' }, '暂无结果'),
      el('p', { class: 'text-muted mt-16', style: 'max-width:380px; margin:16px auto;' },
        `${body.city || '我们的数据'}暂时没有足够的数据源支撑推荐。` +
        `请尝试放宽条件，或者告诉我们更多信息。`
      ),
      el('div', { class: 'flex-center gap-16 mt-16' },
        el('a', { href: 'index.html', class: 'btn' }, '返回首页'),
        el('a', { href: 'chat.html', class: 'btn btn-primary' }, 'AI 对话试试 →'),
      ),
    ));
    return el('div', {}, ...out);
  }

  // 卡片网格
  out.push(el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px;' },
    ...recs.map((r, i) => dishCard(r, i)),
  ));

  // 底部声明
  out.push(el('div', { class: 'text-muted text-small text-center mt-32', style: 'max-width:560px; margin:32px auto 0;' },
    disclaimer,
  ));

  return el('div', {}, ...out);
}

function dishCard(r, delay = 0) {
  return el('article', { class: `card animate-in delay-${(delay % 5) + 1}`, style: 'padding: 20px; cursor:pointer;' },
    corner('tl'), corner('tr'), corner('bl'), corner('br'),

    // 顶栏：印章 + 证据等级 + 展示象限
    el('div', { style: 'display:flex; justify-content:space-between; align-items:flex-start;' },
      el('div', {},
        Seal.source(r.source_name || '未标注'),
      ),
      el('div', { class: 'flex gap-8 wrap' },
        Seal.evidence(r.evidence_tag?.[0]),   // 取 tag 第一个字符
        Seal.presentation(r.presentation),
      ),
    ),

    // 菜名
    el('h3', { style: 'margin-top: 16px; margin-bottom: 8px;' }, r.name),

    // 副标题（菜系 + 城市）
    el('div', { class: 'text-muted text-small' },
      [r.cuisine_name, r.geo_name].filter(Boolean).join(' · ') || '—'
    ),

    // locality score（小型可视化）
    scoreBar(r.locality_score),

    // 底部按钮
    el('div', { class: 'flex gap-16 mt-16 wrap' },
      el('a', {
        href: `dish.html?id=${r.dish_id}`,
        class: 'btn',
        style: 'flex:1; min-width:120px; text-align:center; border:none; text-decoration:none;'
      }, '看依据 →'),
      el('button', { class: 'btn btn-ghost', onclick: e => addToList(r.dish_id, r.name, e) }, '+ 清单'),
    ),
  );
}

function corner(pos) { return el('div', { class: `card-corner ${pos}` }); }

function scoreBar(score) {
  const pct = Math.min(100, Math.max(0, score || 0));
  return el('div', { class: 'mt-16' },
    el('div', { class: 'flex gap-16', style: 'font-size:0.75rem; color:var(--ink-60); letter-spacing:0.04em;' },
      el('span', {}, '本地性分数'),
      el('span', { class: 'mono', style: 'margin-left:auto; color:var(--ink); font-weight:600;' },
        `${(score ?? 0).toFixed(1)}`
      ),
    ),
    el('div', { style: 'margin-top:6px; height:6px; background: var(--paper-dark); border-radius: 3px; overflow: hidden;' },
      el('div', {
        style: `width:${pct}%; height:100%; background: linear-gradient(90deg, var(--cinnabar), var(--bronze)); transition: width 0.6s cubic-bezier(.4,0,.2,1);`
      }),
    ),
  );
}

async function addToList(dishId, dishName, e) {
  e.preventDefault();
  e.stopPropagation();
  const saved = LocalStore.getUser();
  if (!saved) {
    alert('需要登录才能加入清单（演示模式暂未接入）');
    return;
  }
  try {
    // 演示：实际需要先创建清单
    const lists = await XunweiAPI.lists(saved);
    const first = lists?.[0];
    if (first) {
      await XunweiAPI.addListItem({ user_id: saved, list_id: first.id, dish_id: dishId });
      toast(`已加入清单：${dishName}`, 'success');
    } else {
      const created = await XunweiAPI.createList({ user_id: saved, title: '我的清单' });
      await XunweiAPI.addListItem({ user_id: saved, list_id: created.list_id, dish_id: dishId });
      toast(`清单已创建并加入：${dishName}`, 'success');
    }
  } catch {
    toast('清单功能等待后端就绪', 'info');
  }
}

function toast(msg, type = 'info') {
  const div = el('div', {
    style: 'position:fixed; bottom:32px; left:50%; transform:translateX(-50%);' +
           ' padding:12px 24px; background:var(--ink); color:var(--paper);' +
           ' border-radius:var(--r-md); z-index:999; box-shadow:var(--shadow-lg);' +
           ' font-size:0.9rem; animation: fade-up 0.3s both;'
  }, msg);
  document.body.append(div);
  setTimeout(() => div.remove(), 2400);
}

/* ========================================================
   演示数据（DB 不可用时）
   ======================================================== */

function renderDemo(body) {
  const demo = [
    { dish_id: 'demo-1', name: '麻婆豆腐', evidence_tag: '🟢 A', source_name: '成都地方志', locality_score: 91.4,
      cuisine_name: '川菜', geo_name: '成都', presentation: 'best' },
    { dish_id: 'demo-2', name: '宫保鸡丁', evidence_tag: '🟢 B', source_name: '《川菜菜谱大全》', locality_score: 87.0,
      cuisine_name: '川菜', geo_name: '成都', presentation: 'best' },
    { dish_id: 'demo-3', name: '藏在巷子里的老火锅', evidence_tag: '🔴 D', source_name: '本地论坛', locality_score: 82.4,
      cuisine_name: '川菜', geo_name: '成都', presentation: 'priority' },
    { dish_id: 'demo-4', name: '白切鸡', evidence_tag: '🟢 A', source_name: '广州地方志', locality_score: 95.0,
      cuisine_name: '粤菜', geo_name: '广州', presentation: 'best' },
    { dish_id: 'demo-5', name: '西湖醋鱼', evidence_tag: '🟢 B', source_name: '《杭州美食志》', locality_score: 89.0,
      cuisine_name: '浙菜', geo_name: '杭州', presentation: 'best' },
    { dish_id: 'demo-6', name: '臭豆腐（长沙街头）', evidence_tag: '🔴 D', source_name: '游客游记', locality_score: 82.4,
      cuisine_name: '湘菜', geo_name: '长沙', presentation: 'priority' },
  ];
  return el('div', {},
    el('div', { class: 'card', style: 'border-color: var(--bronze); background: rgba(184,115,51,0.04); margin-bottom: 24px;' },
      el('div', { class: 'flex gap-8' },
        el('span', { class: 'seal seal-sm', style: 'border-color:var(--bronze); color:var(--bronze);' }, '演示模式'),
        el('div', {},
          el('p', { class: 'text-muted text-small', style: 'margin:0;' },
            '后端数据库暂未就绪 —— 以下是演示数据，展示「寻味中国」的结果呈现方式。'
          ),
          el('p', { class: 'text-muted text-xs mt-8', style: 'margin:0;' },
            '四条流水线：准入 → 安全 → 排序 → 展示。🔴 + 高本地性的条目不会被折叠（护城河）。'
          ),
        ),
      ),
    ),
    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px;' },
      ...demo.map((r, i) => dishCard(r, i)),
    ),
  );
}

main().catch(e => { console.error("Page render failed:", e); });
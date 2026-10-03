/* ========================================================
   寻味中国 · API 客户端
   所有后端调用集中在这里，便于替换/测试
   ======================================================== */

const API_BASE = (window.location.port === '8000')
  ? '' // 直接访问 API 端口时用相对路径
  : 'http://localhost:8000';

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export const XunweiAPI = {
  // Meta / 公开（无 DB 依赖）
  capability: ()          => api('/api/meta/capability'),
  redLines: ()            => api('/api/meta/red-lines'),
  recommendationEngine: ()=> api('/api/meta/recommendation-engine'),
  allergenTypes: ()       => api('/api/meta/allergen-types'),
  version: ()             => api('/api/meta/version'),
  retention: ()           => api('/api/profile/retention'),
  health: ()              => api('/health'),

  // 推荐（需要 DB）
  recommend: (body)      => api('/api/recommend', { method: 'POST', body: JSON.stringify(body) }),
  discover: (body)       => api('/api/search/discover', { method: 'POST', body: JSON.stringify(body) }),
  dishDetail: (id)       => api(`/api/dishes/${id}`),

  // AI 对话
  chat: (body)           => api('/api/chat', { method: 'POST', body: JSON.stringify(body) }),
  clearChat: (id)        => api(`/api/chat/${id}`, { method: 'DELETE' }),

  // 清单收藏
  createList: (body)     => api('/api/lists', { method: 'POST', body: JSON.stringify(body) }),
  addListItem: (body)    => api('/api/lists/items', { method: 'POST', body: JSON.stringify(body) }),
  lockList: (body)       => api('/api/lists/lock', { method: 'POST', body: JSON.stringify(body) }),
  shareList: (body)      => api('/api/lists/share', { method: 'POST', body: JSON.stringify(body) }),

  // 画像（需要 DB）
  profile: (userId)      => api(`/api/profile?user_id=${encodeURIComponent(userId)}`),
  authorize: (body)      => api('/api/profile/authorize', { method: 'POST', body: JSON.stringify(body) }),
  clearProfile: (body)   => api('/api/profile/clear', { method: 'POST', body: JSON.stringify(body) }),
};

/* ========================================================
   工具：本地存储（画像默认客户端本地）
   ======================================================== */

const LS_USER = 'xw_user_hash';
const LS_RESTRICTIONS = 'xw_restrictions';

export const LocalStore = {
  getUser() { return localStorage.getItem(LS_USER) || null; },
  setUser(id) { localStorage.setItem(LS_USER, id); },
  getRestrictions() {
    try { return JSON.parse(localStorage.getItem(LS_RESTRICTIONS) || '[]'); }
    catch { return []; }
  },
  setRestrictions(arr) { localStorage.setItem(LS_RESTRICTIONS, JSON.stringify(arr)); },
  clear() {
    localStorage.removeItem(LS_USER);
    localStorage.removeItem(LS_RESTRICTIONS);
  },
};

/* ========================================================
   通用 DOM 工具
   ======================================================== */

export function $(sel, root = document) { return root.querySelector(sel); }
export function $$(sel, root = document) { return [...root.querySelectorAll(sel)]; }

export function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(n.style, v);
    else n.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    n.append(c instanceof Node ? c : document.createTextNode(c));
  }
  return n;
}

export function show(el) { el.classList.remove('hidden'); }
export function hide(el) { el.classList.add('hidden'); }

export function toast(msg, type = 'info') {
  const div = el('div', { class: `toast toast-${type}` }, msg);
  document.body.append(div);
  setTimeout(() => div.remove(), 3200);
}

/* ========================================================
   通用组件：印章徽章 / 证据等级 / 展示象限
   ======================================================== */

export const Seal = {
  source(name, size = 'md') {
    return el('span', {
      class: `seal ${size === 'sm' ? 'seal-sm' : ''}`,
      title: `数据源：${name}`,
    }, name || '未标注');
  },

  evidence(tag) {
    // tag: A / B / C / D
    const label = { A: '🟢 充足', B: '🟢 良好', C: '🟡 有限', D: '🔴 稀缺' }[tag] || tag;
    const cls = `badge badge-ev-${tag?.toLowerCase()}`;
    return el('span', { class: cls, title: '信息证据等级' }, label);
  },

  presentation(tier) {
    const map = {
      best:     ['badge-q-best',     '★ 最佳推荐'],
      priority: ['badge-q-priority', '🔴 稀缺但必推（护城河）'],
      standard: ['badge-q-standard', '○ 普通候选'],
      folded:   ['badge-q-folded',   '⬇ 可折叠'],
    };
    const [cls, label] = map[tier] || ['badge-q-standard', tier];
    return el('span', { class: `badge ${cls}` }, label);
  },
};

/* ========================================================
   导航 + 诚实条（所有页面共用）
   ======================================================== */

export function renderNav(active = '') {
  return el('header', { class: 'nav' },
    el('div', { class: 'container nav-inner' },
      el('a', { class: 'nav-logo', href: 'index.html' },
        el('span', { class: 'zh' }, '寻味'),
        el('span', {}, ' · 中国')
      ),
      el('nav', { class: 'nav-links' },
        el('a', { class: active === 'index' ? 'active' : '', href: 'index.html' }, '发现'),
        el('a', { class: active === 'chat'  ? 'active' : '', href: 'chat.html' }, 'AI 对话'),
        el('a', { class: active === 'engine'? 'active' : '', href: 'engine.html' }, '推荐引擎'),
        el('a', { class: active === 'about' ? 'active' : '', href: 'about.html' }, '关于'),
      ),
    ),
  );
}

export function renderHonestyBar(capability = null) {
  const caps = capability || {};
  const redLines = caps.red_lines || {};
  return el('div', { class: 'honesty-bar' },
    el('div', { class: 'container honesty-bar-inner' },
      el('span', {}, '我们不编造 · 不瞎推荐 · 每条推荐都带来源和核验时间'),
      el('span', {}, '｜'),
      el('span', {}, '过敏原违反率'),
      el('span', { class: 'red-line mono' }, `≤${redLines.allergen_violation_target_pct ?? 0}%`),
      el('span', {}, '幻觉率'),
      el('span', { class: 'red-line mono' }, `≤${redLines.hallucination_target_pct ?? 0}%`),
      el('span', {}, '来源标注率'),
      el('span', { class: 'red-line mono' }, `≥${redLines.source_annotation_target_pct ?? 100}%`),
      el('a', { href: 'about.html', title: '了解能力档位和红线详情' }, '什么能 / 不能做 →'),
    ),
  );
}

export function renderFooter() {
  return el('footer', { style: 'margin-top: 80px; padding: 48px 0 32px; border-top: 1px solid var(--rule);' },
    el('div', { class: 'container' },
      el('div', { style: 'display:flex; justify-content:space-between; flex-wrap:wrap; gap:24px;' },
        el('div', {},
          el('div', { class: 'subtitle' }, '寻味中国 · Xunwei China'),
          el('p', { class: 'text-muted text-small', style: 'margin-top:8px; max-width:360px;' },
            '做「菜品的知识与出处」，不做「商户的评分与揭黑」。'
          ),
        ),
        el('div', {},
          el('div', { class: 'subtitle mb-8' }, '架构红线'),
          el('div', { class: 'text-small text-muted', style: 'line-height:1.9;' },
            '过敏原违反率 = 0%<br>',
            '门店事实幻觉率 = 0%<br>',
            '来源标注率 = 100%',
          ),
        ),
        el('div', {},
          el('div', { class: 'subtitle mb-8' }, '隐私'),
          el('div', { class: 'text-small text-muted', style: 'line-height:1.9;' },
            '用户数据默认本地存储<br>',
            '一键清除：POST /api/profile/clear<br>',
            '数据导出：POST /api/profile/export',
          ),
        ),
      ),
      el('div', { class: 'rule-thin' }),
      el('div', { class: 'text-small text-muted text-center' },
        'v0.1.0 · T0 立项验证 · 架构设计见 /architecture/ 目录'
      ),
    ),
  );
}

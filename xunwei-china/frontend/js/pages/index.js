/* ========================================================
   首页 / 发现页
   搜索框（城市 + 菜系 + 忌口）+ 热门城市 + 热门菜系 + 能力档位
   ======================================================== */

import { XunweiAPI, LocalStore, renderNav, renderHonestyBar, renderFooter, el, Seal, $$ } from './lib.js';

const CITIES = ['成都', '广州', '杭州', '长沙', '重庆', '南京', '北京', '西安'];
const CUISINES = ['川菜', '粤菜', '浙菜', '湘菜', '鲁菜', '苏菜', '闽菜', '徽菜'];

async function main() {
  // 顶部条需要能力档位数据
  let capability = null;
  try { capability = await XunweiAPI.capability(); } catch {}

  document.body.append(renderNav('index'));
  document.body.append(renderHonestyBar(capability));

  const main = el('main', {},
    hero(),
    searchPanel(),
    capabilitySection(capability),
    enginePreview(),
  );
  document.body.append(main);
  document.body.append(renderFooter());

  // 事件绑定
  bindSearch();
}

function hero() {
  return el('section', { class: 'container animate-in' },
    el('div', { style: 'text-align:center; padding: 80px 0 48px;' },
      el('div', { class: 'subtitle', style: 'letter-spacing: 0.3em;' }, 'CHINA · LOCAL · AUTHENTIC'),
      el('h1', {},
        '寻味中国',
        el('br'),
        el('span', { style: 'color: var(--cinnabar);' }, '可核验的地方美食 AI 推荐'),
      ),
      el('p', { class: 'text-muted', style: 'max-width:560px; margin:0 auto; font-size:1.05rem;' },
        '我们不不知道的地方就说不知道。不编造，不瞎推荐。' +
        '每一条推荐都带来源和核验时间 —— 因为「本地」不是广告口号，是可核验的事实。'
      ),
      el('div', { class: 'flex-center gap-16 mt-32 wrap' },
        el('span', { class: 'seal', style: 'transform: rotate(-3deg); font-size:0.85rem;' }, '可核验'),
        el('span', { class: 'seal', style: 'transform: rotate(1deg);' }, '不瞎编'),
        el('span', { class: 'seal', style: 'transform: rotate(-2deg);' }, '有来源'),
      ),
    ),
  );
}

function searchPanel() {
  return el('section', { class: 'container animate-in delay-1' },
    el('div', { class: 'card', style: 'padding: 32px;' },
      corner('tl'), corner('tr'), corner('bl'), corner('br'),
      el('h3', {}, '找一道菜'),
      el('p', { class: 'text-muted text-small mt-8 mb-16' },
        '告诉我们你在哪里、喜欢什么、有什么忌口 —— 我们给你筛选本地美食推荐。'
      ),

      el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px;' },
        // 城市
        el('div', { class: 'form-group' },
          el('label', {}, '📍 城市'),
          el('select', { id: 'sel-city' },
            el('option', { value: '' }, '选择城市…'),
            ...CITIES.map(c => el('option', { value: c }, c)),
          ),
        ),
        // 菜系
        el('div', { class: 'form-group' },
          el('label', {}, '🥢 菜系（可选）'),
          el('select', { id: 'sel-cuisine' },
            el('option', { value: '' }, '不限'),
            ...CUISINES.map(c => el('option', { value: c }, c)),
          ),
        ),
      ),

      // 忌口（多选 chips）
      el('div', { class: 'form-group mt-24' },
        el('label', {}, '🚫 忌口 / 过敏原（可多选）'),
        el('div', { id: 'chip-restrictions', class: 'chip-group mt-8' }),
      ),

      // 提交
      el('div', { class: 'flex gap-16 mt-24 wrap' },
        el('button', { id: 'btn-search', class: 'btn btn-primary' }, '开始筛选 →'),
        el('a', { href: 'chat.html', class: 'btn btn-ghost' }, '或者… 聊一聊？'),
      ),
    ),
  );
}

function corner(pos) {
  return el('div', { class: `card-corner ${pos}` });
}

// 忌口 chips
async function bindSearch() {
  let allergens = [];
  try {
    const data = await XunweiAPI.allergenTypes();
    allergens = (data.common || []).map(a => a.name);
  } catch {
    allergens = ['花生', '牛奶', '鸡蛋', '虾', '大豆', '小麦', '坚果', '辣椒'];
  }

  const saved = LocalStore.getRestrictions();
  const chipGroup = $('#chip-restrictions');
  for (const name of allergens) {
    const chip = el('span', { class: 'chip' }, name);
    if (saved.includes(name)) chip.classList.add('active');
    chip.addEventListener('click', () => {
      chip.classList.toggle('active');
      updateRestrictions();
    });
    chipGroup.append(chip);
  }
}

function updateRestrictions() {
  const arr = $$('.chip.active').map(c => c.textContent);
  LocalStore.setRestrictions(arr);
}

$$(document).ready(() => {
  $('#btn-search')?.addEventListener('click', () => {
    const city = $('#sel-city').value;
    const cuisine = $('#sel-cuisine').value;
    const restrictions = LocalStore.getRestrictions();
    if (!city) { alert('请先选择一个城市'); return; }
    const params = new URLSearchParams({ city, cuisine: cuisine || '', restrictions: restrictions.join(',') });
    location.href = `results.html?${params}`;
  });
});

function capabilitySection(cap) {
  if (!cap) return el('section');
  const lv0 = cap.levels?.[0] || {};
  const lv1 = cap.levels?.[1] || {};

  return el('section', { class: 'container animate-in delay-2', style: 'margin-top: 64px;' },
    el('h2', {}, '我的能力档位'),
    el('p', { class: 'subtitle' }, '我诚实告诉你：能做什么，不能做什么'),

    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-top: 24px;' },
      // Level 0 — 诚实拒答
      el('div', { class: 'card' },
        corner('tl'), corner('tr'), corner('bl'), corner('br'),
        el('div', { style: 'display:flex; justify-content:space-between; align-items:center;' },
          el('span', { class: 'mono text-xs text-muted' }, 'Level 0'),
          el('span', { class: 'seal seal-sm' }, '底线'),
        ),
        el('h3', { class: 'mt-16' }, lv0.name || '不知道就说不知道'),
        el('p', { class: 'text-muted text-small mt-8' },
          lv0.description || '不编造菜品、不编造数据源。'
        ),
        el('div', { class: 'text-small mt-16' },
          (lv0.enforced_by || []).map(s =>
            el('div', { class: 'flex gap-8 mt-8' }, el('span', { style: 'color:var(--cinnabar)' }, '✦'), el('span', {}, s))
          ),
        ),
      ),

      // Level 1 — 结构化筛选
      el('div', { class: 'card' },
        corner('tl'), corner('tr'), corner('bl'), corner('br'),
        el('div', { style: 'display:flex; justify-content:space-between; align-items:center;' },
          el('span', { class: 'mono text-xs text-muted' }, 'Level 1'),
          el('span', { class: 'seal seal-sm', style: 'border-color:var(--pine); color:var(--pine); background:rgba(74,124,89,0.08);' }, '核心'),
        ),
        el('h3', { class: 'mt-16' }, lv1.name || '结构化筛选'),
        el('p', { class: 'text-muted text-small mt-8' },
          lv1.description || '按条件筛选，不是黑盒个性化。'
        ),
        el('p', { class: 'text-small mt-16', style: 'background:var(--paper-dark); padding:12px; border-left:3px solid var(--rule); border-radius:0 var(--r-sm) var(--r-sm) 0;' },
          lv1.limitation || '每一条都能说出「为什么是这条」。'
        ),
      ),
    ),

    // 红线三个大数字
    el('div', { style: 'margin-top:40px; text-align:center;' },
      el('div', { class: 'text-muted text-small', style: 'letter-spacing:0.15em; text-transform:uppercase;' }, '架构红线（不可妥协）'),
      el('div', { style: 'display:flex; justify-content:center; gap:48px; flex-wrap:wrap; margin-top:16px;' },
        redNum('0%', '过敏原违反率', 'cinnabar'),
        redNum('0%', '门店事实幻觉率', 'cinnabar'),
        redNum('100%', '来源标注率', 'bronze'),
      ),
      el('a', { href: 'about.html', class: 'btn btn-ghost mt-16' }, '为什么是这三个数字？ →'),
    ),
  );
}

function redNum(num, label, cls) {
  return el('div', { style: 'text-align:center;' },
    el('div', { class: `number-big mono ${cls}` }, num),
    el('div', { class: 'text-muted text-xs mt-8' }, label),
  );
}

function enginePreview() {
  return el('section', { class: 'container animate-in delay-3', style: 'margin-top: 80px;' },
    el('div', { class: 'rule-double' }),
    el('h2', {}, '我们怎么选这道菜？'),
    el('p', { class: 'subtitle' }, '四层流水线 —— 可解释，不黑盒'),

    el('div', { style: 'display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 24px;' },
      layerCard('① 准入层', '二维条件表\n(locality × evidence)\n连锁一律排除', 'cinnabar'),
      layerCard('② 安全层', '召回层硬过滤\n过敏原命中 → 一票否决\n无数据源 → 排除', 'cinnabar'),
      layerCard('③ 排序层', '单标量 locality_score\n60%本地性 + 25%年限 + 15%菜系\n确定性公式', 'bronze'),
      layerCard('④ 展示层', '四象限规则\n🟢 + 高本地性 → 最佳\n🔴 + 高本地性 → 禁折叠（护城河）', 'pine'),
    ),
    el('div', { class: 'mt-16' },
      el('a', { href: 'engine.html', class: 'btn btn-primary' }, '看完整引擎可视化 →'),
    ),
  );
}

function layerCard(title, desc, color) {
  return el('div', { class: 'card', style: 'padding: 20px;' },
    el('h3', { style: `color: var(--${color === 'bronze' ? 'bronze' : color === 'pine' ? 'pine' : 'cinnabar'}); margin-top:0;` }, title),
    el('p', { class: 'text-muted text-small', style: 'white-space: pre-line; margin-top:8px;' }, desc),
  );
}

main().catch(e => { console.error("Page render failed:", e); });
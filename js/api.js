// LETSPLAY · 前端 API 客户端 + 通用工具

// GitHub Pages 部署时 API 指向后端服务器；本地开发时用相对路径
const API_BASE = location.hostname.includes('github.io')
  ? 'https://pve.u2170167.nyat.app:38412'
  : '';

const API = {
  async _fetch(path, opts = {}) {
    const res = await fetch(API_BASE + path, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    });
    let data;
    try { data = await res.json(); } catch { data = {}; }
    if (!res.ok) {
      const msg = data.detail || `请求失败 (${res.status})`;
      throw new Error(msg);
    }
    return data;
  },
  me() { return this._fetch('/api/me'); },
  listBattles() { return this._fetch('/api/battles'); },
  createBattle(type, maxPlayers, totalMatches, bestOf = 3, gamePoint = 21) {
    return this._fetch('/api/battle/create', {
      method: 'POST',
      body: JSON.stringify({
        type, max_players: maxPlayers, total_matches: totalMatches,
        best_of: bestOf, game_point: gamePoint,
      }),
    });
  },
  getBattle(bid) { return this._fetch(`/api/battle/${bid}`); },
  joinBattle(bid) { return this._fetch(`/api/battle/${bid}/join`, { method: 'POST' }); },
  startBattle(bid) { return this._fetch(`/api/battle/${bid}/start`, { method: 'POST' }); },
  getMatches(bid) { return this._fetch(`/api/battle/${bid}/matches`); },
  score(mid, action) {
    return this._fetch(`/api/match/${mid}/score`, {
      method: 'POST', body: JSON.stringify({ action }),
    });
  },
  getMatch(mid) { return this._fetch(`/api/match/${mid}`); },
  getRanking(bid) { return this._fetch(`/api/battle/${bid}/ranking`); },
};

// ---------- 工具 ----------
function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return [...root.querySelectorAll(sel)]; }

function toast(msg, isErr = false) {
  let t = $('.toast');
  if (!t) {
    t = document.createElement('div');
    t.className = 'toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.toggle('err', isErr);
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 2400);
}

// 渲染头像 SVG（字符串 -> DOM）
function avatarHTML(svgStr) {
  return svgStr || '';
}

// 取 URL 参数
function param(name) {
  return new URLSearchParams(location.search).get(name);
}

// 渲染顶部用户身份条
async function renderUserChip() {
  try {
    const user = await API.me();
    const chip = $('#userChip');
    if (!chip) return user;
    chip.innerHTML = `
      <div class="ava">${avatarHTML(user.avatar)}</div>
      <span class="name">${user.nickname}</span>
    `;
    return user;
  } catch (e) {
    return null;
  }
}

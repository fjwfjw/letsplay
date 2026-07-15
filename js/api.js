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
  updateNickname(nickname) {
    return this._fetch('/api/me/nickname', {
      method: 'PUT',
      body: JSON.stringify({ nickname }),
    });
  },
  listBattles() { return this._fetch('/api/battles'); },
  createBattle(type, maxPlayers, totalMatches, bestOf = 3, gamePoint = 21, assignMode = 'random') {
    return this._fetch('/api/battle/create', {
      method: 'POST',
      body: JSON.stringify({
        type, max_players: maxPlayers, total_matches: totalMatches,
        best_of: bestOf, game_point: gamePoint, assign_mode: assignMode,
      }),
    });
  },
  getBattle(bid) { return this._fetch(`/api/battle/${bid}`); },
  joinBattle(bid) { return this._fetch(`/api/battle/${bid}/join`, { method: 'POST' }); },
  startBattle(bid) { return this._fetch(`/api/battle/${bid}/start`, { method: 'POST' }); },
  setAssignMode(bid, mode) {
    return this._fetch(`/api/battle/${bid}/assign-mode`, {
      method: 'POST', body: JSON.stringify({ mode }),
    });
  },
  setTeams(bid, teams) {
    return this._fetch(`/api/battle/${bid}/teams`, {
      method: 'POST', body: JSON.stringify({ teams }),
    });
  },
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

// 将用户信息渲染到顶栏 chip，并绑定点击编辑昵称
function applyUserToChip(user) {
  const chip = $('#userChip');
  if (!chip || !user) return;
  chip.innerHTML = `
    <div class="ava">${avatarHTML(user.avatar)}</div>
    <span class="name">${user.nickname}</span>
    <svg class="edit-pen" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
  `;
  chip.classList.add('editable');
  chip.onclick = () => openNicknameEditor(user);
}

// 渲染顶部用户身份条
async function renderUserChip() {
  try {
    const user = await API.me();
    applyUserToChip(user);
    return user;
  } catch (e) {
    return null;
  }
}

// 昵称编辑弹窗
function openNicknameEditor(user) {
  // 避免重复创建
  if ($('#nickOverlay')) return;
  const overlay = document.createElement('div');
  overlay.id = 'nickOverlay';
  overlay.className = 'nick-overlay';
  overlay.innerHTML = `
    <div class="nick-modal">
      <div class="nick-modal-title">修改昵称</div>
      <div class="nick-modal-ava">${avatarHTML(user.avatar)}</div>
      <input class="nick-input" type="text" maxlength="20" placeholder="输入新昵称" />
      <div class="nick-modal-hint">最多 20 个字符</div>
      <div class="nick-modal-actions">
        <button class="btn btn-ghost nick-cancel">取消</button>
        <button class="btn btn-primary nick-save">保存</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  document.body.style.overflow = 'hidden';
  // 强制 reflow 后显示
  void overlay.offsetWidth;
  overlay.classList.add('show');

  const input = $('.nick-input', overlay);
  input.value = user.nickname;
  input.focus();
  input.select();

  const close = () => {
    overlay.classList.remove('show');
    document.body.style.overflow = '';
    setTimeout(() => overlay.remove(), 250);
  };

  $('.nick-cancel', overlay).onclick = close;
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  const saveBtn = $('.nick-save', overlay);
  saveBtn.onclick = async () => {
    const nick = input.value.trim();
    if (!nick) { toast('昵称不能为空', true); return; }
    if (nick === user.nickname) { close(); return; }
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中…';
    try {
      const updated = await API.updateNickname(nick);
      // 更新 chip 显示
      const chip = $('#userChip');
      if (chip) {
        const nameEl = $('.name', chip);
        if (nameEl) nameEl.textContent = updated.nickname;
      }
      // 更新全局 currentUser（如果存在）
      if (typeof currentUser !== 'undefined' && currentUser) {
        currentUser.nickname = updated.nickname;
      }
      toast('昵称已更新');
      close();
      // 通知页面刷新（如果页面定义了 onNicknameUpdated 回调）
      if (typeof onNicknameUpdated === 'function') onNicknameUpdated(updated);
    } catch (e) {
      toast(e.message || '修改失败', true);
      saveBtn.disabled = false;
      saveBtn.textContent = '保存';
    }
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') saveBtn.click();
    if (e.key === 'Escape') close();
  });
}

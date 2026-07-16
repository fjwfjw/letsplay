// LETSPLAY · 前端 API 客户端 + 通用工具

// GitHub Pages 部署时 API 指向后端服务器；本地开发时用相对路径
const API_BASE = location.hostname.includes('github.io')
  ? 'https://pve.u2170167.nyat.app:38412'
  : '';

// ---------- Token 管理 ----------
const TOKEN_KEY = 'letsplay_token';
const TOKEN_EXPIRE_KEY = 'letsplay_token_expire';
const GUEST_KEY = 'letsplay_guest';
const TOKEN_TTL_MS = 90 * 24 * 3600 * 1000; // 90 天

function getToken() {
  const token = localStorage.getItem(TOKEN_KEY);
  const expire = parseInt(localStorage.getItem(TOKEN_EXPIRE_KEY) || '0', 10);
  if (!token || Date.now() > expire) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_EXPIRE_KEY);
    return null;
  }
  return token;
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(TOKEN_EXPIRE_KEY, String(Date.now() + TOKEN_TTL_MS));
  localStorage.removeItem(GUEST_KEY); // 正式登录清除游客标记
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_EXPIRE_KEY);
  localStorage.removeItem(GUEST_KEY);
}

function isLoggedIn() {
  return !!getToken();
}

function isGuest() {
  return !isLoggedIn() && localStorage.getItem(GUEST_KEY) === '1';
}

function setGuest() {
  localStorage.setItem(GUEST_KEY, '1');
}

function isAuthed() {
  return isLoggedIn() || isGuest();
}

const API = {
  async _fetch(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...opts.headers };
    const token = getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(API_BASE + path, {
      ...opts,
      headers,
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
  updateProfile(nickname, gender) {
    const body = {};
    if (nickname !== undefined) body.nickname = nickname;
    if (gender !== undefined) body.gender = gender;
    return this._fetch('/api/me/profile', {
      method: 'PUT',
      body: JSON.stringify(body),
    });
  },
  // 注册 / 登录
  register(loginKey, gender, nickname, avatar) {
    const body = { login_key: loginKey, gender };
    if (nickname) body.nickname = nickname;
    if (avatar) body.avatar = avatar;
    return this._fetch('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  login(loginKey) {
    return this._fetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ login_key: loginKey }),
    });
  },
  getRandomAvatar() { return this._fetch('/api/avatar/random'); },
  // 好友
  getFriends() { return this._fetch('/api/friends'); },
  getFriendRequests() { return this._fetch('/api/friends/requests'); },
  sendFriendRequest(toUid) {
    return this._fetch('/api/friends/request', {
      method: 'POST',
      body: JSON.stringify({ to_uid: toUid }),
    });
  },
  acceptFriend(fromUid) {
    return this._fetch('/api/friends/accept', {
      method: 'POST',
      body: JSON.stringify({ from_uid: fromUid }),
    });
  },
  // 个人统计
  getMyStats() { return this._fetch('/api/me/stats'); },
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
  setGenderRule(bid, rule) {
    return this._fetch(`/api/battle/${bid}/gender-rule`, {
      method: 'POST', body: JSON.stringify({ rule }),
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
  // 未登录且非游客 -> 显示登录弹窗
  if (!isAuthed()) {
    showLoginDialog();
    return null;
  }
  try {
    const user = await API.me();
    applyUserToChip(user);
    return user;
  } catch (e) {
    // token 失效 -> 清除并显示登录弹窗
    clearToken();
    showLoginDialog();
    return null;
  }
}

// ---------- 登录 / 注册弹窗 ----------
function showLoginDialog() {
  if ($('#loginOverlay')) return;
  const overlay = document.createElement('div');
  overlay.id = 'loginOverlay';
  overlay.className = 'nick-overlay';
  overlay.innerHTML = `
    <div class="nick-modal" style="max-width:360px;">
      <div class="nick-modal-title">LET'S PLAY</div>
      <div style="font-family:var(--font-mono);font-size:11px;color:var(--muted);text-align:center;margin-bottom:20px;letter-spacing:1px;">登录 / 注册</div>

      <!-- Tab 切换 -->
      <div class="login-tabs" style="display:flex;gap:0;margin-bottom:20px;border:1px solid var(--line-strong);border-radius:4px;overflow:hidden;">
        <button class="login-tab active" data-tab="register" style="flex:1;padding:10px;background:var(--lime);color:var(--bg);border:none;font-family:var(--font-body);font-size:13px;font-weight:700;cursor:pointer;">首次注册</button>
        <button class="login-tab" data-tab="login" style="flex:1;padding:10px;background:var(--bg-2);color:var(--fg-dim);border:none;font-family:var(--font-body);font-size:13px;font-weight:500;cursor:pointer;">密钥登录</button>
      </div>

      <!-- 注册面板 -->
      <div id="registerPanel">
        <!-- 头像 + 换头像 -->
        <div style="display:flex;align-items:center;gap:12px;padding:12px;background:var(--bg-2);border-radius:4px;margin-bottom:16px;">
          <div style="position:relative;">
            <div class="nick-modal-ava" id="regAva" style="width:48px;height:48px;"><span class="loading"></span></div>
            <button id="changeAvatarBtn" type="button" style="position:absolute;bottom:-2px;right:-2px;width:20px;height:20px;border-radius:50%;background:var(--lime);color:var(--bg);border:2px solid var(--bg-1);font-size:10px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;">↻</button>
          </div>
          <div style="flex:1;">
            <div style="font-size:11px;color:var(--muted);margin-bottom:4px;">昵称</div>
            <input class="nick-input" id="regNickInput" type="text" maxlength="20" placeholder="输入昵称" style="margin:0;padding:8px 10px;font-size:14px;width:100%;" />
          </div>
        </div>

        <div class="nick-gender-label">性别（用于混双/分性别分配）</div>
        <div class="nick-gender-row">
          <button class="nick-gender-btn" data-gender="male">男</button>
          <button class="nick-gender-btn" data-gender="female">女</button>
        </div>

        <input class="nick-input" id="regKeyInput" type="text" maxlength="20" placeholder="设置登录密钥（6-20位）" style="margin-top:16px;" />
        <div class="nick-modal-hint">需包含大写字母、小写字母和数字</div>

        <div id="registerError" style="color:var(--coral);font-size:12px;margin-top:8px;display:none;"></div>

        <div class="nick-modal-actions" style="margin-top:16px;">
          <button class="btn btn-primary" id="registerBtn" style="width:100%;">注册</button>
        </div>
      </div>

      <!-- 登录面板 -->
      <div id="loginPanel" style="display:none;">
        <input class="nick-input" id="loginKeyInput" type="text" maxlength="20" placeholder="输入登录密钥" />
        <div class="nick-modal-hint">输入注册时设置的密钥</div>

        <div id="loginError" style="color:var(--coral);font-size:12px;margin-top:8px;display:none;"></div>

        <div class="nick-modal-actions" style="margin-top:16px;">
          <button class="btn btn-primary" id="loginBtn" style="width:100%;">登录</button>
        </div>
      </div>

      <!-- 游客登录 -->
      <div style="margin-top:20px;text-align:center;padding-top:16px;border-top:1px solid var(--line);">
        <button class="btn btn-ghost" id="guestBtn" style="width:100%;font-size:12px;color:var(--muted);">游客登录（无法使用好友功能）</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  document.body.style.overflow = 'hidden';
  void overlay.offsetWidth;
  overlay.classList.add('show');

  // 预加载 IP 派生的昵称头像
  let regGender = 'unknown';
  let regAvatar = null;

  // 用不带 token 的请求获取 IP 派生身份
  fetch(API_BASE + '/api/me')
    .then(r => r.json())
    .then(u => {
      regAvatar = u.avatar || '';
      $('#regAva').innerHTML = regAvatar;
      $('#regNickInput').value = u.nickname || '';
    })
    .catch(() => {
      $('#regNickInput').placeholder = '输入昵称';
    });

  // 换头像
  $('#changeAvatarBtn', overlay).addEventListener('click', async () => {
    const btn = $('#changeAvatarBtn');
    btn.disabled = true;
    btn.textContent = '...';
    try {
      const data = await API.getRandomAvatar();
      regAvatar = data.avatar;
      $('#regAva').innerHTML = regAvatar;
    } catch {
      toast('换头像失败', true);
    }
    btn.disabled = false;
    btn.textContent = '↻';
  });

  // Tab 切换
  $$('.login-tab', overlay).forEach(tab => {
    tab.addEventListener('click', () => {
      const isRegister = tab.dataset.tab === 'register';
      $$('.login-tab', overlay).forEach(t => {
        t.classList.toggle('active', t === tab);
        if (t === tab) {
          t.style.background = 'var(--lime)';
          t.style.color = 'var(--bg)';
          t.style.fontWeight = '700';
        } else {
          t.style.background = 'var(--bg-2)';
          t.style.color = 'var(--fg-dim)';
          t.style.fontWeight = '500';
        }
      });
      $('#registerPanel').style.display = isRegister ? '' : 'none';
      $('#loginPanel').style.display = isRegister ? 'none' : '';
    });
  });

  // 性别选择
  $$('.nick-gender-btn', overlay).forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.nick-gender-btn', overlay).forEach(b => b.classList.remove('selected'));
      if (regGender === btn.dataset.gender) {
        regGender = 'unknown';
      } else {
        regGender = btn.dataset.gender;
        btn.classList.add('selected');
      }
    });
  });

  // 注册
  $('#registerBtn', overlay).addEventListener('click', async () => {
    const key = $('#regKeyInput').value.trim();
    const nick = $('#regNickInput').value.trim();
    const errEl = $('#registerError');
    errEl.style.display = 'none';
    if (!nick) {
      errEl.textContent = '请输入昵称';
      errEl.style.display = 'block';
      return;
    }
    if (!key || key.length < 6 || key.length > 20) {
      errEl.textContent = '密钥长度 6-20 位';
      errEl.style.display = 'block';
      return;
    }
    if (!/[A-Z]/.test(key) || !/[a-z]/.test(key) || !/[0-9]/.test(key)) {
      errEl.textContent = '密钥需包含大写字母、小写字母和数字';
      errEl.style.display = 'block';
      return;
    }
    if (regGender === 'unknown') {
      errEl.textContent = '请选择性别';
      errEl.style.display = 'block';
      return;
    }
    const btn = $('#registerBtn');
    btn.disabled = true;
    btn.textContent = '注册中…';
    try {
      const user = await API.register(key, regGender, nick, regAvatar);
      setToken(user.token);
      closeLoginDialog();
      toast('注册成功！');
      // 刷新页面
      location.reload();
    } catch (e) {
      errEl.textContent = e.message || '注册失败';
      errEl.style.display = 'block';
      btn.disabled = false;
      btn.textContent = '注册';
    }
  });

  // 登录
  $('#loginBtn', overlay).addEventListener('click', async () => {
    const key = $('#loginKeyInput').value.trim();
    const errEl = $('#loginError');
    errEl.style.display = 'none';
    if (!key) {
      errEl.textContent = '请输入密钥';
      errEl.style.display = 'block';
      return;
    }
    const btn = $('#loginBtn');
    btn.disabled = true;
    btn.textContent = '登录中…';
    try {
      const user = await API.login(key);
      setToken(user.token);
      closeLoginDialog();
      toast('登录成功！');
      location.reload();
    } catch (e) {
      errEl.textContent = e.message || '登录失败';
      errEl.style.display = 'block';
      btn.disabled = false;
      btn.textContent = '登录';
    }
  });

  // Enter 提交
  $('#regKeyInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('#registerBtn').click();
  });
  $('#loginKeyInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('#loginBtn').click();
  });

  // 游客登录
  $('#guestBtn', overlay).addEventListener('click', () => {
    setGuest();
    closeLoginDialog();
    toast('已以游客身份进入');
    location.reload();
  });
}

function closeLoginDialog() {
  const overlay = $('#loginOverlay');
  if (!overlay) return;
  overlay.classList.remove('show');
  document.body.style.overflow = '';
  setTimeout(() => overlay.remove(), 250);
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
      <div class="nick-modal-title">个人资料</div>
      <div class="nick-modal-ava">${avatarHTML(user.avatar)}</div>
      <input class="nick-input" type="text" maxlength="20" placeholder="输入新昵称" />
      <div class="nick-modal-hint">最多 20 个字符</div>
      <div class="nick-gender-label">性别（用于混双/分性别分配）</div>
      <div class="nick-gender-row">
        <button class="nick-gender-btn" data-gender="male">男</button>
        <button class="nick-gender-btn" data-gender="female">女</button>
      </div>
      <div class="nick-modal-actions">
        <button class="btn btn-ghost nick-cancel">取消</button>
        <button class="btn btn-primary nick-save">保存</button>
      </div>
      ${isLoggedIn() ? '<a href="profile.html" style="display:block;text-align:center;margin-top:14px;font-size:12px;color:var(--muted);font-family:var(--font-mono);text-decoration:none;">个人中心 -&gt;</a>' : ''}
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

  // 性别选择
  let selectedGender = user.gender || 'unknown';
  $$('.nick-gender-btn', overlay).forEach(btn => {
    if (btn.dataset.gender === selectedGender) btn.classList.add('selected');
    btn.addEventListener('click', () => {
      $$('.nick-gender-btn', overlay).forEach(b => b.classList.remove('selected'));
      // 再次点击已选中的 -> 取消选择
      if (selectedGender === btn.dataset.gender) {
        selectedGender = 'unknown';
      } else {
        selectedGender = btn.dataset.gender;
        btn.classList.add('selected');
      }
    });
  });

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
    const genderChanged = selectedGender !== (user.gender || 'unknown');
    const nickChanged = nick !== user.nickname;
    if (!nickChanged && !genderChanged) { close(); return; }
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中…';
    try {
      const updated = await API.updateProfile(
        nickChanged ? nick : undefined,
        genderChanged ? selectedGender : undefined
      );
      // 更新 chip 显示
      const chip = $('#userChip');
      if (chip) {
        const nameEl = $('.name', chip);
        if (nameEl) nameEl.textContent = updated.nickname;
        // 更新 user 对象供下次编辑使用
        user.nickname = updated.nickname;
        user.gender = updated.gender;
      }
      // 更新全局 currentUser（如果存在）
      if (typeof currentUser !== 'undefined' && currentUser) {
        currentUser.nickname = updated.nickname;
        currentUser.gender = updated.gender;
      }
      toast('资料已更新');
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

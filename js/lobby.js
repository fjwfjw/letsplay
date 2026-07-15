// LETSLAY · 对战大厅逻辑

const BID = param('id');
if (!BID) {
  location.href = 'index.html';
}

// 识别手表端：小屏幕 + 高设备像素比 + 短边 <= 350px
function isWatchClient() {
  // 只判断真正的可穿戴设备（手表），手机/平板一律 false
  const shortSide = Math.min(window.innerWidth, window.innerHeight);
  const ua = (navigator.userAgent || '').toLowerCase();
  if (
    ua.includes('apple watch') ||
    ua.includes('watchos') ||
    ua.includes('watchkit') ||
    ua.includes('wear os') ||
    ua.includes('android wear') ||
    /galaxy watch/.test(ua) ||
    /sm-r\d{3}/.test(ua)
  ) return true;
  if (shortSide <= 220) return true;
  if (navigator.maxTouchPoints === 1 && shortSide <= 320) return true;
  return false;
}

let pollTimer = null;
let lastPlayerCount = -1;

async function refresh() {
  try {
    const data = await API.getBattle(BID);
    render(data);
    // 已开赛 -> 跳转
    if (data.battle.status === 'ongoing') {
      clearInterval(pollTimer);
      location.href = `matches.html?id=${BID}`;
      return;
    }
    // 新玩家加入提示（仅创建者）
    if (data.is_creator && data.players.length !== lastPlayerCount) {
      if (lastPlayerCount !== -1 && data.players.length > lastPlayerCount) {
        toast(`${data.players[data.players.length - 1].nickname} 加入了对战`);
      }
      lastPlayerCount = data.players.length;
    }
  } catch (e) {
    if (e.message.includes('不存在')) {
      clearInterval(pollTimer);
      $('#statusText').textContent = '对战不存在';
      toast('对战不存在或已结束', true);
    }
  }
}

function render(data) {
  const { battle, user, players, joined, is_creator } = data;
  window._battleType = battle.type;  // 供组队函数使用

  // 顶栏用户
  applyUserToChip(user);

  // 状态条
  $('#pCount').textContent = players.length;
  $('#pMax').textContent = battle.max_players;
  $('#typeTag').textContent = battle.type === 'singles' ? '单打 1v1' : '双打 2v2';
  const bestOfLabel = battle.best_of === 1 ? '一局定胜负' : '三局两胜';
  $('#matchesTag').textContent = `${battle.total_matches} 场 · ${bestOfLabel} · ${battle.game_point}分制`;
  $('#pCountTag').textContent = `${players.length} / ${battle.max_players}`;

  // 玩家列表
  const list = $('#playersList');
  list.innerHTML = '';
  if (players.length === 0) {
    $('#emptyPlayers').classList.remove('hidden');
  } else {
    $('#emptyPlayers').classList.add('hidden');
    players.forEach(p => {
      const isHost = p.id === battle.creator_id;
      const el = document.createElement('div');
      el.className = 'player' + (isHost ? ' host' : '');
      el.innerHTML = `
        <div class="ava">${p.avatar}</div>
        <div class="meta">
          <div class="nick">${p.nickname}</div>
          <div class="role">${isHost ? '创建者' : '玩家'}</div>
        </div>
      `;
      list.appendChild(el);
    });
  }

  // 分享区（仅创建者）
  if (is_creator) {
    $('#sharePanel').classList.remove('hidden');
    const url = `${location.href.replace(/[^/]*$/, '')}battle.html?id=${BID}`;
    $('#shareLink').textContent = url;
    $('#copyBtn').onclick = async () => {
      try { await navigator.clipboard.writeText(url); toast('邀请链接已复制'); }
      catch { toast('复制失败，请手动复制'); }
    };
    // 手表按钮：点击直接跳转到 watch.html 记分页（不区分设备类型）
    const watchBtn = $('#watchBtn');
    const goWatch = () => {
      const watchUrl = `watch.html?id=${BID}`;
      try { window.location.assign(watchUrl); }
      catch (e) { window.location.href = watchUrl; }
      // 兜底：1.5s 后仍未跳转则强制刷新
      setTimeout(() => {
        if (!location.pathname.includes('watch.html')) {
          window.location.replace(watchUrl);
        }
      }, 1500);
    };
    watchBtn.onclick = goWatch;
    // 兜底：click 不响应时用 touchend
    watchBtn.addEventListener('touchend', (e) => { e.preventDefault(); goWatch(); }, { passive: false });
  }

  // 分配方式面板（仅创建者）
  if (is_creator) {
    $('#assignPanel').classList.remove('hidden');
    syncAssignUI(battle, players, data.teams || {});
  } else {
    $('#assignPanel').classList.add('hidden');
  }

  // 按钮区
  $('#joinBtn').classList.toggle('hidden', joined);
  $('#startBtn').classList.toggle('hidden', !is_creator);
  $('#waitNote').classList.toggle('hidden', !(joined && !is_creator));

  if (is_creator) {
    const minP = battle.type === 'singles' ? 2 : 4;
    const canStart = canStartBattle(battle, players);
    $('#startBtn').disabled = !canStart;
    $('#startBtn').textContent = canStart
      ? '开始对战 →'
      : `等待 ${minP} 人加入（当前 ${players.length}）`;
  }
}

// ---------- 自由对战：分配模式与组队 ----------
let teamsState = {};      // {team_0: [uid,...], ...}
let teamCount = 2;        // 当前队伍数量
let localMode = null;     // 本地缓存的模式，避免轮询覆盖用户操作
let localGenderRule = null; // 本地缓存的性别规则
let playersCache = [];    // 缓存玩家列表

function perTeamSize(battle) {
  return battle.type === 'singles' ? 1 : 2;
}

function canStartBattle(battle, players) {
  const minP = battle.type === 'singles' ? 2 : 4;
  if (players.length < minP) return false;
  // 自由对战：需要所有玩家已分配到队伍，且至少 2 支满员队伍
  if ((battle.assign_mode || localMode) === 'free') {
    const per = perTeamSize(battle);
    const fullTeams = Object.values(teamsState).filter(t => t.length === per);
    const assigned = Object.values(teamsState).reduce((s, t) => s + t.length, 0);
    return fullTeams.length >= 2 && assigned === players.length;
  }
  return true;
}

function syncAssignUI(battle, players, serverTeams) {
  playersCache = players;
  // 高亮当前模式卡片
  const mode = battle.assign_mode || 'random';
  if (localMode === null) localMode = mode;
  $$('#assignGrid .type-card').forEach(c => {
    c.classList.toggle('selected', c.dataset.mode === localMode);
  });
  // 显示/隐藏组队面板
  $('#teamsPanel').classList.toggle('hidden', localMode !== 'free');

  // 性别规则面板（仅随机分配时可见）
  const genderRule = battle.gender_rule || 'none';
  if (localGenderRule === null) localGenderRule = genderRule;
  const grPanel = $('#genderRulePanel');
  if (localMode === 'random') {
    grPanel.classList.remove('hidden');
    buildGenderRuleChips(battle.type);
  } else {
    grPanel.classList.add('hidden');
  }

  if (localMode === 'free') {
    // 同步队伍状态（首次或服务端有数据时）
    if (Object.keys(teamsState).length === 0 && serverTeams && Object.keys(serverTeams).length > 0) {
      teamsState = JSON.parse(JSON.stringify(serverTeams));
      teamCount = Math.max(2, Object.keys(teamsState).length);
    }
    renderTeamsUI(battle, players);
  }
}

function buildGenderRuleChips(battleType) {
  const wrap = $('#genderRuleChips');
  if (!wrap) return;
  const options = battleType === 'doubles'
    ? [{ value: 'none', label: '双打' }, { value: 'mixed', label: '混双' }]
    : [{ value: 'none', label: '单打' }, { value: 'separated', label: '分性别' }];
  wrap.innerHTML = '';
  options.forEach(opt => {
    const c = document.createElement('div');
    c.className = 'chip' + (opt.value === localGenderRule ? ' selected' : '');
    c.textContent = opt.label;
    c.style.minWidth = '70px';
    c.addEventListener('click', async () => {
      if (opt.value === localGenderRule) return;
      localGenderRule = opt.value;
      // 高亮
      $$('#genderRuleChips .chip').forEach(b => b.classList.remove('selected'));
      c.classList.add('selected');
      try {
        await API.setGenderRule(BID, opt.value);
        toast(opt.value === 'none' ? '已切换为普通模式' : `已切换为${opt.label}`);
      } catch (e) {
        toast(e.message, true);
        // 回滚
        localGenderRule = opt.value === 'none' ? 'mixed' : 'none';
        buildGenderRuleChips(battleType);
      }
    });
    wrap.appendChild(c);
  });
}

function renderTeamsUI(battle, players) {
  const per = perTeamSize(battle);
  $('#teamCountVal').textContent = teamCount;

  // 保证 teamsState 有 team_0 ~ team_{teamCount-1}
  for (let i = 0; i < teamCount; i++) {
    const tid = `team_${i}`;
    if (!teamsState[tid]) teamsState[tid] = [];
  }
  // 移除多余的队伍（其成员回到池）
  Object.keys(teamsState).forEach(tid => {
    const idx = parseInt(tid.split('_')[1], 10);
    if (idx >= teamCount) {
      delete teamsState[tid];
    }
  });

  // 已分配玩家集合
  const assigned = new Set();
  Object.values(teamsState).forEach(arr => arr.forEach(u => assigned.add(u)));

  // 未分配玩家池
  const pool = players.filter(p => !assigned.has(p.id));
  $('#poolCount').textContent = pool.length;
  const poolEl = $('#playerPool');
  poolEl.innerHTML = '';
  if (pool.length === 0) {
    poolEl.innerHTML = '<div class="muted" style="padding:8px;font-size:13px;">所有玩家已分配</div>';
  } else {
    pool.forEach(p => {
      const el = document.createElement('div');
      el.className = 'player';
      el.innerHTML = `<div class="ava">${p.avatar}</div><div class="meta"><div class="nick">${p.nickname}</div></div>`;
      // 点击：分配到第一个有空位的队伍
      el.style.cursor = 'pointer';
      el.addEventListener('click', () => assignToFirstTeam(p.id));
      poolEl.appendChild(el);
    });
  }

  // 各队伍
  const teamsList = $('#teamsList');
  teamsList.innerHTML = '';
  const colors = ['#3ad4ff', '#ff5e3a', '#3aff9e', '#ffd23a', '#a23aff', '#ff3a8c'];
  for (let i = 0; i < teamCount; i++) {
    const tid = `team_${i}`;
    const members = teamsState[tid] || [];
    const memberPlayers = members.map(uid => players.find(p => p.id === uid)).filter(Boolean);
    const full = members.length >= per;
    const wrap = document.createElement('div');
    wrap.className = 'panel';
    wrap.style.marginBottom = '12px';
    wrap.style.borderLeft = `4px solid ${colors[i % colors.length]}`;
    wrap.innerHTML = `
      <div class="field-label" style="margin-bottom:8px;">
        <span class="name" style="color:${colors[i % colors.length]}">队伍 ${String.fromCharCode(65 + i)}</span>
        <span class="val muted">${members.length}/${per}</span>
      </div>
      <div class="players" data-tid="${tid}"></div>
    `;
    const memberWrap = wrap.querySelector('.players');
    if (memberPlayers.length === 0) {
      memberWrap.innerHTML = '<div class="muted" style="padding:6px;font-size:12px;">空位</div>';
    } else {
      memberPlayers.forEach(p => {
        const el = document.createElement('div');
        el.className = 'player';
        el.innerHTML = `<div class="ava">${p.avatar}</div><div class="meta"><div class="nick">${p.nickname}</div></div>`;
        el.style.cursor = 'pointer';
        el.addEventListener('click', () => removeFromTeam(p.id));
        memberWrap.appendChild(el);
      });
    }
    teamsList.appendChild(wrap);
  }

  // 更新提示
  $('#teamsHint').textContent = per === 1 ? '单打：每队 1 人' : '双打：每队 2 人';
}

function assignToFirstTeam(uid) {
  const per = perTeamSize({ type: window._battleType || 'singles' });
  for (let i = 0; i < teamCount; i++) {
    const tid = `team_${i}`;
    if ((teamsState[tid] || []).length < per) {
      // 先从其他队伍移除（防止重复）
      removeFromTeam(uid);
      teamsState[tid].push(uid);
      renderTeamsUI({ type: window._battleType }, playersCache);
      return;
    }
  }
  toast('所有队伍已满，请增加队伍数量');
}

function removeFromTeam(uid) {
  Object.keys(teamsState).forEach(tid => {
    teamsState[tid] = (teamsState[tid] || []).filter(u => u !== uid);
  });
  renderTeamsUI({ type: window._battleType }, playersCache);
}

// 分配模式卡片切换
$$('#assignGrid .type-card').forEach(card => {
  card.addEventListener('click', async () => {
    const mode = card.dataset.mode;
    if (mode === localMode) return;
    localMode = mode;
    $$('#assignGrid .type-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    try {
      await API.setAssignMode(BID, mode);
      toast(mode === 'free' ? '已切换为自由对战，请组队' : '已切换为随机分配');
      if (mode === 'free') {
        $('#teamsPanel').classList.remove('hidden');
        $('#genderRulePanel').classList.add('hidden');
        renderTeamsUI({ type: window._battleType }, playersCache);
      } else {
        $('#teamsPanel').classList.add('hidden');
        $('#genderRulePanel').classList.remove('hidden');
        buildGenderRuleChips(window._battleType);
      }
    } catch (e) {
      toast(e.message, true);
      // 回滚
      localMode = mode === 'free' ? 'random' : 'free';
      $$('#assignGrid .type-card').forEach(c => {
        c.classList.toggle('selected', c.dataset.mode === localMode);
      });
    }
  });
});

// 队伍数量增减
$('#teamMinusBtn').addEventListener('click', () => {
  if (teamCount <= 2) { toast('至少需要 2 支队伍'); return; }
  // 移除最后一只队伍的成员回到池
  const tid = `team_${teamCount - 1}`;
  delete teamsState[tid];
  teamCount--;
  renderTeamsUI({ type: window._battleType }, playersCache);
});
$('#teamPlusBtn').addEventListener('click', () => {
  if (teamCount >= 6) { toast('最多 6 支队伍'); return; }
  teamCount++;
  renderTeamsUI({ type: window._battleType }, playersCache);
});

// 保存队伍配置
$('#saveTeamsBtn').addEventListener('click', async () => {
  const btn = $('#saveTeamsBtn');
  btn.disabled = true;
  btn.textContent = '保存中…';
  try {
    await API.setTeams(BID, teamsState);
    toast('队伍配置已保存');
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '保存队伍配置';
  }
});

// 加入对战
$('#joinBtn').addEventListener('click', async () => {
  const btn = $('#joinBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading"></span> 加入中…';
  try {
    await API.joinBattle(BID);
    toast('已加入对战');
    await refresh();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = '加入对战';
  }
});

// 开始对战
$('#startBtn').addEventListener('click', async () => {
  const btn = $('#startBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading"></span> 编排中…';
  try {
    // 自由对战：先保存队伍配置再开始
    if (localMode === 'free') {
      await API.setTeams(BID, teamsState);
    }
    const res = await API.startBattle(BID);
    if (res.gender_fallback) {
      toast('性别人数不足，已自动降级为普通分配', true);
    } else {
      toast('对战开始！');
    }
    setTimeout(() => { location.href = `matches.html?id=${BID}`; }, 1000);
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
    btn.textContent = '开始对战 →';
  }
});

// 左上角 logo 点击返回首页
const _brand = $('.brand');
if (_brand) {
  _brand.style.cursor = 'pointer';
  _brand.addEventListener('click', () => { location.href = 'index.html'; });
}

// 启动轮询
refresh();
pollTimer = setInterval(refresh, 2500);

// 昵称修改后立即刷新页面数据
function onNicknameUpdated() { refresh(); }

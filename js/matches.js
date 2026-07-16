// LETSLAY · 对战列表 + 记分覆盖层（含上滑退出）

const BID = param('id');
if (!BID) location.href = 'index.html';

let pollTimer = null;
let playersMap = {};   // uid -> player
let currentMatch = null; // 当前记分的 match

// ---------- 列表加载 ----------
async function loadMatches() {
  try {
    const data = await API.getMatches(BID);
    playersMap = {};
    data.players.forEach(p => { playersMap[p.id] = p; });
    renderBoard(data);
  } catch (e) {
    $('#matchList').innerHTML = `<div class="empty"><div class="big">加载失败</div><div>${e.message}</div></div>`;
  }
}

function renderBoard(data) {
  const { battle, matches, fairness, players } = data;
  // 顶栏 - 显示当前用户（异步取自己的身份）
  API.me().then(me => {
    if (me && me.id) {
      applyUserToChip(me);
    } else if (players.length) {
      applyUserToChip(players[0]);
    }
  }).catch(() => {
    if (players.length) {
      applyUserToChip(players[0]);
    }
  });
  $('#typeTag').textContent = battle.type === 'singles' ? '单打 1v1' : '双打 2v2';
  const bestOfLabel = battle.best_of === 1 ? '一局定胜负' : '三局两胜';
  $('#matchesTag').textContent = `${battle.total_matches} 场 · ${bestOfLabel} · ${battle.game_point}分制`;
  $('#statusText').textContent = battle.status === 'ongoing' ? '对战进行中' : '对战已结束';
  const done = matches.filter(m => m.status === 'done').length;
  $('#progressTag').textContent = `${done} / ${matches.length}`;
  if (fairness && fairness.appearances) {
    $('#fairnessTag').textContent = `出场均衡 · ${fairness.min}~${fairness.max} 场/人${fairness.balanced ? ' ✓' : ''}`;
  }

  // 渲染参赛玩家（可加好友）
  renderMatchPlayers(players);

  const list = $('#matchList');
  list.innerHTML = '';
  if (!matches.length) {
    list.innerHTML = `<div class="empty"><div class="big">暂无对战</div></div>`;
    return;
  }
  matches.forEach((m, i) => {
    const row = document.createElement('div');
    row.className = 'match-row' + (m.status === 'live' ? ' live' : '') + (m.status === 'done' ? ' done' : '');
    const teamA = m.team_a.map(uid => playersMap[uid]).filter(Boolean);
    const teamB = m.team_b.map(uid => playersMap[uid]).filter(Boolean);
    const aWin = m.status === 'done' && m.game_a > m.game_b;
    const bWin = m.status === 'done' && m.game_b > m.game_a;

    row.innerHTML = `
      <div class="idx">${String(i + 1).padStart(2, '0')}</div>
      <div class="teams">
        <div class="team ${aWin ? 'win' : ''}">
          ${teamA.map(p => `<div class="mini-ava">${p.avatar}</div>`).join('')}
          <span class="pnames">${teamA.map(p => p.nickname).join(' / ') || '—'}</span>
          <span class="pscore">${m.game_a}</span>
        </div>
        <span class="versus">VS</span>
        <div class="team ${bWin ? 'win' : ''}">
          ${teamB.map(p => `<div class="mini-ava">${p.avatar}</div>`).join('')}
          <span class="pnames">${teamB.map(p => p.nickname).join(' / ') || '—'}</span>
          <span class="pscore">${m.game_b}</span>
        </div>
      </div>
      <button class="score-btn ${m.status === 'pending' ? 'go' : m.status === 'live' ? 'live' : 'done'}" data-mid="${m.id}">
        ${m.status === 'pending' ? '记分' : m.status === 'live' ? '继续' : '查看'}
      </button>
    `;
    list.appendChild(row);
  });

  // 绑定记分按钮
  $$('.score-btn').forEach(btn => {
    btn.addEventListener('click', () => openScoring(btn.dataset.mid));
  });

  // 全部比完 → 显示排名面板
  const allDone = matches.length > 0 && matches.every(m => m.status === 'done');
  if (allDone) {
    loadRanking();
  } else {
    $('#rankingPanel').style.display = 'none';
  }
}

// ---------- 参赛玩家（可加好友） ----------
async function renderMatchPlayers(players) {
  const container = $('#matchPlayers');
  if (!container) return;
  // 游客不显示好友按钮
  if (!isLoggedIn()) {
    container.innerHTML = players.map(p => `
      <div style="display:flex;align-items:center;gap:6px;background:var(--bg-2);border:1px solid var(--line);border-radius:20px;padding:4px 10px 4px 4px;">
        <div style="width:24px;height:24px;border-radius:50%;overflow:hidden;">${p.avatar}</div>
        <span style="font-size:12px;font-weight:500;">${escapeHtmlName(p.nickname)}</span>
      </div>
    `).join('');
    return;
  }
  let myId = null;
  try { const me = await API.me(); myId = me?.id; } catch {}
  let friends = [];
  try { const f = await API.getFriends(); friends = (f.friends || []).map(f => f.id); } catch {}

  container.innerHTML = players.map(p => {
    const isMe = p.id === myId;
    const isFriend = friends.includes(p.id);
    let actionHTML = '';
    if (isMe) {
      actionHTML = '<span style="font-size:11px;color:var(--muted);font-family:var(--font-mono);">我</span>';
    } else if (isFriend) {
      actionHTML = '<span style="font-size:11px;color:var(--lime);font-family:var(--font-mono);">好友</span>';
    } else {
      actionHTML = `<button class="add-friend-btn" data-uid="${p.id}" style="background:var(--bg-2);border:1px solid var(--line-strong);color:var(--fg-dim);font-size:11px;padding:3px 10px;border-radius:4px;cursor:pointer;font-family:var(--font-mono);">+好友</button>`;
    }
    return `
      <div style="display:flex;align-items:center;gap:6px;background:var(--bg-2);border:1px solid var(--line);border-radius:20px;padding:4px 10px 4px 4px;">
        <div style="width:24px;height:24px;border-radius:50%;overflow:hidden;">${p.avatar}</div>
        <span style="font-size:12px;font-weight:500;">${escapeHtmlName(p.nickname)}</span>
        ${actionHTML}
      </div>
    `;
  }).join('');

  $$('.add-friend-btn', container).forEach(btn => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.textContent = '...';
      try {
        const res = await API.sendFriendRequest(btn.dataset.uid);
        if (res.accepted) {
          btn.textContent = '好友';
          btn.style.color = 'var(--lime)';
          toast('已添加好友');
        } else {
          btn.textContent = '已请求';
          btn.style.color = 'var(--gold)';
          toast('好友请求已发送');
        }
      } catch (e) {
        toast(e.message, true);
        btn.disabled = false;
        btn.textContent = '+好友';
      }
    });
  });
}

function escapeHtmlName(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// ---------- 排名 ----------
async function loadRanking() {
  try {
    const data = await API.getRanking(BID);
    renderRanking(data.ranking);
  } catch (e) {
    console.error('排名加载失败', e);
  }
}

function renderRanking(ranking) {
  if (!ranking || !ranking.length) return;
  const panel = $('#rankingPanel');
  panel.style.display = '';
  $('#rankingTag').textContent = `${ranking.length} 人`;

  const list = $('#rankingList');
  list.innerHTML = '';
  ranking.forEach(r => {
    const row = document.createElement('div');
    row.className = 'ranking-row';
    const medal = r.rank === 1 ? '🥇' : r.rank === 2 ? '🥈' : r.rank === 3 ? '🥉' : '';
    row.innerHTML = `
      <div class="rank-num">${medal || r.rank}</div>
      <div class="rank-ava">${r.avatar}</div>
      <div class="rank-info">
        <div class="rank-name">${r.nickname}</div>
        <div class="rank-detail">赢 ${r.matches_won} 场 · 胜 ${r.games_won} 局</div>
      </div>
      <div class="rank-score">${r.total_points}<span class="rank-unit">分</span></div>
    `;
    list.appendChild(row);
  });
}

// 返回首页
$('#homeBtn').addEventListener('click', () => { location.href = 'index.html'; });

// ---------- 记分覆盖层 ----------
const overlay = $('#overlay');
const dimmer = $('#dimmer');

async function openScoring(mid) {
  try {
    currentMatch = await API.getMatch(mid);
    fillScoring();
    dimmer.classList.add('open');
    overlay.classList.add('open');
    overlay.classList.remove('closing');
    // 启动记分轮询
    startScorePoll();
  } catch (e) {
    toast(e.message, true);
  }
}

let scorePollTimer = null;
function startScorePoll() {
  stopScorePoll();
  scorePollTimer = setInterval(async () => {
    if (!currentMatch || !overlay.classList.contains('open')) {
      stopScorePoll();
      return;
    }
    try {
      const fresh = await API.getMatch(currentMatch.id);
      // 仅在分数变化时刷新（避免打断手势）
      if (fresh.score_a !== currentMatch.score_a || fresh.score_b !== currentMatch.score_b ||
          fresh.game_a !== currentMatch.game_a || fresh.game_b !== currentMatch.game_b ||
          fresh.status !== currentMatch.status) {
        currentMatch = fresh;
        fillScoring();
      }
    } catch {}
  }, 2500);
}
function stopScorePoll() {
  if (scorePollTimer) { clearInterval(scorePollTimer); scorePollTimer = null; }
}

function fillScoring() {
  const m = currentMatch;
  const teamA = m.team_a.map(uid => playersMap[uid]).filter(Boolean);
  const teamB = m.team_b.map(uid => playersMap[uid]).filter(Boolean);

  $('#ovTitle').textContent = `第 ${m.index + 1} 场`;
  const gameNum = m.game_a + m.game_b + 1;
  const gp = m.game_point || 21;
  const bestOfLabel = m.best_of === 1 ? '一局定胜负' : '三局两胜';
  $('#ovGameTag').textContent = m.status === 'done'
    ? `MATCH OVER · ${m.game_a} - ${m.game_b}`
    : `GAME ${gameNum} · ${bestOfLabel} · FIRST TO ${gp}`;

  $('#avaA').innerHTML = teamA.map(p => `<div class="ava">${p.avatar}</div>`).join('');
  $('#avaB').innerHTML = teamB.map(p => `<div class="ava">${p.avatar}</div>`).join('');
  $('#nameA').textContent = teamA.map(p => p.nickname).join(' / ') || 'A 队';
  $('#nameB').textContent = teamB.map(p => p.nickname).join(' / ') || 'B 队';
  $('#scoreA').textContent = m.score_a;
  $('#scoreB').textContent = m.score_b;
  $('#gameA').textContent = m.game_a;
  $('#gameB').textContent = m.game_b;

  // 发球指示
  $('#sideA').classList.toggle('serving', m.server === 'a' && m.status !== 'done');
  $('#sideB').classList.toggle('serving', m.server === 'b' && m.status !== 'done');
  // 发球区位（偶数右区，奇数左区）
  const courtA = m.score_a % 2 === 0 ? '右区' : '左区';
  const courtB = m.score_b % 2 === 0 ? '右区' : '左区';
  $('#courtA').textContent = courtA;
  $('#courtB').textContent = courtB;

  // 比赛结束遮罩
  const done = m.status === 'done';
  const winnerSide = m.game_a > m.game_b ? 'a' : 'b';
  const winnerTeam = winnerSide === 'a' ? teamA : teamB;
  $('#doneA').classList.toggle('show', done && winnerSide === 'a');
  // B 队胜利时把遮罩挪到 B 侧
  const doneB = $('#doneA');
  if (done && winnerSide === 'b') {
    $('#sideB').appendChild(doneB);
  } else {
    $('#sideA').appendChild(doneB);
  }
  if (done) {
    $('#winnerName').textContent = winnerTeam.map(p => p.nickname).join(' / ');
    $('#finalScore').textContent = `${m.game_a} : ${m.game_b}`;
  }
}

// 点击加分
$('#sideA').addEventListener('click', () => scoreAction('point_a'));
$('#sideB').addEventListener('click', () => scoreAction('point_b'));

async function scoreAction(action) {
  if (!currentMatch) return;
  if (currentMatch.status === 'done' && action !== 'undo' && action !== 'reset') {
    toast('比赛已结束', true);
    return;
  }
  try {
    currentMatch = await API.score(currentMatch.id, action);
    fillScoring();
    if (action === 'point_a' || action === 'point_b') {
      // 若该场结束，刷新列表
      if (currentMatch.status === 'done') {
        loadMatches();
      }
    }
  } catch (e) {
    toast(e.message, true);
  }
}

$('#undoBtn').addEventListener('click', () => scoreAction('undo'));
$('#resetBtn').addEventListener('click', () => {
  if (confirm('确定重置本场比赛比分？')) scoreAction('reset');
});

// ---------- 上滑退出 ----------
function closeScoring() {
  stopScorePoll();
  overlay.classList.remove('open');
  overlay.classList.add('closing');
  dimmer.classList.remove('open');
  setTimeout(() => {
    overlay.classList.remove('closing');
    currentMatch = null;
    loadMatches(); // 退出时刷新列表
  }, 400);
}

$('#ovClose').addEventListener('click', closeScoring);
dimmer.addEventListener('click', closeScoring);

// 识别手表端：仅识别真正的可穿戴设备（手表），手机/平板一律 false
function isWatchClient() {
  const shortSide = Math.min(window.innerWidth, window.innerHeight);
  const ua = (navigator.userAgent || '').toLowerCase();
  // 1. UA 严格匹配 watchOS / watchKit / Android Wear / Galaxy Watch / Wear OS
  if (
    ua.includes('apple watch') ||
    ua.includes('watchos') ||
    ua.includes('watchkit') ||
    ua.includes('wear os') ||
    ua.includes('android wear') ||
    /galaxy watch/.test(ua) ||
    /sm-r\d{3}/.test(ua)
  ) return true;
  // 2. 屏幕短边 <= 220px（覆盖所有 Apple Watch：41mm=176, 45mm=198, Ultra=205；手机最低 320）
  if (shortSide <= 220) return true;
  // 3. 触摸点数兜底：Apple Watch / 小米手表 等穿戴设备 maxTouchPoints=1；手机/平板 = 5
  if (navigator.maxTouchPoints === 1 && shortSide <= 320) return true;
  return false;
}

// Watch 记分按钮：点击直接跳转到 watch.html 记分页（不区分设备类型）
const watchBtn = $('#watchBtn');
const goWatch = () => {
  if (!currentMatch) return;
  const url = `watch.html?m=${currentMatch.id}`;
  try { window.location.assign(url); }
  catch (e) { window.location.href = url; }
  // 兜底：1.5s 后仍未跳转则强制刷新
  setTimeout(() => {
    if (location.pathname.indexOf('watch.html') === -1) {
      window.location.replace(url);
    }
  }, 1500);
};
watchBtn.addEventListener('click', goWatch);
// 兜底：click 不响应时用 touchend
watchBtn.addEventListener('touchend', (e) => { e.preventDefault(); goWatch(); }, { passive: false });

// ESC 退出
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && overlay.classList.contains('open')) closeScoring();
});

// ---------- 启动 ----------
// 左上角 logo 点击返回首页
const _brand = $('.brand');
if (_brand) {
  _brand.style.cursor = 'pointer';
  _brand.addEventListener('click', () => { location.href = 'index.html'; });
}

loadMatches();
pollTimer = setInterval(loadMatches, 5000);

// 昵称修改后立即刷新页面数据
function onNicknameUpdated() { loadMatches(); }

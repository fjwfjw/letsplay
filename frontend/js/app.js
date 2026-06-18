// LETSLAY · 创建对战页逻辑

let state = {
  type: 'singles',
  players: 4,
  matches: 6,
  bestOf: 3,
  gamePoint: 21,
  battleId: null,
};

// 单/双打选择
$$('#typeGrid .type-card').forEach(card => {
  card.addEventListener('click', () => {
    $$('#typeGrid .type-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    state.type = card.dataset.type;
    rebuildPlayerChips();
  });
});

// 人数可选范围
function playerOptions() {
  if (state.type === 'singles') return [2, 3, 4, 5, 6, 8];
  return [4, 5, 6, 7, 8, 10, 12];
}
function matchOptions() {
  return [3, 4, 6, 8, 10, 12, 16, 20];
}

// 数字 chips（人数、场数）
function buildChips(containerId, options, current, key) {
  const wrap = $(`#${containerId}`);
  wrap.innerHTML = '';
  options.forEach(n => {
    const c = document.createElement('div');
    c.className = 'chip' + (n === current ? ' selected' : '');
    c.textContent = n;
    c.addEventListener('click', () => {
      state[key] = n;
      $(`#${key}Val`).textContent = n;
      buildChips(containerId, options, n, key);
    });
    wrap.appendChild(c);
  });
}

// 带 label 的 chips（局制、比分制）
function buildLabeledChips(containerId, options, current, key, valLabel) {
  const wrap = $(`#${containerId}`);
  wrap.innerHTML = '';
  options.forEach(opt => {
    const c = document.createElement('div');
    c.className = 'chip' + (opt.value === current ? ' selected' : '');
    c.textContent = opt.label;
    c.style.minWidth = '70px';
    c.addEventListener('click', () => {
      state[key] = opt.value;
      $(`#${key}Val`).textContent = opt.label;
      buildLabeledChips(containerId, options, opt.value, key, valLabel);
    });
    wrap.appendChild(c);
  });
}

function rebuildPlayerChips() {
  const opts = playerOptions();
  if (!opts.includes(state.players)) state.players = opts[0];
  $(`#playersVal`).textContent = state.players;
  buildChips('playersChips', opts, state.players, 'players');
}

buildChips('matchesChips', matchOptions(), state.matches, 'matches');
rebuildPlayerChips();

// 局制选项
const bestOfOptions = [
  { value: 1, label: '一局定胜负' },
  { value: 3, label: '三局两胜' },
];
buildLabeledChips('bestOfChips', bestOfOptions, state.bestOf, 'bestOf');

// 比分制选项
const gamePointOptions = [
  { value: 15, label: '15 分' },
  { value: 21, label: '21 分' },
];
buildLabeledChips('gamePointChips', gamePointOptions, state.gamePoint, 'gamePoint');

// 创建对战
$('#createBtn').addEventListener('click', async () => {
  const btn = $('#createBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading"></span> 创建中…';
  try {
    const res = await API.createBattle(state.type, state.players, state.matches, state.bestOf, state.gamePoint);
    state.battleId = res.battle.id;
    showShareStep(res.battle.id);
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
    btn.textContent = '创建对战 →';
  }
});

function showShareStep(bid) {
  // 步骤切换
  $('#step1').classList.replace('active', 'done');
  $('#line1').classList.add('done');
  $('#step2').classList.add('active');
  $('#configPanel').classList.add('hidden');
  const sp = $('#sharePanel');
  sp.classList.remove('hidden');
  sp.classList.add('fade-in');

  // 分享链接
  const url = `${location.origin}/battle.html?id=${bid}`;
  $('#shareLink').textContent = url;

  // 复制按钮
  const doCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      toast('邀请链接已复制');
    } catch {
      // 兜底
      const ta = document.createElement('textarea');
      ta.value = url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      toast('邀请链接已复制');
    }
  };
  $('#copyBtn').onclick = doCopy;
  $('#copyBtn2').onclick = doCopy;

  $('#enterLobbyBtn').onclick = () => {
    location.href = `/battle.html?id=${bid}`;
  };
}

// 初始化用户身份
renderUserChip();

// ---------- 房间抽屉 ----------
const roomsBtn = $('#roomsBtn');
const drawer = $('#roomsDrawer');
const drawerMask = $('#drawerMask');
const drawerClose = $('#drawerClose');
const drawerList = $('#drawerList');
const drawerSub = $('#drawerSub');
const roomsDot = $('#roomsDot');

let roomsLoaded = false;
let roomsTimer = null;

function openDrawer() {
  drawer.hidden = false;
  drawerMask.hidden = false;
  // 强制 reflow 后过渡
  void drawer.offsetWidth;
  drawer.classList.add('open');
  drawerMask.classList.add('show');
  document.body.style.overflow = 'hidden';
  loadRooms();
}
function closeDrawer() {
  drawer.classList.remove('open');
  drawerMask.classList.remove('show');
  document.body.style.overflow = '';
  setTimeout(() => {
    drawer.hidden = true;
    drawerMask.hidden = true;
  }, 300);
}

function formatAgo(ts) {
  const s = Math.floor(Date.now() / 1000) - ts;
  if (s < 60) return '刚刚';
  if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
  if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
  return Math.floor(s / 86400) + ' 天前';
}

async function loadRooms() {
  drawerList.innerHTML = '<div class="drawer-empty">加载中…</div>';
  try {
    const res = await API.listBattles();
    const list = res.battles || [];
    roomsLoaded = true;
    // 同步顶部红点
    const myRooms = list.filter(b => b.joined);
    roomsDot.hidden = myRooms.length === 0;

    if (list.length === 0) {
      drawerList.innerHTML = '<div class="drawer-empty">暂无进行中的对战<br><br>快去创建一场吧</div>';
      drawerSub.textContent = '0 个房间';
      return;
    }
    drawerSub.textContent = `${list.length} 个房间 · ${myRooms.length} 个我已加入`;

    drawerList.innerHTML = list.map(b => roomCardHTML(b)).join('');
    // 绑定事件
    $$('.room-card', drawerList).forEach(card => {
      const bid = card.dataset.id;
      const joined = card.dataset.joined === '1';
      const live = card.dataset.live === '1';
      const canEnter = joined || (live && !card.dataset.waiting);
      card.addEventListener('click', () => {
        if (canEnter) {
          location.href = `/battle.html?id=${bid}`;
        } else {
          toast('只有对战的玩家才能加入');
        }
      });
    });
  } catch (e) {
    drawerList.innerHTML = `<div class="drawer-empty">${e.message || '加载失败'}</div>`;
  }
}

function roomCardHTML(b) {
  const isLive = b.status === 'ongoing';
  const isWaiting = b.status === 'waiting';
  const canEnter = b.joined || isLive; // 已加入任意阶段可进；进行中旁观
  const typeLabel = b.type === 'singles' ? '单打' : '双打';
  const bestOfLabel = b.best_of === 1 ? '一局' : '三局两胜';
  const tag = b.joined
    ? '<span class="room-tag joined">已加入</span>'
    : (isLive
        ? '<span class="room-tag live">进行中</span>'
        : '<span class="room-tag waiting">等待中</span>');

  const avatars = (b.players || []).slice(0, 5).map(p => `
    <div class="mini-ava" title="${p.nickname}">${avatarHTML(p.avatar)}</div>
  `).join('');
  const more = (b.players && b.players.length > 5)
    ? `<span class="mini-name">+${b.players.length - 5}</span>` : '';
  const cta = canEnter ? (b.joined ? '进入对战大厅' : '进入旁观') : '等待创建者开赛';

  return `
    <div class="room-card ${b.joined ? 'joined' : ''} ${isLive ? 'live' : ''} ${isWaiting ? 'waiting' : ''} ${canEnter ? '' : 'disabled'}"
         data-id="${b.id}" data-joined="${b.joined ? 1 : 0}" data-live="${isLive ? 1 : 0}" data-waiting="${isWaiting ? 1 : 0}">
      <div class="room-row1">
        <span class="room-id">#${b.id}</span>
        ${tag}
      </div>
      <div class="room-type">${typeLabel} · ${b.game_point} 分制 · ${bestOfLabel}</div>
      <div class="room-meta">
        <b>${b.total_matches}</b> 场 · 创建于 ${formatAgo(b.created_at)}
      </div>
      <div class="room-players">
        ${avatars}
        ${more}
        <span class="room-count"><b>${b.players_count}</b>/${b.max_players}</span>
      </div>
      <div class="room-cta">${cta}</div>
    </div>
  `;
}

roomsBtn.addEventListener('click', openDrawer);
drawerClose.addEventListener('click', closeDrawer);
drawerMask.addEventListener('click', closeDrawer);
// ESC 关闭
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
});
// 抽屉打开时定期刷新（最多每 5s）
drawer.addEventListener('transitionend', () => {
  if (drawer.classList.contains('open')) {
    clearInterval(roomsTimer);
    roomsTimer = setInterval(() => { if (drawer.classList.contains('open')) loadRooms(); }, 5000);
  } else {
    clearInterval(roomsTimer);
  }
});

// 后台静默轮询：检查红点
setInterval(async () => {
  try {
    const res = await API.listBattles();
    const my = (res.battles || []).filter(b => b.joined).length;
    roomsDot.hidden = my === 0;
  } catch {}
}, 15000);

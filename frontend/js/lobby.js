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

  // 顶栏用户
  const chip = $('#userChip');
  chip.innerHTML = `<div class="ava">${user.avatar}</div><span class="name">${user.nickname}</span>`;

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

  // 按钮区
  $('#joinBtn').classList.toggle('hidden', joined);
  $('#startBtn').classList.toggle('hidden', !is_creator);
  $('#waitNote').classList.toggle('hidden', !(joined && !is_creator));

  if (is_creator) {
    const minP = battle.type === 'singles' ? 2 : 4;
    const canStart = players.length >= minP;
    $('#startBtn').disabled = !canStart;
    $('#startBtn').textContent = canStart
      ? '开始对战 →'
      : `等待 ${minP} 人加入（当前 ${players.length}）`;
  }
}

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
    await API.startBattle(BID);
    toast('对战开始！');
    setTimeout(() => { location.href = `matches.html?id=${BID}`; }, 400);
  } catch (e) {
    toast(e.message, true);
    btn.disabled = false;
    btn.textContent = '开始对战 →';
  }
});

// 启动轮询
refresh();
pollTimer = setInterval(refresh, 2500);

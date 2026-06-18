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

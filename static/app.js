/* ================= 欢乐斗地主 · 前端逻辑 ================= */

const $ = (s) => document.querySelector(s);

const SUITS = ['\u2660', '\u2665', '\u2663', '\u2666'];   // ♠ ♥ ♣ ♦
const NAMES = { 0: '你', 1: '电脑·小美', 2: '电脑·老张' };
const SHORT = { 0: '你', 1: '小美', 2: '老张' };

let S = null;              // 当前对局状态
let TOKEN = null;
let selected = new Set();  // 已选中的牌 id
let hintIdx = 0;
let pollTimer = null;
let lastHintKey = '';
let lastBalance = null;    // 用于余额变化动画
let stake = 100;           // 本局底注
let stakeOptions = [50, 100, 200, 500];

/* ---------------- 牌面工具 ---------------- */

const isJoker = (c) => c.rank >= 16;

function rankText(c) {
  if (c.rank === 16) return '小王';
  if (c.rank === 17) return '大王';
  return c.label;
}

function colorClass(c) {
  if (isJoker(c)) return c.rank === 17 ? 'red' : 'black';
  return (c.suit === 1 || c.suit === 3) ? 'red' : 'black';
}

function cardEl(c, cls) {
  const d = document.createElement('div');
  d.className = cls + ' ' + colorClass(c) + (isJoker(c) ? ' joker' : '');
  d.dataset.id = c.id;
  const sub = isJoker(c) ? '' : SUITS[c.suit];
  const big = isJoker(c) ? '王' : SUITS[c.suit];
  d.innerHTML = `<span class="r">${rankText(c)}</span>`
              + `<span class="s">${sub}</span>`
              + `<span class="big">${big}</span>`;
  if (cls === 'card') d.setAttribute('role', 'option');
  return d;
}

const fmt = (n) => Number(n || 0).toLocaleString('en-US');

/* ---------------- API ---------------- */

async function api(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let msg = '请求失败';
    try { msg = (await res.json()).detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

async function fetchState() {
  const res = await fetch(`/api/state?token=${TOKEN}`);
  if (!res.ok) throw new Error('状态获取失败');
  return res.json();
}

/* ---------------- 轮询 ---------------- */

function stopPoll() { clearTimeout(pollTimer); pollTimer = null; }

function schedulePoll(delay) {
  stopPoll();
  pollTimer = setTimeout(poll, delay == null ? 900 : delay);
}

async function poll() {
  if (!TOKEN) return;
  try {
    S = await fetchState();
    render();
    if (S.phase === 'over') { onOver(); return; }
    if (S.is_my_turn) return;           // 轮到我, 停止轮询
  } catch (e) {
    console.warn('poll', e);
  }
  schedulePoll();
}

/* ---------------- 动作 ---------------- */

async function startGame() {
  try {
    const r = await api('/api/new', { human_seat: 0, stake });
    TOKEN = r.token;
    S = r.state;
    selected.clear(); hintIdx = 0; lastHintKey = '';
    $('#result-mask').hidden = true;
    $('#start-mask').hidden = true;
    lastBalance = null;                 // 重新基准, 避免旧动画
    render();
    schedulePoll();
  } catch (e) {
    $('#start-status').textContent = '开局失败: ' + e.message;
    $('#start-status').style.color = '#ef9a93';
  }
}

async function doAction(path, body) {
  try {
    S = await api(path, Object.assign({ token: TOKEN }, body));
    selected.clear(); hintIdx = 0; lastHintKey = '';
    render();
    if (S.phase === 'over') { onOver(); return; }
    schedulePoll();
  } catch (e) {
    flashCenter(e.message, true);
  }
}

function onOver() {
  stopPoll();
  showResult();
}

/* ---------------- 渲染 ---------------- */

function flashCenter(text, isErr) {
  const el = $('#center-msg');
  el.textContent = text;
  el.style.color = isErr ? '#ffb3ac' : '';
  setTimeout(() => { el.style.color = ''; renderCenter(); }, 1800);
}

function renderScoreboard() {
  $('#sb-stake').textContent = fmt(S.stake || stake);
  $('#sb-base').textContent = S.landlord == null ? '—' : (S.base_score || '—');
  $('#sb-mult').textContent = 'x' + (S.multiplier || 1);
  // 本局总注额 = 底注 x 叫分 x 倍数 (未定地主前按倍数 1 估算)
  const base = S.landlord == null ? 1 : (S.base_score || 1);
  $('#sb-pot').textContent = S.landlord == null
    ? '—' : fmt((S.stake || stake) * base * (S.multiplier || 1));
}

function renderWallet() {
  const w = S.wallet;
  if (!w) return;
  const el = $('#wallet-balance');
  const box = $('#wallet-box');
  el.textContent = fmt(w.balance);

  if (lastBalance !== null && w.balance !== lastBalance) {
    box.classList.remove('flash-win', 'flash-lose');
    void box.offsetWidth;                 // 重启动画
    box.classList.add(w.balance > lastBalance ? 'flash-win' : 'flash-lose');
  }
  lastBalance = w.balance;
}

function renderBadge() {
  const b = $('#ai-badge');
  const banner = $('#llm-banner');
  if (!S.llm_enabled) {
    b.className = 'badge badge-warn';
    b.textContent = '规则AI模式';
    banner.hidden = true;
  } else if (S.llm_ready) {
    b.className = 'badge badge-on';
    b.textContent = '大模型驱动';
    banner.hidden = true;
  } else {
    b.className = 'badge badge-off';
    b.textContent = '模型未连接';
    banner.hidden = false;
  }
}

function renderBottom() {
  const box = $('#bottom-area');
  box.innerHTML = '';
  const cards = (S.bottom && S.bottom.length) ? S.bottom : null;
  for (let i = 0; i < 3; i++) {
    if (cards) {
      box.appendChild(cardEl(cards[i], 'mini'));
    } else {
      const d = document.createElement('div');
      d.className = 'mini';
      d.style.background = 'linear-gradient(#2b4b6b,#16324a)';
      d.style.borderColor = '#3a5a78';
      d.innerHTML = '<span class="big" style="color:#8ab4d8;right:auto;left:50%;transform:translateX(50%);bottom:16px">?</span>';
      box.appendChild(d);
    }
  }
}

function renderSeat(seat) {
  const box = $('#seat-' + seat);
  const av = box.querySelector('.avatar-box');
  const tag = box.querySelector('.role-tag');
  const cnt = box.querySelector('.pcount b');
  const dots = box.querySelector('.thinking-dots');

  cnt.textContent = S.counts[seat];
  tag.hidden = (S.landlord !== seat);
  av.classList.toggle('active', S.current === seat && S.phase !== 'over');
  dots.hidden = !(S.thinking === seat);

  const area = $('#play-' + seat);
  area.innerHTML = '';
  const p = S.round_plays ? S.round_plays[String(seat)] : null;
  if (!p) return;
  if (p.pass) {
    area.classList.add('pass');
    area.innerHTML = '<div class="passtag">不要</div>';
  } else {
    area.classList.remove('pass');
    const wrap = document.createElement('div');
    wrap.style.display = 'flex';
    p.cards.forEach((c) => wrap.appendChild(cardEl(c, 'mini')));
    area.appendChild(wrap);
  }
}

function renderMyPlay() {
  const area = $('#play-0');
  area.innerHTML = '';
  const p = S.round_plays ? S.round_plays['0'] : null;
  if (!p) { area.classList.remove('pass'); return; }
  if (p.pass) {
    area.classList.add('pass');
    area.innerHTML = '<div class="passtag">不要</div>';
  } else {
    area.classList.remove('pass');
    p.cards.forEach((c) => area.appendChild(cardEl(c, 'mini')));
  }
}

function renderHand() {
  const box = $('#hand');
  box.innerHTML = '';
  const canPick = S.phase === 'play' && S.is_my_turn;
  S.hand.forEach((c) => {
    const el = cardEl(c, 'card');
    if (selected.has(c.id)) {
      el.classList.add('sel');
      el.setAttribute('aria-selected', 'true');
    } else {
      el.setAttribute('aria-selected', 'false');
    }
    if (!canPick) el.classList.add('dim');
    el.addEventListener('click', () => {
      if (!canPick) return;
      if (selected.has(c.id)) selected.delete(c.id);
      else selected.add(c.id);
      renderHand(); renderActions();
    });
    box.appendChild(el);
  });
  $('#my-count').textContent = S.hand.length;
  $('#my-role').hidden = (S.landlord !== 0);
}

function selRanks() {
  const map = new Map(S.hand.map((c) => [c.id, c]));
  return [...selected].map((id) => map.get(id)).filter(Boolean)
    .map((c) => c.rank).sort((a, b) => a - b);
}

function isValidSelection() {
  if (!selected.size) return false;
  if (!S.legal_moves) return false;
  const r = selRanks();
  return S.legal_moves.some((m) =>
    m.ranks.length === r.length && m.ranks.every((v, i) => v === r[i]));
}

function selectByRanks(ranks) {
  selected.clear();
  const need = {};
  ranks.forEach((r) => { need[r] = (need[r] || 0) + 1; });
  const taken = {};
  S.hand.forEach((c) => {
    if (need[c.rank] && (taken[c.rank] || 0) < need[c.rank]) {
      selected.add(c.id);
      taken[c.rank] = (taken[c.rank] || 0) + 1;
    }
  });
}

function clearSelection() { selected.clear(); }

function renderActions() {
  const box = $('#actions');
  box.innerHTML = '';

  if (S.phase === 'over') return;

  // ---- 叫分阶段 ----
  if (S.phase === 'bid') {
    if (S.is_my_turn) {
      (S.legal_bids || []).forEach((v) => {
        const b = document.createElement('button');
        b.className = 'btn' + (v === 0 ? ' btn-grey' : ' btn-gold');
        b.textContent = v === 0 ? '不叫' : v + ' 分';
        b.onclick = () => doAction('/api/bid', { value: v });
        box.appendChild(b);
      });
    } else {
      box.innerHTML = `<span class="hint-text">等待 ${NAMES[S.current]} 叫分…</span>`;
    }
    return;
  }

  // ---- 出牌阶段 ----
  if (!S.is_my_turn) {
    box.innerHTML = `<span class="hint-text">等待 ${NAMES[S.current]} 出牌…</span>`;
    return;
  }

  const moves = S.legal_moves || [];

  const bHint = document.createElement('button');
  bHint.className = 'btn btn-blue';
  bHint.textContent = '提示';
  bHint.disabled = moves.length === 0;
  bHint.onclick = () => { hintNext(); };
  box.appendChild(bHint);

  const bClear = document.createElement('button');
  bClear.className = 'btn btn-grey';
  bClear.textContent = '重选';
  bClear.disabled = selected.size === 0;
  bClear.onclick = () => { clearSelection(); renderHand(); renderActions(); };
  box.appendChild(bClear);

  const ok = isValidSelection();
  const bPlay = document.createElement('button');
  bPlay.className = 'btn btn-gold';
  bPlay.textContent = ok ? `出牌 (${selected.size})` : '出牌';
  bPlay.disabled = !ok;
  bPlay.onclick = playSelected;
  box.appendChild(bPlay);

  const bPass = document.createElement('button');
  bPass.className = 'btn btn-grey';
  bPass.textContent = '不要';
  bPass.disabled = !!S.must_play;
  bPass.onclick = () => doAction('/api/play', { pass_: true });
  box.appendChild(bPass);
}

function hintNext() {
  const moves = (S && S.legal_moves) || [];
  if (!moves.length) return;
  if (hintIdx >= moves.length) hintIdx = 0;
  selectByRanks(moves[hintIdx].ranks);
  hintIdx = (hintIdx + 1) % moves.length;
  renderHand(); renderActions();
}

function playSelected() {
  if (!isValidSelection()) return;
  const ids = S.hand.filter((c) => selected.has(c.id)).map((c) => c.id);
  doAction('/api/play', { cards: ids });
}

function renderCenter() {
  const el = $('#center-msg');
  const tip = $('#turn-tip');
  if (S.phase === 'over') {
    el.textContent = '本局结束';
    tip.hidden = true;
    return;
  }
  if (S.thinking != null) {
    el.textContent = `${NAMES[S.thinking]} 正在思考…`;
    tip.hidden = true;
    return;
  }
  if (S.is_my_turn) {
    el.textContent = S.phase === 'bid' ? '该你叫分了' : '轮到你出牌';
    tip.textContent = S.phase === 'bid' ? '请选择叫分' : '请出牌';
    tip.hidden = false;
  } else {
    el.textContent = `等待 ${NAMES[S.current]}…`;
    tip.hidden = true;
  }
}

function renderLog() {
  const box = $('#log');
  const items = S.log || [];
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.innerHTML = '';
  items.forEach((e) => {
    const d = document.createElement('div');
    d.className = 'li k-' + (e.kind || 'info');
    d.textContent = e.text;
    box.appendChild(d);
  });
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function renderHistory() {
  const box = $('#history');
  const items = (S.wallet && S.wallet.history) || [];
  box.innerHTML = '';
  items.forEach((h) => {
    const d = document.createElement('div');
    d.className = 'his-row';
    const sign = h.delta > 0 ? '+' : '';
    d.innerHTML = `<span class="d ${h.delta >= 0 ? 'plus' : 'minus'}">${sign}${h.delta}</span>`
                + `<span class="s">${h.summary || ''}</span>`
                + `<span class="d">${fmt(h.balance)}</span>`;
    box.appendChild(d);
  });
}

function renderBubbles() {
  [1, 2].forEach((seat) => {
    const el = $('#bubble-' + seat);
    const s = S && S.says ? S.says[String(seat)] : null;
    if (s && (Date.now() / 1000 - s.t) < 6) {
      if (el.textContent !== s.text) el.textContent = s.text;
      el.hidden = false;
    } else {
      el.hidden = true;
    }
  });
}

function render() {
  if (!S) return;
  renderScoreboard();
  renderWallet();
  renderBadge();
  renderBottom();
  renderSeat(1);
  renderSeat(2);
  renderMyPlay();
  renderHand();
  renderActions();
  renderCenter();
  renderLog();
  renderHistory();
  renderBubbles();

  const key = TOKEN + ':' + (S.turn_no || 0) + ':' + S.current + ':' + S.phase;
  if (key !== lastHintKey) { lastHintKey = key; hintIdx = 0; }
}

/* ---------------- 结算 ---------------- */

function showResult() {
  const d = S.delta || [0, 0, 0];
  const myDelta = d[0] || 0;
  const myWin = myDelta > 0;

  const t = $('#result-title');
  t.textContent = myWin ? '恭喜获胜!' : (myDelta === 0 ? '平局' : '本局告负');
  t.className = 'result-title ' + (myWin ? 'win' : 'lose');

  const landlordWin = (S.winner === S.landlord);
  $('#result-sub').textContent =
    `${landlordWin ? '地主' : '农民'}获胜`
    + ` · 底注 ${fmt(S.stake || stake)} × 叫分 ${S.base_score} × 倍数 ${S.multiplier}`
    + (S.spring ? ' · 春天再翻倍' : '');

  const td = $('#token-delta');
  td.className = 'token-delta ' + (myDelta >= 0 ? 'plus' : 'minus');
  td.innerHTML = `${myDelta >= 0 ? '+' : ''}${fmt(myDelta)}<small>token</small>`;

  const body = $('#result-body');
  body.innerHTML = '';
  [0, 1, 2].forEach((seat) => {
    const tr = document.createElement('tr');
    const role = (seat === S.landlord) ? '地主' : '农民';
    const val = d[seat] || 0;
    tr.innerHTML = `<td>${NAMES[seat]}</td><td>${role}</td>`
      + `<td class="${val >= 0 ? 'plus' : 'minus'}">${val >= 0 ? '+' : ''}${fmt(val)}</td>`;
    body.appendChild(tr);
  });

  const bal = S.wallet ? S.wallet.balance : null;
  $('#result-balance').innerHTML = bal == null ? '' : `当前余额 <b>${fmt(bal)}</b> token`;

  $('#result-mask').hidden = false;
  $('#btn-again').focus();
}

/* ---------------- 底注选择 ---------------- */

function renderStakeOpts() {
  const box = $('#stake-opts');
  box.innerHTML = '';
  stakeOptions.forEach((v) => {
    const b = document.createElement('button');
    b.className = 'stake-opt' + (v === stake ? ' on' : '');
    b.textContent = fmt(v);
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(v === stake));
    b.onclick = () => { stake = v; renderStakeOpts(); };
    box.appendChild(b);
  });
}

/* ---------------- 健康检查 ---------------- */

async function checkHealth() {
  const el = $('#start-status');
  try {
    const [h, w] = await Promise.all([
      fetch('/api/health').then((r) => r.json()),
      fetch('/api/wallet').then((r) => r.json()),
    ]);
    if (w.stake_options) stakeOptions = w.stake_options;
    if (w.balance != null) { $('#wallet-balance').textContent = fmt(w.balance); lastBalance = w.balance; }
    renderStakeOpts();

    if (h.llm_enabled && h.llm_ready) {
      el.innerHTML = `\u2705 大模型已就绪 (${h.llm_url})，AI 将完全由本地大模型驱动`;
      el.style.color = '#7fd39a';
    } else if (h.llm_enabled) {
      el.innerHTML = '\u26a0 大模型未连接，请先运行「启动模型服务.bat」— 否则 AI 以规则兜底';
      el.style.color = 'var(--warn)';
    } else {
      el.innerHTML = '\u2139 当前为纯规则 AI 模式';
      el.style.color = 'var(--text-dim)';
    }
  } catch (e) {
    el.textContent = '本地服务异常';
    el.style.color = '#ef9a93';
  }
}

/* ---------------- 键盘操作 ---------------- */

document.addEventListener('keydown', (e) => {
  if (!S || S.phase === 'over' || !S.is_my_turn) return;
  if (e.target && /^(input|textarea)$/i.test(e.target.tagName)) return;
  if (e.key === 'Enter') { e.preventDefault(); playSelected(); }
  else if (e.key === 'p' || e.key === 'P') {
    if (!S.must_play) doAction('/api/play', { pass_: true });
  }
  else if (e.key === 'h' || e.key === 'H') { hintNext(); }
});

/* ---------------- 事件绑定 ---------------- */

$('#btn-start').onclick = startGame;
$('#btn-again').onclick = async () => {
  // 余额不足时回开始弹窗选底注 / 重置
  $('#result-mask').hidden = true;
  try {
    const w = await fetch('/api/wallet').then((r) => r.json());
    if (w.can_play === false) {
      $('#start-status').textContent = `余额仅剩 ${fmt(w.balance)} token，请重置钱包后再战`;
      $('#start-status').style.color = '#ef9a93';
      $('#start-mask').hidden = false;
      return;
    }
  } catch (e) { /* ignore */ }
  startGame();
};
$('#btn-new').onclick = () => { stopPoll(); startGame(); };

$('#btn-settings').onclick = () => {
  const sb = $('#sidebar');
  sb.hidden = !sb.hidden;
  $('#btn-show-side').hidden = !sb.hidden;
};
$('#btn-toggle-side').onclick = () => {
  $('#sidebar').hidden = true;
  $('#btn-show-side').hidden = false;
};
$('#btn-show-side').onclick = () => {
  $('#sidebar').hidden = false;
  $('#btn-show-side').hidden = true;
};
$('#btn-wallet-reset').onclick = async () => {
  if (!confirm('确定把钱包重置为初始 token 吗？战绩与历史将被清空。')) return;
  const r = await api('/api/wallet/reset');
  lastBalance = null;
  if (S) { S.wallet = await fetch('/api/wallet'); renderWallet(); renderHistory(); }
  flashCenter(r.message);
};

$('#opt-llm').onchange = async (e) => {
  await api('/api/config', { use_llm: e.target.checked });
  const h = await fetch('/api/health').then((r) => r.json());
  S.llm_enabled = h.llm_enabled; S.llm_ready = h.llm_ready;
  renderBadge();
};
$('#opt-say').onchange = (e) => api('/api/config', { allow_say: e.target.checked });

setInterval(renderBubbles, 800);
setInterval(() => { if (S && S.is_my_turn && S.phase !== 'over') renderCenter(); }, 1500);

renderStakeOpts();
checkHealth();

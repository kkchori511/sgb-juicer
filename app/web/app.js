(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let api = null;
  let info = {};
  let cfg = {};
  let ys = { year: 0, years: [] }; // year_state
  let dataDir = ''; // 지금 쓰는 자료 폴더(시작 설정·오류 안내에 보여 줌)
  let dash = null;
  let panel = 'dashboard';
  let dashSel = null;
  let semester = 1;
  let rosterSel = null;
  let showInactive = true;
  let runCost = 0;

  const PANEL_TITLES = {
    dashboard: '현황판', inbox: '자료 인박스', records: '항목별 기록', tagrec: '태그별 기록', export: '검토·내보내기',
    roster: '명렬·담당 관리', tags: '태그 관리', prompts: '프롬프트', standards: '성취기준·활동 개요', settings: '설정', notice: '유의 사항', guide: '사용 안내',
  };
  const HELP = { dashboard: 'g-dashboard', inbox: 'g-inbox', records: 'g-records', tagrec: 'g-tagrec', export: 'g-export',
    roster: 'g-roster', tags: 'g-settings', prompts: 'g-settings', standards: 'g-standards', settings: 'g-settings', notice: 'g-flow' };
  function openGuide(anchor) {
    showPanel('guide');
    const target = document.getElementById(anchor || 'g-flow');
    if (!target) return;
    const body = $('guideBody');
    body.scrollTop = target.offsetTop - body.offsetTop - 8;
    document.querySelectorAll('#guideToc a').forEach((a) => a.classList.toggle('on', a.getAttribute('href') === `#${anchor}`));
    target.classList.add('flash');
    setTimeout(() => target.classList.remove('flash'), 1400);
  }
  const ITEM_LABELS = { autonomy: '자율', career: '진로', behavior: '행특', subject: '세특', club: '동아리' };
  const ITEM_FULL = { autonomy: '자율활동', career: '진로활동', behavior: '행동특성 및 종합의견', subject: '과목 세특(기본)', club: '동아리활동(기본)' };
  const STATUS = {
    none: { icon: '○', text: '기록 없음', cls: 'st-none' },
    progress: { icon: '◐', text: '입력 중', cls: 'st-progress' },
    final: { icon: '◑', text: '최종안 있음', cls: 'st-final' },
    closed: { icon: '●', text: '마감', cls: 'st-closed' },
  };
  const KIND_LABEL = { homeroom: '담임반', subject: '과목', club: '동아리' };

  // ---------- 유틸 ----------
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k === 'html') e.innerHTML = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (k === 'value') e.value = v;
      else if (k === 'checked' || k === 'disabled' || k === 'selected') e[k] = !!v;
      else if (v !== false && v !== null && v !== undefined) e.setAttribute(k, v === true ? '' : v);
    });
    (children || []).forEach((c) => c !== null && c !== undefined && c !== false && e.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c));
    return e;
  }
  // append()는 null을 'null' 글자로 넣으므로 빈 값은 걸러 낸다
  function addTo(parent, ...xs) { parent.append(...xs.filter((x) => x !== null && x !== undefined && x !== false)); }
  // 태그 색: 태그 번호로 파스텔 6색 중 하나를 고정 배정(보라 계열·상태 색 회색·초록·파랑·노랑은 쓰지 않음)
  const tagC = (id) => (id ? ` tc tc${Math.abs(id) % 6}` : '');
  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }
  // 대상별로 따로 미뤄 두는 저장(성취기준·프롬프트). 다른 대상의 저장을 취소하지 않고,
  // 화면·학년도를 바꾸거나 창을 닫기 전에 모두 마저 저장한다.
  const pendingSaves = new Map();
  function saveLater(key, fn, ms) {
    const old = pendingSaves.get(key);
    if (old) clearTimeout(old.t);
    pendingSaves.set(key, { fn, t: setTimeout(() => runPending(key), ms) });
  }
  // 같은 대상의 저장은 순서대로(앞 저장이 끝난 뒤 다음 저장). 실패하면 그 저장을 대기 목록에 남겨 둔다:
  // 화면·담당을 바꾸거나 창을 닫을 때 다시 시도하고, 그동안 이동을 막아 쓰던 글을 잃지 않게 한다.
  const savingByKey = new Map();
  async function runPending(key) {
    const prev = savingByKey.get(key);
    if (prev) await prev.catch(() => false);
    const job = pendingSaves.get(key);
    if (!job) return true;
    pendingSaves.delete(key);
    clearTimeout(job.t);
    saveInflight += 1;
    const p = Promise.resolve().then(() => job.fn());
    savingByKey.set(key, p);
    try {
      let r = false;
      try { r = !!(await p); } catch (e) { r = false; }
      if (!r) {
        markSaveFailed();
        if (!pendingSaves.has(key)) pendingSaves.set(key, { fn: job.fn, t: null, failed: true });
      }
      return r;
    } finally {
      if (savingByKey.get(key) === p) savingByKey.delete(key);
      saveInflight -= 1;
      refreshSaveState();
    }
  }
  function dropPending(key) {
    const job = pendingSaves.get(key);
    if (job) { clearTimeout(job.t); pendingSaves.delete(key); }
  }
  async function flushPending() {
    let ok = true;
    for (const key of [...pendingSaves.keys()]) ok = (await runPending(key)) && ok;
    return ok;
  }
  const SAVE_FAIL_MSG = '저장하지 못한 내용이 있어 화면을 그대로 두었습니다. 다시 시도하거나 내용을 복사해 두세요.';
  async function saveAllPending() {
    const a = await flushFinal();
    const b = await flushPending();
    const c = await flushCfg();
    const d = await flushTagView();
    return a && b && c && d;
  }
  // 학생·항목·학년도·화면을 바꾸기 전에: 저장에 실패하면 false(지금 화면을 그대로 둔다)
  async function leaveOk() {
    if (await saveAllPending()) return true;
    toast(SAVE_FAIL_MSG, 5000);
    return false;
  }
  function fmtCredit(v) {
    if (v === null || v === undefined || isNaN(v)) return '-';
    if (v === 0) return '0';
    return Math.abs(v) < 0.01 ? v.toFixed(5) : v.toFixed(4);
  }
  function todayStr() { return info.today || new Date().toISOString().slice(0, 10); }
  function daysUntil(date) {
    const a = new Date(todayStr() + 'T00:00:00'), b = new Date(date + 'T00:00:00');
    return Math.round((b - a) / 86400000);
  }
  function md(date) { const [, m, d] = date.split('-'); return `${+m}/${+d}`; }
  function schoolYear() { const d = new Date(); return d.getMonth() + 1 >= 3 ? d.getFullYear() : d.getFullYear() - 1; }
  function colName(i) { let s = ''; i += 1; while (i > 0) { const m = (i - 1) % 26; s = String.fromCharCode(65 + m) + s; i = Math.floor((i - 1) / 26); } return s; }
  // ---------- 저장 상태(상단 가운데) ----------
  // 저장됨(초록) / 저장 중…(남은 저장·진행 중) / 저장 안 됨(빨강, 실패) — 누르면 마지막 저장 시각
  let lastSaved = null;
  let saveFailed = false;
  let saveInflight = 0;
  function markSaved() {
    lastSaved = new Date();
    saveFailed = false;
    refreshSaveState();
  }
  function markSaveFailed() { saveFailed = true; refreshSaveState(); }
  function refreshSaveState() {
    const b = $('savedAt');
    if (!b) return;
    const busy = saveInflight > 0 || pendingSaves.size > 0 || Object.keys(cfgPending).length > 0 || draftDirty();
    const st = saveFailed ? 'fail' : busy ? 'busy' : 'ok';
    const text = st === 'fail' ? `저장 안 됨${lastSaved ? ` · 마지막 ${clock(lastSaved)}` : ''}` : st === 'busy' ? '저장 중…' : `저장됨${lastSaved ? ` / ${dayTime(lastSaved)}` : ''}`;
    if (b.textContent === text && b.dataset.st === st) return;
    b.dataset.st = st;
    b.className = `save-state ${st}`;
    b.textContent = text;
  }
  const pad2 = (n) => String(n).padStart(2, '0');
  const clock = (d) => `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  const dayTime = (d) => `${d.getMonth() + 1}월 ${d.getDate()}일(${'일월화수목금토'[d.getDay()]}) ${clock(d)}`;
  // 수동 저장: 남은 저장(최종안·성취기준·프롬프트·설정)을 마치고 자료 파일에 기록한다
  async function manualSave() {
    saveInflight += 1;
    refreshSaveState();
    try {
      const okAll = await saveAllPending();
      const r = okAll && await call('save_now');
      if (r) { markSaved(); toast('저장했습니다.'); } else markSaveFailed();
    } finally { saveInflight -= 1; refreshSaveState(); }
  }

  function toast(msg, ms) {
    const t = $('toast');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { t.hidden = true; }, ms || 2600);
  }
  // 파이썬 호출: 실패하면 알림 창을 띄우고 null을 돌려준다.
  async function call(method, ...args) {
    let r;
    try { r = await api[method](...args); } catch (e) { r = { ok: false, error: String(e) }; }
    if (!r || r.ok === false) {
      if (r && r.cancelled) return null;
      await alertBox((r && r.error) || '처리하지 못했습니다.');
      return null;
    }
    return r;
  }
  async function mutate(method, ...args) {
    const r = await call(method, ...args);
    if (r) markSaved();
    return r;
  }

  // ---------- 확인 창 ----------
  function modal(message, withCancel, html, okText, cancelText) {
    return new Promise((resolve) => {
      if (html) $('modalMsg').innerHTML = message;
      else $('modalMsg').textContent = message;
      $('modalCancel').hidden = !withCancel;
      $('modalOk').textContent = okText || '확인';
      $('modalCancel').textContent = cancelText || '취소';
      $('modal').hidden = false;
      $('modal').setAttribute('aria-modal', 'true');
      const prevFocus = document.activeElement;
      setTimeout(() => (withCancel ? $('modalCancel') : $('modalOk')).focus(), 30);
      const done = (v) => {
        if (prevFocus && prevFocus.focus && prevFocus.isConnected) setTimeout(() => prevFocus.focus(), 0);
        $('modal').hidden = true;
        $('modalOk').onclick = $('modalCancel').onclick = null;
        resolve(v);
      };
      $('modalOk').onclick = () => done(true);
      $('modalCancel').onclick = () => done(false);
    });
  }
  const alertBox = (m) => modal(m, false);
  const confirmBox = (m, okText) => modal(m, true, false, okText);
  // 되돌릴 수 없는(치명적인) 작업: 안내를 읽고 '확인했어요'를 직접 쳐야 [확인] 버튼이 눌린다.
  const TYPED_WORD = '확인했어요';
  function typedConfirm(msg, okText) {
    const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const html = `<div class="typed-conf"><div>${esc(msg).replace(/\n/g, '<br>')}</div>`
      + `<p class="typed-warn">⚠ 되돌릴 수 없는 작업입니다. 계속하려면 아래 칸에 '<b>${TYPED_WORD}</b>'를 그대로 입력하세요.</p>`
      + `<input type="text" id="typedConfInp" autocomplete="off" placeholder="${TYPED_WORD}"></div>`;
    const p = modal(html, true, true, okText);
    const ok = $('modalOk');
    const inp = $('typedConfInp');
    ok.disabled = true;
    inp.addEventListener('input', () => { ok.disabled = inp.value.trim() !== TYPED_WORD; });
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !ok.disabled) ok.click(); });
    setTimeout(() => inp.focus(), 60);
    return p.then((v) => { ok.disabled = false; return v && inp.value.trim() === TYPED_WORD; });
  }

  // 엑셀 시트 고르기: 내용 있는 시트가 여럿일 때. multi면 여러 개(명렬), 아니면 하나. 고른 시트 이름(배열) 또는 null.
  async function pickSheets(info, multi) {
    const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const firstFull = info.sheets.reduce((best, x, i) => (x.rows > (info.sheets[best] || { rows: 0 }).rows ? i : best), -1); // 줄이 가장 많은 시트
    const items = info.sheets.map((x, i) => `<label class="sheet-pick${x.rows ? '' : ' empty'}"><input type="${multi ? 'checkbox' : 'radio'}" name="shPick" value="${i}"${x.rows ? '' : ' disabled'}${(multi ? x.rows : i === firstFull) ? ' checked' : ''}>`
      + `<b>${esc(x.name)}</b> <span class="muted">${x.rows ? `${x.rows}줄` : '빈 시트'}</span>${x.first ? `<div class="sheet-first">${esc(x.first)}</div>` : ''}</label>`).join('');
    const html = `<div><b>${esc(info.file)}</b>에 시트가 여러 개 있습니다. ${multi ? '읽을 시트를 모두 고르세요(시트마다 명렬 하나로 읽습니다).' : '읽을 시트를 하나 고르세요.'}</div><div class="sheet-list">${items}</div>`;
    const ok = await modal(html, true, true, '읽기', '취소');
    const picked = [...document.querySelectorAll('input[name=shPick]:checked')].map((x) => info.sheets[+x.value].name);
    if (!ok || !picked.length) return null;
    return picked;
  }

  function openSheet(build) {
    const box = $('sheetBox');
    box.innerHTML = '';
    box.removeAttribute('style'); // 앞 창의 크기가 남지 않게
    build(box);
    $('sheet').hidden = false;
  }
  function closeSheet() { $('sheet').hidden = true; $('sheetBox').innerHTML = ''; }

  // ---------- 상단 바·메뉴 ----------
  // fromHistory: 마우스 뒤로·앞으로 버튼으로 온 경우(화면 기록을 새로 쌓지 않음)
  function showPanel(name, fromHistory) {
    if (draftDirty() || pendingSaves.size || tvDirty()) {
      saveAllPending().then(async (ok) => {
        if (ok) { showPanelNow(name, fromHistory); return; }
        if (fromHistory) history.pushState({ panel }, '');
        // 다시 시도해도 저장되지 않는 대기 저장(성취기준·활동 개요 등)이 있으면, 버리고 이동할 수 있게 묻는다(그대로 두면 화면을 못 떠남)
        const failed = [...pendingSaves.entries()].filter(([, j]) => j.failed);
        if (failed.length && !draftDirty() && !tvDirty() && await confirmBox(`${SAVE_FAIL_MSG}\n\n저장하지 못한 글을 버리고 이동할까요? 필요하면 [취소]를 누르고 편집칸의 글을 먼저 복사해 두세요.`, '버리고 이동')) {
          failed.forEach(([k]) => dropPending(k));
          saveFailed = false;
          refreshSaveState();
          showPanelNow(name, fromHistory);
          return;
        }
        toast(SAVE_FAIL_MSG, 5000);
      });
      return;
    }
    flushCfg();
    showPanelNow(name, fromHistory);
  }
  function showPanelNow(name, fromHistory) {
    $('actionToast').hidden = true;
    if (!fromHistory && name !== panel) history.pushState({ panel: name }, '');
    panel = name;
    document.querySelectorAll('.nav').forEach((b) => b.classList.toggle('active', b.dataset.panel === name));
    document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.dataset.panelContent === name));
    $('crumb').textContent = `${ys.year ? ys.year + '학년도 › ' : ''}${PANEL_TITLES[name] || ''}`;
    $('main').scrollTop = 0;
    $('helpBtn').hidden = name === 'guide';
    if (name === 'dashboard') loadDashboard();
    if (name === 'roster') renderRoster();
    if (name === 'settings') renderSettings();
    if (name === 'records') renderRecordsPanel();
    if (name === 'export') renderExport();
    if (name === 'tags') renderTags();
    if (name === 'prompts') renderPrompts();
    if (name === 'tagrec') renderTagView(true);
    if (name === 'inbox') renderInbox();
    if (name === 'standards') renderStandards();
  }
  function setCollapsed(v) {
    $('app').classList.toggle('collapsed', v);
  }
  function fillSoon() {
    document.querySelectorAll('.soon').forEach((c) => {
      const [title, text] = c.dataset.soon.split('|');
      c.innerHTML = '';
      c.appendChild(el('h2', { text: title }));
      c.appendChild(el('span', { class: 'soon-badge', text: '준비 중' }));
      c.appendChild(el('p', { text }));
    });
  }
  function showAbout() {
    modal(`<div class="about-box"><img src="face.png" alt="" class="about-face"><div class="about-title">생기부 착즙기</div><div class="muted">v${info.version} 베타</div>` +
      `<div class="about-tag">"${info.tagline}"</div><div class="about-maker">${info.maker}</div></div>`, false, true);
  }
  function renderYearSelect() {
    const s = $('yearSelect');
    s.innerHTML = '';
    (ys.years || []).slice().reverse().forEach((y) => s.appendChild(el('option', { value: y, text: `${y}학년도`, selected: y === ys.year })));
    s.hidden = !(ys.years || []).length;
    $('archivedBadge').hidden = !ys.archived;
    $('app').classList.toggle('archived', !!ys.archived);
  }
  async function reloadYear() {
    const r = await call('year_state');
    if (!r) return;
    ys = r;
    finalDraft = null; // 이전 학년도 화면의 초안은 끝(바꾸기 전에 저장을 마쳤다)
    R.slots = [];
    R.slot = null;
    renderYearSelect();
    $('crumb').textContent = `${ys.year ? ys.year + '학년도 › ' : ''}${PANEL_TITLES[panel] || ''}`;
    if (panel === 'dashboard') loadDashboard();
    if (panel === 'roster') renderRoster();
    if (panel === 'settings') renderSettings();
    if (panel === 'records') renderRecordsPanel();
    if (panel === 'export') renderExport();
    if (panel === 'tags') renderTags();
    if (panel === 'prompts') renderPrompts();
    if (panel === 'tagrec') renderTagView();
    if (panel === 'inbox') { IB.bid = null; renderInbox(); }
    if (panel === 'standards') { SD.gid = null; renderStandards(); }
    refreshInboxBadge();
  }
  function visibleGroups() {
    return (ys.groups || []).filter((g) => ys.role === 'homeroom' || g.kind !== 'homeroom');
  }
  async function refreshBalance() {
    const r = await api.balance();
    $('balance').textContent = r && r.ok ? fmtCredit(r.balance) : '확인 불가';
    if (r && r.ok && (r.balance === null || r.balance === undefined)) $('balance').textContent = cfg.openrouter_key ? '확인 불가' : '-';
  }

  // ---------- 현황판 ----------
  async function loadDashboard() {
    if (!ys.year) return;
    const r = await call('dashboard');
    if (!r) return;
    dash = r;
    renderSchedLine();
    renderDashboard();
  }
  function renderSchedLine() {
    const box = $('schedLine');
    box.innerHTML = '';
    box.appendChild(el('span', { text: '📅' }));
    const up = (dash.schedules || []).filter((s) => daysUntil(s.date) >= 0);
    if (!up.length) {
      box.appendChild(el('span', { class: 'muted', text: '다가오는 일정이 없습니다.' }));
    }
    const MAX = 4;
    up.slice(0, MAX).forEach((s, i) => {
      const d = daysUntil(s.date);
      const cls = d === 0 ? 'today' : d <= 7 ? 'soon' : '';
      if (i) box.appendChild(el('span', { class: 'muted', text: '·' }));
      box.appendChild(el('span', { class: `sched-item ${cls}` }, [el('b', { text: d === 0 ? 'D-Day' : `D-${d}` }), `${s.title} (${md(s.date)})`]));
    });
    if (up.length > MAX) {
      box.appendChild(el('button', { type: 'button', class: 'link', text: `+${up.length - MAX}개`, onclick: () => showAllSchedules(up) }));
    }
    box.appendChild(el('span', { class: 'spacer' }));
    box.appendChild(el('button', { type: 'button', class: 'link edit-only', text: up.length ? '관리' : '일정 추가', onclick: () => { showPanel('settings'); showSettingsTab('sched'); } }));
  }
  function showAllSchedules(list) {
    openSheet((box) => {
      box.style.height = 'auto';
      box.appendChild(el('div', { class: 'sheet-head' }, [el('h2', { text: '다가오는 일정' }), el('span', { class: 'spacer' }), el('button', { type: 'button', text: '닫기', onclick: closeSheet })]));
      const t = el('table', { class: 'tbl' });
      list.forEach((s) => {
        const d = daysUntil(s.date);
        t.appendChild(el('tr', {}, [el('td', { text: d === 0 ? 'D-Day' : `D-${d}` }), el('td', { text: s.date }), el('td', { text: s.title })]));
      });
      box.appendChild(t);
    });
  }
  function shownDashGroups() {
    const subjects = dash.groups.filter((g) => g.kind === 'subject');
    $('semesterSeg').hidden = !subjects.length;
    $('annualHint').hidden = !subjects.length;
    return dash.groups.filter((g) => g.kind !== 'subject' || g.semester === semester);
  }
  function renderDashboard() {
    const groups = shownDashGroups();
    const cards = $('dashCards');
    cards.innerHTML = '';
    if (!groups.find((g) => g.id === dashSel)) dashSel = groups.length ? groups[0].id : null;
    groups.forEach((g) => {
      const s = g.summary;
      const sum = g.kind === 'homeroom'
        ? `${s.students}명 · 마감 ${s.closed}/${s.item_total}항목`
        : `${s.students}명 · 마감 ${s.closed}`;
      const pct = s.item_total ? Math.round((s.closed / s.item_total) * 100) : 0;
      cards.appendChild(el('button', { type: 'button', class: 'gcard' + (g.id === dashSel ? ' active' : '') + (s.item_total && s.closed >= s.item_total ? ' is-closed' : ''), onclick: () => { dashSel = g.id; renderDashboard(); } }, [
        el('span', { class: 'g-kind', text: g.kind === 'homeroom' ? '담임반 · 연간' : g.kind === 'subject' ? `과목 세특 · ${g.semester}학기` : '동아리 · 연간' }),
        el('span', { class: 'g-name', text: g.kind === 'homeroom' ? g.name : g.name }),
        el('span', { class: 'g-sum', text: g.total ? sum : '명렬 미등록' }),
        el('div', { class: 'bar' }, [el('div', { class: 'bar-fill', style: `width:${pct}%` })]),
      ]));
    });
    // 다음 할 일
    const todo = $('todoLine');
    todo.innerHTML = '';
    if (dash.todo.length) {
      todo.appendChild(el('span', { class: 'todo-label', text: '다음 할 일:' }));
      dash.todo.forEach((t) => todo.appendChild(el('button', { type: 'button', text: t.label, onclick: () => {
        if (t.kind === 'roster') { rosterSel = t.group_id; showPanel('roster'); return; }
        if (t.kind === 'inbox') { IB.bid = t.batch_id; showPanel('inbox'); return; }
        if (t.kind === 'tagwork') { goTagWork(t.tag_id, '', t.step); return; }
        openRecords(t.group_id, t.item, null, t.filter);
      } })));
    }
    renderDashTable(groups.find((g) => g.id === dashSel), groups.length);
  }
  function stCell(key) {
    const s = STATUS[key] || STATUS.none;
    return el('td', { class: 'stcell' }, [el('span', { class: `st ${s.cls}`, text: s.icon }), ' ', s.text]);
  }
  const dashFold = new Set(); // 현황판에서 표를 접은 담당
  function renderDashTable(g, count) {
    const card = $('dashTableCard');
    card.innerHTML = '';
    if (!count) {
      card.appendChild(el('div', { class: 'empty-state' }, [
        el('p', { text: '아직 담당이 없습니다. 담임반·과목·동아리를 추가하세요.' }),
        el('div', { class: 'steps-btns' }, [el('button', { type: 'button', class: 'primary', text: '명렬·담당 관리', onclick: () => showPanel('roster') })]),
      ]));
      return;
    }
    if (!g) return;
    if (!g.total) {
      card.appendChild(el('div', { class: 'empty-state' }, [
        el('h2', { text: g.label }),
        el('p', { text: '명렬이 아직 없습니다. 아래 순서로 시작하세요.' }),
        el('div', { class: 'steps-btns' }, [
          el('button', { type: 'button', class: 'primary', text: '① 명렬 등록', onclick: () => { rosterSel = g.id; showPanel('roster'); } }),
          el('button', { type: 'button', text: '② 자료 가져오기', onclick: () => showPanel('inbox') }),
        ]),
      ]));
      return;
    }
    const target = g.kind === 'homeroom' ? null : (g.target_bytes || ys.targets[g.kind]);
    const labelOf = {};
    (dash.groups || []).forEach((x) => { labelOf[x.id] = x.kind === 'subject' ? x.name : x.kind === 'club' ? x.name : x.name; });

    // 제목 줄(담당 이름)을 누르면 아래 표가 접힌다. 제목 옆에는 항목별 마감 현황(활성 학생 기준).
    const shut = dashFold.has(g.id);
    const head = el('div', { class: 'card-head dash-tbl-head', title: shut ? '눌러서 펴기' : '눌러서 접기', onclick: (e) => {
      if (e.target.closest('select, button:not(.dash-fold), a')) return;
      if (dashFold.has(g.id)) dashFold.delete(g.id); else dashFold.add(g.id);
      renderDashTable(g, count);
    } }, [el('h2', {}, [el('span', { class: 'dash-fold', text: shut ? '▸ ' : '▾ ' }), g.label])]);
    card.appendChild(head);
    const act = g.rows.filter((r) => r.active);
    const its = g.kind === 'homeroom' ? g.items : [g.kind];
    its.forEach((it) => {
      const n = act.filter((r) => r.status[it] === 'closed').length;
      const pct = act.length ? Math.round((n / act.length) * 100) : 0;
      head.appendChild(el('span', { class: 'dg-sum' + (!act.length ? '' : n >= act.length ? ' all' : ' open'), title: `${g.kind === 'homeroom' ? ITEM_LABELS[it] : '이 담당'} 마감 ${n}명 / 활성 ${act.length}명` }, [
        `${g.kind === 'homeroom' ? `${ITEM_LABELS[it]} ` : ''}${act.length && n >= act.length ? `● 마감 ${n}/${act.length}명` : `◐ 마감 ${n}/${act.length}명`}`, el('span', { class: 'bar dg-bar' }, [el('span', { class: 'bar-fill', style: `width:${pct}%` })])]));
    });
    if (shut) return;
    let rows = g.rows.slice();
    if (g.kind !== 'homeroom') {
      const inactive = g.rows.filter((r) => !r.active).length;
      if (inactive) head.appendChild(el('span', { class: 'muted', text: `비활성 ${inactive}명 제외` }));
      // 필터
      const f = g._f || (g._f = { cls: '', grade: '', st: '' });
      const filters = el('div', { class: 'filters' });
      const classes = [...new Set(g.rows.map((r) => `${r.grade}-${r.class_no}`))].sort();
      const grades = [...new Set(g.rows.map((r) => r.grade))].sort();
      const sel = (label, key, opts) => {
        const s = el('select', { onchange: (e) => { f[key] = e.target.value; renderDashTable(g, count); } }, [el('option', { value: '', text: '전체' }), ...opts.map(([v, t]) => el('option', { value: v, text: t, selected: f[key] === String(v) }))]);
        filters.appendChild(el('label', { class: 'inline', style: 'margin:0' }, [label, s]));
      };
      if (g.kind === 'club' && grades.length > 1) sel('학년', 'grade', grades.map((x) => [String(x), `${x}학년`]));
      if (classes.length > 1) sel('반', 'cls', classes.map((x) => [x, x]));
      sel('상태', 'st', Object.entries(STATUS).map(([k, v]) => [k, v.text]));
      card.appendChild(filters);
      rows = rows.filter((r) => (!f.cls || `${r.grade}-${r.class_no}` === f.cls) && (!f.grade || String(r.grade) === f.grade) && (!f.st || r.status[g.kind] === f.st));
    }

    const wrap = el('div', { class: 'tbl-wrap' });
    const t = el('table', { class: 'tbl' });
    const th = (x) => el('th', { text: x });
    if (g.kind === 'homeroom') {
      t.appendChild(el('tr', {}, [th('학번'), th('이름'), th('자율(연간)'), th('진로(연간)'), th('행특(연간)'), th('내 과목·동아리'), th('확인 사항')]));
    } else {
      t.appendChild(el('tr', {}, [th('학번'), th('이름'), th('학년-반'), th('상태'), th('기록 수'), th(`최종안 (목표 ${target}B)`), th('확인 사항')]));
    }
    rows.sort((a, b) => (b.active - a.active) || a.student_no.localeCompare(b.student_no));
    rows.forEach((r) => {
      const notes = [];
      if (!r.active) notes.push(el('span', { class: 'tag', text: '비활성' }));
      if (r.senior_note) notes.push(el('span', { class: 'tag warn-tag', text: '3학년: 1학기 마감 대상' }));
      if (r.stale) notes.push(el('span', { class: 'tag warn-tag', text: '채택 후 기록 변경' }));
      const tr = el('tr', { class: 'clickable' + (r.active ? '' : ' inactive'), title: '눌러서 이 학생의 기록 열기', onclick: () => openRecords(g.id, g.items[0], r.student_no) });
      tr.appendChild(el('td', { text: r.student_no }));
      tr.appendChild(el('td', { text: r.name }));
      if (g.kind === 'homeroom') {
        g.items.forEach((it) => { const td = stCell(r.status[it]); td.title = `${ITEM_LABELS[it]} 열기`; td.addEventListener('click', (e) => { e.stopPropagation(); openRecords(g.id, it, r.student_no); }); tr.appendChild(td); });
        tr.appendChild(el('td', {}, r.others.filter((id) => labelOf[id]).map((id) => el('span', { class: 'tag', text: labelOf[id] }))));
      } else {
        tr.appendChild(el('td', { text: `${r.grade}-${r.class_no}` }));
        tr.appendChild(stCell(r.status[g.kind]));
        tr.appendChild(el('td', { text: String(r.records) }));
        tr.appendChild(el('td', { text: r.final_bytes === null ? '-' : `${r.final_bytes}/${target}` }));
      }
      tr.appendChild(el('td', {}, notes));
      t.appendChild(tr);
    });
    if (!rows.length) t.appendChild(el('tr', {}, [el('td', { colspan: 7, class: 'muted', text: '조건에 맞는 학생이 없습니다.' })]));
    wrap.appendChild(t);
    card.appendChild(wrap);
  }

  // ---------- 명렬·담당 관리 ----------
  function renderRoster() {
    const groups = visibleGroups();
    const tabs = $('groupTabs');
    tabs.innerHTML = '';
    if (!groups.find((g) => g.id === rosterSel)) rosterSel = groups.length ? groups[0].id : null;
    groups.forEach((g) => {
      tabs.appendChild(el('button', { type: 'button', class: 'gtab' + (g.id === rosterSel ? ' active' : '') + (g.total ? ' is-done' : ' empty'), title: g.total ? '명렬 등록됨' : '명렬 미등록', onclick: () => { rosterSel = g.id; renderRoster(); } }, [
        g.label, el('span', { class: 'cnt', text: g.total ? `${g.active}명` : '미등록' }),
      ]));
    });
    const body = $('groupBody');
    body.innerHTML = '';
    if (!groups.length) {
      body.appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '담당이 없습니다. [+ 담당 추가]로 담임반·과목·동아리를 만드세요.' })]));
      return;
    }
    const g = groups.find((x) => x.id === rosterSel);
    $('crumb').textContent = `${ys.year}학년도 › 명렬·담당 관리 › ${g.label}`;
    if (returnTo) {
      body.appendChild(el('div', { class: 'return-bar' }, ['📥 자료 인박스에서 학생 매칭 중이었습니다. 명렬을 반영한 뒤 돌아가세요.', el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'primary', text: '매칭으로 돌아가기', onclick: async () => {
          const back = returnTo;
          returnTo = null;
          await call('inbox_rematch', back.bid);
          IB.bid = back.bid;
          showPanel('inbox');
        } }),
        el('button', { type: 'button', class: 'link', text: '닫기', onclick: () => { returnTo = null; renderRoster(); } })]));
    }
    body.appendChild(groupEditor(g));
    loadMembers(g, body);
  }
  function groupEditor(g) {
    const box = el('div', { class: 'wsection edit-only', style: 'margin-top:0;margin-bottom:12px' });
    const row = el('div', { class: 'map-row' });
    const save = async (data) => {
      const r = await mutate('update_group', g.id, data);
      if (r) { ys.groups = r.groups; renderRoster(); if (r.unpaired) alertBox(`학기를 바꿔 1·2학기 합산 연결 ${r.unpaired}개를 풀었습니다. 합산은 2학기 과목에서 1학기 과목을 골라 다시 연결하세요.`); }
    };
    if (g.kind === 'homeroom') {
      const gr = el('input', { type: 'number', class: 'num', value: g.grade, min: 1, max: 6 });
      const cl = el('input', { type: 'number', class: 'num', value: g.class_no, min: 1, max: 30 });
      row.append(el('label', {}, ['학년', gr]), el('label', {}, ['반', cl]),
        el('button', { type: 'button', text: '저장', onclick: () => save({ grade: gr.value, class_no: cl.value }) }));
    } else {
      const nm = el('input', { type: 'text', value: g.name, style: 'width:200px' });
      row.appendChild(el('label', {}, ['이름', nm]));
      let sem = null, sc = null;
      if (g.kind === 'subject') {
        sem = el('select', {}, [1, 2].map((s) => el('option', { value: s, text: `${s}학기`, selected: g.semester === s })));
        sc = el('select', {}, [3, 5].map((s) => el('option', { value: s, text: `${s}단계`, selected: g.level_scale === s })));
        row.append(el('label', {}, ['학기', sem]), el('label', {}, ['성취수준', sc]));
      }
      const paired = g.kind === 'subject' && g.pair_id;
      const tg = el('input', { type: 'number', class: 'num', value: g.target_bytes || '', placeholder: String(ys.targets[g.kind]), disabled: !!paired,
        title: paired ? '1·2학기 합산 연결 중에는 학생별 목표(합산 − 1학기 최종안)를 씁니다. 아래 합산 칸을 고치세요.' : '' });
      row.append(el('label', {}, ['목표 분량', tg, 'B', paired ? el('span', { class: 'muted', text: ' (합산 연결 중 — 사용 안 함)' }) : null]),
        el('button', { type: 'button', text: '저장', onclick: () => save({ name: nm.value, semester: sem && sem.value, level_scale: sc && sc.value, target_bytes: tg.value }) }));
    }
    row.appendChild(el('span', { class: 'spacer' }));
    row.appendChild(el('button', { type: 'button', class: 'link danger-text', text: '담당 삭제', onclick: async () => {
      const im = await call('group_impact', g.id);
      if (!im) return;
      const parts = [`명렬 ${im.members}명`, im.records && `학생관찰기록 ${im.records}건`, im.finals && `최종안 ${im.finals}건(마감 ${im.closed})`,
        im.results && `AI 후보 ${im.results}건`, im.batches && `인박스 묶음 ${im.batches}개`, im.standards && '성취기준', im.outlines && `활동 개요 ${im.outlines}개`].filter(Boolean).join(', ');
      if (!(await typedConfirm(`'${g.label}' 담당을 지우면 함께 지워집니다:\n${parts}\n\n지우기 전에 자동으로 백업합니다(설정 > 백업·자료에서 그 백업으로 복원하는 방법만 있음).`, '삭제'))) return;
      const r = await mutate('delete_group', g.id);
      if (r) { ys.groups = r.groups; rosterSel = null; renderRoster(); toast(`지웠습니다. 백업: ${r.backup}`); }
    } }));
    box.appendChild(row);
    if (g.kind === 'subject') box.appendChild(pairEditor(g, save));
    return box;
  }
  // 1·2학기 합산 과목: 2학기 과목에서 1학기 과목과 합산 목표를 고른다. 2학기 목표 = 합산 − 1학기 최종안(학생별)
  function pairEditor(g, save) {
    const row = el('div', { class: 'map-row pair-row' });
    const firsts = (ys.groups || []).filter((x) => x.kind === 'subject' && x.semester === 1);
    const partnerOf = (ys.groups || []).find((x) => x.pair_id === g.id);
    if (g.semester !== 2) {
      row.append(el('b', { text: '1·2학기 합산' }), partnerOf
        ? el('span', {}, [`2학기 ${partnerOf.label}와 세특 합산 ${partnerOf.pair_total}B. 1학기를 먼저 쓰면 2학기에 남은 바이트가 학생별로 자동 계산됩니다.`])
        : el('span', { class: 'muted', text: '1학기와 2학기가 세특 바이트를 함께 쓰는 과목이면, 2학기 과목 설정에서 이 과목을 고르세요.' }));
      return row;
    }
    const sel = el('select', {}, [el('option', { value: '', text: '(합산 안 함)' }), ...firsts.map((x) => el('option', { value: x.id, text: x.label, selected: x.id === g.pair_id }))]);
    const tot = el('input', { type: 'number', class: 'num', min: 1, value: g.pair_total || 1500 });
    row.append(el('b', { text: '1·2학기 합산' }), el('label', {}, ['1학기 과목', sel]), el('label', {}, ['합산', tot, 'B']),
      el('button', { type: 'button', text: g.pair_id ? '바꾸기' : '연결', onclick: () => save({ pair_id: sel.value || null, pair_total: tot.value }) }));
    if (g.pair_id) row.appendChild(el('button', { type: 'button', class: 'link', text: '연결 풀기', onclick: () => save({ pair_id: null }) }));
    const sug = !g.pair_id && g.pair_suggest && firsts.find((x) => x.id === g.pair_suggest);
    if (sug) row.appendChild(el('span', { class: 'pair-suggest' }, [`${sug.label}과 세특 바이트를 합산하나요? `,
      el('button', { type: 'button', class: 'small primary', text: `${sug.name}와 합산 연결`, onclick: () => save({ pair_id: sug.id, pair_total: tot.value }) })]));
    row.appendChild(el('div', { class: 'hint', style: 'margin:4px 0 0;flex-basis:100%', text: g.pair_id
      ? '이 과목 목표 = 합산 − 1학기 최종안 바이트(학생별). 1학기 최종안이 아직 없으면 합산의 절반을 씁니다. AI 종합도 이 목표에 맞춰 씁니다.'
      : '1학기와 세특 바이트를 함께 쓰는 과목이면 1학기 과목과 합산 바이트를 골라 연결하세요.' }));
    return row;
  }
  async function loadMembers(g, body) {
    const r = await call('members', g.id);
    if (!r || rosterSel !== g.id) return;
    const members = r.members;
    const toolbar = el('div', { class: 'toolbar' });
    toolbar.append(
      el('button', { type: 'button', class: 'primary edit-only', text: '📋 클립보드에서 추가', onclick: () => importFromClipboard(g) }),
      el('button', { type: 'button', class: 'edit-only', text: '📂 파일 추가(여러 개)', onclick: () => importFromXlsx(g) }),
      el('button', { type: 'button', class: 'edit-only', text: '👥 다른 담당 명렬 가져오기', onclick: () => openRosterInput(g, null, 'copy') }),
      el('button', { type: 'button', class: 'edit-only', text: '✍️ 직접 입력', onclick: () => openRosterInput(g, null, 'direct') }),
      el('button', { type: 'button', class: 'edit-only', text: '+ 학생 한 명 추가(전입)', onclick: () => openRosterInput(g, null, 'line') }),
    );
    if (!members.length) {
      body.appendChild(toolbar);
      body.appendChild(el('div', { class: 'empty-state' }, [
        el('p', { text: '명렬이 비어 있습니다.' }),
        el('p', { class: 'hint', text: '엑셀에서 학번·이름 칸(또는 학년·반·번호·이름 칸)을 드래그해 복사한 뒤 [클립보드에서 추가]를 누르세요. 반마다 파일이 따로 있으면 [파일 추가]에서 여러 개를 한꺼번에 고르면 됩니다. 붙여넣기와 파일을 섞어 계속 이어서 넣을 수 있습니다.' }),
      ]));
      return;
    }
    const allAct = el('input', { type: 'checkbox' });
    toolbar.append(
      el('span', { class: 'spacer' }),
      el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', checked: showInactive, onchange: (e) => { showInactive = e.target.checked; renderRoster(); } }), '비활성 학생 보기']),
      el('span', { class: 'edit-only muted', text: '|' }),
      el('button', { type: 'button', class: 'edit-only', text: '선택 학생 전출·빼기', onclick: () => transferOut() }),
      el('button', { type: 'button', class: 'edit-only', text: '다시 활성화', onclick: () => changeActive(true, false) }),
      ...(g.kind === 'subject' ? [el('button', { type: 'button', class: 'edit-only', title: '선택과목: 같은 수업끼리 묶어 보입니다', text: '수업 지정', onclick: () => setSection() })] : []),
    );
    body.appendChild(toolbar);
    const list = members.filter((m) => showInactive || m.active);
    const inactiveCount = members.length - members.filter((m) => m.active).length;
    body.appendChild(el('div', { class: 'hint', text: `활성 ${members.length - inactiveCount}명${inactiveCount ? ` · 비활성 ${inactiveCount}명${showInactive ? '' : '(숨김)'}` : ''}. 비활성 학생은 매칭 후보·일괄 처리·내보내기에서 빠지며, 기록은 지우지 않습니다.` }));
    const wrap = el('div', { class: 'tbl-wrap' });
    const t = el('table', { class: 'tbl' });
    const checkAll = el('input', { type: 'checkbox', onchange: (e) => t.querySelectorAll('.rowcheck').forEach((c) => { c.checked = e.target.checked; }) });
    const subj = g.kind === 'subject';
    t.appendChild(el('tr', {}, [el('th', {}, [checkAll]), ...['학년', '반', '번호', '이름', '학번', ...(subj ? ['수업'] : []), '상태'].map((h) => el('th', { text: h }))]));
    list.forEach((m) => {
      const tr = el('tr', { class: m.active ? '' : 'inactive' });
      tr.appendChild(el('td', {}, [el('input', { type: 'checkbox', class: 'rowcheck', 'data-no': m.student_no })]));
      tr.append(el('td', { text: m.grade ?? '' }), el('td', { text: m.class_no ?? '' }), el('td', { text: m.number ?? '' }), el('td', { text: m.name }), el('td', { class: 'muted', text: m.student_no }),
        ...(subj ? [el('td', { text: m.section || '' })] : []),
        el('td', {}, [m.active ? '활성' : el('span', { class: 'inactive-badge', text: '비활성' })]));
      t.appendChild(tr);
    });
    wrap.appendChild(t);
    body.appendChild(wrap);

    // 선택과목 수업 지정: 같은 수업끼리 묶어 보인다(비우면 학년-반으로)
    async function setSection() {
      const nos = [...t.querySelectorAll('.rowcheck:checked')].map((c) => c.dataset.no);
      if (!nos.length) { toast('학생을 먼저 체크하세요.'); return; }
      const known = [...new Set(members.map((m) => m.section).filter(Boolean))];
      const name = await new Promise((resolve) => openSheet((box) => {
        box.style.height = 'auto'; box.style.width = 'min(520px, 92vw)';
        const inp = el('input', { type: 'text', list: 'secList', placeholder: '예: 물리학 A반 (비우면 학년-반으로 묶음)' });
        addTo(box, el('div', { class: 'sheet-head' }, [el('h2', { text: `${nos.length}명 수업 지정` })]),
          el('p', { class: 'hint', text: '선택과목은 여러 반 학생이 섞여 있으므로, 같은 수업끼리 묶어 항목별 기록의 학생 목록에 보여 줍니다. 한 명이라도 수업이 지정되면 학년-반 대신 수업으로 묶고, 미지정 학생은 \'수업 미지정\' 한 묶음으로 모읍니다.' }),
          inp, el('datalist', { id: 'secList' }, known.map((k) => el('option', { value: k }))),
          known.length ? el('div', { class: 'toolbar', style: 'margin-top:8px' }, known.map((k) => el('button', { type: 'button', class: 'small', text: k, onclick: () => { inp.value = k; } }))) : null,
          el('div', { class: 'sheet-foot' }, [
            el('button', { type: 'button', class: 'link danger-text', text: '수업 지정 해제', onclick: async () => {
              if (!(await confirmBox(`${nos.length}명의 수업 지정을 풉니다(학생·기록은 그대로).`, '해제'))) return;
              closeSheet(); resolve('');
            } }),
            el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => { closeSheet(); resolve(null); } }),
            el('button', { type: 'button', class: 'primary', text: '지정', onclick: () => { if (!inp.value.trim()) { toast('수업 이름을 넣어 주세요. 지정을 풀려면 [수업 지정 해제]를 누르세요.'); return; } closeSheet(); resolve(inp.value.trim()); } })]));
        setTimeout(() => inp.focus(), 50);
      }));
      if (name === null) return;
      const r = await mutate('set_section', g.id, nos, name);
      if (r) { toast(name ? `${r.changed}명을 '${name}' 수업으로 지정했습니다.` : `${r.changed}명의 수업 지정을 풀었습니다.`); renderRoster(); }
    }
    // 전출·빼기: 비활성화(기록 보존) 또는 삭제(기록도 지움, 먼저 백업)
    async function transferOut() {
      const nos = [...t.querySelectorAll('.rowcheck:checked')].map((c) => c.dataset.no);
      if (!nos.length) { toast('학생을 먼저 체크하세요.'); return; }
      const names = members.filter((m) => nos.includes(m.student_no)).map((m) => `${m.student_no} ${m.name}`);
      const choice = await new Promise((resolve) => openSheet((box) => {
        box.style.height = 'auto'; box.style.width = 'min(560px, 92vw)';
        const all = el('input', { type: 'checkbox', checked: g.kind === 'homeroom' });
        box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `${nos.length}명 전출·빼기` })]),
          el('p', { text: names.slice(0, 8).join(', ') + (names.length > 8 ? ` 외 ${names.length - 8}명` : '') }),
          el('label', { class: 'inline' }, [all, '이 학년도의 모든 소속(담임반·과목·동아리)에서 함께 처리(전출)']),
          el('div', { class: 'two-col', style: 'margin-top:10px' }, [
            el('div', { class: 'choice-card' }, [el('b', { text: '비활성화' }), el('p', { class: 'hint', text: '명렬에 남기되 붉은 글씨로 표시합니다. 기록·최종안은 그대로 두고, 매칭·일괄 처리·내보내기에서만 빠집니다. 나중에 다시 활성화할 수 있습니다.' }),
              el('button', { type: 'button', class: 'primary', text: '비활성화', onclick: () => { closeSheet(); resolve({ how: 'deactivate', all: all.checked }); } })]),
            el('div', { class: 'choice-card' }, [el('b', { class: 'danger-text', text: '삭제' }), el('p', { class: 'hint', text: '명렬에서 지우고 그 소속의 학생관찰기록·후보·최종안도 함께 지웁니다. 지우기 전에 자동으로 백업합니다.' }),
              el('button', { type: 'button', class: 'btn-danger', text: '삭제', onclick: () => { closeSheet(); resolve({ how: 'delete', all: all.checked }); } })]),
          ]),
          el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => { closeSheet(); resolve(null); } })]));
      }));
      if (!choice) return;
      if (choice.how === 'deactivate') {
        const r = await mutate('set_active', g.id, nos, false, choice.all);
        if (r) { ys.groups = r.groups; toast(`${nos.length}명을 비활성화했습니다.`); renderRoster(); }
        return;
      }
      const im = await call('member_impact', g.id, nos, choice.all);
      if (!im) return;
      const parts = [im.records && `학생관찰기록 ${im.records}건`, im.finals && `최종안 ${im.finals}건`, im.results && `AI 후보 ${im.results}건`, im.inbox && `인박스 연결 ${im.inbox}건(연결만 풂)`].filter(Boolean).join(', ');
      if (!(await typedConfirm(`${nos.length}명을 ${choice.all ? '모든 소속' : `'${g.label}'`}에서 지웁니다.${parts ? `\n함께 지워지는 자료: ${parts}` : '\n함께 지워지는 기록은 없습니다.'}\n\n지우기 전에 자동으로 백업합니다(되돌리려면 그 백업으로 복원).`, '삭제'))) return;
      const r = await mutate('remove_members', g.id, nos, choice.all);
      if (r) { ys.groups = r.groups; toast(`${nos.length}명을 지웠습니다. 백업: ${r.backup}`); renderRoster(); }
    }
    async function changeActive(active, all) {
      const nos = [...t.querySelectorAll('.rowcheck:checked')].map((c) => c.dataset.no);
      if (!nos.length) { toast('학생을 먼저 체크하세요.'); return; }
      if (!active) {
        const msg = all
          ? `${nos.length}명을 이 학년도의 모든 소속(담임반·과목·동아리)에서 비활성화합니다(전출). 기록은 지우지 않습니다.`
          : `${nos.length}명을 '${g.label}'에서만 비활성화합니다. 기록은 지우지 않습니다.`;
        if (!(await confirmBox(msg + '\n\n비활성 학생은 매칭 후보, 일괄 보내기·종합, 내보내기에서 빠집니다.', '비활성화'))) return;
      }
      const r = await mutate('set_active', g.id, nos, active, all);
      if (r) { ys.groups = r.groups; toast(`${r.changed}건 ${active ? '활성화' : '비활성화'}했습니다.`); renderRoster(); }
    }
  }

  // 명렬 입력: 클립보드·파일(여러 개)·한 줄 입력을 섞어 계속 쌓은 뒤 한 번에 명렬에 더한다.
  // 추가할 때마다 한 묶음으로 기억해 [마지막 추가 취소]로 그 묶음만 뺄 수 있다.
  function importFromClipboard(g, onDone) { openRosterInput(g, onDone, 'clip'); }
  function importFromXlsx(g, onDone) { openRosterInput(g, onDone, 'file'); }
  function openRosterInput(g, onDone, first) {
    const st = { rows: [], batches: [], seq: 0, onlyBad: false, pendingMap: null };
    const roles = [['grade', '학년'], ['class_no', '반'], ['number', '번호'], ['name', '이름'], ['student_no', '학번']];
    let tableBox, summary, applyBtn, undoBtn, mapBox, logBox;

    openSheet((box) => {
      box.style.height = '';
      tableBox = el('div', { class: 'sheet-body' });
      mapBox = el('div', {});
      logBox = el('div', { class: 'muted roster-log' });
      summary = el('span', {});
      applyBtn = el('button', { type: 'button', class: 'primary', text: '명렬에 추가', onclick: apply });
      undoBtn = el('button', { type: 'button', text: '↶ 마지막 추가 취소', disabled: true, onclick: undoLast });
      const onlyBad = el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', onchange: (e) => { st.onlyBad = e.target.checked; renderRows(); } }), '확인 필요만 보기']);
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: `명렬 입력 · ${g.label}` })]),
        el('div', { class: 'hint', text: '엑셀에서 학년·반·번호·이름(또는 학번·이름) 칸을 드래그해 복사한 뒤 [클립보드에서 추가]를 누르세요(이 창에서 Ctrl+V도 됩니다). 다른 범위를 복사해 또 누르면 아래에 이어 붙습니다. 파일 여러 개, 다른 담당의 명렬도 섞어 계속 이어서 넣을 수 있습니다.' }),
        directBox(),
        el('div', { class: 'toolbar' }, [
          el('button', { type: 'button', class: 'primary', text: '📋 클립보드에서 추가', onclick: addClip }),
          el('button', { type: 'button', text: '📂 파일 추가(여러 개)', onclick: addFiles }),
          el('button', { type: 'button', text: '👥 다른 담당 명렬 가져오기', onclick: addCopy }),
          el('button', { type: 'button', text: '+ 한 줄 추가', onclick: () => addLine() }),
          undoBtn, el('span', { class: 'spacer' }), logBox]),
        mapBox,
        tableBox,
        el('div', { class: 'sheet-foot' }, [summary, onlyBad, el('span', { class: 'spacer' }), el('button', { type: 'button', text: '닫기', onclick: closeAsk }), applyBtn]),
      );
      // 창 안에서 Ctrl+V: 입력칸 밖이면 클립보드 내용을 추가
      box.addEventListener('paste', (e) => {
        if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
        const text = e.clipboardData && e.clipboardData.getData('text');
        if (text && text.trim()) { e.preventDefault(); addText(text, '붙여넣기'); }
      });
      box.tabIndex = -1;
      setTimeout(() => box.focus(), 50);
    });
    renderRows();
    if (first === 'direct') setTimeout(() => { const ta = $('rosterDirect'); if (ta) ta.focus(); }, 80);
    if (first === 'clip') addClip();
    else if (first === 'file') addFiles();
    else if (first === 'line') addLine();
    else if (first === 'copy') addCopy();

    // 직접 입력: 한 줄에 한 명을 적으면 바로 읽어 아래 표에 보여 주고, 표에서 칸을 고친 뒤 [아래 목록에 추가]
    function directBox() {
      const D = { rows: [], edited: false, seq: 0 };
      const ta = el('textarea', { id: 'rosterDirect', class: 'roster-direct', rows: 4, placeholder: '직접 입력 — 한 줄에 한 명\n20301 김철수\n2 3 2 이영희\n2학년 3반 3번 박민수' });
      const note = el('div', { class: 'muted small-note' });
      const prev = el('div', { class: 'direct-prev' });
      const addBtn = el('button', { type: 'button', class: 'primary', text: '아래 목록에 추가', disabled: true });
      const reread = el('button', { type: 'button', class: 'small', text: '글로 다시 읽기', hidden: true, onclick: () => { D.edited = false; read(); } });
      const draw = () => {
        prev.innerHTML = '';
        reread.hidden = !D.edited;
        addBtn.disabled = !D.rows.length;
        if (!D.rows.length) { note.textContent = ta.value.trim() ? '읽은 학생이 없습니다. 한 줄에 학번과 이름(또는 학년 반 번호 이름)을 적어 주세요.' : ''; return; }
        const bad = D.rows.filter((r) => r.issues && r.issues.length).length;
        note.textContent = `읽은 학생 ${D.rows.length}명${bad ? ` · 확인 필요 ${bad}명(빨간 줄)` : ''} · 칸을 눌러 직접 고칠 수 있습니다.${D.edited ? ' 직접 고친 칸이 있어 위 글을 고쳐도 다시 읽지 않습니다([글로 다시 읽기]를 누르면 고친 칸은 사라집니다).' : ''}`;
        const t = el('table', { class: 'tbl direct-tbl' });
        t.appendChild(el('tr', {}, ['줄', '학년', '반', '번호', '이름', '학번', '확인'].map((h) => el('th', { text: h }))));
        D.rows.forEach((r) => {
          const cell = (k, w) => el('td', {}, [el('input', { type: 'text', value: r[k] || '', style: `width:${w}`, oninput: (e) => { r[k] = e.target.value.trim(); D.edited = true; revalidateDirect(); } })]);
          t.appendChild(el('tr', { class: r.issues && r.issues.length ? 'row-bad' : '' }, [el('td', { class: 'muted', text: r.line || '' }), cell('grade', '3em'), cell('class_no', '3em'), cell('number', '3em'), cell('name', '8em'), cell('student_no', '6em'),
            el('td', { class: r.issues && r.issues.length ? 'danger-text' : 'muted', text: (r.issues || []).concat(r.notes || []).join(', ') || '✔' })]));
        });
        prev.appendChild(t);
      };
      const read = debounce(async () => {
        if (D.edited) { draw(); return; }
        const seq = ++D.seq;
        const text = ta.value;
        if (!text.trim()) { D.rows = []; draw(); return; }
        const r = await rawCall('roster_direct', g.id, text);
        if (seq !== D.seq || !r || r.ok === false) return;
        D.rows = r.rows;
        draw();
      }, 300);
      const revalidateDirect = debounce(async () => {
        const seq = ++D.seq;
        const r = await rawCall('roster_validate', g.id, D.rows.map((x) => ({ ...plainRow(x), line: x.line })), true);
        if (seq !== D.seq || !r || r.ok === false) return;
        r.rows.forEach((x, i) => { x.line = D.rows[i] && D.rows[i].line; });
        const focus = document.activeElement, pos = focus && focus.closest ? [...prev.querySelectorAll('input')].indexOf(focus) : -1;
        D.rows = r.rows;
        draw();
        if (pos >= 0) { const ins = prev.querySelectorAll('input'); if (ins[pos]) { ins[pos].focus(); const v = ins[pos].value; ins[pos].setSelectionRange(v.length, v.length); } }
      }, 400);
      const add = () => {
        if (!D.rows.length) return;
        pushBatch(D.rows.map((x) => ({ ...x, section: '' })), '직접 입력');
        D.rows = []; D.edited = false; ta.value = ''; draw();
        ta.focus();
      };
      addBtn.addEventListener('click', add);
      ta.addEventListener('input', read);
      ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); add(); } });
      return el('div', { class: 'direct-box' }, [el('div', { class: 'col-label', text: '✍️ 직접 입력 (한 줄에 한 명 · 학번 이름 / 학년 반 번호 이름)' }), ta, note, prev,
        el('div', { class: 'toolbar' }, [reread, el('span', { class: 'spacer' }), el('span', { class: 'muted', text: 'Ctrl+Enter' }), addBtn])]);
    }
    function plainRow(r) { return { student_no: r.student_no, name: r.name, grade: r.grade, class_no: r.class_no, number: r.number, level: '', section: r.section || '', rename_ok: !!r.rename_ok }; }
    // 선택과목: 묶음(파일·붙여넣기)마다 수업 이름. 파일은 파일 이름이 기본, 비우면 학년-반으로 묶는다.
    const isSub = g.kind === 'subject';
    function log() {
      logBox.innerHTML = '';
      if (st.batches.length) {
        logBox.append(`추가 ${st.batches.length}번: `);
        st.batches.forEach((b, i) => {
          const rows = st.rows.filter((r) => r._batch === b.id);
          const secs = [...new Set(rows.map((r) => r.section || ''))];
          logBox.append(i ? ' · ' : '', `${b.label} ${b.count}명`);
          if (isSub) {
            logBox.append(' ', el('input', { type: 'text', class: 'sec-in', placeholder: secs.length > 1 ? '(여러 수업)' : '수업 이름', title: '이 묶음 학생의 수업 이름(예: 물리학 A반). 비우면 새 학생은 수업 미지정, 이미 명렬에 있는 학생은 기존 수업을 그대로 둡니다. 수업을 지우려면 명렬 화면의 [수업 지정] > [수업 지정 해제]를 쓰세요.',
              value: secs.length === 1 ? secs[0] : '', onchange: (e) => { rows.forEach((r) => { r.section = e.target.value.trim(); }); renderRows(); } }));
          }
        });
      }
      undoBtn.disabled = !st.batches.length;
      undoBtn.textContent = st.batches.length ? `↶ 마지막 추가 취소(${st.batches[st.batches.length - 1].label})` : '↶ 마지막 추가 취소';
    }
    async function addClip() {
      const c = await api.read_clipboard();
      const text = c && c.ok ? (c.text || '') : '';
      if (!text.trim()) { toast('클립보드가 비어 있습니다. 엑셀에서 칸을 복사한 뒤 다시 누르세요.', 4000); return; }
      addText(text, '클립보드');
    }
    async function addText(text, label) {
      const r = await call('roster_from_text', text);
      if (r) await addParsed([{ ...r, file: label }], label, true);
    }
    async function addFiles() {
      const r = await call('roster_from_xlsx');
      if (!r) return;
      const files = [...r.files];
      const errors = [...(r.errors || [])];
      for (const a of r.ask || []) { // 시트가 여러 개인 파일: 시트를 골라 다시 읽기
        const sheets = await pickSheets(a, true);
        if (!sheets) continue;
        const x = await call('roster_from_xlsx', a.token, sheets);
        if (x) { files.push(...x.files); errors.push(...(x.errors || [])); }
      }
      if (errors.length) alertBox('읽지 못한 파일이 있습니다.\n' + errors.join('\n'));
      if (!files.length) return;
      await addParsed(files, files.length === 1 ? files[0].file : `파일 ${files.length}개`, false);
    }
    // 다른 담당의 명렬(활성 학생만, 전출 등 비활성 학생은 빼고)을 한 묶음으로
    async function addCopy() {
      const others = (ys.groups || []).filter((x) => x.id !== g.id && x.total);
      if (!others.length) { toast('명렬이 있는 다른 담당이 없습니다.'); return; }
      const sel = el('select', {}, others.map((x) => el('option', { value: x.id, text: `${x.label} (${x.active}명)` })));
      const gid = await new Promise((resolve) => {
        const done = (v) => { mapBox.innerHTML = ''; resolve(v); };
        mapBox.innerHTML = '';
        mapBox.appendChild(el('div', { class: 'map-ask' }, [
          el('b', { text: '어느 담당의 명렬을 가져올까요? 비활성(전출) 학생은 빼고 가져옵니다.' }),
          el('div', { class: 'toolbar' }, [sel, el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => done(null) }),
            el('button', { type: 'button', class: 'primary', text: '가져오기', onclick: () => done(+sel.value) })]),
        ]));
      });
      if (!gid) return;
      const r = await call('roster_copy_source', gid);
      if (!r) return;
      if (!r.rows.length) { toast('가져올 활성 학생이 없습니다.'); return; }
      pushBatch(r.rows.map((x) => ({ ...x, issues: [], notes: [] })), `${r.label} 명렬`);
    }
    function pushBatch(rows, label) {
      const id = ++st.seq;
      rows.forEach((row) => { row._batch = id; st.rows.push(row); });
      st.batches.push({ id, label, count: rows.length });
      log();
      renderRows();
      revalidate();
      toast(`${label}에서 ${rows.length}명을 추가했습니다.`);
    }
    const has = (v) => v !== null && v !== undefined && v !== '';
    function usable(cols) { return has(cols.name) && (has(cols.student_no) || (has(cols.class_no) && has(cols.number) && (has(cols.grade) || has(cols.grade_value)))); }
    // 여러 원본을 한 묶음으로 추가. 붙여넣기는 형태를 먼저 묻고, 파일은 머리글로 알아보면 바로 넣는다.
    async function addParsed(list, label, isPaste) {
      const all = [];
      for (const src of list) {
        const cols = { ...src.columns, level: null };
        const pick = (!isPaste && src.header && usable(cols)) ? { columns: cols, header: true } : await askFormat(src);
        if (!pick) continue;
        const r = await call('roster_build', g.id, src.raw, pick.header, pick.columns, true);
        if (r) all.push(...r.rows.map((x) => ({ ...x, section: isSub && !isPaste && src.file ? src.file.replace(/\.[^.]+$/, '') : '' })));
        if (r && isSub && !isPaste && src.file) toast(`파일 이름 '${src.file.replace(/\.[^.]+$/, '')}'을 수업 이름으로 넣었습니다. 위쪽 추가 기록에서 맞는지 확인하고 고치세요.`, 6000);
      }
      if (all.length) pushBatch(all, label);
    }
    // 명렬 형태 묻기: 학년·반·번호·이름(3열이면 반·번호·이름) / 학번·이름
    function askFormat(src) {
      return new Promise((resolve) => {
        const done = (v) => { mapBox.innerHTML = ''; resolve(v); };
        const width = src.raw[0].length;
        const digit = (v) => /^\d+$/.test((v || '').trim());
        const header = src.header || !src.raw[0].some(digit); // 첫 줄에 숫자 칸이 없으면 머리글
        const body = src.raw.slice(header ? 1 : 0);
        const title = `${src.file || '붙여넣은 내용'}(${body.length}줄)`;
        const ask = (content) => { mapBox.innerHTML = ''; mapBox.appendChild(el('div', { class: 'map-ask' }, content)); };
        const skip = () => el('button', { type: 'button', text: '이 원본 빼기', onclick: () => done(null) });
        const gradeBox = () => {
          if (g.kind === 'homeroom') return { el: el('div', { class: 'muted', text: `학년 열이 없으면 담임반 학년(${g.grade}학년)으로 넣습니다.` }), value: () => g.grade };
          const inp = el('input', { type: 'number', class: 'num', min: 1, max: 6, placeholder: '학년' });
          return { el: el('label', { class: 'inline' }, ['학년 열이 없습니다. 학년: ', inp]), value: () => inp.value };
        };
        const preview = (cols, gb) => {
          const t = el('table', { class: 'tbl mini' });
          t.appendChild(el('tr', {}, ['학년', '반', '번호', '이름'].map((h) => el('th', { text: h }))));
          body.slice(0, 3).forEach((r) => t.appendChild(el('tr', {}, [
            el('td', { text: has(cols.grade) ? r[cols.grade] || '' : '(입력한 학년)' }), el('td', { text: r[cols.class_no] || '' }),
            el('td', { text: r[cols.number] || '' }), el('td', { text: r[cols.name] || '' })])));
          return t;
        };
        const pickColumns = (list, c0, gb) => {
          const c = { ...c0 };
          const row = el('div', { class: 'map-row' });
          list.forEach(([key, label]) => {
            const sel = el('select', { onchange: (e) => { c[key] = e.target.value === '' ? null : +e.target.value; } },
              [el('option', { value: '', text: '(없음)' }), ...Array.from({ length: width }, (_, i) => el('option', { value: i, text: `${colName(i)}열: ${((body[0] || [])[i] || '').slice(0, 8)}`, selected: c[key] === i }))]);
            row.appendChild(el('label', {}, [label, sel]));
          });
          ask([el('b', { text: `${title}: 각 칸이 몇 번째 열인지 골라 주세요.` }), row, gb ? gb.el : null,
            el('div', { class: 'toolbar' }, [el('span', { class: 'spacer' }), skip(),
              el('button', { type: 'button', class: 'primary', text: '이대로 추가', onclick: () => {
                if (gb && !has(c.grade) && !has(c.student_no)) { if (!gb.value()) { toast('학년 열을 고르거나 학년을 넣어 주세요.'); return; } c.grade_value = gb.value(); }
                if (!usable(c)) { toast('이름 열과, 학번 열(또는 반·번호 열)을 골라 주세요.'); return; }
                done({ columns: c, header });
              } })])]);
        };
        const byNo = () => {
          const c = { student_no: src.columns.student_no, name: src.columns.name };
          if (has(c.student_no) && has(c.name)) done({ columns: c, header });
          else pickColumns([['student_no', '학번'], ['name', '이름']], c, null);
        };
        const byClass = () => {
          let c, gb = null;
          if (width >= 4) c = { grade: 0, class_no: 1, number: 2, name: 3 };
          else if (width === 3) { c = { class_no: 0, number: 1, name: 2 }; gb = gradeBox(); }
          else { pickColumns(roles.slice(0, 4), {}, gradeBox()); return; }
          ask([el('b', { text: `${title}: 이 순서가 맞나요?` }), preview(c, gb), gb ? gb.el : null,
            el('div', { class: 'toolbar' }, [el('span', { class: 'spacer' }), skip(),
              el('button', { type: 'button', text: '아니요, 열 직접 고르기', onclick: () => pickColumns(roles.slice(0, 4), c, gb || gradeBox()) }),
              el('button', { type: 'button', class: 'primary', text: '맞음', onclick: () => {
                if (gb) { if (!gb.value()) { toast('학년을 넣어 주세요.'); return; } c.grade_value = gb.value(); }
                done({ columns: c, header });
              } })])]);
        };
        ask([el('b', { text: `${title}: 복사한 명렬은 어떤 형태인가요?` }),
          el('div', { class: 'toolbar' }, [
            el('button', { type: 'button', class: 'primary', text: '학년 · 반 · 번호 · 이름', onclick: byClass }),
            el('button', { type: 'button', class: 'primary', text: '학번(5자리) · 이름', onclick: byNo }),
            el('span', { class: 'spacer' }), skip()]),
          el('div', { class: 'hint', text: '학년 칸이 없는 명렬(반·번호·이름)도 [학년 · 반 · 번호 · 이름]을 고르세요.' })]);
      });
    }
    function addLine() {
      const id = ++st.seq;
      st.rows.push({ _batch: id, student_no: '', name: '', grade: '', class_no: '', number: '', issues: ['학번 없음', '이름 없음'], notes: [] });
      st.batches.push({ id, label: '한 줄', count: 1 });
      log();
      renderRows();
      const inp = tableBox.querySelector('tr:last-child input[data-k="grade"]');
      if (inp) inp.focus();
    }
    function undoLast() {
      const b = st.batches.pop();
      if (!b) return;
      st.rows = st.rows.filter((r) => r._batch !== b.id);
      log();
      renderRows();
      revalidate();
      toast(`${b.label}에서 추가한 ${b.count}명을 뺐습니다.`);
    }
    const revalidate = debounce(async () => {
      if (!st.rows.length) { updateSummary(); return; }
      const r = await call('roster_validate', g.id, st.rows.map(plainRow), true);
      if (!r) return;
      r.rows.forEach((nr, i) => {
        const row = st.rows[i];
        if (!row) return;
        row.issues = nr.issues; row.notes = nr.notes; row.rename = !!nr.rename;
        ['grade', 'class_no', 'number', 'student_no'].forEach((k) => { if (!row[k] && nr[k]) { row[k] = nr[k]; const inp = row._tr && row._tr.querySelector(`[data-k="${k}"]`); if (inp) inp.value = nr[k]; } });
      });
      st.rows.forEach((row) => updateCheck(row));
      updateSummary();
    }, 350);
    function updateCheck(row) {
      if (!row._tr) return;
      row._tr.classList.toggle('bad', !!(row.issues && row.issues.length));
      const td = row._check;
      td.innerHTML = '';
      (row.issues || []).forEach((x) => td.appendChild(el('div', { class: 'issue', text: '! ' + x })));
      if (row.rename) td.appendChild(el('label', { class: 'inline', style: 'margin:2px 0 0;font-size:12.5px' }, [el('input', { type: 'checkbox', checked: !!row.rename_ok, onchange: (e) => { row.rename_ok = e.target.checked; revalidate(); } }), '이름 바꾸기 확인']));
      (row.notes || []).forEach((x) => td.appendChild(el('div', { class: 'note', text: x })));
      if (!(row.issues || []).length && !(row.notes || []).length) td.appendChild(el('span', { class: 'st st-closed', text: '✔ 정상' }));
    }
    function updateSummary() {
      const bad = st.rows.filter((r) => r.issues && r.issues.length).length;
      summary.innerHTML = '';
      summary.append(el('b', { text: `추가할 학생 ${st.rows.length}명` }), ' · ', el('b', { text: `정상 ${st.rows.length - bad}` }), ' / ', el('b', { class: bad ? 'danger-text' : '', text: `확인 필요 ${bad}` }));
      applyBtn.disabled = bad > 0 || !st.rows.length;
      applyBtn.textContent = `명렬에 추가 (${st.rows.length}명)`;
    }
    function renderRows() {
      tableBox.innerHTML = '';
      if (!st.rows.length) {
        tableBox.appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '아직 추가한 학생이 없습니다. 위 버튼으로 클립보드·파일·한 줄 입력을 섞어서 넣을 수 있습니다.' })]));
        updateSummary();
        return;
      }
      const t = el('table', { class: 'tbl' });
      t.appendChild(el('tr', {}, ['#', '학년', '반', '번호', '이름', '학번', ...(isSub ? ['수업'] : []), '확인', ''].map((h) => el('th', { text: h }))));
      st.rows.forEach((row, idx) => {
        if (st.onlyBad && !(row.issues && row.issues.length)) return;
        const tr = el('tr', {});
        const inp = (key, cls) => el('td', {}, [el('input', { type: 'text', class: cls || '', 'data-k': key, value: row[key] || '', oninput: (e) => { row[key] = e.target.value.trim(); revalidate(); } })]);
        tr.append(el('td', { class: 'muted', text: String(idx + 1) }), inp('grade', 'narrow'), inp('class_no', 'narrow'), inp('number', 'narrow'), inp('name'), inp('student_no'));
        if (isSub) tr.appendChild(el('td', {}, [el('input', { type: 'text', class: 'sec-in', value: row.section || '', placeholder: '(미지정)', title: '비우면 새 학생은 수업 미지정, 이미 있는 학생은 기존 수업 유지', onchange: (e) => { row.section = e.target.value.trim(); log(); } })]));
        row._check = el('td', {});
        tr.appendChild(row._check);
        tr.appendChild(el('td', {}, [el('button', { type: 'button', class: 'link', title: '행 빼기', text: '✕', onclick: () => { st.rows.splice(idx, 1); renderRows(); revalidate(); } })]));
        row._tr = tr;
        updateCheck(row);
        t.appendChild(tr);
      });
      tableBox.appendChild(t);
      updateSummary();
    }
    async function closeAsk() {
      if (st.rows.length && !(await confirmBox(`명렬에 아직 넣지 않은 ${st.rows.length}명이 있습니다. 닫으면 버립니다.`, '닫기'))) return;
      closeSheet();
    }
    async function apply() {
      const r = await mutate('roster_apply', g.id, st.rows.map(plainRow), 'add');
      if (!r) return;
      closeSheet();
      ys.groups = r.groups;
      toast(`${r.count}명을 명렬에 넣었습니다.`);
      if (onDone) onDone();
      else renderRoster();
    }
  }

  function openGroupForm(onDone) {
    const hasHomeroom = (ys.groups || []).some((g) => g.kind === 'homeroom');
    const kinds = [];
    if (ys.role === 'homeroom' && !hasHomeroom) kinds.push('homeroom');
    kinds.push('subject', 'club');
    let kind = kinds.includes('subject') ? 'subject' : kinds[0];
    openSheet((box) => {
      box.style.height = 'auto';
      box.style.width = 'min(560px, 92vw)';
      const form = el('div', {});
      const seg = el('div', { class: 'segmented' });
      const render = () => {
        seg.querySelectorAll('.seg').forEach((b) => b.classList.toggle('active', b.dataset.kind === kind));
        form.innerHTML = '';
        form.appendChild(groupFields(kind));
      };
      kinds.forEach((k) => seg.appendChild(el('button', { type: 'button', class: 'seg', 'data-kind': k, text: KIND_LABEL[k], onclick: () => { kind = k; render(); } })));
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '담당 추가' })]), seg, form,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', class: 'primary', text: '추가', onclick: async () => {
            const data = readGroupFields(form, kind);
            const r = await mutate('add_group', data);
            if (r) { ys.groups = r.groups; rosterSel = r.id; closeSheet(); toast('추가했습니다. 이어서 명렬을 등록하세요.'); (onDone || renderRoster)(); }
          } })]));
      render();
    });
  }
  function groupFields(kind) {
    const f = el('div', { class: 'map-row', style: 'margin-top:12px' });
    if (kind === 'homeroom') {
      f.append(el('label', {}, ['학년', el('input', { type: 'number', class: 'num', 'data-f': 'grade', min: 1, max: 6 })]),
        el('label', {}, ['반', el('input', { type: 'number', class: 'num', 'data-f': 'class_no', min: 1, max: 30 })]));
    } else if (kind === 'subject') {
      f.append(el('label', {}, ['과목 이름', el('input', { type: 'text', 'data-f': 'name', placeholder: '예: 공통수학1', style: 'width:200px' })]),
        el('label', {}, ['학기', el('select', { 'data-f': 'semester' }, [el('option', { value: 1, text: '1학기' }), el('option', { value: 2, text: '2학기' })])]),
        el('label', {}, ['성취수준', el('select', { 'data-f': 'level_scale' }, [el('option', { value: 5, text: '5단계(A~E)' }), el('option', { value: 3, text: '3단계(A~C)' })])]));
    } else {
      f.append(el('label', {}, ['동아리 이름', el('input', { type: 'text', 'data-f': 'name', placeholder: '예: 과학탐구반', style: 'width:220px' })]));
    }
    return f;
  }
  function readGroupFields(form, kind) {
    const data = { kind };
    form.querySelectorAll('[data-f]').forEach((i) => { data[i.dataset.f] = i.value; });
    return data;
  }

  // ---------- 설정 ----------
  function showSettingsTab(name) {
    document.querySelectorAll('#settingsTabs .tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.stab === name));
    document.querySelectorAll('.stab').forEach((s) => { s.hidden = s.dataset.stabContent !== name; });
    if (name === 'data') loadBackups();
    if (name === 'year') renderRoleCards($('roleCardsSettings'), ys.role, changeRole);
    if (name === 'sched') { renderTargets(); renderSchedTable(); }
  }
  function renderSettings() {
    $('cfgPath').textContent = info.config_path;
    $('dataDir').textContent = info.data_dir;
    $('delYearHint').textContent = `${ys.year}학년도`;
    $('delYearText').placeholder = `${ys.year}학년도`;
    $('newYear').value = Math.max(schoolYear(), (ys.year || 0) + 1);
    $('aboutName').textContent = info.name;
    $('aboutVer').textContent = 'v' + info.version;
    $('aboutMaker').textContent = info.maker;
    const active = document.querySelector('#settingsTabs .tab-btn.active');
    showSettingsTab(active ? active.dataset.stab : 'conn');
  }
  function fillConfigInputs() {
    document.querySelectorAll('[data-cfg]').forEach((inp) => {
      const v = cfg[inp.dataset.cfg];
      if (inp.type === 'checkbox') inp.checked = !!v;
      else inp.value = v === undefined || v === null ? '' : v;
    });
    renderModelSlots();
  }
  // 여러 칸을 연달아 바꿔도 모두 저장되도록 대기 중 변경을 합친다
  let cfgPending = {};
  let cfgTimer = null;
  function saveCfg(patch) {
    Object.assign(cfgPending, patch || {});
    clearTimeout(cfgTimer);
    cfgTimer = setTimeout(flushCfg, 400);
  }
  async function flushCfg() {
    clearTimeout(cfgTimer);
    const p = cfgPending;
    cfgPending = {};
    if (!Object.keys(p).length) return true;
    saveInflight += 1;
    try {
      const r = await call('save_config', p);
      if (r) markSaved(); else markSaveFailed();
      return !!r;
    } finally { saveInflight -= 1; refreshSaveState(); }
  }
  function bindConfigInputs() {
    document.querySelectorAll('[data-cfg]').forEach((inp) => {
      const handler = () => {
        const key = inp.dataset.cfg;
        const v = inp.type === 'checkbox' ? inp.checked : inp.value.trim();
        cfg[key] = v;
        saveCfg({ [key]: v });
        if (key === 'openrouter_key') { $('keyResult').textContent = ''; refreshBalanceSoon(); }
      };
      inp.addEventListener(inp.type === 'checkbox' || inp.tagName === 'SELECT' ? 'change' : 'input', handler);
    });
    document.querySelectorAll('.pw-toggle').forEach((b) => b.addEventListener('click', () => {
      const t = $(b.dataset.target);
      t.type = t.type === 'password' ? 'text' : 'password';
      b.textContent = t.type === 'password' ? '표시' : '숨김';
    }));
    $('checkKeyBtn').addEventListener('click', () => checkKey($('orKey').value, $('keyResult')));
    $('resetKeysBtn').addEventListener('click', async () => {
      if (!(await typedConfirm('OpenRouter·CLOVA 키를 모두 지웁니다. 학생 자료와 다른 설정은 그대로 둡니다. 지운 키는 백업에도 없어 다시 입력해야 합니다.', '키 초기화'))) return;
      cfgPending = {};
      clearTimeout(cfgTimer);
      if (await mutate('reset_keys')) {
        ['openrouter_key', 'clova_url', 'clova_secret'].forEach((k) => { cfg[k] = ''; });
        fillConfigInputs();
        $('balance').textContent = '-';
        toast('키를 지웠습니다.');
      }
    });
  }
  const refreshBalanceSoon = debounce(refreshBalance, 1200);
  async function checkKey(key, out) {
    out.className = 'check-result';
    out.textContent = '확인 중…';
    const r = await api.check_key(key.trim());
    if (r && r.ok) {
      out.classList.add('ok');
      out.textContent = `✔ 연결됨 · 잔액 ${r.balance === null || r.balance === undefined ? '확인 불가' : fmtCredit(r.balance) + ' 크레딧'}`;
      $('balance').textContent = r.balance === null || r.balance === undefined ? '확인 불가' : fmtCredit(r.balance);
      return true;
    }
    out.classList.add('err');
    out.textContent = '✕ ' + ((r && r.error) || '확인하지 못했습니다.');
    return false;
  }
  function renderModelSlots() {
    const box = $('modelSlots');
    box.innerHTML = '';
    cfg.models.forEach((m, i) => {
      const price = el('div', { class: 'price' }, [el('div', { class: 'price-main', text: m ? '확인 중…' : '비어 있음' }), el('div', { class: 'price-sub' })]);
      const input = el('input', { type: 'text', value: m, placeholder: i === 0 ? 'google/gemma-4-31b-it:free' : '모델 ID', class: 'grow' });
      const setModel = (v) => {
        cfg.models[i] = v.trim();
        saveCfg({ models: cfg.models.slice() });
        lookupPrice(cfg.models[i], price);
      };
      const lookupDebounced = debounce(setModel, 700);
      input.addEventListener('input', () => lookupDebounced(input.value));
      const radio = el('input', { type: 'radio', name: 'defaultModel', checked: cfg.default_model === i, onchange: () => { cfg.default_model = i; saveCfg({ default_model: i }); } });
      box.appendChild(el('div', { class: 'model-row' }, [
        el('div', { class: 'model-no', text: String(i + 1) }),
        el('div', { class: 'model-left' }, [
          el('label', { class: 'default-pick' }, [radio, '기본으로 사용']),
          el('div', { class: 'inline' }, [input,
            el('button', { type: 'button', 'data-url': 'https://openrouter.ai/models', text: '모델 페이지' }),
            el('button', { type: 'button', text: '붙여넣기', onclick: async () => { const c = await api.read_clipboard(); if (c && c.ok && c.text.trim()) { input.value = c.text.trim(); setModel(input.value); } else toast('클립보드가 비어 있습니다.'); } })]),
        ]),
        price,
      ]));
      if (m) lookupPrice(m, price);
    });
  }
  async function lookupPrice(id, box) {
    const main = box.querySelector('.price-main'), sub = box.querySelector('.price-sub');
    box.classList.remove('error');
    if (!id) { main.textContent = '비어 있음'; sub.textContent = ''; return; }
    main.textContent = '확인 중…';
    const r = await api.model_info(id);
    if (r && r.ok) {
      const f = (v) => (v === null || v === undefined ? '?' : v === 0 ? '무료' : v.toFixed(2));
      main.textContent = r.name;
      sub.textContent = `100만 토큰당 입력 ${f(r.prompt_per_m)} / 출력 ${f(r.completion_per_m)} 크레딧`;
    } else {
      box.classList.add('error');
      main.textContent = '모델을 찾지 못했습니다';
      sub.textContent = (r && r.error) || '';
    }
  }
  async function loadClovaGuide() {
    const html = await api.guide_html();
    const body = $('clovaGuideBody');
    body.innerHTML = html;
    const tabs = document.querySelectorAll('#clovaGuide [data-gtab]');
    const show = (name) => {
      tabs.forEach((t) => t.classList.toggle('active', t.dataset.gtab === name));
      body.querySelectorAll('.tab-content').forEach((c) => c.classList.toggle('active', c.dataset.tabContent === name));
    };
    tabs.forEach((t) => t.addEventListener('click', () => show(t.dataset.gtab)));
    show('signup');
  }

  function renderRoleCards(box, current, onPick) {
    box.innerHTML = '';
    const card = (role, title, items) => el('button', { type: 'button', class: 'role-card' + (current === role ? ' active' : ''), onclick: () => onPick(role) }, [
      el('h3', { text: title }), el('div', { class: 'muted', text: '쓰는 항목' }), el('ul', {}, items.map((x) => el('li', { text: x }))),
    ]);
    box.append(
      card('homeroom', '담임', ['자율활동 · 진로활동 · 행동특성 및 종합의견 (담임반, 연간)', '과목별 세특 (학기별)', '동아리활동 (연간)']),
      card('subject', '비담임', ['과목별 세특 (학기별)', '동아리활동 (연간)']),
    );
  }
  async function changeRole(role) {
    if (ys.archived) { toast('보관 학년도는 바꿀 수 없습니다.'); return; }
    if (role === ys.role) return;
    const p = await call('role_change_preview', role);
    if (!p) return;
    if (!(await confirmBox(p.message, '바꾸기'))) return;
    if (await mutate('set_role', role)) { await reloadYear(); showSettingsTab('year'); toast('역할을 바꿨습니다.'); }
  }
  function renderTargets() {
    const box = $('targetGrid');
    box.innerHTML = '';
    const items = ys.role === 'homeroom' ? ['autonomy', 'career', 'behavior', 'subject', 'club'] : ['subject', 'club'];
    items.forEach((k) => {
      const inp = el('input', { type: 'number', class: 'num', value: ys.targets[k], min: 1, step: 100, disabled: !!ys.archived });
      inp.addEventListener('change', async () => {
        const r = await mutate('set_target', k, inp.value);
        if (r) ys.targets = r.targets; else inp.value = ys.targets[k];
      });
      box.appendChild(el('div', {}, [el('label', { text: ITEM_FULL[k] }), el('div', { class: 'inline' }, [inp, `바이트 (한글 약 ${Math.round(ys.targets[k] / 3)}자)`])]));
    });
  }
  function renderSchedTable() {
    const t = $('schedTable');
    t.innerHTML = '';
    t.appendChild(el('tr', {}, ['날짜', '내용', 'D-day', ''].map((h) => el('th', { text: h }))));
    const list = ys.schedules || [];
    if (!list.length) t.appendChild(el('tr', {}, [el('td', { colspan: 4, class: 'muted', text: '등록된 일정이 없습니다.' })]));
    list.forEach((s) => {
      const d = daysUntil(s.date);
      const date = el('input', { type: 'date', value: s.date, disabled: !!ys.archived });
      const title = el('input', { type: 'text', value: s.title, disabled: !!ys.archived });
      const save = async () => { const r = await mutate('update_schedule', s.id, date.value, title.value); if (r) { ys.schedules = r.schedules; renderSchedTable(); } };
      date.addEventListener('change', save);
      title.addEventListener('change', save);
      t.appendChild(el('tr', { class: d < 0 ? 'past' : '' }, [el('td', {}, [date]), el('td', {}, [title]),
        el('td', { text: d < 0 ? '지남' : d === 0 ? 'D-Day' : `D-${d}` }),
        el('td', {}, [el('button', { type: 'button', class: 'link danger-text edit-only', text: '삭제', onclick: async () => { const r = await mutate('delete_schedule', s.id); if (r) { ys.schedules = r.schedules; renderSchedTable(); } } })])]));
    });
  }
  async function addSchedule(dateInp, titleInp, after) {
    const r = await mutate('add_schedule', dateInp.value, titleInp.value);
    if (!r) return;
    ys.schedules = r.schedules;
    titleInp.value = '';
    after();
  }
  // 백업 이름(YYYY-MM-DD_HHMMSS[_사유][_n])을 읽기 쉽게: 백업 시점 / 마지막 작업(왜 만들었나) / 내용
  const BACKUP_WHY = {
    '': ['하루 자동 백업', '앱을 켤 때 하루 한 번'],
    수동: ['직접 백업', '[지금 백업]을 누름'],
    업데이트전: ['업데이트 직전', '새 버전으로 바꾸기 전 · 따로 보관'],
    형식변경전: ['자료 형식 변경 직전', '새 버전을 처음 켤 때 · 따로 보관'],
    복원전: ['다른 백업으로 복원하기 직전', '복원을 되돌릴 때 이 백업으로'],
    담당삭제전: ['담당 삭제 직전', ''],
    학생삭제전: ['학생 삭제 직전', ''],
    삭제전: ['학년도 자료 삭제 직전', ''],
  };
  function backupMeta(name) {
    const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})(?:_([^_]+))?(?:_(\d+))?$/.exec(name);
    if (!m) return { when: name, why: ['알 수 없음', ''], reason: '' };
    const d = new Date(+m[1], +m[2] - 1, +m[3]);
    const wd = '일월화수목금토'[d.getDay()];
    const why = BACKUP_WHY[m[7] || ''] || [m[7], ''];
    return { when: `${m[1]}. ${+m[2]}. ${+m[3]}.(${wd}) ${m[4]}:${m[5]}:${m[6]}`, why, reason: m[7] || '' };
  }
  async function restoreBackup(name, label) {
    if (!(await leaveOk())) return;
    if (!(await typedConfirm(`'${label}' 백업으로 지금 자료를 모두 바꿉니다.\n바꾸기 전에 지금 상태를 '복원하기 직전' 백업으로 먼저 남기므로, 잘못 복원했으면 그 백업으로 다시 복원해 되돌릴 수 있습니다.\n그 사이에 새로 입력한 내용은 되돌릴 때 사라집니다.`, '복원'))) return;
    const x = await mutate('restore_backup', name);
    if (!x) return;
    await reloadYear();
    loadBackups();
    const safety = x.safety;
    if (safety) {
      actionToast('복원했습니다. 복원 전 상태로 되돌리려면 [복원 되돌리기]를 누르세요(설정 > 백업에도 남아 있음).', '복원 되돌리기', async () => {
        if (!(await typedConfirm(`복원하기 직전 상태(${backupMeta(safety).when})로 되돌립니다. 복원한 뒤 새로 입력한 내용은 사라집니다.`, '되돌리기'))) return;
        const y = await mutate('restore_backup', safety);
        if (y) { toast('복원 전 상태로 되돌렸습니다.'); await reloadYear(); loadBackups(); }
      }, 60000);
    } else toast('복원했습니다.');
  }
  async function loadBackups() {
    const r = await call('backups');
    const t = $('backupTable');
    t.innerHTML = '';
    t.appendChild(el('tr', {}, ['백업 시점', '마지막 작업', '내용', ''].map((h) => el('th', { text: h }))));
    if (!r || !r.backups.length) { t.appendChild(el('tr', {}, [el('td', { colspan: 4, class: 'muted', text: '아직 백업이 없습니다.' })])); return; }
    r.backups.forEach((b) => {
      const meta = backupMeta(b.name);
      const years = b.files.map((f) => f.replace('.sqlite', '')).join(', ');
      addTo(t, el('tr', { class: meta.reason === '업데이트전' || meta.reason === '형식변경전' ? 'bk-special' : '' }, [
        el('td', { class: 'bk-when', title: b.name, text: meta.when }),
        el('td', {}, [el('b', { text: meta.why[0] }), meta.why[1] ? el('div', { class: 'muted small-note', text: meta.why[1] }) : null]),
        el('td', {}, [years, b.legacy ? el('div', { class: 'muted small-note', text: '이전 형식(스캔 원본 미포함) — 복원해도 지금 스캔 원본은 그대로 둡니다.' }) : (b.scans ? el('div', { class: 'muted small-note', text: `스캔 원본 ${b.scans}개 포함` }) : null)]),
        el('td', { class: 'bk-act' }, [el('button', { type: 'button', text: '이 백업으로 복원', onclick: () => restoreBackup(b.name, `${meta.when} · ${meta.why[0]}`) })]),
      ]));
    });
  }

  // ---------- 업데이트 ----------
  let updateInfo = null;
  // 새 버전 exe로 바꿔 두었다. 학교 보안 프로그램 때문에 자동으로 켜지 않고 다시 시작을 안내한다.
  async function updateReady(version) {
    $('updateBar').hidden = false;
    $('updateText').textContent = `v${version}로 바꿔 두었습니다. 앱을 종료한 뒤 다시 시작하면 새 버전이 적용됩니다.`;
    $('updateNowBtn').hidden = true;
    $('updateNotesBtn').hidden = true;
    $('updateLaterBtn').textContent = '닫기';
    const quit = await modal(`<b>새 버전(v${version})으로 바꿨습니다.</b><br>앱을 종료한 뒤 다시 시작해 주세요.<br><br>` +
      `<span class="muted">학교 보안 프로그램이 새 파일 실행을 막으면, 보안 프로그램에서 <b>생기부착즙기.exe</b>를 예외(허용)로 등록해 주세요.</span>`, true, true, '지금 종료', '나중에');
    if (quit) window.__beforeClose();
  }
  // 화면을 없애거나 합쳐 자료 위치가 바뀌는 업데이트: 안내를 읽고 '확인했어요'를 직접 쳐야 [업데이트]가 눌린다.
  function updateWarnSheet(info) {
    const word = info.confirm_word || '확인했어요';
    return new Promise((resolve) => openSheet((box) => {
      box.style.height = 'auto'; box.style.width = 'min(640px, 94vw)';
      const inp = el('input', { type: 'text', placeholder: word, autocomplete: 'off' });
      const go = el('button', { type: 'button', class: 'primary', disabled: true, text: '업데이트' });
      inp.addEventListener('input', () => { go.disabled = inp.value.trim() !== word; });
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !go.disabled) go.click(); });
      const done = (v) => { closeSheet(); resolve(v); };
      go.addEventListener('click', () => done(inp.value.trim()));
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: `⚠ v${info.version} 업데이트 전 꼭 읽어 주세요` })]),
        el('div', { class: 'sheet-body' }, [
          el('div', { class: 'warn upd-warn', text: info.warning }),
          el('p', { class: 'hint', text: '업데이트 직전에 자료 전체를 백업합니다(설정 > 백업에서 복원 가능). 이 백업은 하루 백업에 밀려 지워지지 않게 따로 보관합니다.' }),
          el('label', {}, [`내용을 확인했으면 아래 칸에 '${word}'를 그대로 입력하세요.`]), inp,
        ]),
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => done(null) }), go]),
      );
      setTimeout(() => inp.focus(), 50);
    }));
  }
  function showUpdate(ev) {
    updateInfo = ev;
    $('updateText').textContent = `새 버전 v${ev.version}이(가) 있습니다.`;
    $('updateNowBtn').textContent = ev.can_apply ? '지금 업데이트' : '내려받기 페이지';
    $('updateBar').hidden = false;
  }

  // ---------- 마법사 ----------
  const W = { step: 1, mode: 'first', year: 0, role: '', grade: '', class_no: '', pending: [], keyChecked: null };
  function openWizard(mode, startStep, year) {
    W.mode = mode;
    W.step = startStep;
    W.year = year || ys.year || schoolYear();
    W.role = mode === 'first' ? (ys.role || '') : '';
    W.pending = [];
    $('wizard').hidden = false;
    renderWizard();
  }
  function renderWizard() {
    document.querySelectorAll('#wsteps li').forEach((li) => {
      const n = +li.dataset.w;
      li.classList.toggle('active', n === W.step);
      li.classList.toggle('done', n < W.step);
      li.hidden = W.mode === 'newyear' && n === 1;
    });
    const body = $('wizardBody');
    body.innerHTML = '';
    $('wHint').textContent = '';
    const first = W.mode === 'newyear' ? 2 : 1;
    $('wPrev').textContent = W.step === first && W.mode === 'newyear' ? '취소' : '이전';
    $('wPrev').hidden = W.step === first && W.mode === 'first';
    $('wNext').textContent = W.step === 4 ? '시작하기' : '다음';
    if (W.mode === 'first' && dataDir) {
      body.appendChild(el('div', { class: 'wiz-dir' }, [el('b', { text: '자료 폴더: ' }), dataDir,
        ys.years && ys.years.length ? null : el('div', { class: 'muted', text: '이 폴더에는 아직 자료가 없습니다. 쓰던 자료가 있다면 다른 폴더의 exe를 실행한 것일 수 있습니다. 앱을 끄고 원래 폴더의 exe를 실행하세요.' })]));
    }
    [null, wStep1, wStep2, wStep3, wStep4][W.step](body);
  }
  function wStep1(body) {
    const key = el('input', { type: 'password', value: cfg.openrouter_key || '', placeholder: 'sk-or-...', autocomplete: 'off' });
    const res = el('span', { class: 'check-result' });
    key.addEventListener('input', () => { cfg.openrouter_key = key.value.trim(); saveCfg({ openrouter_key: cfg.openrouter_key }); W.keyChecked = null; res.textContent = ''; });
    const priv = el('input', { type: 'checkbox', checked: cfg.privacy_block, onchange: (e) => { cfg.privacy_block = e.target.checked; saveCfg({ privacy_block: cfg.privacy_block }); } });
    body.append(
      el('h3', { text: 'OpenRouter 연결 (필수)' }),
      el('details', { class: 'guide-box', open: !cfg.openrouter_key }, [el('summary', { text: '처음 사용하시나요? 가입 - 키 발급 안내' }), el('ol', { html: $('orGuide').querySelector('ol').innerHTML })]),
      el('label', { text: 'OpenRouter API 키' }),
      el('div', { class: 'inline' }, [el('div', { class: 'pw-wrap grow' }, [key, el('button', { type: 'button', class: 'pw-toggle', text: '표시', onclick: (e) => { key.type = key.type === 'password' ? 'text' : 'password'; e.target.textContent = key.type === 'password' ? '표시' : '숨김'; } })]),
        el('button', { type: 'button', text: '연결 확인', onclick: async () => { W.keyChecked = await checkKey(key.value, res); } })]),
      res,
      el('div', { class: 'wsection' }, [
        el('div', {}, ['AI 모델: 1번 칸에 무료 모델 ', el('code', { text: cfg.models[0] || '(비어 있음)' }), ' 이 들어 있습니다. 설정에서 4칸까지 등록할 수 있습니다.']),
        el('label', { class: 'check-line' }, [priv, 'OpenRouter 학습 차단 켜기 (기본 꺼짐)']),
        el('div', { class: 'hint', text: '켜면 데이터를 수집·보관하지 않는 제공자에게만 보냅니다. 무료 모델과 일부 모델은 쓸 수 없게 됩니다.' }),
      ]),
      el('div', { class: 'wsection' }, [el('b', { text: 'CLOVA OCR' }), ' — 스캔 PDF를 가져올 때 설정합니다(네이버 클라우드 플랫폼 가입 필요). 지금은 건너뛰어도 됩니다.']),
      el('div', { class: 'notice', style: 'margin-top:12px', html: '키는 프로그램 폴더의 설정 파일에 <b>평문</b>으로 저장됩니다. 공용 PC에서는 사용 후 설정의 [키 초기화]를 눌러 주세요. <b>본인이 발급받은 키만</b> 사용하세요.' }),
    );
  }
  function wStep2(body) {
    const yearInp = el('input', { type: 'number', class: 'num', value: W.year, min: 2000, max: 2100, onchange: (e) => { W.year = +e.target.value; } });
    const roleBox = el('div', { class: 'role-cards' });
    const detail = el('div', {});
    const draw = () => {
      renderRoleCards(roleBox, W.role, (r) => { W.role = r; $('wHint').textContent = ''; draw(); });
      detail.innerHTML = '';
      if (!W.role) return;
      const existing = ys.year === W.year ? (ys.groups || []) : [];
      const hr = existing.find((g) => g.kind === 'homeroom');
      if (W.role === 'homeroom') {
        if (hr && !W.grade) { W.grade = hr.grade; W.class_no = hr.class_no; }
        detail.appendChild(el('div', { class: 'wsection' }, [el('h3', { text: '담임반' }), el('div', { class: 'map-row' }, [
          el('label', {}, ['학년', el('input', { type: 'number', class: 'num', value: W.grade, min: 1, max: 6, oninput: (e) => { W.grade = e.target.value; } })]),
          el('label', {}, ['반', el('input', { type: 'number', class: 'num', value: W.class_no, min: 1, max: 30, oninput: (e) => { W.class_no = e.target.value; } })]),
          el('span', { class: 'muted', text: '담임 항목은 연간 기록입니다. 3학년 담임반은 1학기 말 마감 대상으로 표시됩니다.' }),
        ])]));
      }
      const listBox = el('div', { class: 'pending-list' });
      const drawList = () => {
        listBox.innerHTML = '';
        existing.filter((g) => g.kind !== 'homeroom').forEach((g) => listBox.appendChild(el('span', { class: 'tag', text: `✔ ${g.label}` })));
        W.pending.forEach((p, i) => listBox.appendChild(el('span', { class: 'tag' }, [p.kind === 'subject' ? `${p.name}·${p.semester}학기` : `${p.name}·동아리`,
          el('button', { type: 'button', class: 'link', text: '✕', onclick: () => { W.pending.splice(i, 1); drawList(); } })])));
        if (!listBox.children.length) listBox.appendChild(el('span', { class: 'muted', text: '아직 추가한 과목·동아리가 없습니다.' }));
      };
      const sName = el('input', { type: 'text', placeholder: '예: 공통수학1', style: 'width:200px', 'data-w': 'subject' });
      const sSem = el('select', {}, [el('option', { value: 1, text: '1학기' }), el('option', { value: 2, text: '2학기' })]);
      const sScale = el('select', {}, [el('option', { value: 5, text: '5단계(A~E)' }), el('option', { value: 3, text: '3단계(A~C)' })]);
      const cName = el('input', { type: 'text', placeholder: '예: 과학탐구반', style: 'width:200px', 'data-w': 'club' });
      const addS = () => { if (!sName.value.trim()) return; W.pending.push({ kind: 'subject', name: sName.value.trim(), semester: +sSem.value, level_scale: +sScale.value }); sName.value = ''; drawList(); };
      const addC = () => { if (!cName.value.trim()) return; W.pending.push({ kind: 'club', name: cName.value.trim() }); cName.value = ''; drawList(); };
      sName.addEventListener('keydown', (e) => { if (e.key === 'Enter') addS(); });
      cName.addEventListener('keydown', (e) => { if (e.key === 'Enter') addC(); });
      W._flush = () => { addS(); addC(); };
      detail.appendChild(el('div', { class: 'wsection' }, [
        el('h3', { text: '내가 맡은 과목·동아리' }),
        el('div', { class: 'map-row' }, [el('label', {}, ['과목', sName]), sSem, sScale, el('button', { type: 'button', text: '과목 추가', onclick: addS })]),
        el('div', { class: 'hint', text: '과목은 학기마다 따로 등록합니다(예: 공통수학1은 1학기, 공통수학2는 2학기).' }),
        el('div', { class: 'map-row' }, [el('label', {}, ['동아리', cName]), el('button', { type: 'button', text: '동아리 추가', onclick: addC })]),
        listBox,
      ]));
      drawList();
    };
    body.append(
      el('h3', { text: '학년도와 역할' }),
      el('div', { class: 'inline' }, [yearInp, '학년도', W.mode === 'newyear' ? el('span', { class: 'muted', text: '새 학년도를 시작하면 이전 학년도는 보관·조회 전용이 됩니다.' }) : null]),
      el('div', { style: 'height:10px' }),
      roleBox, detail,
    );
    draw();
  }
  function wStep3(body) {
    const groups = visibleGroups();
    const done = groups.filter((g) => g.total).length;
    body.append(el('h3', { text: '명렬 등록' }),
      el('p', { class: 'hint', text: `엑셀에서 학번·이름 칸을 복사해 붙여넣거나 xlsx를 불러오세요. 지금 하지 않아도 되지만, 자료를 학생에게 연결하려면 명렬이 필요합니다. (등록 ${done}/${groups.length})` }));
    const t = el('table', { class: 'tbl' });
    t.appendChild(el('tr', {}, ['담당', '상태', ''].map((h) => el('th', { text: h }))));
    groups.forEach((g) => t.appendChild(el('tr', {}, [el('td', { text: g.label }),
      el('td', {}, [g.total ? el('span', { class: 'st st-closed', text: `✔ ${g.active}명 등록됨` }) : el('span', { class: 'muted', text: '미등록' })]),
      el('td', {}, [el('div', { class: 'inline' }, [
        el('button', { type: 'button', class: g.total ? '' : 'primary', text: '📋 클립보드에서 추가', onclick: () => importFromClipboard(g, wizardAfterRoster) }),
        el('button', { type: 'button', text: '📂 파일 추가', onclick: () => importFromXlsx(g, wizardAfterRoster) }),
      ])])])));
    body.appendChild(t);
  }
  async function wizardAfterRoster() { await reloadYear(); renderWizard(); }
  function wStep4(body) {
    const date = el('input', { type: 'date' });
    const title = el('input', { type: 'text', class: 'grow', placeholder: '예: 1학기 세특 입력 마감' });
    const list = el('div', {});
    const drawList = () => {
      list.innerHTML = '';
      const t = el('table', { class: 'tbl', style: 'margin-top:8px' });
      (ys.schedules || []).forEach((s) => t.appendChild(el('tr', {}, [el('td', { text: s.date }), el('td', { text: s.title }),
        el('td', {}, [el('button', { type: 'button', class: 'link danger-text', text: '삭제', onclick: async () => { const r = await mutate('delete_schedule', s.id); if (r) { ys.schedules = r.schedules; drawList(); } } })])])));
      if ((ys.schedules || []).length) list.appendChild(t);
    };
    const missing = visibleGroups().filter((g) => !g.total);
    body.append(
      el('h3', { text: '생기부 일정 (건너뛰어도 됩니다)' }),
      el('p', { class: 'hint', text: '학교 생기부 마감 일정을 넣으면 현황판 맨 위에 D-day로 보입니다. 나중에 설정 > 분량·일정에서도 넣을 수 있습니다.' }),
      el('div', { class: 'inline' }, [date, title, el('button', { type: 'button', text: '추가', onclick: () => addSchedule(date, title, drawList) })]),
      list,
      el('div', { class: 'wsection' }, [
        el('h3', { text: '준비 상태' }),
        el('div', {}, visibleGroups().map((g) => el('span', { class: 'tag' + (g.total ? '' : ' warn-tag'), text: `${g.label}: ${g.total ? g.active + '명' : '명렬 미등록'}` }))),
        missing.length ? el('p', { class: 'warn' }, [`명렬이 없는 담당 ${missing.length}곳: 자료를 학생에게 연결하기 전에 명렬이 필요합니다. `,
          el('button', { type: 'button', class: 'link', text: '명렬 등록하러 가기', onclick: async () => { await finishWizard(); rosterSel = missing[0].id; showPanel('roster'); } })]) : el('p', { class: 'st st-closed', text: '✔ 모든 담당의 명렬이 준비됐습니다.' }),
      ]),
    );
    drawList();
  }
  async function wizardNext() {
    if (W.step === 1) {
      if (!(cfg.openrouter_key || '').trim()) { $('wHint').textContent = 'OpenRouter API 키를 입력해 주세요.'; return; }
      if (W.keyChecked === false && !(await confirmBox('연결 확인에 실패했습니다. 그래도 계속할까요? 나중에 설정에서 다시 확인할 수 있습니다.', '계속'))) return;
      if (W.keyChecked === null) checkKey(cfg.openrouter_key, el('span', {}));
      W.step = 2;
    } else if (W.step === 2) {
      if (W._flush) W._flush();
      if (!W.year || W.year < 2000) { $('wHint').textContent = '학년도를 입력해 주세요.'; return; }
      if (!W.role) { $('wHint').textContent = '담임 또는 비담임을 골라 주세요.'; return; }
      if (W.mode === 'newyear' && (ys.years || []).includes(W.year)) { $('wHint').textContent = `${W.year}학년도는 이미 있습니다. 상단에서 학년도를 바꿔 주세요.`; return; }
      if (W.role === 'homeroom' && (!W.grade || !W.class_no)) { $('wHint').textContent = '담임반의 학년과 반을 입력해 주세요.'; return; }
      const existing = ys.year === W.year ? (ys.groups || []) : [];
      if (W.role === 'subject' && !W.pending.length && !existing.some((g) => g.kind !== 'homeroom')) { $('wHint').textContent = '과목이나 동아리를 하나 이상 추가해 주세요.'; return; }
      if (!(await mutate('create_year', W.year, W.role))) return;
      await reloadYear();
      const hr = (ys.groups || []).find((g) => g.kind === 'homeroom');
      if (W.role === 'homeroom') {
        const ok = hr ? await mutate('update_group', hr.id, { grade: W.grade, class_no: W.class_no }) : await mutate('add_group', { kind: 'homeroom', grade: W.grade, class_no: W.class_no });
        if (!ok) return;
      }
      const left = [];
      for (const p of W.pending) {
        const r = await api.add_group(p);
        if (!r || !r.ok) left.push([p, r && r.error]);
      }
      W.pending = left.map((x) => x[0]);
      await reloadYear();
      if (left.length) { await alertBox('추가하지 못한 항목:\n' + left.map(([p, e]) => `${p.name}: ${e}`).join('\n')); renderWizard(); return; }
      W.step = 3;
    } else if (W.step === 3) {
      W.step = 4;
    } else {
      await finishWizard();
      showPanel('dashboard');
      actionToast('설정을 마쳤습니다. 처음이시면 사용 안내를 한 번 훑어보세요.', '사용 안내 열기', () => openGuide('g-flow'), 12000);
      return;
    }
    renderWizard();
  }
  function wizardPrev() {
    const first = W.mode === 'newyear' ? 2 : 1;
    if (W.step === first) { if (W.mode === 'newyear') $('wizard').hidden = true; return; }
    W.step -= 1;
    renderWizard();
  }
  async function finishWizard() {
    await mutate('finish_setup');
    cfg.setup_done = true;
    $('wizard').hidden = true;
    await reloadYear();
    fillConfigInputs();
  }

  // =====================================================================
  // v0.2: 항목별 기록 · 정제/종합 · 최종안 · 마감 · 태그 · 내보내기 · 프롬프트
  // =====================================================================
  const R = { slots: [], slot: null, students: [], sno: null, view: null, filter: '', search: '', selected: new Set(), busy: new Set() };
  const slotKey = (s) => `${s.group_id}:${s.item}`;
  const OP_LABEL = { refine: '정제', polish: '다듬기', synth: '종합' };

  function setCredits(r) {
    if (!r) return;
    if (r.run_cost !== undefined) { runCost = r.run_cost; $('runCost').textContent = fmtCredit(runCost); }
    if (r.balance !== undefined) $('balance').textContent = r.balance === null ? '확인 불가' : fmtCredit(r.balance);
  }
  function bytesOf(t) {
    let n = 0;
    for (const ch of t || '') { const c = ch.codePointAt(0); n += (c >= 0xac00 && c <= 0xd7a3) || (c >= 0x1100 && c <= 0x11ff) || (c >= 0x3130 && c <= 0x318f) || (c >= 0xa960 && c <= 0xa97f) || (c >= 0xd7b0 && c <= 0xd7ff) ? 3 : 1; }
    return n;
  }
  function bytesEl(n, target) {
    const over = target && n > target;
    return el('span', { class: 'bytes' + (over ? ' over' : ''), text: target ? `${n} / ${target}B${over ? ` · ${n - target}B 초과` : ''}` : `${n}B` });
  }
  function fillModelSelect(sel) {
    const prev = sel.value;
    sel.innerHTML = '';
    cfg.models.forEach((m, i) => { if (m) sel.appendChild(el('option', { value: i, text: `${i + 1}번 · ${m}`, selected: prev === '' ? i === cfg.default_model : String(i) === prev })); });
    if (!sel.options.length) sel.appendChild(el('option', { value: '', text: '모델 없음(설정에서 등록)' }));
  }
  // ---------- AI 작업: 확인 창 → 진행 창 → 결과 ----------
  // 모든 AI 버튼은 바로 실행하지 않고 확인을 한 번 받는다. 실행 중에는 진행 창(건수·경과 시간·여러 건이면 중지)을 띄운다.
  const escHtml = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  function modelName(sel) { const o = sel && sel.selectedOptions && sel.selectedOptions[0]; return o ? o.textContent : '-'; }
  // kind: 프롬프트를 고르는 작업이면 'synth'(종합·생성) / 'refine'(기록 정제) / 'polish'(다듬기). 없으면 고정 프롬프트 작업.
  // prefer: 이 실행의 처음 고르기 값(예: 스캔 묶음은 '스캔 내용 정리'). 목록에 없으면 작업별 기억값.
  // 확인 없이 바로 실행되던 AI 버튼용 확인 창. scope를 주면 '이 창을 닫을 때까지 다시 묻지 않기'(대화·시험처럼 연달아 누르는 곳)
  const AI_ASK_SKIP = new Set();
  async function aiAsk(title, rows, scope) {
    if (scope && AI_ASK_SKIP.has(scope)) return true;
    const html = `<div class="ai-conf"><b>${escHtml(title)}</b> — AI로 실행할까요?<table>${rows.filter(Boolean).map(([k, v]) => `<tr><th>${escHtml(k)}</th><td>${escHtml(v)}</td></tr>`).join('')}</table>`
      + `<p class="hint">실행하면 크레딧이 듭니다.</p>`
      + (scope ? '<label class="inline" style="margin:0"><input type="checkbox" id="aiAskSkip"> 이 창을 닫을 때까지 다시 묻지 않기</label>' : '') + '</div>';
    $('modalOk').classList.add('ai-btn');
    const p = modal(html, true, true, 'AI 실행', '취소');
    let skip = false;
    const cb = $('aiAskSkip');
    if (cb) cb.addEventListener('change', () => { skip = cb.checked; });
    const ok = await p.finally(() => $('modalOk').classList.remove('ai-btn'));
    if (ok && skip && scope) AI_ASK_SKIP.add(scope);
    return !!ok;
  }
  // 프롬프트 고르는 칸: 직접 만든 것(이 태그에서 쓴 것 먼저)을 위에, 기본 프롬프트는 맨 아래 묶음(옅은 색)으로
  function promptOpts(list, { tagName, label, selected } = {}) {
    const lab = label || ((p) => p.name);
    const used = (p) => (tagName && (p.tags || []).includes(tagName) ? 1 : 0);
    const mine = (list || []).filter((p) => !p.builtin).map((p, i) => [p, i]).sort((a, b) => used(b[0]) - used(a[0]) || a[1] - b[1]).map((x) => x[0]);
    const base = (list || []).filter((p) => p.builtin);
    const opt = (p) => el('option', { value: p.id, class: p.builtin ? 'opt-builtin' : '', text: lab(p), selected: selected === p.id });
    return [...mine.map(opt), base.length ? el('optgroup', { label: '📦 기본 프롬프트', class: 'opt-builtin' }, base.map(opt)) : null].filter(Boolean);
  }
  async function aiConfirm(title, rows, warn, kind, prefer) {
    let pick = '';
    let opts = '';
    if (kind) {
      const r = await loadPromptList();
      if (r) {
        pick = prefer && r.prompts.some((x) => x.id === prefer) ? prefer : r.picks[kind] || '';
        const o1 = (x) => `<option value="${escHtml(x.id)}"${x.builtin ? ' class="opt-builtin"' : ''}${x.id === pick ? ' selected' : ''}>${escHtml(x.name)}</option>`;
        const base = r.prompts.filter((x) => x.builtin);
        opts = r.prompts.filter((x) => !x.builtin).map(o1).join('') + (base.length ? `<optgroup label="📦 기본 프롬프트" class="opt-builtin">${base.map(o1).join('')}</optgroup>` : '');
      }
    }
    const html = `<div class="ai-conf"><b>${escHtml(title)}</b> — AI로 실행할까요?<table>${rows.filter(Boolean).map(([k, v]) => `<tr><th>${escHtml(k)}</th><td>${escHtml(v)}</td></tr>`).join('')}`
      + (opts ? `<tr><th>프롬프트</th><td><select id="aiPrompt">${opts}</select> <span class="muted">(${escHtml(P.data.kinds[kind])} · 고친 것은 메뉴 › 프롬프트)</span></td></tr>` : '') + '</table>'
      + `<label class="ai-extra-label" for="aiExtra">이번 추가 요구 사항 <span class="muted">(선택 · 이번 실행에만 · 저장된 지침은 그대로)</span></label>`
      + `<textarea id="aiExtra" rows="2" maxlength="1000" placeholder="예: 숫자는 빼 줘 / 탐구 과정을 더 강조 / 두 문장으로 짧게"></textarea>`
      + `<p class="hint">명렬의 학번·이름은 따로 보내지 않습니다. 다만 기록 본문에 적힌 이름 등은 그대로 보내지니 확인하세요. 실행하면 크레딧이 듭니다.${warn ? `<br>${escHtml(warn)}` : ''}</p></div>`;
    $('modalOk').classList.add('ai-btn');
    // 반환: 취소면 null, 실행이면 { extra(추가 요구 사항), prompt(고른 프롬프트 id), kind }
    return modal(html, true, true, 'AI 실행', '취소').then((ok) => (ok ? { extra: ($('aiExtra') ? $('aiExtra').value : '').trim(), prompt: $('aiPrompt') ? $('aiPrompt').value : '', kind: kind || '' } : null))
      .finally(() => $('modalOk').classList.remove('ai-btn'));
  }
  // onStop: [다음 건부터 중지](여러 건일 때), onCancel: [바로 중지](언제나)
  function aiProgress(title, total, onStop, onCancel) {
    let box = $('aiProg');
    if (!box) { box = el('div', { id: 'aiProg', class: 'ai-prog', hidden: true }); document.body.appendChild(box); }
    box.innerHTML = '';
    const t0 = Date.now();
    const count = el('div', { class: 'ai-prog-count', text: 'AI에 보내는 중…' });
    const time = el('b', { text: '0:00' });
    // 막대: 끝난 건(파랑)·실패(빨강)·지금 처리 중(빗금이 흐름). 위에 '처리 중 n건 / 전체 N'
    const segDone = el('span', { class: 'seg-done' }), segFail = el('span', { class: 'seg-fail' }), segCur = el('span', { class: 'seg-cur' });
    const bar = el('div', { class: 'ai-bar2' }, [segDone, segFail, segCur]);
    const barLabel = el('div', { class: 'ai-bar-label', text: `지금 처리 중 1 / 전체 ${total}` });
    const stopBtn = onStop ? el('button', { type: 'button', title: '지금 처리 중인 건은 끝까지 처리되고(결과·비용 유지), 남은 건은 실행하지 않습니다', text: '다음 건부터 중지',
      onclick: () => { stopBtn.disabled = true; stopBtn.textContent = '중지 예약됨 — 처리 중인 건이 끝나면 멈춥니다'; onStop(); } }) : null;
    const cancelBtn = onCancel ? el('button', { type: 'button', class: 'btn-danger', title: '처리 중인 건도 바로 끊고 결과를 버립니다(저장하지 않음). 이미 나간 비용은 돌아오지 않습니다', text: '⏹ 바로 중지',
      onclick: () => { cancelBtn.disabled = true; if (stopBtn) stopBtn.disabled = true; cancelBtn.textContent = '중지하는 중…'; onCancel(); } }) : null;
    const result = el('div', { class: 'ai-prog-result' });
    const foot = el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), stopBtn, cancelBtn].filter(Boolean));
    const spin = el('div', { class: 'ai-spin' });
    const wait = el('div', { class: 'muted' }, ['경과 ', time, ' · 멈춘 것이 아니니 기다려 주세요. AI 응답은 보통 수십 초, 느리면 몇 분 걸릴 수 있습니다.']);
    box.appendChild(el('div', { class: 'ai-prog-card', role: 'dialog', 'aria-live': 'polite' }, [el('h2', { text: title }), spin, count, barLabel, bar, wait, result, foot]));
    box.hidden = false;
    box.setAttribute('aria-modal', 'true');
    $('app').inert = true; $('sheet').inert = true; $('modal').inert = true; // 진행 중 배경 조작·단축키 막기
    box.tabIndex = -1;
    setTimeout(() => (stopBtn || cancelBtn || box).focus(), 30);
    const unblock = () => { $('app').inert = false; $('sheet').inert = false; $('modal').inert = false; };
    const tick = () => { const x = Math.floor((Date.now() - t0) / 1000); time.textContent = `${Math.floor(x / 60)}:${String(x % 60).padStart(2, '0')}`; };
    const timer = setInterval(tick, 500);
    return {
      set(done, fail, label, running) {
        const run = running === undefined ? (done + fail < total ? 1 : 0) : running;
        count.textContent = total > 1 ? `완료 ${done}${fail ? ` · 실패 ${fail}` : ''}${label ? `\n지금: ${label}` : ''}` : `AI에 보내는 중…${label ? ` (${label})` : ''}`;
        barLabel.textContent = total > 1 && run > 1 ? `동시에 ${run}건 처리 중 · 끝난 건 ${done + fail} / 전체 ${total}` : `지금 처리 중 ${Math.min(done + fail + 1, total)} / 전체 ${total}`;
        segDone.style.width = `${(done / total) * 100}%`;
        segFail.style.width = `${(fail / total) * 100}%`;
        segCur.style.width = `${(run / total) * 100}%`;
      },
      // 실패가 있거나 요약을 보여야 하면 창을 남기고 [확인]을 기다린다. 아니면 바로 닫는다.
      finish(errors, summary, ratio) {
        clearInterval(timer);
        tick();
        if (!errors.length && !summary) { box.hidden = true; unblock(); return Promise.resolve(); }
        spin.remove(); wait.remove();
        const handled = Math.round((ratio !== undefined ? ratio : 1) * total);
        segCur.style.width = '0';
        segFail.style.width = `${(errors.length / total) * 100}%`;
        segDone.style.width = `${(Math.max(handled - errors.length, 0) / total) * 100}%`;
        barLabel.textContent = `처리 ${handled} / 전체 ${total}`;
        count.textContent = summary || '끝났습니다.';
        if (errors.length) result.appendChild(el('div', { class: 'danger-text', text: `실패 ${errors.length}건\n${errors.join('\n')}` }));
        foot.innerHTML = '';
        return new Promise((resolve) => {
          const ok = el('button', { type: 'button', class: 'primary', text: '확인', onclick: () => { box.hidden = true; unblock(); resolve(); } });
          foot.append(el('span', { class: 'spacer' }), ok);
          setTimeout(() => ok.focus(), 50);
        });
      },
    };
  }
  // jobs: [{ label, run: () => api 결과 }] — api를 직접 불러 오류도 진행 창에서 모아 보여 준다.
  // remember=false: 고른 프롬프트를 작업별 기억값으로 저장하지 않는다(묶음마다 따로 기억하는 경우)
  async function aiRun({ title, rows, warn, jobs, summary, skipConfirm, before, after, extra, kind, prompt, remember, concurrency }) {
    if (!skipConfirm) {
      const conf = await aiConfirm(title, rows, warn, kind);
      if (!conf) return null;
      extra = conf.extra;
      prompt = conf.prompt;
    }
    if (before && !(await before())) return null; // [AI 실행]을 누른 뒤에만 설정을 저장(취소하면 아무것도 바뀌지 않음)
    await api.ai_extra_set(extra || '', prompt || '', remember === false ? '' : kind || ''); // 이번 실행에만: 추가 요구 사항·고른 프롬프트(끝나면 지움)
    try { return await aiRunJobs({ title, jobs, summary, after, concurrency }); } finally { await api.ai_extra_set('', '', ''); }
  }
  // 여러 건은 동시에 AI_PARALLEL건씩 보낸다(concurrency로 바꿈: 앞 결과를 보고 쓰는 작업은 1).
  // out.notRun: 끝내지 못한 건의 번호(중지·장애로 보내지 않았거나 바로 중지로 버린 건) — 이어서 돌릴 때 쓴다.
  const AI_PARALLEL = 8;
  async function aiRunJobs({ title, jobs, summary, after, concurrency }) {
    let stop = false, cancelled = false, cancelNow = null;
    const cancelWait = new Promise((res) => { cancelNow = res; });
    await api.ai_cancel_reset();
    const pg = aiProgress(title, jobs.length, jobs.length > 1 ? () => { stop = true; } : null,
      () => { stop = true; cancelled = true; api.ai_cancel(); cancelNow(); });
    const results = [];
    const errors = [];
    const state = jobs.map(() => 'wait'); // wait → run → ok / fail
    let done = 0, fail = 0, down = null, next = 0;
    const running = new Set();
    const show = () => pg.set(done, fail, jobs.length > 1 ? [...running].map((i) => jobs[i].label).filter(Boolean).slice(0, 3).join(', ') + (running.size > 3 ? ` 외 ${running.size - 3}건` : '') : jobs[0].label, running.size);
    const worker = async () => {
      while (!stop && next < jobs.length) {
        const i = next++;
        const j = jobs[i];
        state[i] = 'run'; running.add(i); show();
        let r;
        try { r = await j.run(); } catch (e) { r = { ok: false, error: String(e) }; }
        running.delete(i);
        if (cancelled) { state[i] = 'wait'; return; } // 바로 중지 뒤에 온 답은 세지 않는다(서버도 저장하지 않음)
        if (r && r.ok !== false) { state[i] = 'ok'; done += 1; results.push(r); setCredits(r); if (j.onDone) j.onDone(r); }
        else {
          state[i] = 'fail'; fail += 1; errors.push(`${j.label ? `${j.label}: ` : ''}${(r && r.error) || '처리하지 못했습니다.'}`); if (j.onFail) j.onFail(r);
          if (r && (r.code === 'service_down' || r.code === 'rate_limited')) { down = r.code; stop = true; } // 장애·속도 제한: 남은 건은 보내지 않는다
        }
        show();
      }
    };
    const n = Math.max(1, Math.min(concurrency || AI_PARALLEL, jobs.length));
    await Promise.race([Promise.all(Array.from({ length: n }, worker)), cancelWait]);
    const notRun = state.map((x, i) => (x === 'wait' || x === 'run' ? i : -1)).filter((i) => i >= 0);
    const out = { done, fail, stopped: stop, cancelled, skipped: notRun.length, notRun, results, errors };
    if (after) after(out);
    const msg = summary ? summary(out) : (cancelled ? `바로 중지했습니다. 완료 ${done}건${fail ? ` · 실패 ${fail}건` : ''}${notRun.length ? ` · 처리하지 않음 ${notRun.length}건(처리 중이던 건은 저장하지 않음)` : ''}`
      : jobs.length > 1 && (fail || stop) ? `완료 ${done}건 · 실패 ${fail}건${out.skipped ? ` · 중지로 건너뜀 ${out.skipped}건` : ''}` : '');
    await pg.finish(errors, msg, (done + fail) / jobs.length);
    if (down && !cancelled) await aiDownBox(down, out.skipped);
    return out;
  }
  // OpenRouter 장애(연결 실패·서버 오류)나 계속되는 속도 제한: 남은 건을 멈췄다고 알리고 상태 페이지를 열 수 있게
  async function aiDownBox(code, skipped) {
    const rest = skipped ? `<br>남은 ${skipped}건은 보내지 않았습니다(크레딧 쓰지 않음). 나중에 다시 실행하세요.` : '';
    const html = code === 'rate_limited'
      ? `<b>⚠ AI 요청이 너무 많아 잠시 막혔습니다(속도 제한).</b><br>잠시 뒤 다시 시도하거나, 위쪽 모델 선택에서 다른 모델(유료 모델 등)을 고르세요. 무료 모델은 제한이 큽니다.${rest}`
      : `<b>⚠ 지금 OpenRouter(AI 서비스)에 연결되지 않습니다.</b><br>OpenRouter 사이트에 장애가 있거나 학교 인터넷 연결이 끊겼을 수 있습니다. 인터넷이 되는지 확인하고, 아래 [OpenRouter 상태 보기]로 사이트 상태를 확인해 보세요.${rest}`;
    if (await modal(html, true, true, 'OpenRouter 상태 보기', '확인')) api.open_url('https://status.openrouter.ai');
  }
  const DROP_WARN = '후보가 3개 차 있으면 잠기지 않은 가장 오래된 후보가 지워집니다.';

  async function busyRun(btn, key, fn) {
    if (R.busy.has(key)) return null;
    R.busy.add(key);
    const old = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.classList.add('busy-btn'); btn.textContent = 'AI 작업 중'; }
    try { return await fn(); } finally {
      R.busy.delete(key);
      if (btn && btn.isConnected) { btn.disabled = false; btn.classList.remove('busy-btn'); btn.textContent = old; }
    }
  }

  async function loadSlots() {
    const r = await call('slots');
    if (!r) return false;
    R.slots = r.slots;
    return true;
  }
  function fillSlotSelect(sel, current) {
    sel.innerHTML = '';
    let lastSem = null;
    R.slots.forEach((s) => sel.appendChild(el('option', { value: slotKey(s), text: s.label + (s.total ? '' : ' (명렬 없음)'), selected: current && slotKey(s) === current })));
    return lastSem;
  }

  // 현황판·다른 화면에서 들어올 때
  async function openRecords(gid, item, sno, filter) {
    if (!(await loadSlots())) return;
    const key = gid ? `${gid}:${item}` : (R.slot ? slotKey(R.slot) : (localStorage.getItem(recSlotKey()) || (R.slots[0] && slotKey(R.slots[0]))));
    R.slot = R.slots.find((s) => slotKey(s) === key) || R.slots[0] || null;
    R.sno = sno || null;
    R.filter = filter || '';
    R.selected.clear();
    showPanel('records');
  }
  const recSlotKey = () => `sgb_rec_slot_${ys.year}`;
  async function renderRecordsPanel() {
    if (!R.slots.length && !(await loadSlots())) return;
    if (!R.slot) { const k = localStorage.getItem(recSlotKey()); R.slot = R.slots.find((s) => slotKey(s) === k) || R.slots[0] || null; }
    if (R.slot) localStorage.setItem(recSlotKey(), slotKey(R.slot));
    fillSlotSelect($('recSlot'), R.slot && slotKey(R.slot));
    fillModelSelect($('recModel'));
    if (!R.slot) {
      $('recList').innerHTML = ''; $('recFinal').innerHTML = '';
      $('recRecords').innerHTML = '';
      unfoldEmpty();
      updateRecTools();
      $('recRecords').appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '담당이 없습니다. 명렬·담당 관리에서 먼저 추가하세요.' }), el('button', { type: 'button', class: 'primary', text: '명렬·담당 관리', onclick: () => showPanel('roster') })]));
      return;
    }
    await loadSlotStudents();
  }
  // 공통 일괄 버튼(이 항목 전체)
  function updateRecTools() {
    const off = !R.slot || !!ys.archived || !(R.students || []).length;
    $('recToolsLabel').textContent = R.slot ? `${R.slot.label} 전체 작업` : '이 항목 전체 작업';
    ['recBulkRecord', 'recBulkExisting', 'recBulkFinal', 'recBasisGen', 'recBulkClose'].forEach((id) => { $(id).disabled = off; });
    const bg = $('recBasisGen');
    bg.hidden = !R.slot || !BASIS_ITEMS.includes(R.slot.item);
    if (R.slot) { bg.textContent = `${basisRo(R.slot.item)} 여러 명 생성`; bg.title = `미입력자를 모으거나 체크한 학생만, 학생관찰기록 없이 ${basisWord(R.slot.item)}만으로 후보를 만듭니다`; }
  }
  let slotReq = 0;
  async function loadSlotStudents() {
    const req = ++slotReq;
    const key = slotKey(R.slot);
    const r = await call('slot_view', R.slot.group_id, R.slot.item);
    if (!r || req !== slotReq || !R.slot || slotKey(R.slot) !== key) return;
    R.students = r.students;
    R.target = r.target;
    updateRecTools();
    if (!R.students.length) {
      R.sno = null;
      renderStudentList();
      $('recStudentHead').textContent = '';
      $('recFinal').innerHTML = '';
      $('recRecords').innerHTML = '';
      unfoldEmpty();
      updateRecTools();
      $('recRecords').appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '이 담당의 명렬이 없습니다.' }), el('button', { type: 'button', class: 'primary', text: '명렬 등록', onclick: () => { rosterSel = R.slot.group_id; showPanel('roster'); } })]));
      return;
    }
    const visible = filteredStudents();
    if (!R.sno || !R.students.find((s) => s.student_no === R.sno)) R.sno = (visible[0] || R.students[0]).student_no;
    renderStudentList();
    await loadStudent();
  }
  // 학생 묶음: 선택과목에 수업이 지정돼 있으면 수업끼리, 아니면 학년-반끼리
  function bySection() { return R.slot && R.slot.kind === 'subject' && R.students.some((s) => s.section); }
  function groupOf(s) {
    if (bySection()) return { key: `s:${s.section || ''}`, label: s.section || '수업 미지정', order: s.section ? `0${s.section}` : '1' };
    if (!s.grade || !s.class_no) return { key: 'c:-', label: '반 정보 없음', order: '9' };
    return { key: `c:${s.grade}-${s.class_no}`, label: `${s.grade}학년 ${s.class_no}반`, order: `0${String(s.grade).padStart(2, '0')}${String(s.class_no).padStart(3, '0')}` };
  }
  function filteredStudents() {
    const q = R.search.trim();
    return R.students.filter((s) => (!R.filter || s.status === R.filter || (R.filter === 'stale' && s.stale)) && (!q || s.name.includes(q) || s.student_no.includes(q) || (s.section || '').includes(q) || groupOf(s).label.includes(q)))
      .sort((a, b) => groupOf(a).order.localeCompare(groupOf(b).order, 'ko', { numeric: true }) || (b.active - a.active) || a.student_no.localeCompare(b.student_no));
  }
  function renderStudentList() {
    const box = $('recList');
    box.innerHTML = '';
    const search = el('input', { type: 'text', class: 'search', placeholder: '이름·학번 찾기', value: R.search, oninput: debounce((e) => { R.search = e.target.value; renderStudentList(); }, 200) });
    const filter = el('select', { onchange: (e) => { R.filter = e.target.value; renderStudentList(); } }, [
      el('option', { value: '', text: '전체 상태' }),
      ...Object.entries(STATUS).map(([k, v]) => el('option', { value: k, text: `${v.icon} ${v.text}`, selected: R.filter === k })),
      el('option', { value: 'stale', text: '! 채택 후 기록 변경', selected: R.filter === 'stale' }),
    ]);
    box.append(statBox(), search, filter);
    const list = filteredStudents();
    // 묶음마다 제목(접기). 검색·필터 중에는 맞는 학생이 있는 묶음을 펼쳐 보인다.
    const narrowing = !!(R.search.trim() || R.filter);
    const groups = [];
    list.forEach((s) => {
      const gk = groupOf(s);
      let gr = groups.find((x) => x.key === gk.key);
      if (!gr) { gr = { ...gk, items: [] }; groups.push(gr); }
      gr.items.push(s);
    });
    groups.forEach((gr) => {
      const fk = `stu:${R.slot.group_id}:${gr.key}`;
      const folded = !narrowing && !!fold[fk];
      const all = R.students.filter((s) => groupOf(s).key === gr.key && s.active);
      const done = all.filter((s) => s.status === 'closed').length;
      const holder = el('div', { class: 'stu-group' + (folded ? ' folded' : ''), style: `--gc:${groupColor(gr.key)}` });
      const head = el('button', { type: 'button', class: 'stu-group-head', 'aria-expanded': folded ? 'false' : 'true', disabled: narrowing,
        title: narrowing ? '검색·필터 중에는 모두 펼쳐 보입니다' : folded ? '펼치기' : '접기',
        onclick: () => { setFold(fk, !folded); renderStudentList(); } }, [el('span', { class: 'g-name', text: `${narrowing ? '•' : folded ? '▸' : '▾'} ${gr.label}` }), el('span', { class: 'cnt', text: `전체 ${all.length}명 · 마감 ${done}명` })]);
      holder.appendChild(head);
      box.appendChild(holder);
      if (folded) return;
      gr.items.forEach((s) => renderStu(holder, s));
    });
    function renderStu(parent, s) {
      const st = STATUS[s.status] || STATUS.none;
      parent.appendChild(el('button', { type: 'button', class: 'stu' + (s.student_no === R.sno ? ' active' : '') + (s.active ? '' : ' inactive'), title: st.text, onclick: async () => { if (s.student_no !== R.sno && !(await leaveOk())) return; R.sno = s.student_no; R.selected.clear(); renderStudentList(); loadStudent(); } }, [
        el('span', { class: `st ${st.cls}`, text: st.icon }), el('span', { class: 'no', text: s.student_no }), el('span', { text: s.name }),
        el('span', { class: 'cnt', text: (s.stale ? '! ' : '') + (s.records ? `${s.records}건` : '') + (s.active ? '' : ' 비활성') }),
      ]));
    }
    if (!list.length) box.appendChild(el('p', { class: 'muted', text: '조건에 맞는 학생이 없습니다.' }));
  }
  // 묶음 색: 반·수업 이름으로 정해 화면이 바뀌어도 같은 색
  const GROUP_COLORS = ['#ea580c', '#7c3aed', '#db2777', '#92400e', '#475569', '#0f766e'];
  function groupColor(key) { let h = 0; for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return GROUP_COLORS[h % GROUP_COLORS.length]; }
  // 맨 위 통계 상자: 담당 전체(검색·필터와 관계없이). 숫자를 누르면 그 상태로 거른다.
  function statBox() {
    const act = R.students.filter((s) => s.active);
    const n = (k) => act.filter((s) => s.status === k).length;
    const done = n('closed');
    const pct = act.length ? Math.round((done / act.length) * 100) : 0;
    const chip = (k, label) => el('button', { type: 'button', class: `stat-chip ${STATUS[k].cls}${R.filter === k ? ' on' : ''}`, title: `${label}만 보기`,
      onclick: () => { R.filter = R.filter === k ? '' : k; renderStudentList(); } }, [`${STATUS[k].icon} ${label} `, el('b', { text: String(n(k)) })]);
    return el('div', { class: 'stat-box' }, [
      el('div', { class: 'stat-top' }, [el('span', { text: '마감 ' }), el('b', { class: 'stat-big', text: `${done}` }), el('span', { text: ` / ${act.length}명` }), el('span', { class: 'spacer' }), el('b', { text: `${pct}%` })]),
      el('div', { class: 'stat-bar' }, [el('span', { style: `width:${pct}%` })]),
      el('div', { class: 'stat-chips' }, [chip('closed', '마감'), chip('final', '최종안'), chip('progress', '입력 중'), chip('none', '기록 없음')]),
      el('div', { class: 'stat-scope', text: `담당 전체 기준${R.students.length > act.length ? ` · 비활성 ${R.students.length - act.length}명 제외` : ''}${R.search.trim() ? ` · 검색어 '${R.search.trim()}' 적용 중(아래 목록 ${filteredStudents().length}명)` : ''}` }),
    ]);
  }
  async function moveStudent(step) {
    const list = filteredStudents();
    const i = list.findIndex((s) => s.student_no === R.sno);
    const next = list[i + step];
    if (!next) { toast(step > 0 ? '마지막 학생입니다.' : '첫 학생입니다.'); return; }
    if (!(await leaveOk())) return;
    R.sno = next.student_no;
    R.selected.clear();
    renderStudentList();
    loadStudent();
  }
  let studentReq = 0;
  async function loadStudent(keepScroll) {
    if (!R.sno) return;
    if (!(await flushFinal())) { toast(SAVE_FAIL_MSG, 5000); return; }
    const scroll = [$('recRecords').scrollTop, $('recFinal').scrollTop];
    const req = ++studentReq;
    const ctx = { year: ys.year, gid: R.slot.group_id, item: R.slot.item, sno: R.sno };
    const r = await call('student_view', ctx.gid, ctx.item, ctx.sno);
    if (!r || req !== studentReq || ctx.year !== ys.year || !R.slot || ctx.gid !== R.slot.group_id || ctx.item !== R.slot.item || ctx.sno !== R.sno) return;
    R.view = r;
    R.viewCtx = ctx;
    R.target = r.target; // 1·2학기 합산 과목은 학생마다 목표가 다르다
    const st = R.students.find((s) => s.student_no === R.sno);
    const stInfo = STATUS[(r.final && r.final.closed) ? 'closed' : r.final ? 'final' : (r.records.length || r.results.length) ? 'progress' : 'none'];
    if (st) st.status = (r.final && r.final.closed) ? 'closed' : r.final ? 'final' : (r.records.length || r.results.length) ? 'progress' : 'none';
    $('recStudentHead').innerHTML = '';
    $('recStudentHead').append(`${r.student.student_no} ${r.student.name} `, el('span', { class: `st ${stInfo.cls}`, text: `${stInfo.icon} ${stInfo.text}` }),
      r.student.active ? '' : el('span', { class: 'tag', text: '비활성' }), r.student.level ? el('span', { class: 'tag', text: `성취수준 ${r.student.level}` }) : '');
    $('crumb').textContent = `${ys.year}학년도 › 항목별 기록 › ${R.slot.label} › ${r.student.name}`;
    renderRecords();
    renderFinal();
    if (keepScroll) { $('recRecords').scrollTop = scroll[0]; $('recFinal').scrollTop = scroll[1]; }
    renderStudentList();
  }
  // 최종안 직접 수정: 쉬면 자동 저장, 학생·화면을 바꾸기 전에도 저장
  // 저장은 한 줄로 세워 차례대로 한다(늦게 끝난 저장이 새 글을 덮어쓰지 않게).
  // 채택·마감도 같은 줄에서 앞선 저장이 끝난 뒤에 한다.
  let finalDraft = null;
  let finalChain = Promise.resolve();
  let finalBusy = 0;
  const finalAutoSave = debounce(() => flushFinal(), 900);
  function finalSerial(fn) {
    finalBusy += 1;
    const p = finalChain.then(fn);
    finalChain = p.then(() => {}, () => {}).then(() => { finalBusy -= 1; });
    return p;
  }
  function draftDirty() {
    const d = finalDraft;
    return finalBusy > 0 || !!(d && !d.dead && d.ta.value.trim() !== (d.saved || '').trim());
  }
  async function doFlushFinal() {
    const d = finalDraft;
    if (!d || d.dead) return true;
    const text = d.ta.value;
    if (text.trim() === (d.saved || '').trim()) { if (d.state && d.state.textContent === '저장 중…') d.state.textContent = ''; return true; }
    const r = await call('edit_final', d.ctx.gid, d.ctx.item, d.ctx.sno, text, d.ctx.year);
    if (!r) { if (d.state) d.state.textContent = '저장 안 됨'; markSaveFailed(); return false; }
    d.saved = text;
    markSaved();
    if (d.state && d.state.isConnected) d.state.textContent = d.ta.value === text ? '저장됨' : '저장 중…';
    if (d.onSaved) d.onSaved(text);
    return true;
  }
  function flushFinal() { return finalSerial(doFlushFinal); }
  // 최종안을 먼저 저장하고, 같은 줄에서 최종안을 바꾸는 작업(채택·마감)을 한다. 성공하면 이 초안은 끝.
  function afterFinalSaved(fn) {
    return finalSerial(async () => {
      if (!(await doFlushFinal())) return null;
      const d = finalDraft;
      if (d) d.ta.disabled = true;
      const r = await fn();
      if (d) { if (r) d.dead = true; else d.ta.disabled = d.ro; }
      return r;
    });
  }
  // 칸 접기(학생관찰기록·최종안·후보): 접은 상태는 기억해 둔다
  const FOLD_KEY = 'sgb.fold';
  const fold = (() => { try { return JSON.parse(localStorage.getItem(FOLD_KEY) || '{}') || {}; } catch (e) { return {}; } })();
  // 최종안 칸은 '최종안'과 '후보'를 따로 접는다. 둘 다 접으면 칸 전체가 막대(제목은 늘 보임).
  const syncFinalCol = () => $('recFinal').classList.toggle('folded-all', !!(fold.final && fold.results));
  function setFold(key, v) {
    fold[key] = v;
    try { localStorage.setItem(FOLD_KEY, JSON.stringify(fold)); } catch (e) { /* 무시 */ }
  }
  function foldBtn(key, target, label) {
    const txt = () => `${fold[key] ? '▸' : '▾'} ${label}`;
    const b = el('button', { type: 'button', class: 'fold-btn', title: fold[key] ? '펼치기' : '접기', text: txt(), 'aria-expanded': fold[key] ? 'false' : 'true' });
    const apply = () => {
      target.classList.toggle('folded', !!fold[key]);
      b.textContent = txt();
      b.title = fold[key] ? '펼치기' : '접기';
      b.setAttribute('aria-expanded', fold[key] ? 'false' : 'true');
      syncFinalCol();
    };
    apply();
    b.addEventListener('click', () => { setFold(key, !fold[key]); apply(); });
    return b;
  }
  // 새 후보가 생기면 후보 칸을 펼쳐 보이게
  function revealResults() { if (fold.results) setFold('results', false); }
  function unfoldEmpty() { ['recRecords', 'recFinal'].forEach((id) => $(id).classList.remove('folded', 'folded-all')); }
  const closedNow = () => !!(R.view && R.view.final && R.view.final.closed) || !!ys.archived;
  // 2학기 합산 과목에서 1학기가 합산을 다 쓰면 AI 종합·다듬기·생성을 미리 막는다
  const pairFull = () => { const p = R.view && R.view.pair; return !!(p && p.role === 'second' && p.remain !== null && p.remain !== undefined && p.remain <= 0); };
  const PAIR_FULL_TIP = '1학기 최종안이 합산 바이트를 이미 다 써서 AI로 쓸 수 없습니다. 1학기 최종안을 줄이거나 합산을 바꾸세요.';

  function renderRecords() {
    const box = $('recRecords');
    box.innerHTML = '';
    const v = R.view;
    const locked = closedNow();
    const head = el('div', { class: 'sec-title' }, [foldBtn('records', box, `${v.student.name} 학생관찰기록 ${v.records.length}건`), el('span', { class: 'spacer' }),
      el('button', { type: 'button', class: 'primary', disabled: locked, text: '+ 학생관찰기록', onclick: () => recordForm(null, 'record') }),
      el('button', { type: 'button', disabled: locked, text: '이미 쓴 생기부 넣기', onclick: () => recordForm(null, 'existing') }),
      BASIS_ITEMS.includes(R.slot.item) ? el('button', { type: 'button', disabled: locked, class: 'ai-btn', title: `학생관찰기록 없이 ${basisWord(R.slot.item)}만으로 이 학생의 후보를 만듭니다`, text: `${basisWord(R.slot.item)}만으로 생성`, onclick: () => openBasisGen(R.sno) }) : null,
    ]);
    box.appendChild(head);
    if (locked && !ys.archived) box.appendChild(el('div', { class: 'stale', text: '● 마감된 항목입니다. 고치려면 오른쪽 [마감 해제]를 누르세요.' }));
    const sel = [...R.selected].filter((id) => v.records.some((r) => r.id === id));
    R.selected = new Set(sel);
    box.appendChild(el('div', { class: 'toolbar' }, [
      el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', checked: sel.length && sel.length === v.records.length, onchange: (e) => { R.selected = new Set(e.target.checked ? v.records.map((r) => r.id) : []); renderRecords(); } }), '전체 선택']),
      (() => { const yet = v.records.filter((r) => !r.candidates.length && !r.original); return el('button', { type: 'button', class: 'small', disabled: !yet.length, title: '정제·다듬기 후보가 없고 AI 결과를 반영한 적도 없는 기록만 고릅니다', text: `정제 안 한 기록만 선택 (${yet.length})`, onclick: () => { R.selected = new Set(yet.map((r) => r.id)); renderRecords(); } }); })(),
      el('span', { class: 'muted', text: `선택 ${sel.length}건` }),
      aiPair(el('button', { type: 'button', class: 'primary ai-btn', disabled: locked || !sel.length || pairFull(), title: pairFull() ? PAIR_FULL_TIP : '', text: `선택 기록 종합하기 (${sel.length})`, onclick: openSynth }),
        recWizBtn('synth', () => v.records.filter((r) => R.selected.has(r.id)).map((r) => r.content).join('\n\n') || (v.records[0] ? v.records[0].content : ''), locked)),
      (() => { const recs = v.records.filter((r) => R.selected.has(r.id) && r.kind !== 'existing'); return el('button', { type: 'button', class: 'ai-btn', disabled: locked || !recs.length, title: '고른 학생관찰기록을 한꺼번에 정제합니다(기존 완성문은 빼고, 다듬기는 카드에서 한 건씩)', text: `선택 기록 정제 (${recs.length})`, onclick: (e) => aiRecords(recs, e.currentTarget) }); })(),
      el('button', { type: 'button', disabled: locked || !sel.length, text: '태그 일괄 지정', onclick: bulkTag }),
      el('button', { type: 'button', disabled: locked || !sel.length, text: '다른 항목으로 이동', onclick: () => openMove(v.records.filter((r) => R.selected.has(r.id))) }),
    ]));
    if (!v.records.length) {
      box.appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '아직 기록이 없습니다.' }), BASIS_ITEMS.includes(R.slot.item) ? el('button', { type: 'button', class: 'primary ai-btn', disabled: locked, text: `기록 없이 ${basisWord(R.slot.item)}만으로 생성`, onclick: () => openBasisGen(R.sno) }) : null, el('p', { class: 'hint', text: '[+ 학생관찰기록]으로 활동을 하나씩 쌓거나, 이미 쓴 생기부를 넣어 다듬을 수 있습니다. 여러 학생의 엑셀 자료는 자료 인박스에서 학생별로 나눠 한 번에 보낼 수 있습니다.' })]));
      return;
    }
    // 기록 순서: ⠿ 끌기·▲▼ (종합할 때 AI에 보내는 순서)
    const cards = v.records.map((r) => ({ id: r.id, el: recordCard(r, locked) }));
    const ctx = { gid: R.slot.group_id, item: R.slot.item, sno: R.sno };
    const handle = sortable(cards, async (ids) => { if (await mutate('reorder_records', ctx.gid, ctx.item, ctx.sno, ids)) loadStudent(true); }, locked || v.records.length < 2);
    cards.forEach((c) => { c.el.querySelector('.rcard-head').prepend(handle(c.id)); box.appendChild(c.el); });
  }
  function sourceLabel(src) {
    src = src || '';
    if (src.startsWith('inbox:')) return '인박스에서';
    if (src.startsWith('moved:')) return `${ITEM_LABELS[src.split(':')[1]] || '다른 항목'}에서 이동`;
    return { manual: '직접 입력', existing: '이미 쓴 생기부', 'existing-bulk': '일괄 넣기', 'record-bulk': '일괄 입력' }[src] || '직접 입력';
  }
  function candInfo(cd) {
    alertBox(`작업: ${OP_LABEL[cd.op]}\n모델: ${cd.meta.model || '-'}${cd.meta.prompt_name ? `\n프롬프트: ${cd.meta.prompt_name}` : ''}${cd.meta.extra ? `\n추가 요구 사항: ${cd.meta.extra}` : ''}\n만든 때: ${cd.created_at}\n비용: ${fmtCredit(cd.cost)} 크레딧${cd.meta.ratios ? `\n비율: ${cd.meta.ratios.join(' / ')}%` : ''}${cd.meta.record_ids ? `\n근거 기록: ${cd.meta.record_ids.length}건` : ''}${cd.meta.level ? `\n성취수준: ${cd.meta.level}` : ''}\n\n[지침]\n${cd.meta.prompt || '-'}${cd.meta.example ? `\n\n[예시]\n${cd.meta.example}` : ''}${cd.meta.standards_text ? `\n\n[쓴 성취기준]\n${cd.meta.standards_text}` : ''}`);
  }
  function recordCard(r, locked) {
    const isSel = R.selected.has(r.id);
    const card = el('div', { class: 'rcard' + (isSel ? ' sel' : '') });
    if (R.highlight === r.id) { // 태그별 기록에서 [이 항목에서 열기]로 온 기록
      R.highlight = null;
      card.classList.add('flash');
      requestAnimationFrame(() => card.scrollIntoView({ block: 'center' }));
    }
    const label = r.kind === 'existing' ? el('span', { class: 'badge existing', text: '기존 완성문' }) : el('span', { class: 'seq', text: `${r.seq}회` });
    card.appendChild(el('div', { class: 'rcard-head' }, [
      el('input', { type: 'checkbox', checked: isSel, onchange: (e) => { if (e.target.checked) R.selected.add(r.id); else R.selected.delete(r.id); renderRecords(); } }),
      label, r.date ? el('span', { text: md(r.date) }) : null, r.title ? el('b', { text: r.title }) : null,
      ...r.tags.map((t) => el('span', { class: 'tag' + tagC(t.id), text: t.name })),
      r.weight !== null && r.weight !== undefined ? el('span', { class: 'badge', text: `비중 ${r.weight}%` }) : null,
      r.original ? el('span', { class: 'badge src', title: '원문은 [수정]에서 볼 수 있습니다', text: 'AI 반영됨' }) : null,
      el('span', { class: 'badge src', text: sourceLabel(r.source) }),
      el('span', { class: 'rcard-acts' }, [
        el('button', { type: 'button', class: 'small', disabled: locked, text: '수정', onclick: () => recordForm(r, r.kind) }),
        el('button', { type: 'button', class: 'small', disabled: locked, title: '이 기록(또는 문단)을 다른 항목으로', text: '이동', onclick: () => openMove([r]) }),
        el('button', { type: 'button', class: 'small link danger-text', disabled: locked, text: '삭제', onclick: async () => {
          if (!(await confirmBox(`이 기록을 지웁니다.${r.candidates.length ? ` 정제 후보 ${r.candidates.length}개도 함께 지워집니다.` : ''}`, '삭제'))) return;
          if (await mutate('delete_record', r.id)) loadStudent(true);
        } })]),
    ]));
    card.appendChild(el('div', { class: 'rcard-body', text: r.content }));
    const blocked = r.kind === 'existing' && pairFull();
    const aiBtn = el('button', { type: 'button', class: 'ai-btn', disabled: locked || blocked, title: blocked ? PAIR_FULL_TIP : '', text: r.kind === 'existing' ? '다듬기(AI)' : '정제(AI)' });
    aiBtn.addEventListener('click', () => aiRecord(r, aiBtn));
    card.appendChild(el('div', { class: 'rcard-foot' }, [
      aiPair(aiBtn, recWizBtn(r.kind === 'existing' ? 'polish' : 'refine', r.content, locked)),
      el('button', { type: 'button', disabled: locked, title: 'AI를 거치지 않고 이 기록 내용을 그대로 최종안으로 넣습니다', text: '그대로 최종안으로', onclick: () => adoptRecordFinal(r) }),
      el('span', { class: 'spacer' }), bytesEl(r.bytes, r.kind === 'existing' ? R.target : 0),
    ]));
    if (r.candidates.length) {
      const c = el('div', { class: 'cands' }, [el('div', { class: 'hint', style: 'margin:0', text: `${r.kind === 'existing' ? '다듬기' : '정제'} 후보 ${r.candidates.length}/3 (잠금 포함 최근 3개 보관)` })]);
      r.candidates.slice().reverse().forEach((cd) => c.appendChild(candEl(cd, locked, [
        el('button', { type: 'button', class: 'small', disabled: locked, text: '이 내용으로 기록 바꾸기', onclick: async () => { if (await mutate('apply_candidate', cd.id)) { toast('기록을 바꿨습니다. 원문은 남겨 둡니다.'); loadStudent(true); } } }),
        el('button', { type: 'button', class: 'small', text: '정보', onclick: () => candInfo(cd) }),
        r.kind === 'existing' ? el('button', { type: 'button', class: 'small', disabled: locked, text: '최종안으로 채택', onclick: async () => { if (await afterFinalSaved(() => mutate('adopt_result', cd.id))) { toast('최종안으로 채택했습니다.'); loadStudent(true); } } }) : null,
      ])));
      card.appendChild(c);
    }
    return card;
  }
  // ---------- 항목별 기록 › 🪄 프롬프트 마법사 ----------
  const KIND_NAMES = { refine: '정제', polish: '다듬기', synth: '종합' };
  function recWizCtx(kind, text) {
    return { rec: { gid: R.slot.group_id, item: R.slot.item, sno: R.sno, kind, text: text || '', label: `${R.view.student.name} · ${R.slot.label}`, year: ys.year } };
  }
  // AI 버튼과 그 마법사 버튼을 한 덩어리로(보라 꽉 찬 버튼 + 보라 테두리 버튼)
  const aiPair = (aiBtn, wiz) => el('span', { class: 'ai-pair' }, [aiBtn, wiz]);
  function recWizBtn(kind, text, locked) {
    return el('button', { type: 'button', class: 'wiz-btn', disabled: locked, title: `대화하며 다듬거나 양식을 채워 ${KIND_NAMES[kind]} 프롬프트를 만듭니다`, text: '🪄 마법사',
      onclick: async () => { if (await flushFinal()) openWizardMenu(recWizCtx(kind, typeof text === 'function' ? text() : text)); } });
  }
  function recUseFor(rc) {
    return { label: `이 항목 ${KIND_NAMES[rc.kind]}의 기본 프롬프트로 바로 쓰기`, done: `다음 ${KIND_NAMES[rc.kind]}부터 이 프롬프트가 기본으로 골라집니다.`,
      apply: async (id) => { await mutate('prompt_pick_set', rc.kind, id); } };
  }
  // 최종안에 글 전체 넣기(덮어쓸 때 확인, [되돌리기]로 원래 최종안)
  async function putFinalText(rc, text) {
    const v = await rawCall('student_view', rc.gid, rc.item, rc.sno);
    const prev = v && v.ok && v.final ? v.final.text || '' : null;
    if (prev && prev.trim() && prev.trim() !== text.trim() && !(await confirmBox(`${rc.label}의 지금 최종안을 이 글로 바꿉니다. 바꾼 직후 [되돌리기]로 원래 최종안을 돌려놓을 수 있습니다.`, '바꾸기'))) return;
    if (!(await mutate('edit_final', rc.gid, rc.item, rc.sno, text, rc.year))) return;
    actionToast('최종안에 넣었습니다.', '되돌리기', async () => { if (await mutate('edit_final', rc.gid, rc.item, rc.sno, prev || '', rc.year)) { toast('원래 최종안으로 되돌렸습니다.'); if (R.sno === rc.sno) loadStudent(true); } }, 20000);
    if (R.sno === rc.sno && panel === 'records') loadStudent(true);
  }
  // 기록 그대로 최종안으로(학생관찰기록·기존 완성문): 덮어쓸 때 확인, [되돌리기]
  async function adoptRecordFinal(r) {
    const prev = R.view.final ? R.view.final.text || '' : '';
    if (prev.trim() && prev.trim() !== (r.content || '').trim() && !(await confirmBox('지금 최종안을 이 기록 내용으로 바꿉니다. 바꾼 직후 [되돌리기]로 원래 최종안을 돌려놓을 수 있습니다.', '바꾸기'))) return;
    const ctx = { gid: R.slot.group_id, item: R.slot.item, sno: R.sno, year: ys.year };
    if (!(await afterFinalSaved(() => mutate('adopt_record', r.id)))) return;
    loadStudent(true);
    actionToast('최종안으로 채택했습니다.', '되돌리기', async () => { if (await mutate('edit_final', ctx.gid, ctx.item, ctx.sno, prev, ctx.year)) { toast('원래 최종안으로 되돌렸습니다.'); if (R.sno === ctx.sno) loadStudent(true); } }, 20000);
  }
  // ---------- 후보 문장을 최종안에 넣기 ----------
  function splitSentences(text) {
    return String(text || '').split(/\n+/).flatMap((p) => p.match(/[^.!?]+[.!?]+["')\]]*|[^.!?]+$/g) || []).map((x) => x.trim()).filter(Boolean);
  }
  // 최종안의 커서 자리(없으면 맨 끝)에 넣는다. 브라우저 되돌리기(Ctrl+Z)가 되도록 insertText를 쓴다.
  function insertToFinal(text) {
    const fd = finalDraft;
    if (!fd || !fd.ta || !fd.ta.isConnected) { toast('최종안 칸이 보이는 화면에서 쓸 수 있습니다.'); return false; }
    if (fd.ro || fd.ta.disabled) { toast('마감되었거나 읽기 전용이라 최종안에 넣을 수 없습니다.'); return false; }
    const ta = fd.ta;
    const [a, b] = ta._sel || [ta.value.length, ta.value.length];
    ta.focus();
    ta.setSelectionRange(a, b);
    let ins = String(text).trim();
    if (!ins) return false;
    if (ta.value.slice(0, a) && !/\s$/.test(ta.value.slice(0, a))) ins = ' ' + ins;
    if (ta.value.slice(b) && !/^\s/.test(ta.value.slice(b))) ins += ' ';
    if (!document.execCommand('insertText', false, ins)) { ta.setRangeText(ins, a, b, 'end'); ta.dispatchEvent(new Event('input')); }
    ta._sel = [ta.selectionStart, ta.selectionEnd];
    return true;
  }
  function sentencePicker(cd) {
    const box = el('div', { class: 'sent-pick', hidden: true });
    const draw = () => {
      box.innerHTML = '';
      const fin = finalDraft && finalDraft.ta ? finalDraft.ta.value.replace(/\s+/g, ' ') : '';
      box.appendChild(el('div', { class: 'muted small-note', text: '문장을 누르면 최종안의 커서 자리(없으면 맨 끝)에 들어갑니다. Ctrl+Z로 되돌릴 수 있습니다. 문장 일부만 필요하면 후보 글을 마우스로 골라 [최종안에 넣기]를 누르세요.' }));
      splitSentences(cd.text).forEach((x) => {
        const used = fin.includes(x.replace(/\s+/g, ' '));
        box.appendChild(el('button', { type: 'button', class: 'sent-chip' + (used ? ' used' : ''), title: used ? '이미 최종안에 있는 문장' : '최종안에 넣기', text: (used ? '✔ ' : '') + x,
          onclick: () => { if (insertToFinal(x)) draw(); } }));
      });
    };
    box.toggle = () => { box.hidden = !box.hidden; if (!box.hidden) draw(); };
    return box;
  }
  function candEl(cd, locked, extra) {
    const picker = sentencePicker(cd);
    const pickBtn = el('button', { type: 'button', class: 'small', disabled: locked, title: '이 후보의 문장을 골라 최종안에 넣습니다', text: '문장 골라 넣기', onclick: () => { picker.toggle(); pickBtn.classList.toggle('on', !picker.hidden); } });
    return el('div', { class: 'cand' + (cd.locked ? ' locked' : '') }, [
      el('div', { class: 'cand-head' }, [el('b', { text: OP_LABEL[cd.op] || cd.op }), stdBadge(cd.meta), cd.meta.extra ? el('span', { class: 'badge extra-badge', title: cd.meta.extra, text: `추가 요구: ${cd.meta.extra.length > 24 ? cd.meta.extra.slice(0, 24) + '…' : cd.meta.extra}` }) : null, cd.created_at.slice(5, 16), cd.meta.model ? `· ${cd.meta.model}` : '',
        cd.meta.ratios ? `· 비율 ${cd.meta.ratios.join('/')}%` : '', el('span', { class: 'spacer' }), bytesEl(cd.bytes, R.target)]),
      el('div', { class: 'cand-body', text: cd.text }),
      picker,
      el('div', { class: 'rcard-foot' }, [...(extra || []), pickBtn, el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'small', title: '새 결과가 생겨도 지우지 않음', text: cd.locked ? '🔒 보관 잠금됨' : '🔓 보관 잠금', onclick: async () => { if (await mutate('lock_result', cd.id, !cd.locked)) loadStudent(true); } }),
        el('button', { type: 'button', class: 'small link danger-text', disabled: locked, text: '삭제', onclick: async () => { if (await mutate('delete_result', cd.id)) loadStudent(true); } })]),
    ]);
  }
  async function aiRecord(r, btn) {
    const what = r.kind === 'existing' ? '기존 완성문 다듬기' : '학생관찰기록 정제';
    const out = await busyRun(btn, `rec${r.id}`, () => aiRun({
      title: what, kind: r.kind === 'existing' ? 'polish' : 'refine',
      rows: [['학생', `${R.view.student.name} · ${R.slot.label}`], ['대상', `${r.kind === 'existing' ? '기존 완성문' : `${r.seq}회 기록`}${r.title ? ` · ${r.title}` : ''} (${r.bytes}B)`], ['모델', modelName($('recModel'))]],
      warn: DROP_WARN,
      jobs: [{ run: () => api.ai_record(r.id, $('recModel').value) }],
    }));
    if (!out || !out.done) return;
    toast(out.results[0].dropped ? '새 후보를 만들고 가장 오래된 후보를 지웠습니다.' : '새 후보를 만들었습니다. 기록 카드 아래에 있습니다.');
    loadStudent(true);
  }

  // 고른 학생관찰기록 여러 건 정제(동시에 보냄). 기존 완성문은 빼고 한다.
  async function aiRecords(recs, btn) {
    if (!recs.length) return;
    const out = await busyRun(btn, `recs${R.sno}`, () => aiRun({
      title: '학생관찰기록 정제', kind: 'refine',
      rows: [['학생', `${R.view.student.name} · ${R.slot.label}`], ['대상', `기록 ${recs.length}건 (${recs.map((r) => `${r.seq}회`).join(', ')})`], ['모델', modelName($('recModel'))]],
      warn: `기록마다 정제 후보를 하나씩 만듭니다. 기록은 [이 내용으로 기록 바꾸기]를 눌러야 바뀝니다. ${DROP_WARN}`,
      jobs: recs.map((r) => ({ label: `${r.seq}회${r.title ? ` ${r.title}` : ''}`, run: () => api.ai_record(r.id, $('recModel').value) })),
    }));
    if (!out) return;
    if (out.done) toast(`${out.done}건의 정제 후보를 만들었습니다. 기록 카드 아래에 있습니다.`);
    loadStudent(true);
  }

  // list: 태그 목록(없으면 항목별 기록 화면의 목록)
  function tagPicker(selected, list) {
    const box = el('div', { class: 'tagpick' });
    const set = new Set(selected || []);
    const all = () => list || (R.view && R.view.tags) || [];
    const draw = () => {
      box.innerHTML = '';
      all().forEach((t) => box.appendChild(el('button', { type: 'button', class: (set.has(t.id) ? 'on' : '') + tagC(t.id), text: t.name, onclick: () => { if (set.has(t.id)) set.delete(t.id); else set.add(t.id); draw(); } })));
      if (!all().length) box.appendChild(el('span', { class: 'muted', text: '태그가 없습니다. 메뉴의 [태그]에서 만드세요.' }));
    };
    draw();
    box.value = () => [...set];
    return box;
  }
  function recordForm(r, kind) {
    const existing = kind === 'existing';
    openSheet((box) => {
      box.style.height = 'auto';
      box.style.width = 'min(860px, 94vw)';
      // 날짜는 선택: 기본은 넣지 않음. 날짜가 있는 기록을 고칠 때는 켜진 채로 연다.
      // 꺼져 있으면 날짜 칸을 숨기고 '날짜 없이 저장'. 켜는 순간 오늘(또는 원래 날짜)을 채운다.
      const had = !!(r && r.date);
      const date = el('input', { type: 'date', value: had ? r.date : '', hidden: !had });
      const dateNote = el('span', { class: 'muted' });
      const syncDate = () => {
        date.hidden = !useDate.checked;
        if (useDate.checked && !date.value) date.value = had ? r.date : todayStr();
        dateNote.textContent = useDate.checked ? '' : had ? `저장하면 원래 날짜(${md(r.date)})를 지웁니다` : '날짜 없이 저장';
        dateNote.className = !useDate.checked && had ? 'danger-text' : 'muted';
      };
      const useDate = el('input', { type: 'checkbox', checked: had, onchange: () => syncDate() });
      syncDate();
      const title = el('input', { type: 'text', class: 'grow', placeholder: existing ? '예: 1학기 작성본' : '예: 진로 독서 감상문', value: r ? r.title : (existing ? '이미 쓴 생기부' : '') });
      const content = el('textarea', { rows: 12, placeholder: existing ? '이미 작성한 생기부 문장을 붙여넣으세요.' : '활동 내용, 학생 글, 관찰 메모 등을 적으세요. 학번·이름은 적지 않아도 됩니다.', value: r ? r.content : '' });
      const bc = el('span', { class: 'bytes' });
      const upd = () => { bc.textContent = `${bytesOf(content.value)}B`; };
      content.addEventListener('input', upd);
      upd();
      const tags = tagPicker(r ? r.tags.map((t) => t.id) : []);
      addTo(box, 
        el('div', { class: 'sheet-head' }, [el('h2', { text: `${r ? '기록 수정' : existing ? '이미 쓴 생기부 넣기' : '학생관찰기록 추가'} · ${R.view.student.name}` }), el('span', { class: 'muted', text: R.slot.label })]),
        existing ? null : el('div', { class: 'inline' }, [el('label', { class: 'date-opt' }, [useDate, '날짜 넣기']), date, dateNote, el('label', { style: 'margin:0' }, ['활동명']), title]),
        existing ? el('div', { class: 'inline' }, [el('label', { style: 'margin:0' }, ['제목']), title]) : null,
        el('label', { text: '태그' }), tags,
        el('label', {}, ['내용 ', bc]), content,
        r && r.original ? el('details', { style: 'margin-top:8px' }, [el('summary', { text: 'AI 반영 전 원문 보기' }), el('div', { class: 'rcard-body', text: r.original })]) : null,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', class: 'primary', text: '저장', onclick: async () => {
            const data = { date: existing || !useDate.checked ? '' : date.value, title: title.value, content: content.value, tag_ids: tags.value(), kind };
            const res = r ? await mutate('update_record', r.id, data) : await mutate('add_record', R.slot.group_id, R.slot.item, R.sno, data);
            if (!res) return;
            closeSheet();
            toast(r ? '고쳤습니다.' : '추가했습니다.');
            const s = R.students.find((x) => x.student_no === R.sno);
            if (s && !r) s.records += 1;
            loadStudent(true);
          } })]),
      );
      setTimeout(() => content.focus(), 50);
    });
  }
  function bulkTag() {
    const ids = [...R.selected];
    openSheet((box) => {
      box.style.height = 'auto';
      box.style.width = 'min(560px, 92vw)';
      const tags = tagPicker([]);
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `태그 일괄 지정 · ${ids.length}건` })]), tags,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', text: '고른 태그 빼기', onclick: async () => { if (await mutate('tag_records', ids, tags.value(), 'remove')) { closeSheet(); loadStudent(true); } } }),
          el('button', { type: 'button', class: 'primary', text: '고른 태그 붙이기', onclick: async () => { if (await mutate('tag_records', ids, tags.value(), 'add')) { closeSheet(); toast('태그를 붙였습니다.'); loadStudent(true); } } })]));
    });
  }

  // 비중 계산(app/weights.py와 같은 규칙) — 화면 미리보기용
  function computeWeights(items, sumCheck) {
    const ws = items.map((it) => (it.weight === '' || it.weight === null || it.weight === undefined ? null : Number(it.weight)));
    if (ws.some((w) => w !== null && (!isFinite(w) || w < 0))) return { error: '비중은 0 이상의 숫자로 입력하세요.' };
    const bs = items.map((it) => Math.max(1, it.bytes || 0));
    const given = ws.reduce((a, w) => a + (w === null ? 0 : w), 0);
    const free = ws.map((w, i) => (w === null ? i : -1)).filter((i) => i >= 0);
    const fb = free.reduce((a, i) => a + bs[i], 0);
    const raw = ws.slice();
    if (sumCheck) {
      if (given > 100 + 1e-9) return { error: `지정한 비중의 합이 ${given}%로 100%를 넘습니다.` };
      const rest = 100 - given;
      if (free.length) { if (rest <= 1e-9) return { error: '비워 둔 기록에 나눠 줄 비율이 남지 않았습니다.' }; free.forEach((i) => { raw[i] = (rest * bs[i]) / fb; }); }
      else if (Math.abs(given - 100) > 1e-6) return { error: `비중의 합이 ${given}%입니다. 100%가 되도록 맞춰 주세요.` };
    } else if (free.length) {
      const rest = 100 - given;
      const base = rest <= 0 ? (given / (ws.length - free.length)) * free.length : rest;
      free.forEach((i) => { raw[i] = (base * bs[i]) / fb; });
    }
    const total = raw.reduce((a, b) => a + b, 0);
    if (total <= 0) return { error: '비중이 모두 0입니다.' };
    return { ratios: raw.map((x) => x / total) };
  }
  async function openSynth() {
    const recs = R.view.records.filter((r) => R.selected.has(r.id));
    openSheet((box) => {
      const inputs = {};
      let sumCheck = !!R.view.weight_sum_check;
      const t = el('table', { class: 'tbl wtbl' });
      const sumLine = el('div', { class: 'sum-line' });
      const runBtn = el('button', { type: 'button', class: 'primary ai-btn', text: `종합 실행` });
      const redraw = () => {
        const items = recs.map((r) => ({ bytes: r.bytes, weight: inputs[r.id].value }));
        const res = computeWeights(items, sumCheck);
        recs.forEach((r, i) => {
          const cell = t.querySelector(`[data-applied="${r.id}"]`);
          cell.textContent = res.ratios ? `${(res.ratios[i] * 100).toFixed(1)}% · 약 ${Math.round(res.ratios[i] * R.target)}B` : '-';
          inputs[r.id].placeholder = res.ratios && inputs[r.id].value === '' ? `자동 ${(res.ratios[i] * 100).toFixed(0)}` : '';
        });
        sumLine.className = 'sum-line' + (res.error ? ' bad' : '');
        sumLine.textContent = res.error ? '✕ ' + res.error : `✔ 적용 비율 합계 100% · 목표 ${R.target}바이트`;
        runBtn.disabled = !!res.error;
      };
      t.appendChild(el('tr', {}, ['기록', '길이', '비중(%)', '적용 비율 · 예상 분량'].map((h) => el('th', { text: h }))));
      recs.forEach((r) => {
        inputs[r.id] = el('input', { type: 'number', min: 0, step: 5, value: r.weight === null || r.weight === undefined ? '' : r.weight, oninput: redraw });
        t.appendChild(el('tr', {}, [el('td', { text: `${r.kind === 'existing' ? '기존 완성문' : r.seq + '회'} ${r.title || ''}`.trim() }), el('td', { text: `${r.bytes}B` }), el('td', {}, [inputs[r.id]]), el('td', { 'data-applied': r.id, class: 'auto-w' })]));
      });
      const chk = el('input', { type: 'checkbox', checked: sumCheck, onchange: (e) => { sumCheck = e.target.checked; redraw(); } });
      const model = el('select', {});
      fillModelSelect(model);
      model.value = $('recModel').value;
      const hasStd = R.slot.item === 'subject' && R.view.standards;
      const stdChk = hasStd ? el('input', { type: 'checkbox', disabled: !R.view.standards.text.trim() }) : null;
      const stdLvl = hasStd ? levelSelect(R.view.standards.level_scale, R.view.student.level) : null;
      const stdTa = hasStd ? el('textarea', { class: 'fill', rows: 7, value: R.view.standards.text }) : null;
      const stdBox = hasStd ? el('div', { hidden: true }, [el('div', { class: 'col-label', text: '이번에 쓸 성취기준 (필요한 부분만 남겨도 됩니다)' }), stdTa]) : null;
      if (stdChk) stdChk.addEventListener('change', () => { stdBox.hidden = !stdChk.checked; });
      runBtn.addEventListener('click', async () => {
        const wm = {};
        recs.forEach((r) => { wm[r.id] = inputs[r.id].value; });
        const std = stdChk && stdChk.checked ? { text: stdTa.value, level: stdLvl.value } : null;
        const out = await busyRun(runBtn, `synth${R.sno}`, () => aiRun({
          title: '선택 기록 종합', kind: 'synth',
          rows: [['학생', `${R.view.student.name} · ${R.slot.label}`], ['기록', `${recs.length}건 (${recs.reduce((a, r) => a + r.bytes, 0)}B)`], ['목표', `${R.target}B`], ['모델', modelName(model)],
            std ? ['성취기준', `사용 · 성취수준 ${std.level || '없음'}`] : null],
          warn: DROP_WARN,
          jobs: [{ run: () => api.ai_synth(R.slot.group_id, R.slot.item, R.sno, recs.map((r) => r.id), wm, model.value, sumCheck, std) }],
        }));
        if (!out || !out.done) return;
        const res = out.results[0];
        closeSheet();
        revealResults();
        toast(res.dropped ? '종합 후보를 만들고 가장 오래된 후보를 지웠습니다.' : '종합 후보를 만들었습니다. 최종안 아래 [종합·다듬기 후보]에서 확인하세요.');
        loadStudent(true);
      });
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: `종합 설정 · ${R.view.student.name}` }), el('span', { class: 'muted', text: `${R.slot.label} · 목표 ${R.target}B` })]),
        el('div', { class: 'sheet-body' }, [
          el('p', { class: 'hint', text: '비중은 결과 문장에서 차지할 분량 비율입니다. 비워 두면 기록 길이에 비례해 자동으로 나눕니다. 입력한 비중은 기록에 저장됩니다. 비율은 목표이며 결과가 정확히 맞지는 않을 수 있습니다.' }),
          t, sumLine,
          el('div', { class: 'map-row' }, [el('label', {}, [chk, '비중 합계 100% 검사']), el('label', {}, ['모델', model]),
            stdChk ? el('label', { title: R.view.standards.text.trim() ? '' : '성취기준 메뉴에서 먼저 넣으세요' }, [stdChk, '성취기준 사용']) : null,
            stdChk ? el('label', {}, ['성취수준', stdLvl]) : null]),
          stdBox,
          el('p', { class: 'hint', text: '쓸 프롬프트는 [종합 실행]을 누르면 나오는 확인 창에서 고릅니다(지침·예시 고치기는 메뉴 › 프롬프트). AI에는 명렬의 학번·이름 없이 기록 내용과 비율만 보냅니다(본문에 적힌 이름은 그대로 갑니다).' }),
        ]),
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), runBtn]),
      );
      redraw();
    });
  }

  function renderFinal() {
    const box = $('recFinal');
    box.innerHTML = '';
    const v = R.view;
    const f = v.final;
    const closed = !!(f && f.closed);
    const ro = closed || !!ys.archived;
    let fmeta = {};
    try { fmeta = f ? JSON.parse(f.meta || '{}') : {}; } catch (e) { fmeta = {}; }
    const finSec = el('div', { class: 'final-sec' });
    box.appendChild(finSec);
    finSec.appendChild(el('div', { class: 'sec-title' }, [foldBtn('final', finSec, '최종안'), el('span', { class: 'muted', text: `목표 ${R.target}B` }), stdBadge(fmeta)]));
    const pairBox = pairInfo(v.pair);
    if (pairBox) finSec.appendChild(pairBox);
    const fb = el('div', { class: 'final-box' + (f ? ' has' : '') + (closed ? ' closed' : '') });
    if (f && f.stale && !closed) fb.appendChild(el('div', { class: 'stale', text: '! 최종안을 채택한 뒤 기록이 바뀌었습니다. 다시 종합하거나 내용을 확인하세요.' }));
    const ta = el('textarea', { value: f ? f.text : '', placeholder: '아직 최종안이 없습니다. 아래 종합 후보에서 [최종안으로 채택]을 누르거나 여기에 직접 쓰세요.', disabled: ro });
    const bc = el('span', {});
    const upd = () => { bc.innerHTML = ''; bc.appendChild(bytesEl(bytesOf(ta.value), R.target)); };
    ta.addEventListener('input', () => { upd(); saveState.textContent = '저장 중…'; finalAutoSave(); });
    // 후보 문장을 넣을 자리: 마지막 커서 위치를 기억(없으면 맨 끝)
    const keepSel = () => { ta._sel = [ta.selectionStart, ta.selectionEnd]; };
    ['keyup', 'click', 'select', 'blur'].forEach((ev) => ta.addEventListener(ev, keepSel));
    const saveState = el('span', { class: 'muted' });
    const ctx = R.viewCtx;
    finalDraft = { ctx, saved: f ? f.text : '', ta, state: saveState, ro };
    const saveBtn = el('button', { type: 'button', hidden: true, text: '저장' });
    const polishBtn = el('button', { type: 'button', class: 'ai-btn', disabled: ro || !f || pairFull(), title: pairFull() ? PAIR_FULL_TIP : '최종안을 AI로 다듬어 후보로 만듭니다', text: '다듬기(AI)' });
    const polishWiz = recWizBtn('polish', () => ta.value, ro || !f);
    polishBtn.addEventListener('click', async () => {
      if (!(await flushFinal())) return;
      const out = await busyRun(polishBtn, `synth${R.sno}`, () => aiRun({
        title: '최종안 다듬기', kind: 'polish',
        rows: [['학생', `${R.view.student.name} · ${R.slot.label}`], ['최종안', `${bytesOf(ta.value)}B → 목표 ${R.target}B`], ['모델', modelName($('recModel'))]],
        warn: `${DROP_WARN} 최종안 자체는 바뀌지 않고 후보로 만듭니다.`,
        jobs: [{ run: () => api.ai_polish_final(R.slot.group_id, R.slot.item, R.sno, $('recModel').value) }],
      }));
      if (out && out.done) { revealResults(); toast('다듬기 후보를 만들었습니다. 최종안 아래 후보에서 확인하세요.'); loadStudent(true); }
    });
    const closeBtn = closed
      ? el('button', { type: 'button', disabled: !!ys.archived, text: '마감 해제', onclick: async () => { if (await mutate('set_closed', R.slot.group_id, R.slot.item, R.sno, false)) { toast('마감을 해제했습니다.'); loadStudent(true); } } })
      : el('button', { type: 'button', class: 'primary', disabled: !f || !!ys.archived, text: '● 마감', title: f ? '검토를 끝내고 편집을 잠급니다' : '최종안이 있어야 마감할 수 있습니다', onclick: async () => {
        const c = ctx;
        if (await afterFinalSaved(() => mutate('set_closed', c.gid, c.item, c.sno, true))) { toast('마감했습니다. 다음 학생으로 넘어가세요.'); loadStudent(true); }
      } });
    // 직접 쓴 글이 저장되면 마감·다듬기 버튼과 학생 상태를 바로 맞춘다
    finalDraft.onSaved = (text) => {
      const has = !!text.trim();
      if (!closed) {
        closeBtn.disabled = !has || !!ys.archived;
        closeBtn.title = has ? '검토를 끝내고 편집을 잠급니다' : '최종안이 있어야 마감할 수 있습니다';
        polishBtn.disabled = ro || !has || pairFull();
        polishWiz.disabled = ro || !has;
      }
      if (R.view !== v) return;
      v.final = has ? { ...(v.final || {}), text, closed: false, stale: false } : null;
      const st = R.students.find((s) => s.student_no === ctx.sno);
      if (st && R.sno === ctx.sno && st.status !== 'closed') {
        st.status = has ? 'final' : (v.records.length || v.results.length) ? 'progress' : 'none';
        renderStudentList();
      }
    };
    upd();
    fb.append(ta, el('div', { class: 'final-actions' }, [bc, saveState, el('span', { class: 'spacer' }), saveBtn, aiPair(polishBtn, polishWiz), closeBtn]));
    if (closed) fb.appendChild(el('div', { class: 'hint', text: `● ${f.closed_at || ''} 마감 — 기록·AI·최종안 편집이 잠겼습니다. 조회·복사·내보내기는 됩니다.` }));
    finSec.appendChild(fb);

    const resSec = el('div', { class: 'res-sec' });
    box.appendChild(resSec);
    resSec.appendChild(el('div', { class: 'sec-title' }, [foldBtn('results', resSec, `종합·다듬기 후보 ${v.results.length}/3`), el('span', { class: 'muted', text: '잠금 포함 최근 3개 보관, 4번째부터 잠기지 않은 가장 오래된 것 삭제' })]));
    if (!v.results.length) resSec.appendChild(el('p', { class: 'hint', text: '기록을 골라 [선택 기록 종합하기]를 누르면 여기에 후보가 생깁니다.' }));
    v.results.slice().reverse().forEach((cd) => resSec.appendChild(candEl(cd, ro, [
      el('button', { type: 'button', class: 'small primary', disabled: ro, text: '✔ 최종안으로 채택', onclick: async () => {
        if (!(await flushFinal())) return;
        if (ta.value.trim() && ta.value.trim() !== cd.text.trim() && !(await confirmBox('지금 최종안을 이 후보로 바꿉니다. 계속할까요?', '채택'))) return;
        if (await afterFinalSaved(() => mutate('adopt_result', cd.id))) { toast('최종안으로 채택했습니다.'); loadStudent(true); }
      } }),
      el('button', { type: 'button', class: 'small', text: '정보', onclick: () => candInfo(cd) }),
    ])));
  }

  // 1·2학기 합산 안내(최종안 칸 위)
  function pairInfo(p) {
    if (!p) return null;
    if (p.role === 'first') {
      return el('div', { class: 'pair-box' + (p.over ? ' over' : '') }, [el('b', { text: `1·2학기 합산 ${p.total}B` }),
        ` · 2학기 ${p.other}${p.second_bytes !== null && p.second_bytes !== undefined ? ` 최종안 ${p.second_bytes}B` : ''}`,
        el('div', { class: 'muted', text: '여기(1학기)에서 쓴 바이트만큼 2학기 목표가 줄어듭니다.' }),
        p.over ? el('div', { class: 'danger-text', text: `1학기 ${p.first_bytes}B + 2학기 최종안이 합산 ${p.total}B를 넘습니다. 2학기${(p.others || []).some((x) => x.second_closed) ? '(마감됨)' : ''}를 다시 확인하세요.` }) : null]);
    }
    const over = p.remain !== null && p.remain !== undefined && p.remain <= 0;
    const box = el('div', { class: 'pair-box' + (over ? ' over' : '') });
    const add = (...xs) => box.append(...xs.filter((x) => x !== null && x !== undefined));
    if (p.first_bytes === null || p.first_bytes === undefined) {
      add(el('b', { text: `1학기 ${p.other} 최종안 없음` }), ` · 합산 ${p.total}B → 우선 절반 `, el('b', { text: `${p.target}B` }), '를 목표로 씁니다.',
        p.member ? null : el('div', { class: 'muted', text: '이 학생은 1학기 명렬에 없습니다.' }));
      return box;
    }
    add(p.over ? el('div', { class: 'danger-text', style: 'font-weight:800', text: `⚠ 합산 초과: 1학기 ${p.first_bytes}B + 이번 학기 ${p.second_bytes}B = ${p.first_bytes + p.second_bytes}B > ${p.total}B${p.second_closed ? ' — 마감했지만 다시 확인이 필요합니다' : ''}` }) : null);
    add(el('b', { text: `1학기 ${p.other} 최종안 ${p.first_bytes}B${p.first_closed ? ' (마감)' : ''}` }), ` · 합산 ${p.total}B → 이번 학기 남은 `,
      el('b', { class: over ? 'danger-text' : '', text: `${p.remain}B` }),
      over ? el('div', { class: 'danger-text', text: '1학기가 합산을 이미 채워 AI 종합·다듬기를 할 수 없습니다. 1학기 최종안을 줄이거나 합산 목표를 바꾸세요.' }) : null,
      el('details', {}, [el('summary', { text: '1학기 최종안 보기' }), el('div', { class: 'cmp-text', text: p.first_text })]));
    return box;
  }

  // 줄 순서 바꾸기: ⠿ 손잡이를 끌거나 ▲▼ 버튼. items: 화면 순서의 [{ id, el }].
  // 돌려주는 함수로 줄마다 손잡이를 만든다. onSave(새 id 순서)
  function sortable(items, onSave, disabled) {
    const ids = items.map((x) => x.id);
    let dragId = null;
    const clear = () => items.forEach((x) => x.el.classList.remove('drop-before', 'drop-after', 'dragging'));
    const move = (from, to) => { const n = ids.slice(); const [v] = n.splice(from, 1); n.splice(to, 0, v); return n; };
    items.forEach((it, idx) => {
      it.el.addEventListener('dragover', (e) => {
        if (dragId === null) return;
        e.preventDefault();
        const r = it.el.getBoundingClientRect();
        const before = e.clientY < r.top + r.height / 2;
        items.forEach((x) => x.el.classList.remove('drop-before', 'drop-after'));
        it.el.classList.add(before ? 'drop-before' : 'drop-after');
      });
      it.el.addEventListener('drop', (e) => {
        if (dragId === null) return;
        e.preventDefault();
        const before = it.el.classList.contains('drop-before');
        const from = ids.indexOf(dragId);
        let to = idx + (before ? 0 : 1);
        if (from < to) to -= 1;
        dragId = null;
        clear();
        if (from !== to) onSave(move(from, to));
      });
    });
    return (id) => {
      const i = ids.indexOf(id);
      const h = el('span', { class: 'drag-handle' + (disabled ? ' off' : ''), draggable: disabled ? null : 'true', title: disabled ? '' : '끌어서 순서 바꾸기', text: '⠿' });
      h.addEventListener('dragstart', (e) => {
        dragId = id;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(id));
        items[i].el.classList.add('dragging');
        try { e.dataTransfer.setDragImage(items[i].el, 12, 12); } catch (x) { /* 무시 */ }
      });
      h.addEventListener('dragend', () => { dragId = null; clear(); });
      return el('span', { class: 'sort-ctl' }, [h,
        el('button', { type: 'button', class: 'mini', disabled: disabled || i === 0, title: '한 칸 위로', text: '▲', onclick: () => onSave(move(i, i - 1)) }),
        el('button', { type: 'button', class: 'mini', disabled: disabled || i === ids.length - 1, title: '한 칸 아래로', text: '▼', onclick: () => onSave(move(i, i + 1)) })]);
    };
  }

  // 실행 버튼은 한 번만: 누르면 바로 잠그고 '… 중'으로. 요청 번호도 함께 보내 서버에서도 한 번만 적용한다.
  async function runOnce(btn, busyText, fn) {
    if (btn.dataset.running) return null;
    btn.dataset.running = '1';
    const old = btn.textContent;
    btn.disabled = true;
    btn.textContent = busyText;
    const reqId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    try { return await fn(reqId); } finally {
      delete btn.dataset.running;
      if (btn.isConnected) { btn.textContent = old; btn.disabled = false; if (btn._refresh) btn._refresh(); }
    }
  }
  const stepBar = (n) => el('div', { class: 'steps' }, ['① 자료 붙여넣기', '② 열·학생 연결 확인', '③ 입력'].map((t, i) => el('span', { class: i + 1 === n ? 'on' : '', text: t })));

  // 여러 학생 일괄 입력: kind='existing'(이미 쓴 생기부 → 기존 완성문, 학생당 한 줄) / 'record'(학생관찰기록, 한 학생 여러 줄, 활동명·날짜 선택).
  // 파일마다 다른 형식. 이름·내용만 있으면 이름으로 연결한다. NEIS 업로드 파일(반/번호·성명·내용)도 알아본다.
  // 표에서 고친 것(내용·학생·확정·빼기·순서)은 원본 행 번호로 기억해, 열을 다시 골라도 그대로 둔다.
  async function openExistingBulk(kind) {
    if (!R.slot) return;
    const isRec = kind === 'record';
    const what = isRec ? '학생관찰기록' : '이미 쓴 생기부';
    const c = await api.read_clipboard();
    const clip = c && c.ok && (c.text || '').includes('\t') ? c.text : '';
    const gid = R.slot.group_id, item = R.slot.item, slotLabel = R.slot.label;
    const intro = isRec
      ? '학생별 학생관찰기록으로 추가합니다. 한 학생이 여러 줄이면 줄마다 한 건씩 들어가고 회차는 이어 붙습니다. 이미 있는 기록은 바꾸지 않습니다. 이름과 기록 내용 칸만 있으면 되고, 활동명·날짜 칸은 고를 때만 넣습니다.'
      : "작성해 둔 문장을 학생별 '기존 완성문' 기록으로 추가합니다. 아직 최종안은 아닙니다 — 최종안 반영은 다음 단계([✔ 기존 완성문 → 최종안 일괄])입니다. 이미 있는 기록은 바꾸지 않습니다. 이름과 생기부 내용 칸만 있으면 되고, NEIS 업로드 파일(학년도·학기·…·반/번호·성명·학적변동 구분·내용)도 그대로 읽습니다.";
    let lastText = clip;
    openSheet((box) => {
      const body = el('div', { class: 'sheet-body' });
      const foot = el('div', { class: 'sheet-foot' });
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `${what} 일괄 입력` }), el('span', { class: 'muted', text: `${slotLabel} · 학생 목록의 검색·필터와 관계없이 이 담당 명렬 전체` })]), body, foot);
      const start = (prefill, fromClip) => {
        body.innerHTML = '';
        foot.innerHTML = '';
        const ta = el('textarea', { rows: 10, value: prefill || '', placeholder: `엑셀에서 이름·내용 칸(있으면 반/번호·학번${isRec ? '·활동명·날짜' : ''}도)을 함께 복사해 여기에 붙여넣으세요.` });
        const lines = (prefill || '').split('\n').filter((l) => l.trim()).length;
        addTo(body, stepBar(1), el('p', { class: 'hint', text: intro }),
          fromClip ? el('div', { class: 'warn', text: `클립보드에 있던 표 ${lines}줄을 넣어 두었습니다(아직 저장 전). 이번에 넣을 자료가 맞는지 확인하고, 아니면 지우고 다시 붙여넣으세요.` }) : null, ta);
        const readBtn = el('button', { type: 'button', class: 'primary', text: '열·학생 연결 확인 →' });
        readBtn.addEventListener('click', async () => { lastText = ta.value; const r = await call('existing_parse', gid, item, ta.value, false); if (r) preview(r); });
        foot.append(el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', text: '📂 xlsx 불러오기', onclick: async () => {
            let r = await call('existing_parse', gid, item, null, true);
            if (r && r.sheets) { const sh = await pickSheets(r, false); r = sh ? await call('existing_parse', gid, item, null, true, r.token, sh[0]) : null; }
            if (r) { lastText = ''; preview(r); }
          } }), readBtn);
        setTimeout(() => ta.focus(), 50);
      };
      const preview = async (pz) => {
        const st = { raw: pz.raw, header: pz.header, cols: { ...pz.columns }, rows: [], members: [], onlyBad: false, building: false };
        // 표에서 고친 것: 원본 행(raw 번호) → { content:{col,text}, sno:{v,state,note}, confirm, date:{col,v}, dateSkip }
        const edits = new Map();
        const removed = new Set();
        let order = null; // 끌어서 바꾼 순서(원본 행 번호)
        const ed = (r) => { if (!edits.has(r.key)) edits.set(r.key, {}); return edits.get(r.key); };
        const dirty = () => edits.size > 0 || removed.size > 0 || !!order;
        body.innerHTML = '';
        foot.innerHTML = '';
        const width = Math.max(...st.raw.map((r) => r.length));
        const bodyRows = () => st.raw.slice(st.header ? 1 : 0);
        const optText = (i) => {
          const ex = bodyRows().map((r) => (r[i] || '').trim()).filter(Boolean).slice(0, 2).map((v) => `“${v.slice(0, 12)}${v.length > 12 ? '…' : ''}”`);
          const hd = st.header ? (st.raw[0][i] || '').trim() : '';
          return [`${colName(i)}열`, hd, ex.join(' / ')].filter(Boolean).join(' · ');
        };
        const clsRole = () => ['clsnum', 'gradecls', 'clsany'].find((k) => st.cols[k] !== null && st.cols[k] !== undefined);
        const selects = [];
        const colSel = (label, get, set, required) => {
          const s = el('select', { onchange: (e) => { set(e.target.value === '' ? null : +e.target.value); build(); } });
          const fill = () => {
            s.innerHTML = '';
            s.append(el('option', { value: '', text: required ? '(고르세요)' : '(사용 안 함)' }),
              ...Array.from({ length: width }, (_, i) => el('option', { value: i, text: optText(i), selected: get() === i })));
          };
          fill();
          selects.push(fill);
          return el('label', {}, [label, s]);
        };
        const role = (k) => [() => st.cols[k], (v) => { st.cols[k] = v; }];
        const clsSel = colSel('반/번호(선택)', () => { const k = clsRole(); return k ? st.cols[k] : null; }, (v) => { st.cols.clsnum = null; st.cols.gradecls = null; st.cols.clsany = v; });
        const tableBox = el('div', {});
        const summary = el('span', {});
        const confirmAll = el('button', { type: 'button', text: '추천 모두 확정' });
        const skipDates = el('button', { type: 'button', hidden: true });
        const applyBtn = el('button', { type: 'button', class: 'primary', text: '입력' });
        const headChk = el('input', { type: 'checkbox', checked: st.header, onchange: (e) => { st.header = e.target.checked; selects.forEach((f) => f()); build(); } });
        body.append(stepBar(2),
          el('div', { class: 'map-row' }, [el('label', {}, [headChk, '첫 줄은 머리글']),
            colSel('이름 열', ...role('name'), true), colSel(isRec ? '기록 내용 열' : '생기부 내용 열', ...role('content'), true), clsSel, colSel('학번(선택)', ...role('student_no')),
            isRec ? colSel('활동명(선택)', ...role('title')) : null, isRec ? colSel('날짜(선택)', ...role('date')) : null]),
          el('div', { class: 'toolbar' }, [summary, el('span', { class: 'spacer' }),
            el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', onchange: (e) => { st.onlyBad = e.target.checked; draw(); } }), '확인 필요만 보기']), skipDates, confirmAll]),
          tableBox);
        foot.append(el('span', { class: 'muted', text: '추천(노랑)은 확정해야 넣고, 확인 필요(빨강)는 학생을 고르거나 ✕로 빼세요.' }), el('span', { class: 'spacer' }),
          el('button', { type: 'button', text: '← 자료 다시 붙여넣기', onclick: async () => { if (dirty() && !(await confirmBox('표에서 고친 내용은 사라집니다. 자료 붙여넣기로 돌아갈까요?', '돌아가기'))) return; start(lastText, false); } }),
          el('button', { type: 'button', text: '취소', onclick: closeSheet }), applyBtn);
        const mOf = (sno) => st.members.find((m) => m.student_no === sno);
        const dateCol = () => isRec && st.cols.date !== null && st.cols.date !== undefined;
        const badDate = (r) => dateCol() && r.date_raw && !r.date && !r.dateSkip;
        const issues = (r) => {
          const out = [];
          const m = mOf(r.student_no);
          if (!r.student_no) out.push(r.note || '학생을 골라 주세요');
          else if (!m) out.push('명렬에 없는 학생');
          else if (!m.active) out.push('비활성 학생');
          else if (m.closed) out.push('마감된 학생');
          if (!(r.content || '').trim()) out.push('내용 없음');
          if (!isRec && r.student_no && st.rows.filter((x) => x.student_no === r.student_no).length > 1) out.push('같은 학생이 다른 줄에도 있음');
          if (badDate(r)) out.push(`날짜를 읽지 못함(원본 “${r.date_raw}”) — 날짜를 고치거나 [날짜 없이]`);
          return out;
        };
        const draw = () => {
          tableBox.innerHTML = '';
          const t = el('table', { class: 'tbl' });
          t.appendChild(el('tr', {}, ['순서', '원본 행', '원본 학번·반/번호·이름', '연결할 학생', '상태', isRec ? '날짜·활동명 / 내용' : '내용', ''].map((h) => el('th', { text: h }))));
          const items = [];
          const holders = [];
          st.rows.forEach((r, i) => {
            const iss = issues(r);
            r._bad = iss.length > 0;
            if (st.onlyBad && !iss.length && r.state === 'confirmed') return;
            const opts = [el('option', { value: '', text: '학생 고르기' }), ...st.members.map((m) => el('option', { value: m.student_no, text: `${m.grade}-${m.class_no}-${m.number} ${m.name}${m.closed ? ' (마감)' : ''}${m.active ? '' : ' (비활성)'}`, selected: m.student_no === r.student_no }))];
            const sel = el('select', { onchange: (e) => {
              r.student_no = e.target.value || null; r.state = r.student_no ? 'confirmed' : 'none'; r.note = r.student_no ? '직접 고름' : '';
              ed(r).sno = { v: r.student_no, state: r.state, note: r.note };
              draw();
            } }, opts);
            const ta = el('textarea', { class: 'cell-edit', rows: 2, value: r.content, oninput: (e) => { r.content = e.target.value; ed(r).content = { col: st.cols.content, text: r.content }; }, onchange: () => draw() });
            const holder = el('td', {});
            const stateTd = el('td', {}, [
              el('div', { class: `st-chip ${iss.length ? 'none' : r.state}`, text: iss.length ? '! 확인 필요' : ST_CHIP[r.state] }),
              ...(iss.length ? iss : (r.note && r.state !== 'confirmed' ? [r.note] : [])).map((x) => el('div', { class: 'note', text: x })),
              r.change ? el('div', { class: 'note', text: `학적변동: ${r.change}` }) : null,
              r.state === 'suggested' && r.student_no && !iss.length ? el('button', { type: 'button', class: 'small', text: '확정', onclick: () => { r.state = 'confirmed'; ed(r).confirm = r.student_no; draw(); } }) : null,
              badDate(r) ? el('button', { type: 'button', class: 'small', text: '날짜 없이', onclick: () => { r.dateSkip = true; ed(r).dateSkip = true; draw(); } }) : null]);
            const dateIn = dateCol() ? el('input', { type: 'date', value: r.date || '', onchange: (e) => { r.date = e.target.value; r.dateSkip = !r.date; ed(r).date = { col: st.cols.date, v: r.date }; ed(r).dateSkip = r.dateSkip; draw(); } }) : null;
            const meta = isRec ? el('div', { class: 'inline', style: 'gap:6px;margin-bottom:4px' }, [dateIn, dateCol() && r.date_raw ? el('span', { class: 'note', text: `원본 ${r.date_raw}` }) : null, r.title ? el('span', { class: 'note', text: r.title }) : null]) : null;
            const tr = el('tr', { class: iss.length ? 'row-pending bad' : r.state === 'suggested' ? 'row-pending' : '' }, [holder, el('td', { class: 'muted', text: String(r.key + 1) }),
              el('td', { text: [r.ext_no, r.ext_cls, r.ext_name].filter(Boolean).join(' ') || '-' }), el('td', {}, [sel]), stateTd,
              el('td', {}, [meta, ta]),
              el('td', {}, [el('button', { type: 'button', class: 'link', title: '이 줄 빼기', text: '✕', onclick: () => { removed.add(r.key); st.rows.splice(i, 1); draw(); } })])]);
            items.push({ id: i, el: tr });
            holders.push([holder, i]);
            t.appendChild(tr);
          });
          const handle = sortable(items, (ord) => { st.rows = ord.map((k) => st.rows[k]); order = st.rows.map((r) => r.key); draw(); }, st.onlyBad);
          holders.forEach(([h, i]) => h.appendChild(handle(i)));
          tableBox.appendChild(t);
          const bad = st.rows.filter((r) => r._bad).length;
          const sug = st.rows.filter((r) => !r._bad && r.state === 'suggested').length;
          const conf = st.rows.length - bad - sug;
          const nBadDate = st.rows.filter(badDate).length;
          summary.innerHTML = '';
          summary.append(el('b', { text: `확정 ${conf}` }), ' · ', el('b', { style: 'color:#a16207', text: `추천 ${sug}` }), ' · ', el('b', { class: bad ? 'danger-text' : '', text: `확인 필요 ${bad}` }),
            removed.size ? el('span', { class: 'muted', text: ` · 뺀 줄 ${removed.size}` }) : '');
          confirmAll.disabled = !sug;
          confirmAll.textContent = `추천 ${sug}건 모두 확정`;
          skipDates.hidden = !nBadDate;
          skipDates.textContent = `못 읽은 날짜 ${nBadDate}건 날짜 없이 넣기`;
          const nStu = new Set(st.rows.map((r) => r.student_no).filter(Boolean)).size;
          applyBtn.textContent = isRec ? `${nStu}명 ${st.rows.length}건 입력` : `${st.rows.length}명 내용 입력`;
          applyBtn.disabled = st.building || !st.rows.length || bad > 0 || sug > 0;
        };
        applyBtn._refresh = draw;
        skipDates.addEventListener('click', () => { st.rows.forEach((r) => { if (badDate(r)) { r.dateSkip = true; ed(r).dateSkip = true; } }); draw(); });
        confirmAll.addEventListener('click', async () => {
          if (!(await confirmBox('추천은 이름이 비슷하거나 학번·반·번호가 달라 앱이 짐작한 연결입니다. 원본과 대조해 보셨나요? 추천 모두를 확정합니다.', '확정'))) return;
          st.rows.forEach((r) => { if (!r._bad && r.state === 'suggested') { r.state = 'confirmed'; ed(r).confirm = r.student_no; } });
          draw();
        });
        // 열을 바꾸면 다시 연결하되, 표에서 고친 것은 원본 행 번호로 다시 입힌다. 늦게 온 응답은 버린다.
        let buildReq = 0;
        const build = async () => {
          const req = ++buildReq;
          st.building = true;
          applyBtn.disabled = true;
          const r = await call('existing_build', gid, item, st.raw, st.header, st.cols);
          if (req !== buildReq) return;
          st.building = false;
          if (!r) { draw(); return; }
          st.members = r.members.slice().sort((a, b) => (a.grade - b.grade) || (a.class_no - b.class_no) || (a.number - b.number));
          let kept = 0, lost = 0;
          let rows = r.rows.map((x) => ({ ...x, key: st.header ? x.row : x.row - 1 })).filter((x) => !removed.has(x.key));
          rows.forEach((x) => {
            const e = edits.get(x.key);
            if (!e) return;
            if (e.content) { if (e.content.col === st.cols.content) { x.content = e.content.text; kept += 1; } else lost += 1; }
            if (e.sno) { x.student_no = e.sno.v; x.state = e.sno.state; x.note = e.sno.note; kept += 1; }
            if (e.confirm && x.student_no === e.confirm && x.state === 'suggested') { x.state = 'confirmed'; kept += 1; }
            if (e.date && e.date.col === st.cols.date) { x.date = e.date.v; kept += 1; }
            if (e.dateSkip && st.cols.date !== null) x.dateSkip = true;
          });
          if (order) { const pos = new Map(order.map((k, i) => [k, i])); rows = rows.slice().sort((a, b) => (pos.has(a.key) ? pos.get(a.key) : 1e9 + a.key) - (pos.has(b.key) ? pos.get(b.key) : 1e9 + b.key)); }
          st.rows = rows;
          draw();
          if (lost) toast(`내용 열을 바꿔, 표에서 고친 내용 ${lost}건은 새 열의 내용으로 바뀌었습니다.`, 5000);
          else if (kept || removed.size || order) toast('열을 다시 연결했습니다. 표에서 고친 것(학생·확정·빼기·순서)은 그대로 두었습니다.', 4000);
        };
        applyBtn.addEventListener('click', () => runOnce(applyBtn, '입력 중…', async (reqId) => {
          const send = st.rows.map((x) => ({ student_no: x.student_no, content: x.content, title: x.title || '', date: dateCol() ? (x.date || '') : '' }));
          const r = await mutate('existing_apply', gid, item, send, kind, reqId);
          if (!r) return;
          closeSheet();
          loadSlotStudents();
          if (isRec) { toast(`${r.students}명 ${r.count}건 입력했습니다.`); return; }
          if (await modal(`${r.count}명 내용 입력했습니다.\n\n학생마다 '기존 완성문' 기록으로 추가했고, 아직 최종안은 아닙니다. 이어서 기존 완성문을 최종안으로 보낼까요?`, true, false, '최종안 일괄 보내기 열기', '나중에')) openFinalBulk();
        }));
        await build();
      };
      start(clip, !!clip);
    });
  }

  // 기존 완성문 → 최종안 일괄(이 반·과목 전체). 최종안이 빈 학생은 새로 반영, 이미 있으면 덮어쓰기를 직접 체크한다.
  // 기존 완성문이 여러 개인 학생: 마지막으로 추가한 것으로 미리 고르기 / 직접 고르기(고르기 전에는 제외). 줄에서 버전을 바꿀 수 있다.
  async function openFinalBulk() {
    if (!R.slot) return;
    const gid = R.slot.group_id, item = R.slot.item, slotLabel = R.slot.label;
    if (!(await flushFinal())) { toast(SAVE_FAIL_MSG, 5000); return; }
    const v = await call('finals_bulk_view', gid, item);
    if (!v) return;
    const studs = v.students.slice().sort((a, b) => (b.active - a.active) || (a.grade - b.grade) || (a.class_no - b.class_no) || (a.number - b.number));
    const isMulti = (x) => x.active && !x.closed && x.existing.length > 1;
    const nMulti = studs.filter(isMulti).length;
    let multi = 'latest';
    const pick = new Map(); // 직접 바꾼 체크
    const choice = new Map(); // 여러 개인 학생에서 직접 고른 기록 id
    const open = new Set(); // 전문 비교를 펼친 학생
    const when = (s) => (s || '').slice(5, 16).replace(' ', ' ');
    const recInfo = (r) => `${r.title || '제목 없음'} · 추가 ${when(r.created_at)}${r.updated_at && r.updated_at !== r.created_at ? ` · 수정 ${when(r.updated_at)}` : ''} · ${r.bytes}B`;
    const clip = (t) => el('div', { class: 'clip', text: t || '-' });
    openSheet((box) => {
      const body = el('div', { class: 'sheet-body' });
      const summary = el('span', {});
      const tbox = el('div', {});
      const sendBtn = el('button', { type: 'button', class: 'primary' });
      const recOf = (x) => {
        const n = x.existing.length;
        if (n === 1) return x.existing[0];
        if (choice.has(x.student_no)) return x.existing.find((e) => e.id === choice.get(x.student_no)) || null;
        return multi === 'latest' ? x.existing[n - 1] : null;
      };
      // kind: off(이번 일괄 대상 아님) / need(버전 고르기 필요) / new(최종안 없음) / over(최종안 있음)
      const classify = (x) => {
        if (!x.active) return { kind: 'off', why: '비활성' };
        if (x.closed) return { kind: 'off', why: '마감' };
        if (!x.existing.length) return { kind: 'off', why: '기존 완성문 없음' };
        const rec = recOf(x);
        if (!rec) return { kind: 'need', why: `기존 완성문 ${x.existing.length}개 — 보낼 것을 고르세요` };
        if (x.final.trim() && x.final.trim() === rec.content.trim()) return { kind: 'off', rec, why: '이미 같은 최종안' };
        return { kind: x.final.trim() ? 'over' : 'new', rec, why: x.final.trim() ? '최종안 있음' : '최종안 없음' };
      };
      const isOn = (x, c) => (c.kind === 'new' || c.kind === 'over') && (pick.has(x.student_no) ? pick.get(x.student_no) : c.kind === 'new');
      const draw = () => {
        tbox.innerHTML = '';
        const t = el('table', { class: 'tbl final-bulk' });
        t.appendChild(el('tr', {}, ['', '학생', '처리', '보낼 기존 완성문', '지금 최종안', ''].map((h) => el('th', { text: h }))));
        let nNew = 0, nOver = 0, nOff = 0, nNeed = 0;
        studs.forEach((x) => {
          const c = classify(x);
          const on = isOn(x, c);
          if (on) { if (c.kind === 'new') nNew += 1; else nOver += 1; } else { nOff += 1; if (c.kind === 'need') nNeed += 1; }
          const can = c.kind === 'new' || c.kind === 'over';
          const chk = el('input', { type: 'checkbox', checked: on, disabled: !can, onchange: (e) => { pick.set(x.student_no, e.target.checked); draw(); } });
          const chip = on ? (c.kind === 'new' ? ['confirmed', '새로 반영'] : ['suggested', '덮어쓰기']) : ['excluded', can ? '이번에는 제외' : '제외'];
          const verSel = isMulti(x) ? el('select', { class: 'ver-sel', onchange: (e) => { if (e.target.value) choice.set(x.student_no, +e.target.value); else choice.delete(x.student_no); draw(); } }, [
            el('option', { value: '', text: multi === 'latest' ? '(마지막으로 추가한 것)' : '보낼 것 고르기' }),
            ...x.existing.map((r, i) => el('option', { value: r.id, selected: choice.get(x.student_no) === r.id, text: `${i + 1}번째 추가 · ${when(r.created_at)} · ${r.bytes}B${i === x.existing.length - 1 ? ' (마지막)' : ''}` }))]) : null;
          t.appendChild(el('tr', { class: !on ? 'off' : c.kind === 'over' ? 'row-pending' : '' }, [
            el('td', {}, [chk]),
            el('td', { text: `${x.grade}-${x.class_no}-${x.number} ${x.name}` }),
            el('td', {}, [el('div', { class: `st-chip ${chip[0]}`, text: chip[1] }), el('div', { class: 'note', text: c.why })]),
            el('td', {}, [verSel, c.rec ? clip(c.rec.content) : null, c.rec ? el('div', { class: 'note', text: recInfo(c.rec) }) : (verSel ? null : clip(''))]),
            el('td', {}, [clip(x.final)]),
            el('td', {}, [c.rec ? el('button', { type: 'button', class: 'small', text: open.has(x.student_no) ? '비교 닫기' : '전문 비교', onclick: () => { if (open.has(x.student_no)) open.delete(x.student_no); else open.add(x.student_no); draw(); } }) : null]),
          ]));
          if (c.rec && open.has(x.student_no)) {
            t.appendChild(el('tr', { class: 'cmp-row' }, [el('td', {}), el('td', { colspan: 5 }, [el('div', { class: 'cmp' }, [
              el('div', {}, [el('div', { class: 'col-label', text: `지금 최종안${x.final ? ` · ${bytesOf(x.final)}B` : ''}` }), el('div', { class: 'cmp-text', text: x.final || '(없음)' })]),
              el('div', {}, [el('div', { class: 'col-label', text: `보낼 기존 완성문 · ${recInfo(c.rec)}` }), el('div', { class: 'cmp-text', text: c.rec.content })]),
            ])])]));
          }
        });
        tbox.appendChild(t);
        summary.innerHTML = '';
        summary.append(el('b', { text: `반영 ${nNew + nOver}명` }), ` (새로 ${nNew} · `, el('b', { style: 'color:#a16207', text: `덮어쓰기 ${nOver}` }), ') · ',
          el('b', { class: 'muted', text: `제외 ${nOff}명` }), nNeed ? el('span', { class: 'danger-text', text: ` (그중 고르기 필요 ${nNeed})` }) : '', el('span', { class: 'muted', text: ` · 전체 ${studs.length}명` }));
        sendBtn.textContent = `${nNew + nOver}명 최종안으로 보내기${nOver ? ` (덮어쓰기 ${nOver}명)` : ''}`;
        sendBtn.disabled = !(nNew + nOver);
      };
      sendBtn._refresh = draw;
      const radio = (val, label) => el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'radio', name: 'fbMulti', checked: multi === val, onchange: () => { multi = val; draw(); } }), label]);
      addTo(body, 
        el('p', { class: 'hint', text: '학생마다 기존 완성문을 그대로 최종안으로 보냅니다. 최종안이 없는 학생은 미리 체크되어 있고, 최종안이 있는 학생은 [전문 비교]로 확인한 뒤 덮어쓸 학생만 체크하세요. 마감·비활성 학생과 기존 완성문이 없는 학생은 제외됩니다. 학생 목록의 검색·필터와 관계없이 이 담당 명렬 전체가 대상입니다. 보낸 직후에는 [되돌리기]로 원래 최종안을 돌려놓을 수 있습니다.' }),
        nMulti ? el('div', { class: 'map-row' }, [el('b', { text: `기존 완성문이 여러 개인 학생 ${nMulti}명:` }), radio('latest', '마지막으로 추가한 것으로 미리 고르기'), radio('skip', '직접 고르기(고르기 전에는 제외)'),
          el('span', { class: 'hint', style: 'margin:0', text: '줄마다 보낼 것을 바꿀 수 있습니다.' })]) : null,
        el('div', { class: 'toolbar' }, [summary, el('span', { class: 'spacer' }),
          el('button', { type: 'button', class: 'small', title: '최종안이 아직 없는 학생만 체크합니다(덮어쓰기 없음)', text: '최종안 없는 학생만 선택', onclick: () => { studs.forEach((x) => { const c = classify(x); if (c.kind === 'new' || c.kind === 'over') pick.set(x.student_no, c.kind === 'new'); }); draw(); } }),
          el('button', { type: 'button', class: 'small', title: '보낼 수 있는 학생을 모두 체크합니다(최종안 있는 학생은 덮어씀)', text: '전체 선택', onclick: () => { studs.forEach((x) => { const c = classify(x); if (c.kind === 'new' || c.kind === 'over') pick.set(x.student_no, true); }); draw(); } }),
          el('button', { type: 'button', class: 'small', text: '선택 해제', onclick: () => { studs.forEach((x) => pick.set(x.student_no, false)); draw(); } })]),
        tbox,
      );
      sendBtn.addEventListener('click', () => runOnce(sendBtn, '보내는 중…', async (reqId) => {
        const picks = [];
        const overNames = [];
        studs.forEach((x) => { const c = classify(x); if (isOn(x, c)) { picks.push({ student_no: x.student_no, record_id: c.rec.id }); if (c.kind === 'over') overNames.push(x.name); } });
        if (!picks.length) return;
        if (overNames.length && !(await confirmBox(`${overNames.length}명의 지금 최종안을 기존 완성문으로 바꿉니다.\n${overNames.slice(0, 10).join(', ')}${overNames.length > 10 ? ` 외 ${overNames.length - 10}명` : ''}\n\n보낸 직후 [되돌리기]로 원래 최종안을 돌려놓을 수 있습니다. 계속할까요?`, '덮어쓰고 보내기'))) return;
        const r = await afterFinalSaved(() => mutate('finals_from_existing', gid, item, picks, reqId));
        if (!r) return;
        closeSheet();
        loadSlotStudents();
        actionToast(`${r.count}명 최종안으로 보냈습니다.`, '되돌리기', async () => {
          const u = await mutate('finals_bulk_undo');
          if (!u) return;
          toast(`${u.count}명 되돌렸습니다.${u.skipped ? ` 그 뒤 고치거나 마감한 ${u.skipped}명은 그대로 두었습니다.` : ''}`, 5000);
          loadSlotStudents();
        }, 30000);
      }));
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '기존 완성문 → 최종안 일괄' }), el('span', { class: 'muted', text: `${slotLabel} · 이 담당 명렬 전체` })]), body,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), sendBtn]));
      draw();
    });
  }

  // ---------- 검토·내보내기 ----------
  const E = { slotKey: null, rows: [] };
  async function renderExport() {
    if (!(await loadSlots())) return;
    const sel = $('expSlot');
    if (!E.slotKey || !R.slots.find((s) => slotKey(s) === E.slotKey)) E.slotKey = R.slot ? slotKey(R.slot) : (R.slots[0] && slotKey(R.slots[0]));
    fillSlotSelect(sel, E.slotKey);
    await loadExport();
  }
  // 검토·내보내기 표 열 너비: 기본은 글자 길이에 맞추고(남는 너비는 최종안), 머리 칸 오른쪽 끝을 끌어 바꿀 수 있다. 바꾼 너비는 기억한다.
  const EXP_COLW = 'sgb.expColW';
  const expColW = () => { try { return JSON.parse(localStorage.getItem(EXP_COLW) || '{}') || {}; } catch (e) { return {}; } };
  function expColResize(t) {
    const saved = expColW();
    t.querySelectorAll('th').forEach((th) => {
      const key = th.dataset.col;
      if (saved[key]) { th.style.width = `${saved[key]}px`; th.style.minWidth = `${saved[key]}px`; th.classList.add('sized'); }
      const grip = el('span', { class: 'col-grip', title: '끌어서 열 너비 바꾸기 · 두 번 누르면 원래대로' });
      grip.addEventListener('mousedown', (e) => {
        e.preventDefault();
        const x0 = e.clientX, w0 = th.getBoundingClientRect().width;
        document.body.classList.add('col-resizing');
        const move = (ev) => { const w = Math.max(36, Math.round(w0 + ev.clientX - x0)); th.style.width = `${w}px`; th.style.minWidth = `${w}px`; th.classList.add('sized'); };
        const up = () => {
          document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up);
          document.body.classList.remove('col-resizing');
          const all = expColW(); all[key] = Math.round(th.getBoundingClientRect().width);
          try { localStorage.setItem(EXP_COLW, JSON.stringify(all)); } catch (er) { /* 무시 */ }
        };
        document.addEventListener('mousemove', move); document.addEventListener('mouseup', up);
      });
      grip.addEventListener('dblclick', () => {
        th.style.width = ''; th.style.minWidth = ''; th.classList.remove('sized');
        const all = expColW(); delete all[key];
        try { localStorage.setItem(EXP_COLW, JSON.stringify(all)); } catch (er) { /* 무시 */ }
      });
      th.appendChild(grip);
    });
  }
  // 1·2학기 합산 과목 합쳐 보기: 생기부 조회 화면처럼 1학기 최종안, 빈 줄 하나, 2학기 최종안. 바이트는 두 학기 합(빈 줄 제외) / 합산.
  async function renderExportCombined(s, box) {
    const r = await call('export_combined', s.group_id, $('expScopeRows').value === 'closed', $('expOrder').value);
    if (!r) return;
    E.rows = [];
    const both = r.rows.filter((x) => x.closed).length;
    const over = r.rows.filter((x) => x.bytes > r.total).length;
    $('expSummary').textContent = `${r.first} + ${r.second} · ${r.rows.length}명 · 두 학기 모두 마감 ${both}${over ? ` · 합산 초과 ${over}` : ''} · 비활성 학생 제외`;
    const t = el('table', { class: 'tbl exp-tbl' });
    const cols = ['학년', '반', '번호', '이름', '상태', '최종안 (1학기 · 빈 줄 · 2학기)', '바이트'];
    t.appendChild(el('tr', {}, cols.map((h) => el('th', { class: h.startsWith('최종안') ? 'exp-main' : 'exp-fit', 'data-col': h.startsWith('최종안') ? '최종안' : h, text: h }))));
    expColResize(t);
    const stOf = (closed, text) => { const k = closed ? 'closed' : text ? 'final' : 'none'; return el('span', { class: `exp-st ${STATUS[k].cls}`, text: STATUS[k].icon }); };
    r.rows.forEach((x) => t.appendChild(el('tr', { class: x.closed ? '' : 'bad' }, [el('td', { text: x.grade ?? '' }), el('td', { text: x.class_no ?? '' }), el('td', { text: x.number ?? '' }), el('td', { text: x.name }),
      el('td', { title: `1학기 ${x.closed1 ? '마감' : x.text1 ? '미마감' : '최종안 없음'} · 2학기 ${x.closed2 ? '마감' : x.text2 ? '미마감' : '최종안 없음'}` }, ['1 ', stOf(x.closed1, x.text1), '  2 ', stOf(x.closed2, x.text2)]),
      el('td', {}, [el('div', { class: 'exp-text', text: x.text })]),
      el('td', { class: x.bytes > r.total ? 'danger-text' : '', title: `1학기 ${x.bytes1}B + 2학기 ${x.bytes2}B`, text: `${x.bytes}/${r.total}B` })])));
    if (!r.rows.length) t.appendChild(el('tr', {}, [el('td', { colspan: 7, class: 'muted', text: '보여 줄 학생이 없습니다.' })]));
    box.appendChild(t);
    $('expCopyBtn').textContent = '클립보드 복사';
    $('expXlsxBtn').textContent = 'xlsx 저장';
  }
  async function loadExport() {
    const s = R.slots.find((x) => slotKey(x) === E.slotKey);
    const box = $('expTable');
    box.innerHTML = '';
    if (!s) { box.appendChild(el('p', { class: 'muted', text: '담당이 없습니다.' })); return; }
    const r = await call('export_preview', s.group_id, s.item, $('expScopeRows').value === 'closed', $('expOrder').value);
    if (!r) return;
    $('expCombineWrap').hidden = !r.paired;
    const combine = r.paired && $('expCombine').checked;
    ['expCopyBtn', 'expXlsxBtn'].forEach((id) => { $(id).disabled = combine; $(id).title = combine ? '합쳐 보기는 확인용입니다. 내보내기는 합쳐 보기를 끄고 학기별로 하세요.' : ''; });
    if (combine) { renderExportCombined(s, box); return; }
    E.rows = r.rows;
    const closed = r.rows.filter((x) => x.closed).length;
    const empty = r.rows.filter((x) => !x.text).length;
    $('expSummary').textContent = `${r.rows.length}명 · 마감 ${closed} · 미마감 ${r.rows.length - closed} · 최종안 없음 ${empty}(빈칸) · 비활성 학생 제외`;
    const t = el('table', { class: 'tbl exp-tbl' });
    const paired = r.rows.some((x) => x.pair_total);
    const cols = ['학년', '반', '번호', '이름', '상태', '최종안', '바이트', ...(paired ? ['1학기 · 합계'] : [])];
    t.appendChild(el('tr', {}, cols.map((h) => el('th', { class: h === '최종안' ? 'exp-main' : 'exp-fit', 'data-col': h, text: h }))));
    expColResize(t);
    r.rows.forEach((x) => t.appendChild(el('tr', { class: x.closed ? '' : 'bad' }, [el('td', { text: x.grade ?? '' }), el('td', { text: x.class_no ?? '' }), el('td', { text: x.number ?? '' }), el('td', { text: x.name }),
      el('td', {}, [(() => { const k = x.closed ? 'closed' : x.text ? 'final' : 'none'; return el('span', { class: `exp-st ${STATUS[k].cls}`, title: x.closed ? '마감' : x.text ? '미마감(최종안 있음)' : '최종안 없음', text: `${STATUS[k].icon} ${x.closed ? '마감' : x.text ? '최종안' : '없음'}` }); })()]),
      el('td', {}, [el('div', { class: 'exp-text', text: x.text || '' })]), el('td', {}, [x.text ? bytesEl(x.bytes, x.target ?? r.target) : el('span', { class: 'muted', text: '-' })]),
      ...(paired ? [el('td', { class: (x.first_bytes || 0) + x.bytes > x.pair_total ? 'danger-text' : '', text: x.pair_total ? `${x.first_bytes ?? 0}B · ${(x.first_bytes || 0) + x.bytes}/${x.pair_total}B` : '' })] : [])])));
    if (!r.rows.length) t.appendChild(el('tr', {}, [el('td', { colspan: 7, class: 'muted', text: '내보낼 학생이 없습니다.' })]));
    box.appendChild(t);
    $('expCopyBtn').textContent = `클립보드 복사: ${r.rows.length}명`;
    $('expXlsxBtn').textContent = `xlsx 저장: ${r.rows.length}명`;
  }
  async function doExport(kind) {
    const s = R.slots.find((x) => slotKey(x) === E.slotKey);
    if (!s || !E.rows.length) { toast('내보낼 학생이 없습니다.'); return; }
    const onlyClosed = $('expScopeRows').value === 'closed';
    const open = E.rows.filter((x) => !x.closed).length;
    const over = E.rows.filter((x) => x.pair_total && x.text && (x.first_bytes || 0) + x.bytes > x.pair_total && (!onlyClosed || x.closed));
    if (over.length && !(await confirmBox(`1·2학기 합산 바이트를 넘는 학생이 ${over.length}명 있습니다.\n${over.slice(0, 10).map((x) => `${x.name} ${(x.first_bytes || 0) + x.bytes}/${x.pair_total}B`).join(', ')}${over.length > 10 ? ` 외 ${over.length - 10}명` : ''}\n\n그래도 내보낼까요?`, '그래도 내보내기'))) return;
    if (kind === 'copy') {
      const r = await call('export_copy', s.group_id, s.item, onlyClosed, $('expOrder').value, $('expCols').value, $('expHeader').checked);
      if (r) toast(`${r.count}명 최종안을 복사했습니다.${open ? ` (미마감 ${open}명 포함)` : ''}`);
    } else {
      const name = `${ys.year}_${s.label.replace(/[\\/:*?"<>|·]/g, ' ').replace(/\s+/g, '_')}.xlsx`;
      const r = await call('export_xlsx', s.group_id, s.item, onlyClosed, $('expOrder').value, $('expCols').value, name);
      if (r) alertBox(`저장했습니다. (${r.count}명${open ? `, 미마감 ${open}명은 노란색` : ''})\n${r.path}`);
    }
  }

  // ---------- 태그별 기록 ----------
  // 태그 하나를 고르면 그 태그가 붙은 기록을 학생 전부 한 화면에 모아 바로 고친다.
  // 저장: 칸을 벗어나거나 Ctrl+S. 기록마다 순서대로(앞 저장이 끝나야 다음). 화면을 연 뒤 다른 곳에서 바뀐 기록은 덮지 않는다(expect).
  // 되돌리기: 이 학년도에서 이 화면으로 고치기 전 값(undo.before)으로. 서버가 그 뒤 바뀌었거나 마감됐으면 거절한다.
  // 상태(기록 줄): 되돌리는 중 > 저장 중 > 저장 실패 > 저장 전 > 저장됨(되돌리기) — tvRowState로 매번 계산한다.
  const TV_ITEM_ICON = { autonomy: '🏫', career: '🧭', behavior: '💬', subject: '📘', club: '🎭' };
  const TV_FLT0 = () => ({ scope: '', slot: '', status: 'all', q: '', inactive: false });
  const TV = { tag: null, flt: TV_FLT0(), data: null, limit: 100, rec: new Map(), sel: new Set(), out: new Set(), queue: new Map(),
    undo: new Map(), ops: new Set(), slotUI: new Map(), seq: 0, cseq: 0, loading: false, year: null, anchor: null, bulk: null };
  const tvTagKey = () => `sgb.tv.tag.${ys.year}`;
  async function rawCall(method, ...args) {
    try { return await api[method](...args); } catch (e) { return { ok: false, error: String(e) }; }
  }
  const tvFields = (r) => ({ content: r.content, date: r.date || '', title: r.title || '', tag_ids: [...(r.tag_ids || r.tags || [])].sort((a, b) => a - b) });
  const sameVal = (k, a, b) => (k === 'tag_ids' ? JSON.stringify([...(a || [])].sort((x, y) => x - y)) === JSON.stringify([...(b || [])].sort((x, y) => x - y)) : (a || '').trim() === (b || '').trim());
  const sameAll = (cur, want) => Object.keys(want || {}).every((k) => sameVal(k, cur[k], want[k]));
  const slotKeyOf = (r) => `${r.group_id}:${r.item}:${r.student_no}`;
  function tvDiff(st) {
    const d = {};
    ['content', 'date', 'title', 'tag_ids'].forEach((k) => { if (!sameVal(k, st.draft[k], st.saved[k])) d[k] = st.draft[k]; });
    return d;
  }
  const tvHasDiff = (st) => Object.keys(tvDiff(st)).length > 0;
  function tvDirty() {
    if (TV.queue.size || TV.ops.size || twDirty()) return true;
    for (const st of TV.rec.values()) if (tvHasDiff(st)) return true;
    return false;
  }
  // 저장 대기·진행 중인 것과 되돌리기·일괄 작업을 모두 끝낸다. 남은 글이 있으면 false(화면을 바꾸지 않는다)
  async function flushTagView() {
    const twOk = await twFlush(); // 태그 AI 변환: 프롬프트 초안·고친 결과 저장
    const jobs = [...TV.ops];
    for (const [rid, st] of TV.rec) if (tvHasDiff(st) && !(st.err && st.err.code)) jobs.push(tvSave(rid));
    jobs.push(...TV.queue.values());
    await Promise.all(jobs);
    tvSaveSummary();
    for (const st of TV.rec.values()) if (tvHasDiff(st)) return false;
    return twOk;
  }
  // 기록 하나의 작업 줄(저장·되돌리기)에 이어 붙인다
  function tvEnqueue(rid, fn) {
    const prev = TV.queue.get(rid) || Promise.resolve();
    const p = prev.then(fn, fn);
    TV.queue.set(rid, p);
    p.finally(() => { if (TV.queue.get(rid) === p) TV.queue.delete(rid); const st = TV.rec.get(rid); if (st) tvMark(st); tvSaveSummary(); });
    return p;
  }
  function tvSave(rid) {
    const st = TV.rec.get(rid);
    if (st) { st.pending = true; tvMark(st); }
    return tvEnqueue(rid, () => tvSaveNow(rid));
  }
  async function tvSaveNow(rid) {
    const st = TV.rec.get(rid);
    if (!st) return;
    st.pending = false;
    const diff = tvDiff(st);
    if (!Object.keys(diff).length) return;
    const expect = {};
    Object.keys(diff).forEach((k) => { expect[k] = st.saved[k]; });
    const before = { ...st.saved };
    st.saving = true; tvMark(st); tvSaveSummary();
    const r = await rawCall('update_record', rid, { ...diff, expect, year: TV.year });
    st.saving = false;
    if (!r || r.ok === false) {
      st.err = { msg: (r && r.error) || '저장하지 못했습니다.', code: r && r.code };
      tvMark(st);
      return;
    }
    st.err = null;
    markSaved();
    const now = tvFields(r.record);
    // 칸마다 맞춘다: 저장하는 동안 손대지 않은 칸은 서버 값으로, 더 고친 칸은 고친 글을 그대로 둔다
    ['content', 'date', 'title', 'tag_ids'].forEach((k) => {
      const untouched = k in diff ? sameVal(k, st.draft[k], diff[k]) : sameVal(k, st.draft[k], before[k]);
      if (untouched) st.draft[k] = now[k];
    });
    // 되돌리기 기준: 처음 고치기 전 값(before)과 지금 저장된 값(after)
    const u = st.undo || { before: {}, after: {} };
    Object.keys(diff).forEach((k) => { if (!(k in u.before)) u.before[k] = before[k]; });
    Object.keys(u.before).forEach((k) => { if (sameVal(k, u.before[k], now[k])) delete u.before[k]; });
    u.after = {};
    Object.keys(u.before).forEach((k) => { u.after[k] = now[k]; });
    st.undo = Object.keys(u.before).length ? u : null;
    if (st.undo) TV.undo.set(rid, st.undo); else TV.undo.delete(rid);
    st.saved = now;
    tvApplyState(st, r.record);
  }
  // 서버의 기록 상태를 화면에 반영(태그·제외 예정·최종안 확인 필요)
  function tvApplyState(st, rec) {
    st.r.tags = [...st.saved.tag_ids];
    st.r.closed = !!rec.closed;
    tvSetSlotStale(slotKeyOf(st.r), !!rec.stale);
    tvOutCheck(st);
    if (st.sync) st.sync();
    tvMark(st);
    tvSaveSummary();
    tvRefreshCounts();
  }
  function tvOutCheck(st) {
    const id = st.r.id, tags = st.saved.tag_ids;
    const out = TV.tag === 0 ? tags.length > 0 : TV.tag ? !tags.includes(TV.tag) : false;
    if (out) TV.out.add(id); else TV.out.delete(id);
  }
  function tvSetSlotStale(key, stale) {
    for (const st of TV.rec.values()) if (slotKeyOf(st.r) === key) st.r.stale = stale;
    const ui = TV.slotUI.get(key);
    if (ui) ui.stale.hidden = !stale || ui.closed;
  }
  function tvUndo(rid) {
    const st = TV.rec.get(rid);
    if (!st || !st.undo || st.busy) return;
    st.busy = true; tvMark(st);
    return tvEnqueue(rid, async () => {
      const u = st.undo;
      const r = await rawCall('revert_record', rid, u.before, u.after, TV.year);
      st.busy = false;
      if (!r || r.ok === false) { tvMark(st); await alertBox((r && r.error) || '되돌리지 못했습니다.'); return; }
      markSaved();
      st.saved = tvFields(r.record); st.draft = { ...st.saved }; st.undo = null; st.err = null;
      TV.undo.delete(rid);
      tvApplyState(st, r.record);
      toast('이 화면에서 고치기 전 내용으로 되돌렸습니다.');
    });
  }
  // 충돌·마감으로 저장하지 못한 기록: 내 글을 복사해 두고 지금 저장된 내용을 불러온다
  async function tvDiscard(rid, copy) {
    const st = TV.rec.get(rid);
    if (!st) return;
    if (copy && !(await tvCopy(st.draft.content))) return;
    const r = await call('record_state', rid);
    if (!r) return;
    st.saved = tvFields(r.record); st.draft = { ...st.saved }; st.err = null; st.undo = null; TV.undo.delete(rid);
    st.r.closed = !!r.record.closed;
    const old = st.ui && st.ui.card;
    if (old && old.isConnected) old.replaceWith(tvRecordCard(st.r));
    tvApplyState(st, r.record);
  }
  async function tvCopy(text) {
    const r = await rawCall('copy_text', text);
    if (r && r.ok !== false) { toast('내 글을 클립보드에 복사했습니다.'); return true; }
    await alertBox('클립보드에 복사하지 못했습니다. 글상자의 내용을 직접 복사해 두세요.');
    return false;
  }
  function tvSaveSummary() {
    const box = $('tvSave');
    if (!box) return;
    let dirty = 0, fail = 0, busy = 0;
    for (const st of TV.rec.values()) {
      if (st.err) fail++;
      else if (st.saving || st.busy || st.pending) busy++;
      else if (tvHasDiff(st)) dirty++;
    }
    box.className = 'tv-save' + (fail ? ' bad' : busy || dirty || TV.ops.size ? ' busy' : '');
    box.textContent = fail ? `저장 실패 ${fail}건 — 빨간 기록을 확인하세요` : busy || TV.ops.size ? `저장 중 ${busy || ''}…` : dirty ? `저장 전 ${dirty}건 (칸을 벗어나거나 Ctrl+S)` : (TV.data ? '모두 저장됨' : '');
  }
  function tvRowState(st) {
    if (st.busy) return 'undoing';
    if (st.saving || st.pending) return 'saving';
    if (st.err) return 'fail';
    if (tvHasDiff(st)) return 'dirty';
    if (st.undo) return 'saved';
    return 'none';
  }
  function tvMark(st) {
    if (!st.ui) return;
    const state = tvRowState(st);
    const s = st.ui.state;
    s.innerHTML = '';
    st.ui.card.classList.toggle('save-fail', state === 'fail');
    const lockEdit = state === 'undoing';
    st.ui.ta.readOnly = !st.ui.can || lockEdit;
    if (state === 'undoing') s.append(el('span', { class: 'tv-st saving', text: '되돌리는 중…' }));
    else if (state === 'saving') s.append(el('span', { class: 'tv-st saving', text: '저장 중…' }));
    else if (state === 'fail') {
      const hard = st.err.code === 'conflict' || st.err.code === 'closed';
      s.append(el('span', { class: 'tv-st fail', text: `저장 못 함: ${st.err.msg}` }));
      if (hard) {
        s.append(el('button', { type: 'button', class: 'small', text: '내 글 복사', onclick: () => tvCopy(st.draft.content) }),
          el('button', { type: 'button', class: 'small', text: '내 글 복사 후 지금 내용 불러오기', onclick: () => tvDiscard(st.r.id, true) }));
      } else {
        s.append(el('button', { type: 'button', class: 'small', text: '다시 저장', onclick: () => { st.err = null; tvSave(st.r.id); } }),
          el('button', { type: 'button', class: 'small', text: '내 글 복사', onclick: () => tvCopy(st.draft.content) }));
      }
    } else if (state === 'dirty') s.append(el('span', { class: 'tv-st dirty', text: '저장 전' }));
    else if (state === 'saved') {
      s.append(el('span', { class: 'tv-st ok', text: '저장됨' }),
        el('button', { type: 'button', class: 'link', text: '되돌리기', title: '이 화면에서 고치기 전 내용으로 돌아갑니다(그 뒤 다른 곳에서 바뀌었거나 마감했으면 되돌리지 않습니다)', onclick: () => tvUndo(st.r.id) }));
    }
    const b = st.ui.badges;
    b.innerHTML = '';
    if (TV.out.has(st.r.id)) b.append(el('span', { class: 'badge tv-out', text: TV.tag === 0 ? '태그를 붙임 · 다음 조회 때 목록에서 빠짐' : '이 태그를 뺌 · 다음 조회 때 목록에서 빠짐' }));
    st.ui.bytes.textContent = `${bytesOf(st.draft.content)}B`;
  }
  function tvEditable(r) { return !ys.archived && !r.closed && r.active && !r.gone; }
  function tvLock(r) {
    if (r.closed) return { cls: 'closed', text: '● 마감됨 · 읽기 전용' };
    if (ys.archived) return { cls: 'other', text: '🔒 보관 학년도 · 읽기 전용' };
    if (!r.active || r.gone) return { cls: 'other', text: '🔒 비활성 학생 · 읽기 전용' };
    return null;
  }
  const tvAnyFilter = () => !!(TV.flt.scope || TV.flt.slot || TV.flt.status !== 'all' || TV.flt.q || TV.flt.inactive);
  // 조회: 가장 최근 요청의 응답만 반영한다. 조회하는 동안 목록은 고칠 수 없다. 실패하면 false
  async function renderTagView(keepScroll) {
    if (TV.year !== ys.year) {
      TV.year = ys.year; TV.data = null; TV.rec.clear(); TV.sel.clear(); TV.out.clear(); TV.undo.clear(); TV.flt = TV_FLT0(); TV.bulk = null; TV.anchor = null;
      if (TW.year !== ys.year) twReset();
      const saved = localStorage.getItem(tvTagKey()); TV.tag = saved === null || saved === '' ? null : +saved;
    }
    const seq = ++TV.seq, year = ys.year;
    const main = $('tvMain');
    const top = main.scrollTop;
    TV.loading = true; main.inert = true; main.classList.add('loading');
    const r = await rawCall('tag_view', TV.tag, { ...TV.flt });
    if (seq !== TV.seq || year !== ys.year) return false; // 더 새 조회가 있거나 학년도가 바뀜
    TV.loading = false; main.inert = false; main.classList.remove('loading');
    if (!r || r.ok === false) { await alertBox((r && r.error) || '불러오지 못했습니다.'); return false; }
    if (TV.tag && !r.tags.some((t) => t.id === TV.tag)) { TV.tag = null; return renderTagView(); }
    TV.data = r;
    TV.rec.clear(); TV.out.clear(); TV.slotUI.clear();
    const live = new Set(r.records.filter(tvEditable).map((x) => x.id));
    for (const id of [...TV.sel]) if (!live.has(id)) TV.sel.delete(id);
    r.records.forEach((x) => {
      const f = tvFields(x);
      const u = TV.undo.get(x.id);
      const undo = u && sameAll(f, u.after) ? u : null; // 다시 불러와도 되돌리기를 남긴다(그 뒤 바뀌었으면 버림)
      if (u && !undo) TV.undo.delete(x.id);
      TV.rec.set(x.id, { r: x, saved: f, draft: { ...f }, undo, err: null, ui: null });
    });
    tvRenderFilters();
    tvRenderTags();
    tvRenderMain();
    tvSaveSummary();
    if (keepScroll) main.scrollTop = top;
    if (TV.anchor) {
      const st = TV.rec.get(TV.anchor);
      TV.anchor = null;
      if (st && st.ui) { st.ui.card.scrollIntoView({ block: 'center' }); st.ui.card.classList.add('flash'); }
    }
    return true;
  }
  function tvRenderFilters() {
    const o = TV.data.options;
    const fill = (sel, groups, cur) => {
      sel.innerHTML = '';
      groups.forEach(([label, opts]) => {
        if (!label) { opts.forEach((x) => sel.appendChild(el('option', { value: x.key, text: x.label, selected: x.key === cur }))); return; }
        if (!opts.length) return;
        sel.appendChild(el('optgroup', { label }, opts.map((x) => el('option', { value: x.key, text: x.label, selected: x.key === cur }))));
      });
    };
    fill($('tvScope'), [['', [{ key: '', label: '전체' }]], ['학년-반 (그 반 학생의 모든 기록)', o.classes], ['수업 (그 과목·수업 기록만)', o.sections]], TV.flt.scope);
    fill($('tvSlot'), [['', [{ key: '', label: '전체' }]], ['항목', o.items], ['과목·동아리', o.slots]], TV.flt.slot);
    $('tvStatus').value = TV.flt.status;
    if (document.activeElement !== $('tvQ')) $('tvQ').value = TV.flt.q;
    $('tvInactive').checked = !!TV.flt.inactive;
    $('tvClear').hidden = !tvAnyFilter();
    const ts = $('tvTagSel');
    ts.innerHTML = '';
    ts.appendChild(el('option', { value: '', text: '태그 고르기', selected: TV.tag === null }));
    TV.data.tags.forEach((t) => ts.appendChild(el('option', { value: t.id, text: `${t.name} (${t.count}건)`, selected: t.id === TV.tag })));
    ts.appendChild(el('option', { value: '0', text: `태그 없음 (${TV.data.untagged}건)`, selected: TV.tag === 0 }));
  }
  function tvRenderTags() {
    const box = $('tvTags');
    const q0 = box.querySelector('input.search');
    const keepQ = q0 ? q0.value : '';
    box.innerHTML = '';
    const d = TV.data;
    const find = el('input', { type: 'search', class: 'search', placeholder: '태그 찾기', 'aria-label': '태그 찾기', value: keepQ });
    const list = el('div', { class: 'tv-taglist' });
    const draw = () => {
      list.innerHTML = '';
      const q = find.value.trim();
      d.tags.filter((t) => !q || t.name.includes(q)).forEach((t) => list.appendChild(el('button', { type: 'button', class: 'tv-tag' + (t.id === TV.tag ? ' active' : '') + (t.count ? '' : ' zero'), 'aria-pressed': t.id === TV.tag ? 'true' : 'false',
        onclick: () => tvPickTag(t.id) }, [el('span', { class: 'tdot' + tagC(t.id) }), el('span', { class: 'nm', text: t.name }), el('span', { class: 'cnt', text: `${t.count}건` })])));
      if (!d.tags.length) list.appendChild(el('p', { class: 'muted', text: '태그가 없습니다.' }));
    };
    find.addEventListener('input', draw);
    draw();
    box.append(el('div', { class: 'tv-tags-title', text: '태그' }), find, list,
      el('div', { class: 'tv-sep' }),
      el('button', { type: 'button', class: 'tv-tag untag' + (TV.tag === 0 ? ' active' : ''), 'aria-pressed': TV.tag === 0 ? 'true' : 'false', onclick: () => tvPickTag(0) }, [el('span', { class: 'nm', text: '태그 없음' }), el('span', { class: 'cnt', text: `${d.untagged}건` })]),
      el('p', { class: 'hint', text: '숫자는 위 필터를 적용한 기록 수입니다. 한 기록에 태그가 여럿이면 각각 셉니다.' }),
      el('button', { type: 'button', class: 'link', text: '태그 관리로 →', onclick: () => showPanel('tags') }));
    rawCall('tag_orphans', ys.year).then((o) => {
      if (!o || !o.ok || !o.works.length || !box.isConnected) return;
      box.append(el('div', { class: 'tv-sep' }), el('div', { class: 'tv-tags-title', text: '지운 태그의 AI 변환' }),
        ...o.works.map((w) => el('button', { type: 'button', class: 'tv-tag', title: '반영 기록 보기·되돌리기', onclick: () => twOrphanSheet(w) },
          [el('span', { class: 'nm', text: `${w.tag_name}(지움)` }), el('span', { class: 'cnt', text: `반영 ${w.live}건` })])));
    });
  }
  async function tvPickTag(id) {
    if (id === TV.tag) return;
    if (!(await leaveOk())) { if (TV.data) tvRenderFilters(); return; }
    const prev = TV.tag;
    TV.tag = id; TV.limit = 100; TW.plan = null; TW.review = null; TW.seq += 1;
    if (await renderTagView()) {
      if (TV.sel.size) toast('태그를 바꿔 선택을 풀었습니다.');
      TV.sel.clear(); TV.bulk = null; tvRenderBulk(); tvRenderSum();
      try { localStorage.setItem(tvTagKey(), String(id)); } catch (e) { /* 무시 */ }
    } else if (TV.seq && TV.tag === id) { TV.tag = prev; if (TV.data) { tvRenderFilters(); tvRenderTags(); } }
  }
  async function tvSetFilter(patch) {
    if (!(await leaveOk())) { if (TV.data) tvRenderFilters(); return; }
    const prev = { ...TV.flt };
    Object.assign(TV.flt, patch); TV.limit = 100; TW.plan = null; TW.seq += 1;
    if (await renderTagView()) {
      if (TV.sel.size) toast('조건을 바꿔 선택을 풀었습니다.');
      TV.sel.clear(); TV.bulk = null; tvRenderBulk(); tvRenderSum();
    } else if (JSON.stringify(TV.flt) === JSON.stringify({ ...prev, ...patch })) { TV.flt = prev; if (TV.data) tvRenderFilters(); }
  }
  async function tvRefreshCounts() {
    const seq = ++TV.cseq, year = ys.year;
    const r = await rawCall('tag_view', null, { ...TV.flt });
    if (seq !== TV.cseq || year !== ys.year || !r || r.ok === false || !TV.data) return;
    TV.data.tags = r.tags; TV.data.untagged = r.untagged;
    tvRenderTags();
    tvRenderFilters();
  }
  function tvRenderSum() {
    const d = TV.data, sum = $('tvSum');
    sum.innerHTML = '';
    if (!d || TV.tag === null) return;
    const name = TV.tag === 0 ? '태그 없음' : (d.tags.find((t) => t.id === TV.tag) || {}).name;
    const editable = d.records.filter(tvEditable).length;
    const shown = Math.min(TV.limit, d.records.length);
    if (TV.tag > 0) sum.appendChild(TW.open ? el('span', { class: 'badge', text: '🤖 AI 변환 중' }) : el('button', { type: 'button', class: 'small primary ai-btn', title: '이 태그 기록 한 건으로 프롬프트를 시험하고, 확정한 프롬프트로 나머지를 한꺼번에 변환합니다', text: '🤖 이 태그 AI 변환', onclick: () => twOpen() }));
    addTo(sum, el('b', { text: name }), ` · ${d.students}명 ${d.records.length}건`,
      el('span', { class: 'muted', text: ` (고칠 수 있음 ${editable}건 · 읽기 전용 ${d.records.length - editable}건) · ${shown}/${d.records.length}건 표시` }),
      editable ? el('button', { type: 'button', class: 'small', text: `이 조건 모두 선택 (${editable}건)`, title: '지금 필터에 맞는 기록 중 고칠 수 있는 것을 모두 고릅니다(더 보기 아래 기록 포함)', onclick: () => tvSelectAll(true) }) : null,
      (() => { const yet = d.records.filter((r) => tvEditable(r) && !r.has_final).length; return editable ? el('button', { type: 'button', class: 'small', disabled: !yet, title: '최종안이 아직 없는 학생(항목)의 기록만 고릅니다', text: `최종안 없는 학생 기록만 선택 (${yet}건)`, onclick: () => tvSelectAll(true, (r) => !r.has_final) }) : null; })());
    if (TV.bulk) {
      const b = TV.bulk;
      sum.append(el('span', { class: 'tv-bulk-note' }, [`최근 일괄 작업: ${b.text} `, el('button', { type: 'button', class: 'link', text: '되돌리기', onclick: () => tvBulkUndo() })]));
    }
    sum.append(el('span', { class: 'tv-note', text: '이 태그가 붙은 기록만 보입니다(학생별 미입력 현황이 아님). 기록을 고쳐도 최종안 문장은 자동으로 바뀌지 않습니다. [되돌리기]는 이 학년도에서 이 화면을 쓰는 동안 남습니다.' }));
  }
  function tvClassOf(r) {
    if (!r.grade || !r.class_no) return { key: 'c:-', label: '반 정보 없음' };
    return { key: `c:${r.grade}-${r.class_no}`, label: `${r.grade}학년 ${r.class_no}반` };
  }
  function tvSrcLabel(r) {
    const it = ITEM_LABELS[r.item];
    if (r.gkind === 'subject') return `${it} · ${r.group_name}${r.semester ? `(${r.semester}학기)` : ''}`;
    return `${it} · ${r.group_name}`;
  }
  function tvRenderMain(focusFrom) {
    const main = $('tvMain');
    main.innerHTML = '';
    TV.slotUI.clear();
    const d = TV.data;
    tvRenderSum();
    if (TW.open && TV.tag) { // 태그 AI 변환 작업 영역
      $('tvBulk').hidden = true;
      if (TW.tag !== TV.tag) { main.appendChild(el('p', { class: 'muted', text: '불러오는 중…' })); twLoad().then((ok) => { if (ok) twRender(); else tvRenderMain(); }); return; }
      twRender();
      return;
    }
    if (TW.open && !TV.tag) TW.open = false;
    if (TV.tag === null) {
      main.appendChild(el('div', { class: 'empty-state' }, [el('p', { text: d.tags.length ? '태그를 고르세요. 그 태그가 붙은 기록이 학생 전부 한 화면에 모입니다.' : '아직 태그가 없습니다. 태그 관리에서 먼저 만드세요.' }),
        d.tags.length ? null : el('button', { type: 'button', class: 'primary', text: '태그 관리', onclick: () => showPanel('tags') })]));
      tvRenderBulk();
      return;
    }
    const recs = d.records.slice(0, TV.limit);
    if (!d.records.length) {
      const total = TV.tag === 0 ? d.untagged : ((d.tags.find((t) => t.id === TV.tag) || {}).count || 0);
      main.appendChild(el('div', { class: 'empty-state' }, [
        el('p', { text: tvAnyFilter() ? '필터 조건에 맞는 기록이 없습니다.' : total === 0 && TV.tag !== 0 ? '이 태그가 붙은 기록이 아직 없습니다. 기록에 태그를 붙이면 여기에 모입니다.' : '기록이 없습니다.' }),
        tvAnyFilter() ? el('button', { type: 'button', text: '필터 지우기', onclick: () => tvSetFilter(TV_FLT0()) }) : null,
        !TV.flt.inactive ? el('p', { class: 'hint', text: '비활성 학생의 기록은 [비활성 포함]을 켜야 보입니다.' }) : null]));
      tvRenderBulk();
      return;
    }
    // 학년-반 → 학생 → 담당(항목) → 기록
    const total = {}, shownPer = {}, clsCount = {};
    d.records.forEach((r) => { total[r.student_no] = (total[r.student_no] || 0) + 1; const k = tvClassOf(r).key; clsCount[k] = clsCount[k] || { n: 0, s: new Set() }; clsCount[k].n++; clsCount[k].s.add(r.student_no); });
    recs.forEach((r) => { shownPer[r.student_no] = (shownPer[r.student_no] || 0) + 1; });
    let cls = null, stu = null, slot = null, clsBox = null, stuBox = null, slotBox = null;
    let focusEl = null;
    recs.forEach((r, i) => {
      const c = tvClassOf(r);
      if (c.key !== cls) {
        cls = c.key; stu = null;
        const fk = `tv:${c.key}`;
        const box = el('div', { class: 'tv-class' + (fold[fk] ? ' folded' : ''), style: `--gc:${groupColor(c.key)}` });
        const cc = clsCount[c.key];
        const arrow = el('span', { text: `${fold[fk] ? '▸' : '▾'} ${c.label}` });
        const head = el('button', { type: 'button', class: 'tv-class-head', 'aria-expanded': fold[fk] ? 'false' : 'true', title: fold[fk] ? '펼치기' : '접기' },
          [arrow, el('span', { class: 'cnt', text: `학생 ${cc.s.size}명 · 기록 ${cc.n}건` })]);
        head.addEventListener('click', () => {
          setFold(fk, !fold[fk]);
          box.classList.toggle('folded', !!fold[fk]);
          arrow.textContent = `${fold[fk] ? '▸' : '▾'} ${c.label}`;
          head.setAttribute('aria-expanded', fold[fk] ? 'false' : 'true');
          head.title = fold[fk] ? '펼치기' : '접기';
        });
        box.appendChild(head);
        main.appendChild(box);
        clsBox = box;
      }
      if (r.student_no !== stu) {
        stu = r.student_no; slot = null;
        const part = shownPer[r.student_no] < total[r.student_no] ? ` (표시 ${shownPer[r.student_no]}/${total[r.student_no]}건 — 나머지는 아래 [다음 100건 보기])` : '';
        stuBox = el('div', { class: 'tv-stu' }, [el('div', { class: 'tv-stu-head' }, [
          el('b', { text: `${r.student_no} ${r.name}` }), r.active && !r.gone ? null : el('span', { class: 'badge', text: '비활성' }),
          el('span', { class: 'muted', text: `이 태그 기록 ${total[r.student_no]}건${part}` })])]);
        clsBox.appendChild(stuBox);
      }
      const sk = `${r.group_id}:${r.item}`;
      if (sk !== slot) {
        slot = sk;
        const st = STATUS[r.status] || STATUS.none;
        const stale = el('span', { class: 'badge tv-stale', text: '최종안 확인 필요', title: '기록이 바뀌었습니다. 이 항목에서 열어 최종안을 확인하세요.', hidden: !(r.stale && !r.closed) });
        TV.slotUI.set(slotKeyOf(r), { stale, closed: r.closed });
        slotBox = el('div', { class: 'tv-slot' + (r.closed ? ' is-closed' : '') }, [el('div', { class: 'tv-slot-head' }, [
          el('span', { class: `tv-src it-${r.item}`, text: `${TV_ITEM_ICON[r.item] || ''} ${tvSrcLabel(r)}` }),
          r.gkind === 'subject' && r.section ? el('span', { class: 'muted', text: `수업: ${r.section}` }) : null,
          el('span', { class: `tv-stat ${st.cls}`, title: '이 항목의 상태', text: `${st.icon} ${st.text}` }),
          stale,
          el('span', { class: 'spacer' }),
          el('button', { type: 'button', class: 'link', text: '이 항목에서 열기 ↗', title: '항목별 기록에서 이 학생의 이 항목을 엽니다. 돌아오면 이 자리로 옵니다.',
            onclick: () => { TV.anchor = r.id; R.highlight = r.id; openRecords(r.group_id, r.item, r.student_no); } })])]);
        stuBox.appendChild(slotBox);
      }
      const card = tvRecordCard(r);
      slotBox.appendChild(card);
      if (focusFrom !== undefined && i === focusFrom) focusEl = card;
    });
    if (d.records.length > recs.length) {
      const from = recs.length;
      main.appendChild(el('button', { type: 'button', class: 'tv-more', text: `전체 결과 중 다음 100건 보기 (남은 ${d.records.length - recs.length}건)`,
        onclick: async () => { if (!(await leaveOk())) return; TV.limit += 100; tvRenderMain(from); } }));
    }
    if (focusEl) { focusEl.scrollIntoView({ block: 'start' }); const ta = focusEl.querySelector('textarea'); if (ta) ta.focus({ preventScroll: true }); }
    tvRenderBulk();
  }
  function tvRecordCard(r) {
    const st = TV.rec.get(r.id);
    const can = tvEditable(r);
    const who = `${r.name} · ${tvSrcLabel(r)}${r.seq ? ` · ${r.seq}회` : r.kind === 'existing' ? ' · 기존 완성문' : ''}`;
    const card = el('div', { class: 'tv-rec' + (can ? '' : ' locked') + (TV.sel.has(r.id) ? ' sel' : ''), 'data-rid': r.id });
    const cb = can ? el('input', { type: 'checkbox', class: 'tv-pick', checked: TV.sel.has(r.id), title: '여러 기록 태그 작업에 고르기', 'aria-label': `${who} 기록 고르기` }) : null;
    if (cb) cb.addEventListener('change', () => { cb.checked ? TV.sel.add(r.id) : TV.sel.delete(r.id); card.classList.toggle('sel', cb.checked); tvRenderBulk(); });
    const metaStr = () => [r.kind === 'existing' ? '기존 완성문' : (r.seq ? `${r.seq}회` : ''), st.draft.date, st.draft.title].filter(Boolean).join(' · ') || '(활동명·날짜 없음)';
    const metaText = el('span', { class: 'tv-meta', text: metaStr() });
    const ta = el('textarea', { class: 'tv-ta', rows: 2, 'aria-label': `${who} 내용` });
    ta.value = st.draft.content;
    ta.readOnly = !can;
    const fit = () => { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight + 2, 420) + 'px'; };
    requestAnimationFrame(fit);
    ta.addEventListener('input', () => { if (ta.readOnly) return; st.draft.content = ta.value; fit(); tvMark(st); tvSaveSummary(); });
    ta.addEventListener('blur', () => { if (tvHasDiff(st) && !(st.err && st.err.code)) tvSave(r.id); });
    // 날짜·활동명: 펼쳐서 고친다
    const metaEdit = el('div', { class: 'tv-meta-edit', hidden: true });
    let di = null, ti = null;
    if (can && r.kind !== 'existing') {
      di = el('input', { type: 'date', value: st.draft.date || '', 'aria-label': `${who} 날짜` });
      ti = el('input', { type: 'text', value: st.draft.title || '', placeholder: '활동명', 'aria-label': `${who} 활동명` });
      di.addEventListener('change', () => { st.draft.date = di.value; metaText.textContent = metaStr(); tvMark(st); tvSave(r.id); });
      ti.addEventListener('input', () => { st.draft.title = ti.value; metaText.textContent = metaStr(); tvMark(st); tvSaveSummary(); });
      ti.addEventListener('blur', () => { if (tvHasDiff(st) && !(st.err && st.err.code)) tvSave(r.id); });
      metaEdit.append(el('label', { class: 'inline' }, ['날짜 ', di]), el('label', { class: 'inline grow' }, ['활동명 ', ti]));
    }
    // 태그 칩
    const chips = el('div', { class: 'tv-chips' });
    const drawChips = () => {
      chips.innerHTML = '';
      const names = new Map((TV.data.tags || []).map((t) => [t.id, t.name]));
      const off = !can || st.busy;
      st.draft.tag_ids.forEach((tid) => chips.appendChild(el('span', { class: 'tag' + tagC(tid) + (tid === TV.tag ? ' cur' : '') }, [names.get(tid) || '(지운 태그)',
        off ? null : el('button', { type: 'button', class: 'x', text: '×', title: `이 기록에서 '${names.get(tid)}' 태그만 빼기`, 'aria-label': `${who}에서 ${names.get(tid)} 태그만 빼기`,
          onclick: () => { st.draft.tag_ids = st.draft.tag_ids.filter((x) => x !== tid); drawChips(); tvSave(r.id); } })])));
      if (!off) {
        const rest = (TV.data.tags || []).filter((t) => !st.draft.tag_ids.includes(t.id));
        if (rest.length) {
          const add = el('select', { class: 'tv-addtag', 'aria-label': `${who}에 태그 더하기` }, [el('option', { value: '', text: '+ 태그' }), ...rest.map((t) => el('option', { value: t.id, text: t.name }))]);
          add.addEventListener('change', () => { if (!add.value) return; st.draft.tag_ids = [...st.draft.tag_ids, +add.value]; drawChips(); tvSave(r.id); });
          chips.appendChild(add);
        }
      }
      if (!st.draft.tag_ids.length && !can) chips.appendChild(el('span', { class: 'muted', text: '태그 없음' }));
    };
    drawChips();
    const state = el('span', { class: 'tv-state', 'aria-live': 'polite' });
    const badges = el('span', { class: 'tv-badges' });
    const bytes = el('span', { class: 'muted tv-bytes' });
    const lock = tvLock(r);
    card.append(el('div', { class: 'tv-rec-head' }, [cb, metaText,
      can && r.kind !== 'existing' ? el('button', { type: 'button', class: 'link', text: '날짜·활동명 수정', 'aria-label': `${who} 날짜·활동명 수정`, onclick: () => { metaEdit.hidden = !metaEdit.hidden; if (!metaEdit.hidden) ti.focus(); } }) : null,
      lock ? el('span', { class: `tv-lock ${lock.cls}`, text: lock.text }) : null, el('span', { class: 'spacer' }), badges, bytes]),
    metaEdit, ta, el('div', { class: 'tv-rec-foot' }, [chips, el('span', { class: 'spacer' }), state]));
    st.ui = { card, state, badges, bytes, ta, can };
    // 저장 응답·되돌리기·일괄 작업 뒤 화면을 고친 글(draft)에 맞춘다. 지금 쓰고 있는 칸은 건드리지 않는다
    st.sync = () => {
      if (document.activeElement !== ta && ta.value !== st.draft.content) { ta.value = st.draft.content; fit(); }
      if (di && document.activeElement !== di && di.value !== (st.draft.date || '')) di.value = st.draft.date || '';
      if (ti && document.activeElement !== ti && ti.value !== (st.draft.title || '')) ti.value = st.draft.title || '';
      metaText.textContent = metaStr();
      if (!chips.contains(document.activeElement)) drawChips();
    };
    tvMark(st);
    return card;
  }
  function tvRenderBulk() {
    const bar = $('tvBulk');
    bar.innerHTML = '';
    if (!TV.sel.size || !TV.data) { bar.hidden = true; return; }
    bar.hidden = false;
    const recs = TV.data.records.filter((r) => TV.sel.has(r.id));
    const n = new Set(recs.map((r) => r.student_no)).size;
    const tagSel = (ph) => el('select', { 'aria-label': ph }, [el('option', { value: '', text: ph }), ...TV.data.tags.map((t) => el('option', { value: t.id, text: t.name }))]);
    const addSel = tagSel('태그 더하기…'), rmSel = tagSel('태그 빼기…');
    addSel.addEventListener('change', () => tvBulkRun(addSel, 'add', n));
    rmSel.addEventListener('change', () => tvBulkRun(rmSel, 'remove', n));
    const titleIn = el('input', { type: 'text', class: 'tv-bulk-in', placeholder: '활동명', 'aria-label': '고른 기록에 넣을 활동명' });
    const dateIn = el('input', { type: 'date', class: 'tv-bulk-in', 'aria-label': '고른 기록에 넣을 날짜' });
    const setTitle = el('button', { type: 'button', text: '활동명 바꾸기', onclick: () => tvBulkField('title', titleIn.value, n) });
    titleIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') setTitle.click(); });
    bar.append(el('b', { text: `선택 ${n}명 ${recs.length}건` }), el('span', { class: 'muted', text: '(고칠 수 있는 기록만 고를 수 있습니다)' }), addSel, rmSel,
      el('span', { class: 'tv-bulk-grp' }, [titleIn, setTitle]),
      el('span', { class: 'tv-bulk-grp' }, [dateIn, el('button', { type: 'button', text: '날짜 바꾸기', onclick: () => tvBulkField('date', dateIn.value, n) }),
        el('button', { type: 'button', class: 'link', text: '날짜 비우기', onclick: () => tvBulkField('date', '', n) })]),
      el('button', { type: 'button', text: '선택 해제', onclick: () => tvSelectAll(false) }),
      el('button', { type: 'button', class: 'danger-text', text: `선택 기록 삭제`, onclick: () => tvBulkDelete(recs, n) }));
  }
  // 이 조건(태그·필터)의 고칠 수 있는 기록 모두 고르기 / 모두 풀기 — 아직 그리지 않은(더 보기 아래) 기록도 포함
  function tvSelectAll(on, only) {
    TV.sel.clear();
    if (on) TV.data.records.filter((r) => tvEditable(r) && (!only || only(r))).forEach((r) => TV.sel.add(r.id));
    document.querySelectorAll('#tvMain .tv-rec').forEach((c) => {
      const pick = TV.sel.has(+c.dataset.rid);
      c.classList.toggle('sel', pick);
      const x = c.querySelector('input.tv-pick');
      if (x) x.checked = pick;
    });
    tvRenderBulk();
    if (on) toast(`${TV.sel.size}건을 골랐습니다. 아래 줄에서 태그를 더하거나 빼거나 지울 수 있습니다.`);
  }
  // 고른 기록 지우기(되돌릴 수 없음 → '확인했어요')
  async function tvBulkDelete(recs, n) {
    if (!(await leaveOk())) return;
    const msg = [`고른 기록 ${n}명 ${recs.length}건을 지웁니다.`,
      '· 기록에 딸린 정제 후보도 함께 지워집니다.',
      '· 이미 만든 최종안 문장은 자동으로 바뀌지 않습니다(다시 만들기 표시가 붙습니다).'].join('\n');
    if (!(await typedConfirm(msg, '선택 기록 삭제'))) return;
    const r = await tvOp(() => mutate('delete_records', recs.map((x) => x.id), TYPED_WORD, TV.year));
    if (!r) return;
    TV.sel.clear(); TV.bulk = null;
    toast(`${r.students}명 ${r.deleted}건을 지웠습니다.`);
    await renderTagView(true);
  }
  // 일괄 태그: 목록을 다시 불러오지 않고 바뀐 기록만 고친다(개별 되돌리기·제외 예정 표시 유지)
  function tvApplyStates(states, keys) {
    Object.entries(states || {}).forEach(([rid, rec]) => {
      const st = TV.rec.get(+rid);
      if (!st) return;
      const now = tvFields(rec);
      (keys || ['tag_ids']).forEach((k) => {
        if (sameVal(k, st.draft[k], st.saved[k])) st.draft[k] = now[k];
        st.saved[k] = now[k];
        if (st.undo && k in st.undo.after) st.undo.after[k] = now[k];
        if (k === 'title' || k === 'date') st.r[k] = now[k];
      });
      tvApplyState(st, rec);
    });
  }
  async function tvOp(fn) {
    const main = $('tvMain');
    const p = (async () => { main.inert = true; try { return await fn(); } finally { main.inert = false; } })();
    TV.ops.add(p);
    tvSaveSummary();
    try { return await p; } finally { TV.ops.delete(p); tvSaveSummary(); }
  }
  async function tvBulkRun(sel, mode, n) {
    if (!sel.value) return;
    const tid = +sel.value, tname = sel.selectedOptions[0].textContent;
    sel.value = '';
    if (!(await leaveOk())) return;
    const ids = [...TV.sel];
    const r = await tvOp(() => mutate('tag_records_undoable', ids, [tid], mode, TV.year));
    if (!r) return;
    tvApplyStates(r.states);
    TV.bulk = { text: `${n}명 ${ids.length}건 중 ${r.pairs.length}건에 '${tname}' 태그 ${mode === 'add' ? '더함' : '뺌'}`, pairs: r.pairs, mode };
    tvRenderSum();
    toast(`${TV.bulk.text}. 위 요약 줄의 [되돌리기]로 취소할 수 있습니다.`);
  }
  // 고른 기록의 활동명·날짜를 한꺼번에 같은 값으로(되돌리기 가능)
  async function tvBulkField(field, value, n) {
    const v = (value || '').trim();
    const name = field === 'title' ? '활동명' : '날짜';
    if (field === 'title' && !v && !(await confirmBox('활동명을 비웁니다. 고른 기록의 활동명이 모두 지워집니다.', '비우기'))) return;
    if (!(await leaveOk())) return;
    const ids = [...TV.sel];
    const r = await tvOp(() => mutate('records_set_field', ids, field, v, TV.year));
    if (!r) return;
    tvApplyStates(r.states, [field]);
    const shown = field === 'date' && v ? md(v) : v;
    TV.bulk = { text: `${n}명 ${ids.length}건 중 ${r.pairs.length}건 ${name} ${v ? `'${shown}'(으)로 바꿈` : '비움'}`, pairs: r.pairs, mode: 'field', field };
    tvRenderSum();
    toast(r.pairs.length ? `${TV.bulk.text}. 위 요약 줄의 [되돌리기]로 취소할 수 있습니다.` : `바뀐 기록이 없습니다(이미 같은 ${name}이거나 마감·비활성).`, 5000);
  }
  async function tvBulkUndo() {
    const b = TV.bulk;
    if (!b) return;
    if (!(await leaveOk())) return;
    if (b.mode === 'field') {
      const u = await tvOp(() => mutate('undo_records_field', b.pairs, b.field, TV.year));
      if (!u) return;
      tvApplyStates(u.states, [b.field]);
      TV.bulk = null;
      tvRenderSum();
      const why = [u.changed ? `${u.changed}건은 그 뒤 다시 바뀌어` : '', u.skipped - u.changed ? `${u.skipped - u.changed}건은 마감·삭제되어` : ''].filter(Boolean).join(', ');
      toast(why ? `${u.done}건을 되돌렸습니다. ${why} 건너뛰었습니다.` : `${u.done}건을 되돌렸습니다.`, why ? 6000 : 3000);
      return;
    }
    const u = await tvOp(() => mutate('undo_tag_records', b.pairs, b.mode, TV.year));
    if (!u) return;
    tvApplyStates(u.states);
    TV.bulk = null;
    tvRenderSum();
    const why = [u.changed ? `${u.changed}건은 그 뒤 태그가 다시 바뀌어` : '', u.skipped - u.changed ? `${u.skipped - u.changed}건은 마감·삭제되어` : ''].filter(Boolean).join(', ');
    toast(why ? `${u.done}건을 되돌렸습니다. ${why} 건너뛰었습니다.` : `${u.done}건을 되돌렸습니다.`, why ? 6000 : 3000);
  }

  // ---------- 태그 AI 변환(태그별 기록 › [이 태그 AI 변환]) — docs/plan/tag-flow.md ----------
  // ① 프롬프트 적용 시험: 기록 한 건으로 프롬프트를 바꿔 가며 후보 3칸 → ✔ 확정(그 기록에 반영 + 단계가 태그 설정)
  // ② 나머지 변환: 확정 단계를 대상마다 그대로 재현(결과는 후보, 기록은 아직 안 바뀜)
  // ③ 검토·반영: 체크한 것만 기록에 반영, 반영 묶음 되돌리기
  const TW = { open: false, tag: null, year: null, seq: 0, step: 'trial', work: null, trials: [], batches: [], runs: [], rid: null, src: 'original', req: '',
    lib: null, plan: null, planFlt: null, pick: new Set(), review: null, reviewRun: null, rfilter: 'all', saving: new Set(), draftTimer: null, draftDirty: false, cont: null,
    edits: new Map(), editTimers: new Map(), editChain: new Map(), lastApplied: [] };
  // 학년도가 바뀌면 태그 변환 상태를 모두 버린다(학년도마다 id가 겹침)
  function twReset() {
    TW.draftTimer && clearTimeout(TW.draftTimer);
    TW.editTimers.forEach((t) => clearTimeout(t));
    Object.assign(TW, { open: false, tag: null, year: null, work: null, trials: [], batches: [], runs: [], rid: null, plan: null, planFlt: null, review: null, reviewRun: null,
      draftTimer: null, draftDirty: false, draftVer: 0, draftChain: null, cont: null, lastApplied: [] });
    TW.edits.clear(); TW.editTimers.clear(); TW.editChain.clear(); TW.pick.clear(); TW.seq += 1;
  }
  const twDirty = () => TW.draftDirty || TW.edits.size > 0;
  const TW_STEPS = [['trial', '① 프롬프트 적용 시험'], ['bulk', '② 나머지 변환'], ['review', '③ 검토·반영']];
  function twTrack(p) { TW.saving.add(p); p.finally(() => TW.saving.delete(p)); return p; }
  // 프롬프트 초안·고친 결과를 저장한다. 하나라도 저장하지 못했으면 false(이동·반영·종료를 막음, 글은 화면에 남김)
  async function twFlush() {
    if (TW.draftTimer) { clearTimeout(TW.draftTimer); TW.draftTimer = null; }
    if (TW.draftDirty) twTrack(twSaveDraft());
    TW.editTimers.forEach((t) => clearTimeout(t)); TW.editTimers.clear();
    [...TW.edits.keys()].forEach((cid) => twTrack(twSaveEdit(cid)));
    await Promise.all([...TW.saving]);
    return !twDirty();
  }
  // 고친 결과 저장: 후보마다 순서대로(늦게 온 응답이 새 글을 덮지 않게)
  function twSaveEdit(cid) {
    const prev = TW.editChain.get(cid) || Promise.resolve();
    const p = prev.then(async () => {
      if (!TW.edits.has(cid)) return;
      const text = TW.edits.get(cid), year = TW.year;
      const r = await rawCall('tag_cand_edit', cid, text, year);
      if (r && r.ok) { if (TW.edits.get(cid) === text) TW.edits.delete(cid); const c = twFindCand(cid); if (c) c.edited = text.trim() === (c.text || '').trim() ? null : text; }
      else toast(`고친 결과를 저장하지 못했습니다: ${(r && r.error) || '알 수 없는 오류'}. 글은 화면에 남아 있으니 다시 시도하세요.`, 7000);
    });
    TW.editChain.set(cid, p);
    return p;
  }
  function twFindCand(cid) { const rows = TW.review ? TW.review.rows : []; const x = rows.find((y) => y.cand && y.cand.id === cid); return x ? x.cand : null; }
  async function twFlushOrWarn() {
    if (await twFlush()) return true;
    await alertBox('프롬프트 초안이나 고친 결과를 저장하지 못했습니다. 글은 화면에 남아 있습니다.\n잠시 뒤 다시 시도하거나, 필요하면 글을 복사해 두세요.');
    return false;
  }
  // 다른 화면에서 태그 AI 변환으로 바로 가기(인박스 보내기 뒤·현황판)
  async function goTagWork(tagId, slot, step, scope) {
    if (!(await leaveOk())) return;
    if (TV.year !== ys.year) { TV.year = ys.year; TV.data = null; TV.rec.clear(); TV.sel.clear(); TV.out.clear(); TV.undo.clear(); TV.bulk = null; TV.anchor = null; }
    if (TW.year !== ys.year) twReset();
    TV.tag = tagId; TV.flt = { ...TV_FLT0(), slot: slot || '', scope: scope || '' }; TV.limit = 100;
    try { localStorage.setItem(tvTagKey(), String(tagId)); } catch (e) { /* 무시 */ }
    TW.open = true; TW.step = step || 'trial'; TW.tag = null; TW.plan = null; TW.review = null;
    showPanel('tagrec');
  }
  async function twOpen(step) {
    if (!TV.tag) return;
    if (!(await leaveOk())) return;
    TW.open = true; TW.step = step || 'trial';
    await twLoad();
    tvRenderMain();
  }
  async function twClose() {
    if (!(await twFlushOrWarn())) return;
    TW.open = false; TW.plan = null; TW.review = null;
    AI_ASK_SKIP.delete('tw');
    tvRenderMain();
  }
  async function twLoad() {
    if (TW.year !== ys.year) { twReset(); TW.open = true; }
    const seq = ++TW.seq, tag = TV.tag, year = ys.year;
    const r = await rawCall('tag_work', tag, year);
    if (seq !== TW.seq || tag !== TV.tag || year !== ys.year) return false; // 더 새 요청이 있음
    if (!r || r.ok === false) { await alertBox((r && r.error) || '불러오지 못했습니다.'); TW.open = false; return false; }
    if (!r.work) { await alertBox('보관 학년도에서는 새 태그 변환을 시작할 수 없습니다(조회만 가능).'); TW.open = false; return false; }
    if (TW.tag !== tag) { TW.rid = null; TW.plan = null; TW.review = null; TW.reviewRun = null; TW.cont = null; TW.req = ''; TW.lastApplied = []; }
    const keepDraft = TW.draftDirty && TW.work && TW.work.id === r.work.id ? TW.work.draft : null; // 아직 저장 못 한 초안은 덮지 않음
    TW.year = year; TW.tag = tag; TW.work = r.work; TW.progress = r.progress;
    if (keepDraft) TW.work.draft = keepDraft; TW.trials = r.trials; TW.batches = r.batches; TW.runs = r.runs;
    if (!TW.lib) { const l = await rawCall('prompt_list'); TW.lib = l && l.ok ? l.prompts : []; }
    if (!TW.work.draft || !TW.work.draft.prompt) { // 처음: 기본 프롬프트에서 시작
      const base = TW.lib.find((p) => p.id === 'default') || TW.lib[0];
      if (base) TW.work.draft = { prompt: base.prompt, example: base.example || '', lib_id: base.id, lib_name: base.name };
    }
    const recs = TV.data ? TV.data.records : [];
    if (!recs.some((x) => x.id === TW.rid)) {
      const withTrial = TW.trials.length ? TW.trials[TW.trials.length - 1].record_id : null;
      const first = recs.find((x) => x.id === withTrial) || recs.find((x) => tvEditable(x) && x.kind === 'record') || null;
      TW.rid = first ? first.id : null;
    }
    return true;
  }
  // 프롬프트 초안 저장: 차례대로(늦게 끝난 옛 저장이 새 글을 덮지 않게), 마지막 고친 글이 저장돼야 깨끗함
  function twSaveDraft() {
    TW.draftChain = (TW.draftChain || Promise.resolve()).then(async () => {
      if (!TW.work || !TW.draftDirty) return;
      const ver = TW.draftVer || 0, draft = TW.work.draft, wid = TW.work.id, year = TW.year;
      const r = await rawCall('tag_draft_save', wid, draft, year);
      if (r && r.ok) { if ((TW.draftVer || 0) === ver) TW.draftDirty = false; }
      else toast(`프롬프트 초안을 저장하지 못했습니다: ${(r && r.error) || '알 수 없는 오류'}. 글은 화면에 남아 있습니다.`, 7000);
    });
    return TW.draftChain;
  }
  function twDraftChanged() {
    TW.draftDirty = true; TW.draftVer = (TW.draftVer || 0) + 1;
    if (TW.draftTimer) clearTimeout(TW.draftTimer);
    TW.draftTimer = setTimeout(() => { TW.draftTimer = null; twTrack(twSaveDraft()); }, 700);
  }
  const twShort = (t, n) => { const s = String(t || '').replace(/\s+/g, ' ').trim(); return s.length > n ? `${s.slice(0, n)}…` : s; };
  function twChainText(chain) {
    if (!chain || !chain.steps) return '';
    const parts = [chain.src === 'current' ? '지금 기록 내용' : '처음 원문'];
    chain.steps.forEach((s, i) => parts.push(i === 0 ? `지침 '${twShort(s.prompt, 24)}'${s.request ? ` + 요청 '${twShort(s.request, 20)}'` : ''}`
      : `요청 '${twShort(s.request || '(전체 프롬프트 고침)', 24)}'${s.only_here ? '(이 기록만)' : s.with_src ? '(원문 함께)' : ''}`));
    return parts.join(' → ');
  }
  function twChainInfo(chain, title) {
    const lines = [`보낸 글: ${chain.src === 'current' ? '지금 기록 내용' : '처음 원문'}`];
    chain.steps.forEach((s, i) => {
      lines.push(`\n[${i + 1}단계]`);
      if (s.prompt) lines.push(`지침:\n${s.prompt}`);
      if (s.example) lines.push(`예시:\n${s.example}`);
      if (s.request) lines.push(`${i === 0 ? '추가 요청' : '이어서 고칠 요청'}: ${s.request}`);
      if (i > 0 && !s.prompt) lines.push('(지침은 앞 단계에서 마지막으로 쓴 것 그대로)');
      if (s.with_src) lines.push('(원문도 함께 보냄)');
      if (s.only_here) lines.push('📌 이 기록에만 적용 — ② 나머지 변환에서는 이 단계를 뺍니다');
    });
    alertBox(`${title || '이 후보를 만든 단계'}\n\n${lines.join('\n')}`);
  }
  // 나머지 변환에서 실제로 거치는 단계(그 기록에만 맞는 단계는 뺌) — 서버 replay_chain과 같게
  const twReplaySteps = (chain) => chain.steps.filter((s, i) => i === 0 || !s.only_here);
  // 이어 고치기 칸 도구: 원문도 함께 보내기 + 원문에서 고른 부분 넣기(그 기록에만 적용)
  function contSrcTools(rq, srcEls) {
    const st = { withSrc: true, pick: false };
    const note = el('div', { class: 'tw-pick-note' }); note.hidden = true;
    const clearPick = () => { st.pick = false; note.hidden = true; };
    const cb = el('input', { type: 'checkbox', checked: true, onchange: (e) => { st.withSrc = e.target.checked; if (!st.withSrc) clearPick(); } });
    const pickBtn = el('button', { type: 'button', class: 'small', text: '➕ 원문에서 고른 부분 넣기', title: '원문 칸에서 넣을 문장을 마우스로 끌어 고른 뒤 누르세요',
      onclick: () => {
        const sel = window.getSelection();
        const t = sel ? String(sel).replace(/\s+/g, ' ').trim() : '';
        const inSrc = sel && sel.rangeCount && srcEls().some((x) => x.contains(sel.anchorNode));
        if (!t || !inSrc) { toast('먼저 원문 칸에서 넣을 부분을 마우스로 끌어 고르세요.'); return; }
        const q = t.length > 300 ? `${t.slice(0, 300)}…` : t;
        rq.value = `${rq.value.trim() ? `${rq.value.trim()} / ` : ''}원문의 "${q}" 내용을 알맞은 자리에 넣어 줘`;
        st.pick = true; st.withSrc = true; cb.checked = true;
        note.replaceChildren('📌 원문에서 고른 부분은 이 기록에만 맞으므로, ② 나머지 변환에서는 이 단계를 빼고 실행합니다. ',
          el('button', { type: 'button', class: 'link', text: '다른 기록에도 쓸 요청으로 바꾸기', title: '요청을 다른 학생에게도 통하는 말로 고쳤다면 누르세요', onclick: clearPick }));
        note.hidden = false;
        rq.focus();
      } });
    pickBtn.addEventListener('mousedown', (e) => e.preventDefault()); // 누를 때 고른 글이 풀리지 않게
    const box = el('div', { class: 'tw-src-tools' }, [el('div', { class: 'tw-row' }, [
      el('label', { class: 'inline', style: 'margin:0', title: '켜면 앞 결과와 함께 원문도 AI에 보내, 결과에서 빠진 원문 내용을 다시 가져와 넣을 수 있습니다' }, [cb, '원문도 함께 보내기']), pickBtn]), note]);
    return { el: box, flags: () => (st.withSrc ? { with_src: true, ...(st.pick ? { only_here: true } : {}) } : {}) };
  }
  function twRec(id) { return TV.data ? TV.data.records.find((x) => x.id === id) : null; }
  function twRecLabel(x) { return `${x.name || x.student_no}${x.seq ? ` · ${x.seq}회` : x.kind === 'existing' ? ' · 기존 완성문' : ''}${x.title ? ` · ${x.title}` : ''}`; }

  function twRender() {
    const main = $('tvMain');
    main.innerHTML = '';
    const tagName = (TV.data.tags.find((t) => t.id === TV.tag) || {}).name || '';
    const tabs = el('div', { class: 'tw-tabs', role: 'tablist' }, TW_STEPS.map(([k, label]) => el('button', { type: 'button', role: 'tab', class: 'tw-tab' + (TW.step === k ? ' on' : ''), 'aria-selected': TW.step === k ? 'true' : 'false', text: label,
      onclick: async () => { if (!(await twFlushOrWarn())) return; TW.step = k; if (k === 'review') TW.review = null; if (k === 'bulk') TW.plan = null; twRender(); } })));
    main.appendChild(el('div', { class: 'tw-head' }, [el('b', { text: `🤖 '${tagName}' AI 변환` }), tabs, el('span', { class: 'spacer' }),
      el('button', { type: 'button', class: 'small', text: '← 기록 목록으로', onclick: () => twClose() })]));
    const body = el('div', { class: 'tw-body' });
    main.appendChild(body);
    if (TW.step === 'trial') twTrial(body);
    else if (TW.step === 'bulk') twBulk(body);
    else twReview(body);
  }

  // ① 프롬프트 적용 시험
  function twTrial(body) {
    const recs = TV.data.records;
    const w = TW.work;
    if (!recs.length) { body.appendChild(el('p', { class: 'muted', text: '지금 조건에 맞는 기록이 없습니다. 필터를 바꿔 보세요.' })); return; }
    body.appendChild(el('p', { class: 'hint', text: '기록 한 건으로 프롬프트를 고쳐 가며 변환해 보세요. 후보는 3칸까지 쌓이고(잠근 것은 남음), 마음에 드는 후보를 [✔ 확정]하면 그 기록에 반영되고 그 후보를 만든 단계로 ② 나머지 기록을 변환합니다.' }));
    if (w.confirmed) body.appendChild(el('div', { class: 'tw-confirmed' }, [el('b', { text: '확정한 설정: ' }), `${twConfLabel(w)} `,
      el('button', { type: 'button', class: 'link', text: '자세히', onclick: () => twChainInfo(w.confirmed.chain, '확정한 설정') }),
      el('button', { type: 'button', class: 'small primary', text: '② 나머지 변환으로 →', onclick: () => { TW.step = 'bulk'; TW.plan = null; twRender(); } })]));
    // 시험할 기록
    const sel = el('select', { 'aria-label': '시험할 기록', onchange: (e) => { TW.rid = +e.target.value; TW.cont = null; twRender(); } });
    const groups = [['학생관찰기록', recs.filter((x) => x.kind === 'record')], ['기존 완성문', recs.filter((x) => x.kind !== 'record')]];
    groups.forEach(([label, list]) => { if (list.length) sel.appendChild(el('optgroup', { label }, list.map((x) => el('option', { value: x.id, selected: x.id === TW.rid, disabled: !tvEditable(x), text: `${twRecLabel(x)} — ${twShort(x.content, 30)}${tvEditable(x) ? '' : ' (읽기 전용)'}` })))); });
    const rec = twRec(TW.rid);
    body.appendChild(el('div', { class: 'tw-row' }, [el('label', { class: 'inline' }, ['시험할 기록', sel]), rec ? el('span', { class: 'muted', text: `${tvSrcLabel(rec)} · ${rec.bytes}B` }) : null,
      rec ? el('button', { type: 'button', class: 'link', text: '이 학생 항목별 기록 ↗', onclick: () => openRecords(rec.group_id, rec.item, rec.student_no) }) : null]));
    if (!rec) return;
    const trials = TW.trials.filter((t) => t.record_id === rec.id);
    const hasOrig = !!(rec.original && rec.original !== rec.content);
    const grid = el('div', { class: 'tw-grid' });
    // 왼쪽: 원문·프롬프트
    const left = el('div', { class: 'tw-left' });
    const srcCard = el('div', { class: 'tw-box tw-box-src' }, [el('div', { class: 'tw-box-title', text: '📄 원문' })]);
    srcCard.append(el('div', { class: 'col-label', text: hasOrig ? '처음 원문' : '원문(지금 기록 내용)' }), el('div', { class: 'cmp-text tw-src', text: hasOrig ? rec.original : rec.content }));
    if (hasOrig) srcCard.append(el('div', { class: 'col-label', text: '지금 기록 내용(앞서 반영한 글)' }), el('div', { class: 'cmp-text tw-src', text: rec.content }));
    left.appendChild(srcCard);
    const prCard = el('div', { class: 'tw-box tw-box-pr' });
    const libOf = () => (TW.lib || []).find((p) => p.id === (w.draft && w.draft.lib_id));
    const libName = () => { const p = libOf(); if (!p) return ''; const same = (w.draft.prompt || '').trim() === (p.prompt || '').trim() && (w.draft.example || '').trim() === (p.example || '').trim(); return same ? p.name : `${p.name} (고침)`; };
    const libSel = el('select', { 'aria-label': '프롬프트 불러오기', class: 'tw-libsel' });
    const fillLib = () => {
      libSel.innerHTML = '';
      const cur = libOf();
      libSel.appendChild(el('option', { value: '', text: cur ? libName() : '프롬프트 목록에서 불러오기…', selected: true }));
      promptOpts(TW.lib, { tagName: (TV.data.tags.find((x) => x.id === TV.tag) || {}).name, label: (p) => `${p.name}${p.tags && p.tags.length ? ` · ${p.tags.join('·')}에서 사용` : ''}` }).forEach((o) => libSel.appendChild(o));
    };
    fillLib();
    const pr = el('textarea', { class: 'tw-prompt', rows: 12, 'aria-label': '프롬프트(지침)' }); pr.value = (w.draft && w.draft.prompt) || '';
    const ex = el('textarea', { rows: 3, 'aria-label': '예시', placeholder: '예시(선택): 문체·형식만 따라 합니다' }); ex.value = (w.draft && w.draft.example) || '';
    libSel.addEventListener('change', async () => {
      const p = (TW.lib || []).find((x) => x.id === libSel.value);
      if (!p) return;
      if ((pr.value.trim() && pr.value.trim() !== p.prompt.trim()) && !(await confirmBox(`지금 고치던 프롬프트를 '${p.name}'으로 바꿉니다. 이미 만든 후보에는 영향이 없습니다.`, '불러오기'))) { libSel.value = ''; return; }
      pr.value = p.prompt; ex.value = p.example || '';
      w.draft = { prompt: p.prompt, example: p.example || '', lib_id: p.id, lib_name: p.name };
      twDraftChanged(); fillLib(); fromLine.textContent = fromText();
    });
    const fromText = () => (w.draft && w.draft.lib_name ? `'${w.draft.lib_name}'에서 시작${libName().endsWith('(고침)') ? ' · 고친 내용 있음' : ''}` : '직접 쓴 프롬프트');
    const fromLine = el('div', { class: 'tw-from muted', text: fromText() });
    const onEdit = () => { w.draft = { ...(w.draft || {}), prompt: pr.value, example: ex.value }; twDraftChanged(); fromLine.textContent = fromText(); if (libSel.options[0]) libSel.options[0].textContent = libOf() ? libName() : '프롬프트 목록에서 불러오기…'; };
    pr.addEventListener('input', onEdit); ex.addEventListener('input', onEdit);
    const tagNm = (TV.data.tags.find((x) => x.id === TV.tag) || {}).name || '';
    prCard.append(el('div', { class: 'tw-row' }, [el('div', { class: 'tw-box-title', text: '✍️ 프롬프트(지침)' }), el('span', { class: 'spacer' }),
      el('button', { type: 'button', class: 'wiz-btn', title: '대화하며 다듬거나 양식을 채워 프롬프트를 만듭니다', text: '🪄 프롬프트 마법사', onclick: async () => { if (await twFlushOrWarn()) openWizardMenu({ tag: TV.tag, tagName: tagNm, rid: rec.id }); } })]),
      el('label', { class: 'tw-libline' }, [el('span', { class: 'muted', text: '불러온 프롬프트' }), libSel]), fromLine, pr,
      el('details', { open: !!ex.value }, [el('summary', { text: '예시(선택)' }), ex]));
    const model = el('select', { 'aria-label': '모델' }); fillModelSelect(model);
    const srcBox = el('div', { class: 'tw-src-pick' }, [el('span', { class: 'muted', text: '보낼 글:' }),
      ...[['original', '처음 원문'], ['current', '지금 기록 내용']].map(([v, label]) => el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'radio', name: 'twSrc', checked: TW.src === v, onchange: () => { TW.src = v; } }), label]))]);
    const req = el('input', { type: 'text', placeholder: '이번 추가 요청(선택): 예) 탐구 과정을 더 살려서', value: TW.req, oninput: (e) => { TW.req = e.target.value; } });
    const full = trials.length >= 3 && trials.every((t) => t.locked);
    const go = el('button', { type: 'button', class: 'primary ai-btn', disabled: !tvEditable(rec) || full, title: full ? '후보 3칸이 모두 잠겨 있습니다' : '', text: '이 프롬프트로 변환' });
    go.addEventListener('click', () => twRunTrial(rec, { src: TW.src, steps: [{ prompt: pr.value, example: ex.value, request: TW.req.trim() }] }, null, model, go));
    prCard.append(srcBox, req, el('div', { class: 'tw-row' }, [el('label', { class: 'inline', style: 'margin:0' }, ['모델', model]), el('span', { class: 'spacer' }), go]));
    if (!tvEditable(rec)) prCard.appendChild(el('p', { class: 'warn-text', text: '마감·비활성·보관 학년도 기록은 변환할 수 없습니다.' }));
    left.appendChild(prCard);
    // 오른쪽: 후보 3칸
    const right = el('div', { class: 'tw-cands' });
    if (!trials.length) right.appendChild(el('div', { class: 'tw-empty', text: '아직 후보가 없습니다. 왼쪽에서 [✨ 이 프롬프트로 변환]을 누르세요.' }));
    trials.forEach((t) => right.appendChild(twCandCard(t, rec, model)));
    grid.append(left, right);
    body.appendChild(grid);
  }
  function twCandCard(t, rec, model) {
    const conf = TW.work.confirmed && TW.work.confirmed.cand_id === t.id;
    const steps = t.chain.steps.length;
    const card = el('div', { class: 'tw-cand' + (conf ? ' conf' : '') + (t.locked ? ' locked' : '') });
    card.appendChild(el('div', { class: 'tw-cand-head' }, [
      el('b', { text: `프롬프트 ${t.ver_no || '?'}번` }), steps > 1 ? el('span', { class: 'badge', text: `이어 고침 ${steps - 1}번` }) : null,
      t.chain.src === 'current' ? el('span', { class: 'badge', text: '지금 내용에서' }) : null,
      t.chain.steps.some((s) => s.only_here) ? el('span', { class: 'badge', title: '원문에서 고른 부분을 넣은 단계는 ② 나머지 변환에서 뺍니다', text: '📌 이 기록만 단계' }) : null, conf ? el('span', { class: 'badge ok', text: '✔ 확정' }) : null,
      el('span', { class: 'spacer' }),
      el('button', { type: 'button', class: 'small', title: '잠그면 새 후보가 생겨도 지워지지 않습니다', text: t.locked ? '🔒 잠김' : '🔓', onclick: async () => { if (await mutate('tag_cand_lock', t.id, !t.locked, TW.year)) { t.locked = !t.locked; twRender(); } } }),
      el('button', { type: 'button', class: 'small', text: '단계', title: '이 후보를 만든 프롬프트·요청 보기', onclick: () => twChainInfo(t.chain) }),
      el('button', { type: 'button', class: 'small link danger-text', text: '지우기', onclick: async () => { if (await mutate('tag_cand_delete', t.id, TW.year)) { TW.trials = TW.trials.filter((x) => x.id !== t.id); twRender(); } } })]));
    card.appendChild(el('div', { class: 'tw-cand-text', text: t.text }));
    card.appendChild(el('div', { class: 'muted tw-cand-meta', text: `${bytesOf(t.text)}B · ${t.model || ''} · ${fmtCredit(t.cost)} 크레딧 · ${t.created_at.slice(5, 16)}` }));
    const foot = el('div', { class: 'tw-cand-foot' });
    if (TW.cont === t.id) {
      const rq = el('input', { type: 'text', placeholder: '이어서 고칠 요청: 예) 조금 더 짧게, 마지막 문장은 빼고', 'aria-label': '이어서 고칠 요청' });
      const eff = [...t.chain.steps].reverse().find((x) => x.prompt) || t.chain.steps[0];
      const fp = el('textarea', { rows: 8, 'aria-label': '이 단계의 전체 프롬프트' }); fp.value = eff.prompt;
      const det = el('details', {}, [el('summary', { text: '전체 프롬프트 고치기(선택)' }), el('p', { class: 'hint', text: '그대로 두면 지금까지의 지침을 그대로 지키며 요청만 반영합니다. 고치면 이 단계부터 고친 지침을 씁니다.' }), fp]);
      const run = el('button', { type: 'button', class: 'primary ai-btn small', text: '이어서 고치기' });
      const tools = contSrcTools(rq, () => [...document.querySelectorAll('#tvMain .tw-src')]);
      run.addEventListener('click', () => {
        const changed = fp.value.trim() && fp.value.trim() !== eff.prompt.trim();
        if (!rq.value.trim() && !changed) { toast('고칠 요청을 적어 주세요.'); rq.focus(); return; }
        twRunTrial(rec, { src: t.chain.src, steps: [...t.chain.steps, { prompt: changed ? fp.value : '', example: '', request: rq.value.trim(), ...tools.flags() }] }, t.id, model, run);
      });
      rq.addEventListener('keydown', (e) => { if (e.key === 'Enter') run.click(); });
      foot.append(rq, tools.el, det, el('div', { class: 'tw-row' }, [el('button', { type: 'button', class: 'small', text: '취소', onclick: () => { TW.cont = null; twRender(); } }), el('span', { class: 'spacer' }), run]));
      setTimeout(() => rq.focus(), 30);
    } else {
      foot.append(
        el('button', { type: 'button', class: 'small', disabled: !tvEditable(rec), text: '이 후보를 더 고치기', onclick: () => { TW.cont = t.id; twRender(); } }),
        el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'small primary', disabled: !tvEditable(rec), text: '✔ 확정', onclick: () => twConfirm(t, rec) }));
    }
    card.appendChild(foot);
    return card;
  }
  async function twRunTrial(rec, chain, parentId, model, btn) {
    if (!(chain.steps[0].prompt || '').trim()) { toast('프롬프트(지침)를 입력해 주세요.'); return; }
    if (!(await aiAsk(parentId ? '이어서 고치기' : '시험 변환', [['기록', twRecLabel(rec)], ['모델', modelName(model)], ['AI 호출', '1번']], 'tw'))) return;
    if (!(await twFlushOrWarn())) return;
    const out = await busyRun(btn, `tw${rec.id}`, () => aiRun({ title: parentId ? '이어서 고치기' : '시험 변환', skipConfirm: true,
      jobs: [{ label: twRecLabel(rec), run: () => api.tag_trial_run(TW.work.id, rec.id, chain, parentId, model.value, TW.year) }] }));
    if (!out || !out.done) return;
    TW.cont = null;
    if (out.results[0].dropped) toast('새 후보를 만들고 잠기지 않은 가장 오래된 후보를 지웠습니다.');
    await twLoad();
    twRender();
  }
  const twConfLabel = (w) => {
    const sk = w.confirmed.skill, ed = w.confirmed.edit;
    const head = ed ? (ed.by === '목록' ? `📚 '${ed.lib_name}' 프롬프트` : '✏️ 고친 설정')
      : sk ? `🧪 스킬화 프롬프트${sk.scores && sk.scores.length ? `(검증 ${sk.scores.join('·')}점)` : ''}` : `프롬프트 ${w.confirmed.ver_no || ''}번`;
    return `${head} · ${twChainText(w.confirmed.chain)}`;
  };
  async function twAfterConfirm(r, tagId) {
    const sk = r.applied && r.applied.skipped && r.applied.skipped[0];
    if (sk) await alertBox(`설정은 확정했지만 기록은 바꾸지 않았습니다: ${sk.why}`);
    if (TW.open && (!tagId || TV.tag === tagId)) {
      await renderTagView(true);
      await twLoad();
      TW.step = 'bulk'; TW.plan = null;
      twRender();
    }
    if (!sk) toast('확정했습니다. 이 설정으로 나머지 기록을 변환할 수 있습니다.');
  }
  async function twConfirm(t, rec, plain) {
    if (!plain && twReplaySteps(t.chain).length > 1) { // 이어 고친 단계가 있으면 스킬화(한 프롬프트로 종합 + 검증)
      if (!(await twFlushOrWarn())) return;
      openSkillSheet({ cid: t.id, year: TW.year, tagId: TV.tag, tagName: (TV.data.tags.find((x) => x.id === TV.tag) || {}).name || '',
        label: twRecLabel(rec), target: t.edited !== null && t.edited !== undefined ? t.edited : t.text, chainText: twChainText(t.chain),
        plainLabel: '단계 재현으로 확정', plainTitle: '스킬화하지 않고 지금처럼 단계를 차례로 다시 실행합니다(나머지 기록마다 AI를 단계 수만큼 부름)',
        plain: () => twConfirm(t, rec, true), after: (r) => twAfterConfirm(r, TV.tag) });
      return;
    }
    const steps = twReplaySteps(t.chain).length, only = t.chain.steps.length - steps;
    const html = `<b>이 후보를 확정합니다.</b><br>· 이 후보로 '${escHtml(twRecLabel(rec))}' 기록 내용을 바꿉니다(처음 원문은 남고, ③의 반영 기록에서 되돌릴 수 있음).<br>`
      + `· 이 후보를 만든 단계(${t.chain.steps.length}단계: ${escHtml(twChainText(t.chain))})로 ② 나머지 기록을 변환합니다.${steps > 1 ? ' 나머지 기록도 같은 단계를 차례로 거치므로 AI를 기록마다 ' + steps + '번 부릅니다.' : ''}<br>`
      + (only ? `· 📌 이 기록에만 적용한 단계 ${only}개(원문에서 고른 부분 넣기)는 나머지 변환에서 뺍니다.<br>` : '')
      + `· 최종안은 바뀌지 않습니다(학생별로 종합할 때 씁니다).<br><br>`
      + `<label class="inline" style="margin:0"><input type="checkbox" id="twSaveLib"> 프롬프트 목록에도 저장</label> <input type="text" id="twLibName" placeholder="이름" style="width:220px" value="${escHtml(`${(TV.data.tags.find((x) => x.id === TV.tag) || {}).name || '태그'} 변환`)}">`
      + (steps > 1 ? '<br><span class="muted">목록에는 1단계 지침과 예시만 저장됩니다(이어 고친 요청은 이 태그 작업에만 남음).</span>' : '');
    const p = modal(html, true, true, '확정');
    let save = false, name = '';
    const cbx = $('twSaveLib'), nm = $('twLibName');
    name = nm ? nm.value.trim() : '';
    if (cbx) cbx.addEventListener('change', () => { save = cbx.checked; });
    if (nm) nm.addEventListener('input', () => { name = nm.value.trim(); });
    const ok = await p;
    if (!ok) return;
    if (!(await twFlushOrWarn())) return;
    const r = await call('tag_confirm', t.id, true, TW.year);
    if (!r) return;
    if (save) {
      const s = await rawCall('prompt_save', { name: name || '태그 변환', prompt: t.chain.steps[0].prompt, example: t.chain.steps[0].example || '' });
      if (s && s.ok) { TW.lib = null; toast(`프롬프트 목록에 '${name}'으로 저장했습니다.`); } else toast((s && s.error) || '프롬프트 목록에 저장하지 못했습니다.', 5000);
    }
    await twAfterConfirm(r);
  }
  // ---------- 스킬화: 이어 고친 단계를 한 프롬프트로 종합 → 같은 원문으로 2번 다시 돌려 확정할 결과와 비교(둘 다 90점 이상이면 통과) ----------
  const SKILL_PASS = 90, SKILL_TRIES = 3;
  function openSkillSheet(o) {
    const SK = { tries: [], sel: -1, running: false };
    openSheet((box) => {
      box.style.width = 'min(1200px, 96vw)';
      const model = el('select', { 'aria-label': '모델' }); fillModelSelect(model);
      const body = el('div', { class: 'sheet-body sk-body' });
      const nameIn = el('input', { type: 'text', maxlength: 60, value: `${o.tagName || '태그'} 스킬` });
      const saveCb = el('input', { type: 'checkbox', checked: true });
      const startBtn = el('button', { type: 'button', class: 'primary ai-btn' });
      const okBtn = el('button', { type: 'button', class: 'primary' });
      const saveOnly = el('button', { type: 'button', text: '목록에 저장만', title: '확정하지 않고 프롬프트 목록에만 저장합니다' });
      const plainBtn = o.plain ? el('button', { type: 'button', text: o.plainLabel, title: o.plainTitle || '' }) : null;
      const cur = () => SK.tries[SK.sel];
      const prevOf = (a) => {
        const w = a.checks.slice().sort((x, y) => x.score - y.score)[0];
        return w ? { prompt: a.prompt, out: w.text, diff: w.diff || `유사도 ${w.score}점(내용 ${w.content}·문체 ${w.style}·길이 ${w.length})` } : null;
      };
      const pickBest = () => {
        let b = -1;
        SK.tries.forEach((a, i) => { if (b < 0 || (a.pass && !SK.tries[b].pass) || (a.pass === SK.tries[b].pass && (a.min || 0) > (SK.tries[b].min || 0))) b = i; });
        SK.sel = b;
      };
      const verify = async (a) => {
        const out = await aiRun({ title: `스킬화 ${a.no}번째 — 같은 원문으로 2번 변환해 비교`, skipConfirm: true, concurrency: 2,
          jobs: [1, 2].map((k) => ({ label: `검증 ${k}`, run: () => api.tag_skill_check(o.cid, a.prompt, a.example, model.value, o.year) })) });
        if (!out) return false;
        a.checks = out.results.map((r) => ({ text: r.text, score: r.score, content: r.content, style: r.style, length: r.length, diff: r.diff }));
        a.min = a.checks.length ? Math.min(...a.checks.map((c) => c.score)) : 0;
        a.pass = a.checks.length === 2 && a.min >= SKILL_PASS;
        return out.done === 2;
      };
      const run = async () => {
        if (SK.running) return;
        if (!(await aiAsk('스킬화', [['기록', o.label], ['모델', modelName(model)], ['AI 호출', `최대 ${SKILL_TRIES * 5}번(시도마다 5번, 통과하면 멈춤)`]]))) return;
        SK.running = true; draw();
        try {
          let prev = SK.tries.length ? prevOf(SK.tries[SK.tries.length - 1]) : null;
          for (let i = 0; i < SKILL_TRIES; i += 1) {
            const c = await aiRun({ title: `스킬화 ${SK.tries.length + 1}번째 — 프롬프트 만들기`, skipConfirm: true,
              jobs: [{ label: o.label, run: () => api.tag_skill_compose(o.cid, prev, model.value, o.year) }] });
            if (!c || !c.done) break;
            const a = { no: SK.tries.length + 1, prompt: c.results[0].prompt, example: c.results[0].example || '', checks: [], pass: false, copied: !!c.results[0].copied };
            SK.tries.push(a); SK.sel = SK.tries.length - 1; draw();
            const full = await verify(a);
            if (!full || a.pass) break;
            prev = prevOf(a);
          }
        } finally { SK.running = false; pickBest(); draw(); }
      };
      const reverify = async (text) => {
        if (!(await aiAsk('고친 프롬프트 검증', [['기록', o.label], ['모델', modelName(model)], ['AI 호출', '4번(변환 2 + 채점 2)']]))) return;
        const base = cur();
        const a = { no: SK.tries.length + 1, prompt: text, example: base ? base.example : '', checks: [], pass: false, edited: true };
        SK.running = true; SK.tries.push(a); SK.sel = SK.tries.length - 1; draw();
        try { await verify(a); } finally { SK.running = false; draw(); }
      };
      const draw = () => {
        body.innerHTML = '';
        body.appendChild(el('p', { class: 'hint', text: `이어 고친 단계(${o.chainText || ''})를 AI가 한 프롬프트로 종합하고, 그 프롬프트로 같은 원문을 2번 변환해 아래 '확정할 결과'와 비교합니다. 두 번 모두 ${SKILL_PASS}점 이상이면 통과입니다(내용 50·문체 30·길이 20). 못 넘으면 차이를 알려 고치기를 ${SKILL_TRIES}번까지 합니다. 한 번 시도에 AI를 5번 부릅니다(프롬프트 1 + 변환 2 + 채점 2). 확정하면 ② 나머지 변환은 기록마다 이 프롬프트로 한 번만 변환합니다.` }));
        const a = cur();
        if (SK.tries.length) {
          body.appendChild(el('div', { class: 'sk-tries' }, SK.tries.map((t, i) => el('button', { type: 'button', class: 'small' + (i === SK.sel ? ' primary' : ''),
            text: `${t.edited ? '고친 프롬프트' : `시도 ${t.no}`} · ${t.checks.length ? `${t.checks.map((c) => c.score).join('·')}점 ${t.pass ? '✔' : '✖'}` : '검증 안 됨'}`, onclick: () => { SK.sel = i; draw(); } }))));
        }
        const cols = el('div', { class: 'sk-cols' });
        cols.appendChild(el('div', { class: 'sk-col' }, [el('div', { class: 'col-label', text: `확정할 결과(목표) · ${(o.target || '').length}자` }), el('div', { class: 'cmp-text sk-text', text: o.target || '' })]));
        if (a) a.checks.forEach((c, k) => cols.appendChild(el('div', { class: 'sk-col' }, [
          el('div', { class: 'col-label' }, [el('b', { class: c.score >= SKILL_PASS ? 'sk-ok' : 'sk-no', text: `검증 ${k + 1} · ${c.score}점` }), ` (내용 ${c.content}·문체 ${c.style}·길이 ${c.length}) · ${c.text.length}자`]),
          c.diff ? el('div', { class: 'muted small-note', text: `차이: ${c.diff}` }) : null,
          el('div', { class: 'cmp-text sk-text', text: c.text })])));
        body.appendChild(cols);
        if (a) {
          const ta = el('textarea', { class: 'sk-prompt', rows: 10, 'aria-label': '스킬화한 프롬프트' }); ta.value = a.prompt;
          const again = el('button', { type: 'button', class: 'small ai-btn', text: '고친 프롬프트로 다시 검증', disabled: true, onclick: () => reverify(ta.value.trim()) });
          ta.addEventListener('input', () => { again.disabled = SK.running || !ta.value.trim() || ta.value.trim() === a.prompt.trim(); okBtn.disabled = !again.disabled; });
          body.appendChild(el('div', { class: 'tw-row' }, [el('b', { text: '스킬화한 프롬프트' }), el('span', { class: 'muted', text: a.pass ? ` ✔ 통과(${a.min}점 이상)` : a.checks.length ? ` ✖ 90점 미만(가장 낮은 점수 ${a.min}점)` : ' 검증 전' }), el('span', { class: 'spacer' }), again]));
          if (a.copied && ta.value === a.prompt) body.appendChild(el('div', { class: 'warn', text: '⚠ 이 프롬프트에 이 학생의 원문·결과 문장이 그대로 들어 있습니다. 다른 학생 결과에 이 학생의 표현이 섞일 수 있으니, 그 부분(주로 예시)을 일반적인 문장으로 고친 뒤 [고친 프롬프트로 다시 검증]하세요.' }));
          body.appendChild(ta);
        } else if (!SK.running) body.appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '[▶ 스킬화 시작]을 누르세요.' })]));
        startBtn.textContent = SK.tries.length ? `▶ ${SKILL_TRIES}번 더 시도` : '▶ 스킬화 시작';
        startBtn.disabled = SK.running || (a && a.pass);
        okBtn.textContent = a && !a.pass ? '그래도 이 프롬프트로 확정' : '이 프롬프트로 확정';
        okBtn.disabled = SK.running || !a || !a.checks.length;
        saveOnly.disabled = SK.running || !a;
        if (plainBtn) plainBtn.disabled = SK.running;
      };
      startBtn.addEventListener('click', run);
      okBtn.addEventListener('click', async () => {
        const a = cur();
        if (!a) return;
        if (!a.pass && !(await confirmBox(`이 프롬프트의 검증 점수는 ${a.min}점으로 ${SKILL_PASS}점에 못 미칩니다. 나머지 기록의 결과가 이 기록과 다르게 나올 수 있습니다. 그래도 확정할까요?`, '그래도 확정'))) return;
        const name = saveCb.checked ? nameIn.value.trim() : '';
        if (saveCb.checked && !name) { toast('저장할 이름을 적어 주세요.'); nameIn.focus(); return; }
        const r = await call('tag_confirm_skill', o.cid, a.prompt, a.example, { scores: a.checks.map((c) => c.score), tries: SK.tries.length }, name, o.year);
        if (!r) return;
        closeSheet(); TW.lib = null;
        if (name) toast(`프롬프트 목록에 '${name}'으로 저장했습니다.`);
        await o.after(r);
      });
      saveOnly.addEventListener('click', async () => {
        const a = cur();
        const name = nameIn.value.trim();
        if (!a) return;
        if (!name) { toast('저장할 이름을 적어 주세요.'); nameIn.focus(); return; }
        const r = await mutate('prompt_save', { name, prompt: a.prompt, example: a.example, made: '스킬화', tags: o.tagName ? [o.tagName] : [] });
        if (r) { TW.lib = null; toast(`프롬프트 목록에 '${name}'으로 저장했습니다(확정은 하지 않음).`); }
      });
      if (plainBtn) plainBtn.addEventListener('click', () => { if (SK.running) return; closeSheet(); o.plain(); });
      addTo(box, el('div', { class: 'sheet-head' }, [el('h2', { text: '🧪 스킬화 — 이어 고친 단계를 하나의 프롬프트로' }), el('span', { class: 'muted', text: o.label })]),
        el('div', { class: 'tw-row sk-ctrl' }, [el('label', { class: 'inline', style: 'margin:0' }, ['모델', model]), startBtn]),
        body,
        el('div', { class: 'sheet-foot sk-foot' }, [el('label', { class: 'inline', style: 'margin:0' }, [saveCb, '목록에 저장']), nameIn, saveOnly, el('span', { class: 'spacer' }),
          el('button', { type: 'button', text: '닫기', onclick: () => { if (!SK.running) closeSheet(); } }), plainBtn, okBtn]));
      draw();
    });
  }

  // ② 나머지 변환
  // ② 확정 설정 [✏️ 수정]: 지침·예시·단계별 요청을 고쳐 바로 적용(시험 없이)
  function twEditConfirmed(w) {
    const chain = JSON.parse(JSON.stringify(w.confirmed.chain));
    openSheet((box) => {
      box.style.width = 'min(980px, 94vw)';
      const body = el('div', { class: 'sheet-body' });
      body.appendChild(el('p', { class: 'hint', text: `보낼 글: ${chain.src === 'current' ? '지금 기록 내용' : '처음 원문'} · 고친 설정은 ② 나머지 변환에 바로 쓰입니다(이미 만든 결과는 그대로).` }));
      chain.steps.forEach((s, i) => {
        const sec = el('div', { class: 'tw-box' }, [el('div', { class: 'tw-box-title', text: i === 0 ? '1단계 · 지침' : `${i + 1}단계 · 이어서 고칠 요청${s.only_here ? ' (📌 이 기록만 — 나머지 변환에서 뺌)' : ''}` })]);
        if (i === 0 || s.prompt) {
          const pr = el('textarea', { rows: i === 0 ? 14 : 6, 'aria-label': `${i + 1}단계 지침` }); pr.value = s.prompt || '';
          pr.addEventListener('input', () => { s.prompt = pr.value; });
          sec.appendChild(pr);
        }
        if (i === 0) {
          const ex = el('textarea', { rows: 5, placeholder: '예시(선택): 직접 붙여넣거나 [📥 예시 불러오기]로 고르세요. 문체·형식만 따르고 내용은 참고하지 않습니다.', 'aria-label': '예시' }); ex.value = s.example || '';
          ex.addEventListener('input', () => { s.example = ex.value; });
          const exSel = el('select', { 'aria-label': '예시 불러오기' }, [el('option', { value: '', text: '📥 예시 불러오기…' })]);
          rawCall('tag_examples', w.id, TW.year).then((r) => {
            const xs = r && r.ok ? r.examples : [];
            if (!xs.length) exSel.appendChild(el('option', { value: '', disabled: true, text: '(불러올 결과가 아직 없습니다)' }));
            xs.forEach((x, k) => exSel.appendChild(el('option', { value: String(k), text: `${x.label} — ${twShort(x.text, 40)}` })));
            exSel._xs = xs;
          });
          exSel.addEventListener('change', async () => {
            const x = (exSel._xs || [])[+exSel.value];
            exSel.value = '';
            if (!x) return;
            if (ex.value.trim() && ex.value.trim() !== x.text.trim() && !(await confirmBox('지금 예시 칸의 글을 고른 결과로 바꿀까요?', '바꾸기'))) return;
            ex.value = x.text; s.example = x.text;
          });
          sec.append(el('div', { class: 'tw-row' }, [el('div', { class: 'col-label', text: '예시(선택)' }), el('span', { class: 'spacer' }), exSel]), ex);
        }
        const rq = el('input', { type: 'text', value: s.request || '', placeholder: i === 0 ? '추가 요청(선택)' : '이어서 고칠 요청', 'aria-label': `${i + 1}단계 요청` });
        rq.addEventListener('input', () => { s.request = rq.value; });
        sec.appendChild(rq);
        if (i > 0) sec.appendChild(el('button', { type: 'button', class: 'small link danger-text', text: '이 단계 빼기', onclick: () => { chain.steps.splice(i, 1); closeSheet(); twEditConfirmed({ ...w, confirmed: { ...w.confirmed, chain } }); } }));
        body.appendChild(sec);
      });
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '✏️ 확정한 설정 수정' })]), body,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', class: 'primary', text: '이 설정으로 적용', onclick: async () => {
            const r = await call('tag_confirm_set', w.id, chain, null, TW.year);
            if (!r) return;
            closeSheet();
            TW.work.confirmed = r.confirmed;
            toast('확정 설정을 고쳐 적용했습니다.');
            twRender();
          } })]));
    });
  }
  async function twBulk(body) {
    const w = TW.work;
    if (!w.confirmed) {
      body.appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '먼저 ① 프롬프트 적용 시험에서 마음에 드는 후보를 [✔ 확정]하세요. 그 후보를 만든 단계로 나머지 기록을 변환합니다.' }),
        el('button', { type: 'button', class: 'primary', text: '① 프롬프트 적용 시험으로', onclick: () => { TW.step = 'trial'; twRender(); } })]));
      return;
    }
    if (!TW.lib) { const l = await rawCall('prompt_list'); TW.lib = l && l.ok ? l.prompts : []; }
    const swap = el('select', { class: 'tw-swap', 'aria-label': '프롬프트 목록에서 바꾸기', title: '1단계에서 목록에 저장한 프롬프트(또는 다른 프롬프트)로 확정 설정을 바꿉니다' },
      [el('option', { value: '', text: '📚 목록 프롬프트로 바꾸기…' }), ...promptOpts(TW.lib, { tagName: w.tag_name, label: (p) => `${p.name}${p.tags && p.tags.length ? ` · ${p.tags.join('·')}에서 사용` : ''}` })]);
    swap.addEventListener('change', async () => {
      const id = swap.value;
      if (!id) return;
      const r = await call('tag_confirm_set', w.id, null, id, TW.year);
      if (!r) { swap.value = ''; return; }
      w.confirmed = r.confirmed; TW.lib = null;
      toast('확정 설정을 고른 프롬프트로 바꿨습니다.');
      twRender();
    });
    body.appendChild(el('div', { class: 'tw-confirmed' }, [el('b', { text: '확정한 설정: ' }), `${twConfLabel(w)} `,
      el('button', { type: 'button', class: 'small', text: '✏️ 수정', title: '확정한 설정의 지침·예시·요청을 마지막으로 고쳐 바로 적용합니다', onclick: () => twEditConfirmed(w) }), swap]));
    if (!TW.plan) {
      body.appendChild(el('p', { class: 'muted', text: '대상을 불러오는 중…' }));
      const seq = TW.seq, flt = { ...TV.flt };
      const label = [flt.scope ? $('tvScope').selectedOptions[0].textContent : '', flt.slot ? $('tvSlot').selectedOptions[0].textContent : '', flt.status !== 'all' ? $('tvStatus').selectedOptions[0].textContent : '', flt.q ? `'${flt.q}' 찾기` : ''].filter(Boolean);
      const r = await call('tag_plan', w.id, flt, TW.year);
      if (!r || seq !== TW.seq || TW.step !== 'bulk') return;
      TW.plan = r; TW.planFlt = { flt, label }; TW.pick = new Set(r.targets.filter((x) => x.default).map((x) => x.id));
      twRender();
      return;
    }
    const pl = TW.plan, ts = pl.targets;
    const can = (x) => !x.blocked;
    const steps = twReplaySteps(w.confirmed.chain).length;
    const flt = TW.planFlt.label;
    if (steps < w.confirmed.chain.steps.length) body.appendChild(el('p', { class: 'hint', text: `📌 이 기록에만 적용한 단계 ${w.confirmed.chain.steps.length - steps}개는 빼고, ${steps}단계로 변환합니다.` }));
    body.appendChild(el('p', { class: 'hint', text: `지금 화면 조건(${flt.join(' · ') || '조건 없음: 이 학년도의 이 태그 전체'})의 기록입니다. 체크를 풀면 뺍니다. 이미 반영한 기록과 기존 완성문은 체크가 풀린 채 시작합니다. 변환 결과는 바로 반영되지 않고 ③에서 검토합니다.` }));
    const items = Object.entries(pl.items);
    if (items.length > 1) body.appendChild(el('div', { class: 'warn', text: `다른 항목(담당) 기록이 섞여 있습니다: ${items.map(([k, n]) => `${k} ${n}건`).join(' · ')}. 한 번에 한 항목만 변환할 수 있으니 위 항목 필터로 하나를 고르세요.` }));
    const nPick = () => ts.filter((x) => TW.pick.has(x.id) && can(x)).length;
    const est = el('div', { class: 'tw-est' });
    const goBtn = el('button', { type: 'button', class: 'primary ai-btn' });
    const model = el('select', { 'aria-label': '모델' }); fillModelSelect(model);
    const tbl = el('table', { class: 'tbl tw-plan' });
    const drawEst = () => {
      const n = nPick(), calls = n * steps;
      const per = pl.cost_per_call;
      const kinds = new Set(ts.filter((x) => TW.pick.has(x.id) && can(x)).map((x) => `${x.group_id}:${x.item}`));
      est.textContent = kinds.size > 1 ? `서로 다른 항목(담당) ${kinds.size}곳의 기록이 골라져 있습니다. 위 항목 필터로 하나만 골라 나눠 실행하세요.`
        : `${n}건 · 단계 ${steps}개 → AI ${calls}회${per ? ` · 예상 약 ${fmtCredit(per * calls * 0.7)}~${fmtCredit(per * calls * 1.5)} 크레딧(시험 비용 기준, 모델을 바꾸면 달라짐)` : ''}`;
      est.classList.toggle('danger-text', kinds.size > 1);
      goBtn.textContent = `✨ ${n}건 변환 시작`; goBtn.disabled = !n || kinds.size > 1;
    };
    const drawTbl = () => {
      tbl.innerHTML = '';
      tbl.appendChild(el('tr', {}, ['', '학생', '항목', '기록', '내용', '상태'].map((h) => el('th', { text: h }))));
      ts.forEach((x) => {
        const cb = el('input', { type: 'checkbox', disabled: !can(x), checked: TW.pick.has(x.id) && can(x), 'aria-label': `${x.name} 기록 고르기`, onchange: (e) => { if (e.target.checked) TW.pick.add(x.id); else TW.pick.delete(x.id); drawEst(); } });
        const st = x.blocked ? x.blocked : x.applied ? '반영함' : x.kind !== 'record' ? '기존 완성문' : x.has_bulk ? '변환 결과 있음' : '';
        tbl.appendChild(el('tr', { class: can(x) ? '' : 'off' }, [el('td', {}, [cb]), el('td', { text: `${x.grade || ''}-${x.class_no || ''}-${x.number || ''} ${x.name}` }), el('td', { text: x.slot_label }),
          el('td', { text: x.kind === 'record' ? `${x.seq ? `${x.seq}회` : ''}${x.title ? ` ${x.title}` : ''}` : '기존 완성문' }), el('td', { class: 'tw-snip', text: twShort(x.content, 60) }), el('td', { text: st })]));
      });
      drawEst();
    };
    const setAll = (fn) => { TW.pick = new Set(ts.filter((x) => can(x) && fn(x)).map((x) => x.id)); drawTbl(); };
    body.appendChild(el('div', { class: 'tw-row' }, [
      el('button', { type: 'button', class: 'small', text: '모두 선택', onclick: () => setAll(() => true) }),
      el('button', { type: 'button', class: 'small', text: '선택 해제', onclick: () => setAll(() => false) }),
      el('button', { type: 'button', class: 'small', text: '변환 안 한 것만 선택', onclick: () => setAll((x) => !x.applied && !x.has_bulk && x.kind === 'record') }),
      el('span', { class: 'spacer' }), el('button', { type: 'button', class: 'small', text: '↻ 대상 다시 불러오기', onclick: () => { TW.plan = null; twRender(); } })]));
    body.appendChild(el('div', { class: 'tw-plan-wrap' }, [tbl]));
    body.appendChild(el('div', { class: 'tw-row tw-go' }, [est, el('span', { class: 'spacer' }), el('label', { class: 'inline', style: 'margin:0' }, ['모델', model]), goBtn]));
    goBtn.addEventListener('click', () => twStartBulk(ts.filter((x) => TW.pick.has(x.id) && can(x)), model, steps, flt));
    drawTbl();
  }
  async function twStartBulk(list, model, steps, flt) {
    if (!list.length) return;
    const bal = await rawCall('balance');
    const per = TW.plan.cost_per_call;
    const estHi = per ? per * list.length * steps * 1.5 : null;
    const low = bal && bal.ok && typeof bal.balance === 'number' && estHi && estHi > bal.balance;
    const msg = `${list.length}건을 확정한 단계로 변환합니다(AI ${list.length * steps}회${per ? `, 예상 약 ${fmtCredit(per * list.length * steps * 0.7)}~${fmtCredit(estHi)} 크레딧` : ''}).\n대상 조건: ${flt.join(' · ') || '이 태그 전체'}\n결과는 ③ 검토·반영에서 확인한 뒤 반영합니다(기록은 아직 바뀌지 않음).${low ? `\n\n⚠ 남은 크레딧(${fmtCredit(bal.balance)})보다 많이 들 수 있습니다.` : ''}`;
    if (!(await confirmBox(msg, '변환 시작'))) return;
    if (!(await twFlushOrWarn())) return;
    const r = await call('tag_run_create', TW.work.id, list.map((x) => x.id), TW.planFlt.flt, TW.year);
    if (!r) { TW.plan = null; twRender(); return; }
    await twRunItems(r.run.id, list.map((x) => ({ id: x.id, label: `${x.name} ${x.seq ? `${x.seq}회` : ''}`.trim() })), model.value);
  }
  async function twRunItems(runId, list, modelValue) {
    await jobStart();
    let out;
    try {
      out = await aiRun({ title: '태그 변환', skipConfirm: true,
        jobs: list.map((x) => ({ label: x.label, run: () => api.tag_run_item(runId, x.id, modelValue, TW.year) })),
        summary: (o) => `${o.cancelled ? '바로 중지했습니다(처리 중이던 건은 저장하지 않음). ' : ''}완료 ${o.done}건 · 실패 ${o.fail}건${o.skipped ? ` · 처리하지 않음 ${o.skipped}건` : ''}\n③ 검토·반영에서 결과를 확인하고 체크한 것만 반영하세요.` });
    } finally { await jobEnd(); }
    await rawCall('tag_run_finish', runId, out && (out.stopped || out.cancelled) ? 'stopped' : 'done', TW.year);
    refreshBalance();
    await twLoad();
    TW.step = 'review'; TW.review = null; TW.plan = null; TW.reviewRun = runId;
    twRender();
  }

  // ③ 검토·반영
  async function twReview(body) {
    const w = TW.work;
    if (!TW.review) {
      body.appendChild(el('p', { class: 'muted', text: '불러오는 중…' }));
      const seq = TW.seq, want = TW.reviewRun || null;
      const r = await call('tag_review', w.id, want, TW.year);
      if (!r || seq !== TW.seq || TW.step !== 'review' || (TW.reviewRun || null) !== want) return;
      TW.review = r;
      twRender();
      return;
    }
    const rv = TW.review;
    twBatches(body, rv.batches);
    if (TW.lastApplied && TW.lastApplied.length) body.appendChild(el('div', { class: 'tw-row' }, [el('button', { type: 'button', class: 'small', text: `바뀐 학생 목록(${TW.lastApplied.length}건) — 항목별 기록에서 하나씩 보기`, onclick: () => twAppliedSheet() })]));
    if (!rv.run) {
      body.appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '아직 나머지 변환을 하지 않았습니다.' }), el('button', { type: 'button', class: 'primary', text: '② 나머지 변환으로', onclick: () => { TW.step = 'bulk'; TW.plan = null; twRender(); } })]));
      return;
    }
    const rows = rv.rows;
    const stOf = (x) => (x.state === 'missing' ? '기록 없음' : x.state === 'none' ? '결과 없음' : x.state === 'failed' ? '실패' : x.applied ? '반영함' : x.changed ? '원문 바뀜' : x.closed ? '마감' : !x.active ? '비활성' : '반영 전');
    const canApply = (x) => x.state === 'ok' && !x.applied && !x.changed && !x.closed && x.active;
    const cnt = (f) => rows.filter(f).length;
    const runSel = el('select', { 'aria-label': '변환 실행', onchange: (e) => { TW.reviewRun = +e.target.value; TW.review = null; TW.seq += 1; twRender(); } },
      rv.runs.map((x) => el('option', { value: x.id, selected: x.id === rv.run.id, text: `${x.created_at.slice(5, 16)} · ${x.total}건(성공 ${x.ok} · 실패 ${x.failed})${x.status === 'stopped' ? ' · 중지됨' : ''}` })));
    const retry = rows.filter((x) => x.state === 'failed' || x.state === 'none');
    const model = el('select', { 'aria-label': '모델' }); fillModelSelect(model);
    body.appendChild(el('div', { class: 'tw-row' }, [el('label', { class: 'inline', style: 'margin:0' }, ['변환 실행', runSel]),
      el('span', { class: 'muted', text: `반영 전 ${cnt((x) => canApply(x))} · 반영함 ${cnt((x) => x.applied)} · 실패 ${cnt((x) => x.state === 'failed')} · 결과 없음 ${cnt((x) => x.state === 'none')} · 원문 바뀜 ${cnt((x) => x.state === 'ok' && x.changed && !x.applied)}` }),
      el('span', { class: 'spacer' }),
      retry.length ? el('label', { class: 'inline', style: 'margin:0' }, ['모델', model]) : null,
      retry.length ? el('button', { type: 'button', class: 'ai-btn small', text: `실패·결과 없음 ${retry.length}건 다시 변환`, onclick: () => twRunItems(rv.run.id, retry.map((x) => ({ id: x.record_id, label: x.name })), model.value) }) : null]));
    const fsel = el('div', { class: 'tw-filter' }, [['all', '전체'], ['todo', '반영 전'], ['failed', '실패'], ['changed', '원문 바뀜'], ['applied', '반영함']].map(([k, label]) => el('button', { type: 'button', class: 'small' + (TW.rfilter === k ? ' on' : ''), text: label, onclick: () => { TW.rfilter = k; twRender(); } })));
    const show = rows.filter((x) => TW.rfilter === 'all' || (TW.rfilter === 'todo' && canApply(x)) || (TW.rfilter === 'failed' && x.state === 'failed') || (TW.rfilter === 'changed' && x.changed && !x.applied) || (TW.rfilter === 'applied' && x.applied));
    const checked = () => rows.filter((x) => canApply(x) && x.cand.checked);
    const applyBtn = el('button', { type: 'button', class: 'primary' });
    const drawApply = () => { const n = checked().length; applyBtn.textContent = `체크한 ${n}건 기록에 반영`; applyBtn.disabled = !n; };
    const setCheck = async (list, on) => {
      const ids = list.filter(canApply).map((x) => x.cand.id);
      if (!ids.length) return;
      if (!(await mutate('tag_cand_check', ids, on, TW.year))) return;
      list.forEach((x) => { if (canApply(x)) x.cand.checked = on ? 1 : 0; });
      twRender();
    };
    body.appendChild(el('div', { class: 'tw-row' }, [fsel, el('span', { class: 'spacer' }),
      el('button', { type: 'button', class: 'small', text: '보이는 것 모두 체크', onclick: () => setCheck(show, true) }),
      el('button', { type: 'button', class: 'small', text: '체크 해제', onclick: () => setCheck(rows, false) })]));
    const list = el('div', { class: 'tw-review' });
    show.forEach((x) => list.appendChild(twReviewRow(x, canApply(x), stOf(x), drawApply)));
    if (!show.length) list.appendChild(el('p', { class: 'muted', text: '이 조건의 결과가 없습니다.' }));
    body.appendChild(list);
    applyBtn.addEventListener('click', () => twApply(checked()));
    body.appendChild(el('div', { class: 'tw-row tw-go' }, [el('span', { class: 'muted', text: '반영하면 기록 내용이 결과로 바뀝니다(처음 원문은 남음). 최종안은 바뀌지 않고 \'확인 필요\'로 표시됩니다.' }), el('span', { class: 'spacer' }), applyBtn]));
    drawApply();
  }
  function twReviewRow(x, can, st, onCheck) {
    const c = x.cand;
    const row = el('div', { class: 'tw-rv' + (can ? '' : ' off') });
    const cb = el('input', { type: 'checkbox', disabled: !can, checked: !!(c && c.checked && can), 'aria-label': `${x.name} 결과 반영 체크` });
    cb.addEventListener('change', async () => { if (await mutate('tag_cand_check', [c.id], cb.checked, TW.year)) { c.checked = cb.checked ? 1 : 0; onCheck(); } else cb.checked = !cb.checked; });
    const who = el('div', { class: 'tw-rv-who' }, [cb, el('b', { text: `${x.grade || ''}-${x.class_no || ''}-${x.number || ''} ${x.name}` }),
      el('span', { class: `tw-chip ${x.applied ? 'tw-applied' : x.closed ? 'tw-closed' : can ? 'tw-todo' : 'tw-off'}`, text: st }),
      x.applied && x.closed ? el('span', { class: 'tw-chip tw-closed', text: '마감' }) : null,
      x.state !== 'missing' && !x.active && st !== '비활성' ? el('span', { class: 'tw-chip tw-off', text: '비활성' }) : null,
      el('span', { class: 'muted', text: [ITEM_LABELS[x.item] || '', x.kind === 'existing' ? '기존 완성문' : x.seq ? `${x.seq}회` : '', x.title, x.date ? md(x.date) : ''].filter(Boolean).join(' · ') }),
      x.group_id ? el('button', { type: 'button', class: 'link', text: '항목별 기록 ↗', onclick: () => openRecords(x.group_id, x.item, x.student_no) }) : null]);
    row.appendChild(who);
    if (!c) { row.appendChild(el('div', { class: 'muted', text: x.state === 'missing' ? '기록이 지워졌습니다.' : '결과가 없습니다(중지됐거나 아직 변환하지 않음).' })); return row; }
    if (c.status === 'failed') { row.appendChild(el('div', { class: 'danger-text', text: c.error || '실패' })); return row; }
    const ta = el('textarea', { rows: 5, disabled: !!x.applied, 'aria-label': `${x.name} 변환 결과` });
    ta.value = TW.edits.has(c.id) ? TW.edits.get(c.id) : c.edited !== null && c.edited !== undefined ? c.edited : c.text;
    const save = () => { const t = TW.editTimers.get(c.id); if (t) clearTimeout(t); TW.editTimers.delete(c.id); twTrack(twSaveEdit(c.id)); };
    ta.addEventListener('input', () => { TW.edits.set(c.id, ta.value); const t = TW.editTimers.get(c.id); if (t) clearTimeout(t); TW.editTimers.set(c.id, setTimeout(save, 600)); });
    ta.addEventListener('blur', () => { if (TW.editTimers.has(c.id)) save(); });
    row.appendChild(el('div', { class: 'tw-rv-cols' }, [
      el('div', {}, [el('div', { class: 'col-label', text: x.changed && !x.applied ? '보낸 원문 (그 뒤 기록이 바뀜)' : '보낸 원문' }), el('div', { class: 'cmp-text', text: c.input_text })]),
      el('div', {}, [el('div', { class: 'col-label', text: `변환 결과${c.edited !== null && c.edited !== undefined ? ' (고침)' : ''} · ${fmtCredit(c.cost)} 크레딧` }), ta])]));
    return row;
  }
  async function twApply(list) {
    if (!list.length) return;
    if (!(await twFlushOrWarn())) return;
    if (!(await confirmBox(`${list.length}건의 기록 내용을 변환 결과로 바꿉니다.\n처음 원문은 남고, 아래 '반영 기록'의 [되돌리기]로 이번 반영을 되돌릴 수 있습니다(앱을 껐다 켜도 가능).\n최종안은 바뀌지 않고 '확인 필요'로 표시됩니다.`, '반영'))) return;
    const r = await mutate('tag_apply', TW.work.id, list.map((x) => x.cand.id), TW.year);
    if (!r) return;
    if (r.skipped.length) await alertBox(`${r.applied.length}건을 반영했습니다.\n반영하지 않은 ${r.skipped.length}건:\n${r.skipped.map((s) => `· ${(list.find((x) => x.record_id === s.record_id) || {}).name || s.record_id}: ${s.why}`).join('\n')}`);
    TW.review = null;
    await renderTagView(true);
    TW.lastApplied = r.applied;
    if (r.applied.length) actionToast(`${r.applied.length}건을 기록에 반영했습니다.`, '바뀐 학생 목록 보기', () => twAppliedSheet(), 15000);
  }
  // 지운 태그의 작업: 반영 기록 보기·되돌리기
  async function twOrphanSheet(w) {
    const r = await call('tag_batches', w.work_id, ys.year);
    if (!r) return;
    openSheet((box) => {
      box.style.height = 'auto'; box.style.width = 'min(560px, 92vw)';
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `'${w.tag_name}' 태그(지움)의 반영 기록` })]),
        el('p', { class: 'hint', text: '태그는 지웠지만 AI 변환으로 기록을 바꾼 이력은 남아 있습니다. 반영 한 번 단위로 되돌릴 수 있습니다.' }));
      const body = el('div', {});
      twBatches(body, r.batches, w.work_id);
      box.append(body, el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '닫기', onclick: closeSheet })]));
    });
  }
  // 반영한 학생 목록: 하나씩 항목별 기록으로 열기
  function twAppliedSheet() {
    const list = TW.lastApplied || [];
    if (!list.length) return;
    const recs = new Map((TV.data ? TV.data.records : []).map((x) => [x.id, x]));
    openSheet((box) => {
      box.style.height = 'auto'; box.style.width = 'min(560px, 92vw)';
      const seen = new Set();
      const rows = list.filter((a) => { const k = `${a.group_id}:${a.item}:${a.student_no}`; if (seen.has(k)) return false; seen.add(k); return true; });
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `이번에 반영한 학생 ${rows.length}명` })]),
        el('p', { class: 'hint', text: '학생을 누르면 항목별 기록에서 그 학생을 엽니다. 이 목록은 [바뀐 학생 목록] 버튼(③ 위)으로 다시 볼 수 있습니다.' }),
        el('div', { class: 'tw-applied-list' }, rows.map((a) => { const x = recs.get(a.record_id) || {}; return el('button', { type: 'button', text: `${x.name || a.student_no} · ${ITEM_LABELS[a.item] || a.item}`, onclick: () => { closeSheet(); openRecords(a.group_id, a.item, a.student_no); } }); })),
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '닫기', onclick: closeSheet })]));
    });
  }
  function twBatches(body, batches, wid) {
    if (!batches || !batches.length) return;
    const live = batches.filter((b) => b.undone < b.count);
    const box = el('details', { class: 'tw-batches', open: !!wid }, [el('summary', { text: `반영 기록 ${batches.length}번${live.length ? ` (아직 되돌리지 않은 반영 ${live.length}번)` : ''}` })]);
    batches.forEach((b) => box.appendChild(el('div', { class: 'tw-row' }, [el('span', { text: `${b.at.slice(5, 16)} · ${b.count}건${b.undone ? ` (되돌림 ${b.undone}건)` : ''}` }),
      b.undone < b.count ? el('button', { type: 'button', class: 'small', text: '이 반영 되돌리기', onclick: () => twUndo(b, wid) }) : el('span', { class: 'muted', text: '되돌림' })])));
    body.appendChild(box);
  }
  async function twUndo(b, wid) {
    if (!(await confirmBox(`${b.at.slice(5, 16)}에 반영한 ${b.count - b.undone}건을 반영 전 내용으로 되돌립니다.\n반영 뒤 직접 고쳤거나 마감한 기록은 그대로 두고 알려 드립니다.`, '되돌리기'))) return;
    const r = await mutate('tag_undo', wid || TW.work.id, b.batch, TW.year || ys.year);
    if (!r) return;
    await alertBox(`${r.undone.length}건을 되돌렸습니다.${r.skipped.length ? `\n그대로 둔 ${r.skipped.length}건: ${[...new Set(r.skipped.map((s) => s.why))].join(', ')}` : ''}`);
    if (wid) { closeSheet(); toast('되돌렸습니다.'); await renderTagView(true); return; }
    TW.review = null;
    await renderTagView(true);
    await twLoad();
    twRender();
  }

  // ---------- 태그 관리 ----------
  async function renderTags() {
    const r = await call('tags');
    if (!r) return;
    const t = $('tagTable');
    t.innerHTML = '';
    t.appendChild(el('tr', {}, ['태그', '쓰인 기록', ''].map((h) => el('th', { text: h }))));
    if (!r.tags.length) t.appendChild(el('tr', {}, [el('td', { colspan: 3, class: 'muted', text: '아직 태그가 없습니다.' })]));
    r.tags.forEach((tg) => {
      const name = el('input', { type: 'text', value: tg.name, disabled: !!ys.archived });
      name.addEventListener('change', async () => { if (await mutate('rename_tag', tg.id, name.value)) { toast('이름을 바꿨습니다. 모든 기록에 반영됩니다.'); renderTags(); } else name.value = tg.name; });
      t.appendChild(el('tr', {}, [el('td', { class: 'tag-name-cell' }, [el('span', { class: 'tdot' + tagC(tg.id) }), name]), el('td', { text: `${tg.used}건${tg.used_closed ? ` (마감 ${tg.used_closed})` : ''}${tg.used_inbox ? ` · 인박스 ${tg.used_inbox}` : ''}` }), el('td', {}, [el('button', { type: 'button', class: 'link danger-text edit-only', text: '삭제', onclick: async () => {
        if ((tg.used || tg.used_inbox) && !(await typedConfirm(`'${tg.name}' 태그를 지우면 기록 ${tg.used}건${tg.used_closed ? `(마감된 기록 ${tg.used_closed}건 포함)` : ''}${tg.used_inbox ? `과 보내기 전 인박스 묶음 ${tg.used_inbox}개` : ''}에서 빠집니다. 태그 정리는 마감과 관계없이 반영됩니다. 이 태그로 한 AI 변환의 반영 기록은 남고, 태그별 기록 왼쪽 '지운 태그의 AI 변환'에서 되돌릴 수 있습니다.`, '삭제'))) return;
        if (await mutate('delete_tag', tg.id)) renderTags();
      } })])]));
    });
  }

  // 인박스 묶음 이름 → 태그. 만든 태그는 같은 이름의 보내기 전 묶음에도 붙인다.
  async function tagsFromInbox() {
    const r = await call('inbox_tag_names');
    if (!r) return;
    if (!r.names.length) { alertBox('자료 인박스에 묶음이 없습니다.'); return; }
    const picks = new Set();
    openSheet((box) => {
      const okBtn = el('button', { type: 'button', class: 'primary', disabled: true, text: '태그로 만들기' });
      const upd = () => { okBtn.disabled = !picks.size; okBtn.textContent = picks.size ? `태그 ${picks.size}개 만들기` : '태그로 만들기'; };
      const list = el('div', { class: 'tag-inbox-list' }, r.names.map((n) => {
        const cb = el('input', { type: 'checkbox', disabled: n.exists, checked: n.exists });
        cb.addEventListener('change', () => { cb.checked ? picks.add(n.name) : picks.delete(n.name); upd(); });
        const note = n.exists ? '이미 태그 있음' : n.open ? `보내기 전 묶음 ${n.open}개에 붙임` : '보낸 묶음 — 태그만 만듦';
        return el('label', { class: 'tag-inbox-row' + (n.exists ? ' is-done' : '') }, [cb, el('b', { text: n.name }), el('span', { class: 'muted', text: note })]);
      }));
      okBtn.onclick = async () => {
        const res = await mutate('tags_from_inbox', [...picks]);
        if (!res) return;
        closeSheet(); renderTags();
        toast(`태그 ${res.made}개를 만들었습니다${res.attached ? ` · 인박스 묶음 ${res.attached}개에 붙임` : ''}.`);
      };
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: '인박스 묶음 이름을 태그로' })]),
        el('p', { class: 'hint', text: '고른 이름으로 태그를 만듭니다. 보내기 전 묶음에는 그 태그를 바로 붙여, 보낼 때 기록에 함께 붙습니다. 이미 보낸 묶음은 바꾸지 않습니다.' }),
        list,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), okBtn]));
    });
  }

  // ---------- 프롬프트 목록(메뉴 › 프롬프트) ----------
  const P = { data: null, id: 'default' };
  async function loadPromptList() {
    const r = await call('prompt_list');
    if (r) P.data = r;
    return r;
  }
  async function renderPrompts() {
    const r = await loadPromptList();
    if (!r) return;
    if (!r.prompts.some((x) => x.id === P.id)) P.id = r.prompts[0].id;
    const list = $('prList');
    list.innerHTML = '';
    const usedBy = (id) => Object.entries(r.picks).filter(([, v]) => v === id).map(([k]) => r.kinds[k]);
    const item = (x) => {
      const uses = usedBy(x.id);
      return el('button', { type: 'button', class: 'pr-item' + (x.id === P.id ? ' active' : ''), onclick: async () => { await flushPending(); P.id = x.id; P.openGroup = !!x.builtin; renderPrompts(); } },
        [el('b', { text: x.name }), x.builtin ? el('span', { class: 'tag', text: '기본' }) : null, x.made ? el('span', { class: 'tag', text: x.made === '스킬화' ? '🧪 스킬화' : `마법사·${x.made}` }) : null,
          x.tags && x.tags.length ? el('div', { class: 'muted small-note', text: `🏷 ${x.tags.join('·')}에서 사용` }) : null,
          uses.length ? el('div', { class: 'muted small-note', text: `지금 선택: ${uses.join(', ')}` }) : null]);
    };
    // 기본 프롬프트는 한 묶음으로 접어 둔다(마지막 상태 기억, 고른 것이 기본이면 펼침)
    const builtins = r.prompts.filter((x) => x.builtin), mine = r.prompts.filter((x) => !x.builtin);
    const curBuiltin = builtins.some((x) => x.id === P.id);
    const open = localStorage.getItem('sgb_pr_builtin_open') === '1' || (curBuiltin && P.openGroup);
    const grp = el('details', { class: 'pr-group', open }, [el('summary', {}, [el('b', { text: `📦 기본 프롬프트 (${builtins.length})` }),
      el('div', { class: 'muted small-note', text: '지울 수 없고, 고친 뒤 [기본값으로 되돌리기] 가능' })]), ...builtins.map(item)]);
    grp.addEventListener('toggle', () => { try { localStorage.setItem('sgb_pr_builtin_open', grp.open ? '1' : '0'); } catch (e) { /* 무시 */ } });
    list.appendChild(grp);
    if (mine.length) list.appendChild(el('div', { class: 'pr-mine-title', text: `직접 만든 프롬프트 (${mine.length})` }));
    mine.forEach((x) => list.appendChild(item(x)));
    const cur = r.prompts.find((x) => x.id === P.id);
    $('prName').value = cur.name;
    $('prName').disabled = !!cur.builtin;
    $('prName').title = cur.builtin ? '기본 프롬프트는 이름을 바꿀 수 없습니다(복사해서 새로 만들면 바꿀 수 있음)' : '';
    $('prPrompt').value = cur.prompt;
    $('prExample').value = cur.example;
    $('prResetBtn').hidden = !cur.builtin;
    $('prDelBtn').hidden = !!cur.builtin;
    $('prState').textContent = cur.builtin ? (cur.prompt === r.defaults[cur.id] && !cur.example ? '기본값 사용 중' : '기본에서 고침') : '';
  }
  function savePrompt() {
    $('prState').textContent = '저장 중…';
    const entry = { id: P.id, name: $('prName').value, prompt: $('prPrompt').value, example: $('prExample').value };
    saveLater(`prompt:${entry.id}`, async () => {
      const r = await mutate('prompt_save', entry);
      if (r && P.id === entry.id) {
        $('prState').textContent = '저장됨';
        const it = P.data && P.data.prompts.find((x) => x.id === entry.id);
        if (it) { Object.assign(it, { name: it.builtin ? it.name : entry.name, prompt: entry.prompt, example: entry.example }); }
        const btn = document.querySelector('#prList .pr-item.active b');
        if (btn && it) btn.textContent = it.name;
      }
      return r;
    }, 600);
  }
  // 프롬프트 생성 마법사: 큰 틀(역할·입력 자료·시점과 문체·내용·쓰지 않는 것·틀린/옳은 예시·출력 형태·마지막 점검)을 채우면
  // 오른쪽에 완성된 프롬프트가 보이고 [목록에 저장]으로 새 프롬프트가 된다. 기본값 그대로면 기본 프롬프트와 같은 글.

  // ---------- 🪄 프롬프트 마법사: 💬 대화 / 📋 양식 ----------
  // ctx: 태그 AI 변환 화면에서 열면 { tag, tagName, rid } — 대화는 그 태그 작업의 시험 후보 3칸을 함께 쓴다.
  async function openWizardMenu(ctx) {
    const pick = await new Promise((resolve) => openSheet((box) => {
      box.style.height = 'auto'; box.style.width = 'min(560px, 92vw)';
      const card = (key, icon, title, desc) => el('button', { type: 'button', class: 'wiz-pick', onclick: () => { closeSheet(); resolve(key); } }, [el('div', { class: 'wiz-pick-t', text: `${icon} ${title}` }), el('div', { class: 'muted', text: desc })]);
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '🪄 프롬프트 마법사' })]),
        el('div', { class: 'wiz-picks' }, [
          card('chat', '💬', '대화', '기록 한 건을 놓고 AI와 대화하듯 결과를 보며 고쳐 갑니다. 마음에 들면 [프롬프트 제작]으로 대화를 종합한 프롬프트를 만듭니다.'),
          card('form', '📋', '양식', '역할·문체·쓰지 않는 것·예시 같은 칸을 채우면, 기본 프롬프트를 참고해 AI가 정교한 프롬프트로 써 줍니다.')]),
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => { closeSheet(); resolve(null); } })]));
    }));
    if (pick === 'chat') openChatWizard(ctx);
    else if (pick === 'form') openPromptWizard(ctx);
  }

  // 대화 마법사 상태: 기록 모드(태그 작업의 시험 후보) / 붙여넣기 모드(메모리)
  const CW = { ctx: null, mode: 'record', tag: null, tagName: '', work: null, rid: null, recs: [], trials: [], cur: null, paste: '', local: [], seq: 0, year: null };
  async function openChatWizard(ctx) {
    if (!(await leaveOk())) return;
    AI_ASK_SKIP.delete('cw');
    const recCtx = ctx && ctx.rec ? ctx.rec : null; // 항목별 기록에서 연 경우: 그 기록 글을 붙여넣기로 시작
    Object.assign(CW, { ctx: ctx || null, mode: recCtx ? 'paste' : 'record', tag: ctx && !recCtx ? ctx.tag : null, tagName: ctx && !recCtx ? ctx.tagName : '', work: null, rid: ctx && !recCtx ? ctx.rid : null, recs: [], trials: [], cur: null, paste: recCtx ? recCtx.text || '' : '', local: [], year: ys.year,
      firstPrompt: null, firstEx: '', useCurrent: false });
    const [tags, lib] = await Promise.all([call('tags'), rawCall('prompt_list')]);
    CW.allTags = (tags && tags.tags) || [];
    CW.lib = lib && lib.ok ? lib.prompts : [];
    if (!(ctx && ctx.tag && TW.work && TW.work.draft && TW.work.draft.prompt)) { const d = CW.lib.find((p) => p.id === 'default'); if (d) { CW.firstPrompt = d.prompt; CW.firstEx = d.example || ''; } }
    if (!CW.tag && CW.allTags.length) { CW.tag = CW.allTags[0].id; CW.tagName = CW.allTags[0].name; }
    if (!CW.tag || recCtx) CW.mode = 'paste';
    openSheet((box) => {
      box.style.width = 'min(1280px, 96vw)';
      CW.box = box;
      cwLoad().then(() => cwRender());
    });
  }
  async function cwLoad() {
    if (CW.mode !== 'record' || !CW.tag) return;
    const seq = ++CW.seq;
    const [w, v] = await Promise.all([rawCall('tag_work', CW.tag, CW.year), rawCall('tag_view', CW.tag, {})]);
    if (seq !== CW.seq) return;
    if (!w || !w.ok || !w.work) { toast((w && w.error) || '태그 작업을 열지 못했습니다(보관 학년도는 붙여넣기만 됩니다).', 6000); CW.mode = 'paste'; return; }
    CW.work = w.work; CW.trials = w.trials;
    CW.recs = (v && v.ok ? v.records : []).filter((x) => !x.closed && x.active && !x.gone);
    if (!CW.recs.some((x) => x.id === CW.rid)) CW.rid = (CW.recs.find((x) => x.kind === 'record') || CW.recs[0] || {}).id || null;
    const mine = CW.trials.filter((t) => t.record_id === CW.rid);
    if (!mine.some((t) => t.id === (CW.cur && CW.cur.id))) CW.cur = mine.length ? mine[mine.length - 1] : null;
  }
  const cwCands = () => (CW.mode === 'paste' ? CW.local : CW.trials.filter((t) => t.record_id === CW.rid));
  function cwRender() {
    const box = CW.box;
    if (!box || !box.isConnected) return;
    box.innerHTML = '';
    // 자료 고르기
    const modeSel = el('div', { class: 'segmented' }, [['record', '태그 기록으로'], ['paste', '글 붙여넣기']].map(([k, t]) => el('button', { type: 'button', class: 'seg' + (CW.mode === k ? ' active' : ''), disabled: k === 'record' && !CW.allTags.length,
      text: t, onclick: async () => { if (CW.mode === k) return; CW.mode = k; CW.cur = null; if (k === 'record') await cwLoad(); cwRender(); } })));
    const src = el('div', { class: 'cw-src' });
    if (CW.mode === 'record') {
      const tagSel = el('select', { 'aria-label': '태그', disabled: !!(CW.ctx && CW.ctx.tag), onchange: async (e) => { CW.tag = +e.target.value; CW.tagName = e.target.selectedOptions[0].textContent; CW.rid = null; CW.cur = null; await cwLoad(); cwRender(); } },
        CW.allTags.map((t) => el('option', { value: t.id, selected: t.id === CW.tag, text: t.name })));
      const recSel = el('select', { 'aria-label': '기록', onchange: (e) => { CW.rid = +e.target.value; const m = cwCands(); CW.cur = m.length ? m[m.length - 1] : null; cwRender(); } },
        CW.recs.map((x) => el('option', { value: x.id, selected: x.id === CW.rid, text: `${x.name}${x.seq ? ` · ${x.seq}회` : x.kind === 'existing' ? ' · 기존 완성문' : ''}${x.title ? ` · ${x.title}` : ''} — ${twShort(x.content, 28)}` })));
      src.append(el('label', { class: 'inline', style: 'margin:0' }, ['태그', tagSel]), el('label', { class: 'inline', style: 'margin:0' }, ['기록', recSel]));
      if (!CW.recs.length) src.appendChild(el('span', { class: 'warn-text', text: '이 태그에 고칠 수 있는 기록이 없습니다.' }));
    } else {
      const ta = el('textarea', { rows: 3, placeholder: '변환해 볼 학생 활동 글을 붙여넣으세요(저장하지 않음, 창을 닫으면 대화도 사라짐)', 'aria-label': '붙여넣을 글' });
      ta.value = CW.paste;
      ta.addEventListener('input', () => { CW.paste = ta.value; });
      src.appendChild(ta);
    }
    const rec = CW.mode === 'record' ? CW.recs.find((x) => x.id === CW.rid) : null;
    const original = rec ? (rec.original && rec.original !== rec.content ? rec.original : rec.content) : CW.paste;
    // 대화(지금 고른 후보까지의 흐름)
    const chat = el('div', { class: 'cw-chat', role: 'log', 'aria-live': 'polite' });
    const bubble = (who, text, extra) => el('div', { class: `cw-msg ${who}` }, [el('div', { class: 'cw-who', text: who === 'me' ? '나' : who === 'ai' ? 'AI 결과' : '원문' }), el('div', { class: 'cw-text', text }), extra || null]);
    chat.appendChild(bubble('src', original || '(원문 없음)'));
    const cur = CW.cur;
    if (cur) {
      const all = cwCands();
      const byId = new Map(all.map((t) => [t.id, t]));
      const path = [];
      for (let t = cur; t; t = t.parent_id ? byId.get(t.parent_id) : null) path.unshift(t);
      const steps = cur.chain.steps;
      steps.forEach((s, i) => {
        const msg = i === 0 ? `지침: ${twShort(s.prompt, 140)}${s.example ? `\n예시: ${twShort(s.example, 80)}` : ''}${s.request ? `\n요청: ${s.request}` : ''}`
          : `${s.request || '(요청 없음)'}${s.prompt ? `\n(지침 전체를 고침: ${twShort(s.prompt, 100)})` : ''}${s.only_here ? '\n📌 원문 함께 · 이 기록에만 적용' : s.with_src ? '\n(원문 함께 보냄)' : ''}`;
        chat.appendChild(bubble('me', msg));
        const t = path.find((x) => x.chain.steps.length === i + 1);
        chat.appendChild(bubble('ai', t ? t.text : '(이 단계 결과는 후보 3칸에서 밀려나 보이지 않습니다)'));
      });
    } else {
      chat.appendChild(el('div', { class: 'cw-empty muted', text: '아래에 지침(프롬프트)을 쓰고 [보내기]를 누르면 대화가 시작됩니다. 결과를 보고 "더 짧게"처럼 요구를 이어서 보내세요.' }));
    }
    // 입력
    const model = el('select', { 'aria-label': '모델' }); fillModelSelect(model);
    const input = el('div', { class: 'cw-input' });
    const send = el('button', { type: 'button', class: 'primary ai-btn', text: '보내기' });
    if (!cur) {
      const lib = el('select', { 'aria-label': '프롬프트 불러오기' }, [el('option', { value: '', text: '시작 프롬프트 불러오기…' }), ...promptOpts(CW.lib, { tagName: CW.tagName })]);
      const pr = el('textarea', { rows: 7, placeholder: '처음 지침(프롬프트)', 'aria-label': '처음 지침' });
      const tagCtx = CW.ctx && CW.ctx.tag;
      pr.value = CW.firstPrompt != null ? CW.firstPrompt : ((tagCtx && TW.work && TW.work.draft && TW.work.draft.prompt) || '');
      if (CW.firstPrompt == null && tagCtx && TW.work && TW.work.draft) CW.firstEx = TW.work.draft.example || '';
      pr.addEventListener('input', () => { CW.firstPrompt = pr.value; });
      lib.addEventListener('change', () => { const p = (CW.lib || []).find((x) => x.id === lib.value); if (p) { pr.value = p.prompt; CW.firstPrompt = p.prompt; CW.firstEx = p.example || ''; } lib.value = ''; });
      const rq = el('input', { type: 'text', placeholder: '(선택) 이번 추가 요청' });
      const srcPick = CW.mode === 'record' && rec && rec.original && rec.original !== rec.content
        ? el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', checked: CW.useCurrent, onchange: (e) => { CW.useCurrent = e.target.checked; } }), '처음 원문 대신 지금 기록 내용 보내기']) : null;
      addTo(input, el('div', { class: 'tw-row' }, [el('b', { text: '처음 지침' }), el('span', { class: 'spacer' }), lib]), pr, rq, srcPick);
      send.addEventListener('click', () => cwSend({ src: CW.useCurrent ? 'current' : 'original', steps: [{ prompt: pr.value, example: CW.firstEx || '', request: rq.value.trim() }] }, null, model, send));
    } else {
      const rq = el('textarea', { rows: 2, placeholder: '결과를 보고 요구할 것을 쓰세요. 예) 더 짧게, 탐구 과정을 더 살리고 마지막 문장은 빼기', 'aria-label': '이어서 요구' });
      const eff = [...cur.chain.steps].reverse().find((x) => x.prompt) || cur.chain.steps[0];
      const fp = el('textarea', { rows: 6 }); fp.value = eff.prompt;
      const tools = contSrcTools(rq, () => [...box.querySelectorAll('.cw-msg.src .cw-text')]);
      rq.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send.click(); });
      input.append(rq, tools.el, el('details', {}, [el('summary', { text: '지침 전체 고치기(선택)' }), fp]));
      send.addEventListener('click', () => {
        const changed = fp.value.trim() && fp.value.trim() !== eff.prompt.trim();
        if (!rq.value.trim() && !changed) { toast('요구할 것을 적어 주세요.'); rq.focus(); return; }
        cwSend({ src: cur.chain.src, steps: [...cur.chain.steps, { prompt: changed ? fp.value : '', example: '', request: rq.value.trim(), ...tools.flags() }] }, cur, model, send);
      });
      setTimeout(() => rq.focus(), 30);
    }
    input.appendChild(el('div', { class: 'tw-row' }, [el('label', { class: 'inline', style: 'margin:0' }, ['모델', model]),
      cur ? el('button', { type: 'button', class: 'small', text: '처음부터 새로', title: '지침부터 다시 시작합니다(지금 후보는 남아 있음)', onclick: () => { CW.cur = null; cwRender(); } }) : null,
      el('span', { class: 'spacer' }), el('span', { class: 'muted', text: cur ? 'Ctrl+Enter로 보내기' : '' }), send]));
    // 후보 3칸
    const cands = el('div', { class: 'cw-cands' }, [el('div', { class: 'col-label', text: `결과 후보 ${cwCands().length}/3 — 골라서 그 지점부터 이어 갑니다` })]);
    cwCands().slice().reverse().forEach((t) => cands.appendChild(el('div', { class: 'cw-cand' + (cur && cur.id === t.id ? ' on' : '') + (t.locked ? ' locked' : '') }, [
      el('div', { class: 'tw-row' }, [el('b', { text: `${t.chain.steps.length}단계` }), el('span', { class: 'muted', text: t.created_at ? t.created_at.slice(5, 16) : '' }), el('span', { class: 'spacer' }),
        CW.mode === 'record' ? el('button', { type: 'button', class: 'small', text: t.locked ? '🔒' : '🔓', title: '잠그면 새 결과가 생겨도 지워지지 않습니다', onclick: async () => { if (await mutate('tag_cand_lock', t.id, !t.locked, CW.year)) { t.locked = !t.locked; cwRender(); } } })
          : el('button', { type: 'button', class: 'small', text: t.locked ? '🔒' : '🔓', onclick: () => { t.locked = !t.locked; cwRender(); } })]),
      el('div', { class: 'cw-cand-text', text: twShort(t.text, 160) }),
      CW.ctx && CW.ctx.rec ? el('button', { type: 'button', class: 'small', text: '이 결과를 최종안으로', title: `${CW.ctx.rec.label}의 최종안에 이 결과 전체를 넣습니다`, onclick: () => putFinalText(CW.ctx.rec, t.text) }) : null,
      el('button', { type: 'button', class: 'small' + (cur && cur.id === t.id ? ' primary' : ''), text: cur && cur.id === t.id ? '지금 이어 가는 중' : '여기서 이어 가기', onclick: () => { CW.cur = t; cwRender(); } })])));
    box.append(
      el('div', { class: 'sheet-head' }, [el('h2', { text: '💬 프롬프트 마법사 · 대화' }), modeSel, el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'primary', disabled: !cur, title: cur ? '지금 이어 가는 후보까지의 대화를 종합해 완성된 프롬프트를 만듭니다' : '먼저 대화를 시작하세요', text: '🧩 프롬프트 제작', onclick: () => cwCompose(model) })]),
      el('div', { class: 'sheet-body cw-body' }, [el('div', { class: 'cw-main' }, [src, chat, input]), cands]),
      el('div', { class: 'sheet-foot' }, [el('span', { class: 'muted', text: CW.mode === 'record' ? '이 대화의 결과는 태그 AI 변환 ① 프롬프트 적용 시험의 후보와 같습니다(거기서 [✔ 확정] 가능).' : '붙여넣은 글로 한 대화는 저장하지 않습니다.' }),
        el('span', { class: 'spacer' }), el('button', { type: 'button', text: '닫기', onclick: () => cwClose() })]));
    chat.scrollTop = chat.scrollHeight;
  }
  async function cwClose() {
    closeSheet();
    if (CW.ctx && CW.ctx.tag && TW.open) { await twLoad(); twRender(); }
    if (CW.ctx && CW.ctx.rec && R.sno) loadStudent(true);
  }
  async function cwSend(chain, parent, model, btn) {
    if (!(chain.steps[0].prompt || '').trim()) { toast('처음 지침(프롬프트)을 입력해 주세요.'); return; }
    if (!(await aiAsk(parent ? '이어서 고치기' : '대화 시작', [['자료', CW.mode === 'record' ? `'${CW.tagName}' 태그 기록` : '붙여넣은 글'], ['모델', modelName(model)], ['AI 호출', '1번']], 'cw'))) return;
    if (CW.mode === 'record') {
      if (!CW.rid) { toast('기록을 고르세요.'); return; }
      const out = await busyRun(btn, `cw${CW.rid}`, () => aiRun({ title: parent ? '이어서 고치기' : '대화 시작', skipConfirm: true,
        jobs: [{ label: CW.tagName, run: () => api.tag_trial_run(CW.work.id, CW.rid, chain, parent ? parent.id : null, model.value, CW.year) }] }));
      if (!out || !out.done) return;
      if (out.results[0].dropped) toast('잠기지 않은 가장 오래된 후보를 지웠습니다.');
      await cwLoad();
      const nid = out.results[0].id;
      CW.cur = CW.trials.find((t) => t.id === nid) || CW.cur;
      cwRender();
      return;
    }
    const text = parent ? parent.text : CW.paste;
    if (!text.trim()) { toast('변환해 볼 글을 붙여넣으세요.'); return; }
    if (!parent && CW.local.length >= 3 && CW.local.every((t) => t.locked)) { toast('후보 3칸이 모두 잠겨 있습니다.'); return; }
    const out = await busyRun(btn, 'cwpaste', () => aiRun({ title: parent ? '이어서 고치기' : '대화 시작', skipConfirm: true,
      jobs: [{ label: '붙여넣은 글', run: () => api.prompt_chat_free(chain, text, model.value, parent ? parent.orig : CW.paste) }] }));
    if (!out || !out.done) return;
    const t = { id: `L${Date.now()}`, parent_id: parent ? parent.id : null, orig: parent ? parent.orig : CW.paste, chain, text: out.results[0].text, locked: false, created_at: new Date().toISOString().replace('T', ' ') };
    CW.local.push(t);
    while (CW.local.length > 3) { const i = CW.local.findIndex((x) => !x.locked && x !== t); if (i < 0) break; CW.local.splice(i, 1); }
    CW.cur = t;
    cwRender();
  }
  // [프롬프트 제작]: 대화를 종합한 프롬프트 → 확인·고치기 → 이름 정해 저장
  async function cwCompose(model) {
    const cur = CW.cur;
    if (!cur) return;
    if (CW.mode === 'record' && twReplaySteps(cur.chain).length > 1 && !CW.plainCompose) { // 태그 기록 대화: 스킬화 + 같은 원문 검증
      const rec = CW.recs.find((x) => x.id === CW.rid);
      openSkillSheet({ cid: cur.id, year: CW.year, tagId: CW.tag, tagName: CW.tagName, label: rec ? twRecLabel(rec) : CW.tagName,
        target: cur.edited !== null && cur.edited !== undefined ? cur.edited : cur.text, chainText: twChainText(cur.chain),
        plainLabel: '검증 없이 프롬프트만 만들기', plainTitle: '예전처럼 대화 과정만 종합해 프롬프트를 만듭니다(같은 원문 검증 없음)',
        plain: async () => { CW.plainCompose = true; try { await cwCompose(model); } finally { CW.plainCompose = false; } },
        after: (r) => twAfterConfirm(r, CW.tag) });
      return;
    }
    if (!(await aiAsk('프롬프트 제작', [['재료', `대화 ${cur.chain.steps.length}단계`], ['모델', modelName(model)], ['AI 호출', '1번']]))) return;
    const out = await aiRun({ title: '프롬프트 제작', skipConfirm: true, jobs: [{ label: '대화 종합', run: () => api.prompt_compose(cur.chain, model.value) }] });
    if (!out || !out.done) return;
    await promptSaveSheet(out.results[0].text, cur.chain.steps[0].example || '', '대화', CW.mode === 'record' ? CW.tagName : '',
      `${CW.tagName || (CW.ctx && CW.ctx.rec ? CW.ctx.rec.label : '대화')} 프롬프트`, CW.ctx && CW.ctx.rec ? recUseFor(CW.ctx.rec) : (CW.ctx && TW.open));
  }
  // 마법사 결과 저장 창(대화·양식 공용): 내용 고치기, 이름, 쓴 태그 기록, 태그 화면이면 바로 쓰기
  function promptSaveSheet(text, example, made, tagName, defName, canUse, alt) {
    return new Promise((resolve) => openSheet((box) => {
      box.style.width = 'min(980px, 94vw)';
      const ta = el('textarea', { class: 'wiz-preview', 'aria-label': '만든 프롬프트' }); ta.value = text;
      const ex = el('textarea', { rows: 3, placeholder: '(선택) 예시' }); ex.value = example || '';
      const nameIn = el('input', { type: 'text', maxlength: 60, value: defName || '' });
      const use = canUse ? el('input', { type: 'checkbox', checked: true }) : null;
      const useLabel = canUse && canUse.label ? canUse.label : '이 태그 AI 변환 프롬프트로 바로 쓰기';
      const altBox = alt ? el('details', {}, [el('summary', { text: alt.label }), el('div', { class: 'cmp-text', style: 'max-height:30vh;overflow:auto', text: alt.text }),
        el('button', { type: 'button', class: 'small', text: '이 글로 바꾸기', onclick: () => { ta.value = alt.text; } })]) : null;
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `🧩 완성된 프롬프트 (${made})` }), el('span', { class: 'muted', text: '저장 전에 고칠 수 있습니다.' })]),
        el('div', { class: 'sheet-body' }, [ta, altBox, el('div', { class: 'col-label', text: '예시 (선택)' }), ex,
          tagName ? el('p', { class: 'hint', text: `저장하면 '${tagName}' 태그에서 쓴 프롬프트로 표시됩니다.` }) : null]),
        el('div', { class: 'sheet-foot' }, [el('label', { class: 'inline', style: 'margin:0' }, ['이름', nameIn]),
          use ? el('label', { class: 'inline', style: 'margin:0' }, [use, useLabel]) : null,
          el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => { closeSheet(); resolve(null); } }),
          el('button', { type: 'button', class: 'primary', text: '프롬프트 목록에 저장', onclick: async () => {
            const name = nameIn.value.trim();
            if (!name) { toast('이름을 적어 주세요.'); nameIn.focus(); return; }
            if (!ta.value.trim()) { toast('프롬프트가 비어 있습니다.'); return; }
            const r = await mutate('prompt_save', { name, prompt: ta.value, example: ex.value, made, tags: tagName ? [tagName] : [] });
            if (!r) return;
            closeSheet();
            TW.lib = null; P.id = r.id;
            if (use && use.checked && canUse.apply) await canUse.apply(r.id, name);
            else if (use && use.checked && TW.work) {
              TW.work.draft = { prompt: ta.value, example: ex.value, lib_id: r.id, lib_name: name };
              twDraftChanged(); await twFlush();
              const l = await rawCall('prompt_list'); TW.lib = l && l.ok ? l.prompts : null;
              TW.step = 'trial'; await twLoad(); twRender();
            }
            if ($('prList') && document.querySelector('[data-panel-content=prompts]:not([hidden])')) renderPrompts();
            toast(`'${name}' 프롬프트를 저장했습니다.${use && use.checked ? (canUse.apply ? ` ${canUse.done || '바로 쓰도록 골라 두었습니다.'}` : ' 이 태그 AI 변환의 시작 프롬프트로 넣었습니다.') : ''}`, 5000);
            resolve(r.id);
          } })]));
      setTimeout(() => nameIn.select(), 50);
    }));
  }

  async function openPromptWizard(ctx) {
    const r0 = await call('prompt_wizard_spec');
    if (!r0) return;
    const spec = r0.spec;
    openSheet((box) => {
      box.style.width = 'min(1280px, 96vw)';
      const preview = el('textarea', { class: 'wiz-preview', readonly: true });
      const nameIn = el('input', { type: 'text', maxlength: 60, placeholder: '예: 수학 세특 · 짧게', value: '' });
      const exIn = el('textarea', { rows: 3, placeholder: '(선택) 원하는 결과 모양의 생기부 문장. AI가 문체·형식을 따릅니다.' });
      const wizModel = el('select', { 'aria-label': '모델' }); fillModelSelect(wizModel);
      const refresh = debounce(async () => { const r = await call('prompt_wizard_build', spec); if (r) preview.value = r.text; }, 250);
      const txt = (key, ph) => el('input', { type: 'text', value: spec[key] || '', placeholder: ph || '', oninput: (e) => { spec[key] = e.target.value; refresh(); } });
      const chk = (key, label) => el('label', { class: 'wiz-chk' }, [el('input', { type: 'checkbox', checked: !!spec[key], onchange: (e) => { spec[key] = e.target.checked; refresh(); } }), label]);
      const lineList = (key) => {
        const wrap = el('div', { class: 'wiz-lines' });
        const draw = () => {
          wrap.innerHTML = '';
          spec[key].forEach((x, i) => wrap.appendChild(el('div', { class: 'wiz-line' + (x.on ? '' : ' off') }, [
            el('input', { type: 'checkbox', checked: !!x.on, title: '넣기/빼기', onchange: (e) => { x.on = e.target.checked; draw(); refresh(); } }),
            el('input', { type: 'text', value: x.text, oninput: (e) => { x.text = e.target.value; refresh(); } }),
            el('button', { type: 'button', class: 'link danger-text', text: '지우기', onclick: () => { spec[key].splice(i, 1); draw(); refresh(); } })])));
          wrap.appendChild(el('button', { type: 'button', class: 'small', text: '+ 줄 추가', onclick: () => { spec[key].push({ text: '', on: true }); draw(); refresh(); const ins = wrap.querySelectorAll('.wiz-line input[type=text]'); if (ins.length) ins[ins.length - 1].focus(); } }));
        };
        draw();
        return wrap;
      };
      const pairBox = el('div', { class: 'wiz-lines' });
      const drawPairs = () => {
        pairBox.innerHTML = '';
        spec.pairs.forEach((p, i) => pairBox.appendChild(el('div', { class: 'wiz-pair' }, [
          el('label', {}, ['틀린 예', el('input', { type: 'text', value: p.wrong, oninput: (e) => { p.wrong = e.target.value; refresh(); } })]),
          el('label', {}, ['옳은 예', el('input', { type: 'text', value: p.right, oninput: (e) => { p.right = e.target.value; refresh(); } })]),
          el('button', { type: 'button', class: 'link danger-text', text: '지우기', onclick: () => { spec.pairs.splice(i, 1); drawPairs(); refresh(); } })])));
        pairBox.appendChild(el('button', { type: 'button', class: 'small', text: '+ 예시 쌍 추가', onclick: () => { spec.pairs.push({ wrong: '', right: '' }); drawPairs(); refresh(); } }));
      };
      drawPairs();
      const sec = (n, title, hint, ...kids) => el('details', { class: 'wiz-sec', open: n <= 2 }, [el('summary', {}, [el('b', { text: `${n}. ${title}` }), hint ? el('span', { class: 'muted', text: ` — ${hint}` }) : null]), ...kids]);
      const itemSel = el('select', { onchange: (e) => { spec.item = e.target.value; refresh(); } }, [el('option', { value: '', text: '(항목 지정 안 함)' }), ...r0.items.map((x) => el('option', { value: x, text: x }))]);
      const outSel = el('div', { class: 'segmented' });
      const drawOut = () => {
        outSel.innerHTML = '';
        [['opinion', '본문 + 교사 의견(이어서 한 문단)'], ['single', '본문 한 문단만']].forEach(([v, t]) => outSel.appendChild(el('button', { type: 'button', class: 'seg' + (spec.output === v ? ' active' : ''), text: t, onclick: () => { spec.output = v; drawOut(); refresh(); } })));
      };
      drawOut();
      const left = el('div', { class: 'wiz-form' }, [
        sec(1, '역할', '누가 무엇을 쓰는지', el('div', { class: 'map-row' }, [el('label', {}, ['학교급', txt('school', '고등학교')]), el('label', {}, ['과목', txt('subject', '(선택) 예: 수학')]), el('label', {}, ['항목', itemSel])])),
        sec(2, '입력 자료', 'AI에 주는 학생 자료가 무엇인지', el('label', {}, ['자료 설명', txt('material', '예: 수행평가 자료 및 교사 의견')])),
        sec(3, '시점과 문체', '체크를 끄면 빠집니다', lineList('style')),
        sec(4, '내용', '무엇을 중심으로 쓸지', lineList('content')),
        sec(5, '쓰지 않는 것', '', chk('banned_personal', '학생 이름·번호 등 개인정보'), el('label', {}, ['쓰지 않을 단어(쉼표로 구분)', txt('banned_words')]), lineList('banned_extra'), chk('no_preface', '글 앞뒤 머리말·설명 쓰지 않기')),
        sec(6, '틀린/옳은 예시', '관찰자 시점으로 끝맺는 예', pairBox, chk('pair_note', '예시 뒤에 "학생이 한 일로 끝나게" 설명 넣기')),
        sec(7, '출력 형태', '', outSel, el('label', {}, ['교사 의견 문장 수', txt('opinion_n', '2~3')])),
        sec(8, '마지막 점검', '', chk('recheck', '최종 재검토 단계'), chk('compare', '예시와 비교(점수는 출력하지 않음)')),
        sec(9, '그 밖의 지침', '(선택) 직접 더할 규칙', lineList('extra')),
      ]);
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: '📋 프롬프트 마법사 · 양식' }), el('span', { class: 'muted', text: '왼쪽 칸을 채우고 [✨ AI로 정교하게 만들기]를 누르면, 기본 프롬프트를 참고해 AI가 완성된 프롬프트로 씁니다. 오른쪽은 칸을 이어 붙인 미리보기입니다.' })]),
        el('div', { class: 'sheet-body wiz-body' }, [left, el('div', { class: 'wiz-right' }, [el('div', { class: 'col-label', text: '칸을 이어 붙인 미리보기(AI가 이것을 바탕으로 다듬음)' }), preview,
          el('div', { class: 'col-label', text: '예시 (선택)' }), exIn, el('p', { class: 'hint', text: r0.note })])]),
        el('div', { class: 'sheet-foot' }, [el('label', { class: 'inline', style: 'margin:0' }, ['이름', nameIn]), el('label', { class: 'inline', style: 'margin:0' }, ['모델', wizModel]), el('span', { class: 'spacer' }),
          el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', class: 'primary ai-btn', text: 'AI로 정교하게 만들기', onclick: async () => {
            const name = nameIn.value.trim() || `${ctx && ctx.tagName ? ctx.tagName : spec.subject || '양식'} 프롬프트`;
            const ex = exIn.value;
            if (!(await aiAsk('프롬프트 만들기(양식)', [['재료', '양식 칸 내용'], ['모델', modelName(wizModel)], ['AI 호출', '1번']]))) return;
            const out = await aiRun({ title: '프롬프트 만들기(양식)', skipConfirm: true, jobs: [{ label: '양식 → 프롬프트', run: () => api.prompt_form_ai(spec, wizModel.value) }] });
            if (!out || !out.done) return;
            const res = out.results[0];
            closeSheet();
            const id = await promptSaveSheet(res.text, ex, '양식', ctx && ctx.tag ? ctx.tagName : '', name, ctx && ctx.rec ? recUseFor(ctx.rec) : !!(ctx && ctx.tag && TW.open), { label: '칸만 이어 붙인 글 보기(AI 다듬기 전)', text: res.assembled });
            if (id && !ctx) { P.id = id; await renderPrompts(); }
          } })]));
      refresh();
    });
  }
  async function newPrompt(copyOf) {
    await flushPending();
    const src = copyOf ? P.data.prompts.find((x) => x.id === copyOf) : null;
    const r = await mutate('prompt_save', src ? { name: `${src.name} 복사본`.slice(0, 60), prompt: src.prompt, example: src.example } : { name: '새 프롬프트', prompt: '', example: '' });
    if (!r) return;
    P.id = r.id;
    await renderPrompts();
    $('prName').focus(); $('prName').select();
  }

  // =====================================================================
  // v0.3: 자료 인박스 — ① 가져오기 → ② 학생 매칭 → ③ AI 정제(선택) → ④ 보내기 검토
  // =====================================================================
  const IB = { list: [], bid: null, view: null, raw: null, opts: null, preview: [], onlyPending: false, sel: new Set(), stop: false };
  const STAGE_NAME = { import: '① 가져오기', match: '② 매칭 대기', refine: '③ 정제', review: '④ 보내기 대기', sent: '✔ 보냄' };
  const ST_CHIP = { confirmed: '✔ 확정', suggested: '추천', none: '! 확인 필요', excluded: '제외' };
  let returnTo = null; // 명렬 등록하러 갔다가 돌아올 곳

  async function refreshInboxBadge() {
    if (!ys.year) return;
    const r = await api.inbox_list();
    if (!r || !r.ok) return;
    IB.list = r.batches;
    const n = r.batches.filter((b) => b.stage !== 'sent').length;
    $('ibBadge').hidden = !n;
    $('ibBadge').textContent = n;
  }
  async function renderInbox() {
    if (!(await loadSlots())) return;
    await refreshInboxBadge();
    renderInboxList();
    if (IB.bid && IB.list.find((b) => b.id === IB.bid)) await loadBatch();
    else { IB.bid = null; renderInboxEmpty(); }
  }
  function slotLabel(gid, item) {
    const s = R.slots.find((x) => x.group_id === gid && x.item === item);
    return s ? s.label : '(담당 없음)';
  }
  function renderInboxList() {
    const box = $('ibList');
    box.innerHTML = '';
    box.appendChild(el('button', { type: 'button', class: 'primary edit-only', style: 'width:100%;margin-bottom:10px', text: '+ 새 자료 묶음', onclick: newBatch }));
    const item = (b) => el('button', { type: 'button', class: 'ib-item' + (b.id === IB.bid ? ' active' : ''), onclick: () => { IB.bid = b.id; IB.raw = null; IB.sel.clear(); renderInboxList(); loadBatch(); } }, [
      el('span', { class: 't', text: b.title }),
      el('span', { class: 's', text: slotLabel(b.group_id, b.item) }),
      el('span', { class: 's' }, [el('span', { class: 'stage-chip' + (b.stage === 'sent' ? ' sent' : ''), text: b.stage === 'sent' && b.rounds > 1 ? `✔ 보냄 ${b.rounds}회` : STAGE_NAME[b.stage] }),
        b.stage === 'sent' ? ` ${b.sent_summary}` : `${b.n ? ` 새 자료 ${b.n}건${b.pending ? ` · 확인 필요 ${b.pending}` : ''}` : ''}${b.n_sent ? ` · 보낸 ${b.n_sent}건` : ''}`]),
      b.sent_at ? el('span', { class: 's when', text: `마지막으로 보낸 때 ${b.sent_at}` }) : null,
    ]);
    if (!IB.list.length) box.appendChild(el('p', { class: 'hint', text: '묶음이 없습니다. 학습지·엑셀 자료를 [+ 새 자료 묶음]으로 가져오세요.' }));
    IB.list.forEach((b) => box.appendChild(item(b)));
  }
  function renderInboxEmpty() {
    const m = $('ibMain');
    m.innerHTML = '';
    m.appendChild(el('div', { class: 'empty-state' }, [
      el('h2', { text: '자료 인박스' }),
      el('p', { text: '어떤 활동 자료든 여기로 가져와 학생별로 나눈 뒤 항목에 보냅니다.' }),
      el('p', { class: 'hint', text: '① 가져오기(엑셀 붙여넣기·xlsx·스캔 PDF) → ② 학생 매칭 → ③ AI 정제(선택) → ④ 보내기 검토. 스캔 PDF는 CLOVA OCR로 읽습니다. 한 학생씩 직접 쓰는 기록은 항목별 기록의 [+ 학생관찰기록]을 쓰세요.' }),
      el('div', { class: 'steps-btns' }, [el('button', { type: 'button', class: 'primary edit-only', text: '+ 새 자료 묶음', onclick: newBatch })]),
    ]));
  }
  function slotSelect(current, onlyGroup) {
    const s = el('select', {});
    R.slots.filter((x) => !onlyGroup || x.group_id === onlyGroup).forEach((x) => s.appendChild(el('option', { value: slotKey(x), text: x.label + (x.total ? '' : ' (명렬 없음)'), selected: current === slotKey(x) })));
    return s;
  }
  function newBatch() {
    if (!R.slots.length) { alertBox('담당이 없습니다. 명렬·담당 관리에서 먼저 추가하세요.'); return; }
    openSheet((box) => {
      box.style.height = 'auto';
      box.style.width = 'min(560px, 92vw)';
      const title = el('input', { type: 'text', placeholder: '예: 1학기 진로 학습지, 독서 기록' });
      const slot = slotSelect(R.slot ? slotKey(R.slot) : null);
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '새 자료 묶음' })]),
        el('label', { text: '묶음 이름' }), title,
        el('label', { text: '대상 명렬 · 보낼 항목' }), slot,
        el('p', { class: 'hint', text: '먼저 정해 두면 매칭 후보가 그 명렬로 좁혀지고, 정제 지침도 그 항목의 지침을 씁니다. 보내기 전에 바꿀 수 있습니다.' }),
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', class: 'primary', text: '만들기', onclick: async () => {
            const [gid, item] = slot.value.split(':');
            const r = await mutate('inbox_create', title.value, +gid, item);
            if (!r) return;
            closeSheet();
            IB.bid = r.id;
            IB.raw = null;
            await renderInbox();
          } })]));
      setTimeout(() => title.focus(), 50);
    });
  }
  let batchReq = 0;
  async function loadBatch() {
    const req = ++batchReq;
    const bid = IB.bid;
    const r = await call('inbox_view', bid);
    if (!r || req !== batchReq || bid !== IB.bid) return;
    r.sentRows = r.rows.filter((x) => x.state === 'sent');
    r.rows = r.rows.filter((x) => x.state !== 'sent');
    IB.view = r;
    { const t = await rawCall('tags'); IB.tags = t && t.ok ? t.tags : IB.tags || []; }
    refreshInboxBadge().then(renderInboxList);
    const b = r.batch;
    if (b.meta && b.meta.raw && !IB.raw) { IB.raw = b.meta.raw; IB.opts = Object.assign({ structure: b.structure }, b.meta.opts || {}); }
    renderBatch();
  }
  function stepsBar(stage) {
    const order = ['import', 'match', 'refine', 'review'];
    const idx = stage === 'sent' ? 4 : order.indexOf(stage);
    const refined = !!(IB.view && (IB.view.rows || []).some((r) => r.cands && r.cands.length));
    return el('div', { class: 'steps-bar' }, ['1 가져오기', '2 학생 매칭', '3 AI 정제(선택)', '4 보내기 검토'].map((t, i) => el('span', {
      class: i === idx ? 'active' : i < idx ? (i === 2 && !refined ? 'skipped' : 'done') : '', text: t })));
  }
  function renderBatch() {
    const m = $('ibMain');
    m.innerHTML = '';
    const b = IB.view.batch;
    const sent = b.stage === 'sent';
    const hasSent = IB.view.sentRows.length > 0;
    const title = el('input', { type: 'text', value: b.title });
    title.addEventListener('change', async () => { if (await mutate('inbox_update', b.id, { title: title.value })) { refreshInboxBadge().then(renderInboxList); } });
    const slot = slotSelect(`${b.group_id}:${b.item}`);
    slot.disabled = hasSent;
    if (hasSent) slot.title = '이미 보낸 행이 있어 대상 명렬·항목을 바꿀 수 없습니다';
    slot.addEventListener('change', async () => {
      const [gid, item] = slot.value.split(':');
      if (+gid !== b.group_id && IB.view.rows.length && !(await confirmBox('대상 명렬을 바꾸면 학생 매칭을 처음부터 다시 합니다. 계속할까요?', '바꾸기'))) { slot.value = `${b.group_id}:${b.item}`; return; }
      if (await mutate('inbox_update', b.id, { group_id: +gid, item })) { await refreshInboxBadge(); renderInboxList(); loadBatch(); }
    });
    m.appendChild(el('div', { class: 'ib-head' }, [title, el('span', { class: 'muted', text: '→' }), slot, el('span', { class: 'spacer' }),
      hasSent ? el('span', { class: 'stage-chip sent', text: `보낸 기록 ${b.sent_summary} · 마지막 ${b.sent_at}` }) : el('button', { type: 'button', class: 'link danger-text', text: '묶음 삭제', onclick: async () => {
        if (!(await typedConfirm(`'${b.title}' 묶음을 지웁니다. 아직 보내지 않은 자료는 사라집니다.`, '삭제'))) return;
        if (await mutate('inbox_delete', b.id)) { IB.bid = null; renderInbox(); }
      } })]));
    m.appendChild(stepsBar(b.stage));
    if (hasSent && !sent) m.appendChild(sentFold(false));
    const body = el('div', {});
    m.appendChild(body);
    if (b.stage === 'import') renderImport(body);
    else if (b.stage === 'match') renderMatch(body);
    else if (b.stage === 'refine') renderRefine(body);
    else if (b.stage === 'review') renderReview(body);
    else renderSent(body);
  }

  // ① 가져오기
  function renderImport(body) {
    const b = IB.view.batch;
    if (b.source === 'scan' && b.meta.scan) { renderScan(body); return; }
    if (IB.shared && IB.shared.bid !== b.id) IB.shared = null;
    if (!IB.shared && b.structure === 'shared' && b.meta.shared && !IB.raw && IB.sharedOff !== b.id) IB.shared = sharedState(b, b.meta.shared);
    if (IB.view.sentRows.length) body.appendChild(el('div', { class: 'note', text: `이미 보낸 ${IB.view.sentRows.length}건은 그대로 두고, 새로 가져온 자료만 덧붙여 보냅니다. 태그는 앞 회차와 같게 붙습니다.` }));
    if (IB.shared) { renderShared(body); return; }
    if (!IB.raw) {
      const ta = el('textarea', { rows: 8, placeholder: '또는 여기를 누르고 Ctrl+V로 붙여넣은 뒤 [읽기]' });
      body.append(
        el('p', { text: '자료를 가져오세요. 엑셀에서 학생 칸과 내용 칸을 드래그해 복사하면 셀마다 기록 한 건으로 나눕니다.' }),
        el('div', { class: 'src-btns' }, [
          el('button', { type: 'button', class: 'primary', text: '📋 엑셀 붙여넣기(클립보드)', onclick: async () => { const c = await api.read_clipboard(); const t = c && c.ok ? c.text : ''; if (!t.trim()) { toast('클립보드가 비어 있습니다. 아래 칸에 직접 붙여넣어도 됩니다.'); ta.focus(); return; } loadSource(() => call('inbox_source_text', b.id, t)); } }),
          el('button', { type: 'button', text: '📂 xlsx 불러오기', onclick: () => loadSource(async () => {
            const r = await call('inbox_source_xlsx', b.id);
            if (!r || !r.sheets) return r;
            const sh = await pickSheets(r, false);
            return sh ? call('inbox_source_xlsx', b.id, r.token, sh[0]) : null;
          }) }),
          el('button', { type: 'button', text: '🖨 스캔 PDF (CLOVA OCR)', onclick: () => startScanPick(b) }),
          el('button', { type: 'button', title: '학번 없는 모둠·개인 보고서처럼 한 문서를 고른 학생 모두에게 같은 원문으로 넣습니다', text: '📄 한 문서 → 여러 학생', onclick: () => { IB.shared = sharedState(b, b.meta.shared); renderBatch(); } }),
        ]),
        ta,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '읽기', onclick: () => loadSource(() => call('inbox_source_text', b.id, ta.value)) })]),
      );
      return;
    }
    const o = IB.opts;
    const members = IB.view.members;
    const seg = (key, choices) => el('div', { class: 'segmented' }, choices.map(([v, t]) => el('button', { type: 'button', class: 'seg' + (o[key] === v ? ' active' : ''), text: t, onclick: () => { o[key] = v; renderBatch(); } })));
    const lineOpts = () => {
      const g = o.orient === 'cols' ? IB.raw[0].map((_, j) => IB.raw.map((r) => r[j] || '')) : IB.raw.map((r) => r);
      const width = Math.max(...g.map((r) => r.length));
      const first = g[o.header ? 1 : 0] || [];
      const head = o.header ? g[0] || [] : first;
      return Array.from({ length: width }, (_, j) => [j, `${o.orient === 'cols' ? `${j + 1}행` : `${colName(j)}열`} ${(head[j] || '').replace(/_x000D_/g, '').replace(/\s+/g, ' ').slice(0, 12)}`]);
    };
    const ctrl = el('div', { class: 'map-row' }, [seg('structure', [['multi', '여러 학생에게'], ['single', '한 학생에게 여러 건']])]);
    if (o.structure === 'single') {
      ctrl.append(el('label', {}, ['학생', el('select', { onchange: (e) => { o.student_no = e.target.value; renderBatch(); } }, [el('option', { value: '', text: '학생 고르기' }), ...members.map((x) => el('option', { value: x.student_no, text: `${x.student_no} ${x.name}`, selected: o.student_no === x.student_no }))])]),
        el('span', { text: '읽는 순서' }), seg('order', [['row', '행 우선(→)'], ['col', '열 우선(↓)']]));
    } else {
      ctrl.append(seg('orient', [['rows', '한 행이 한 학생'], ['cols', '한 열이 한 학생']]),
        el('button', { type: 'button', text: '가로↔세로 바꾸기', onclick: () => { o.orient = o.orient === 'cols' ? 'rows' : 'cols'; o.no_idx = null; o.name_idx = null; o.roles = null; renderBatch(); } }));
    }
    ctrl.append(el('label', {}, [el('input', { type: 'checkbox', checked: !!o.header, onchange: (e) => { o.header = e.target.checked; o.roles = null; renderBatch(); } }), '첫 줄은 머리글(날짜·회차 제목)']));
    body.appendChild(ctrl);
    const roleBox = el('div', {});
    if (o.structure === 'multi') body.appendChild(roleBox);
    const left = el('div', { class: 'prev-box' });
    const right = el('div', { class: 'prev-box mk-list' });
    const summary = el('span', {});
    const go = el('button', { type: 'button', class: 'primary', text: '확정하고 매칭으로' });
    body.append(el('div', { class: 'split2' }, [el('div', {}, [el('div', { class: 'col-label', text: '원본 셀 미리보기' }), left]), el('div', {}, [el('div', { class: 'col-label', text: '만들어질 기록' }), right])]),
      el('div', { class: 'sheet-foot' }, [summary, el('span', { class: 'spacer' }), el('button', { type: 'button', text: '다시 가져오기', onclick: () => { IB.raw = null; renderBatch(); } }), go]));
    go.addEventListener('click', async () => {
      const r = await mutate('inbox_import', b.id, o);
      if (!r) return;
      toast(`${r.count}건을 만들었습니다. 학생 매칭을 확인하세요.`);
      await refreshInboxBadge();
      renderInboxList();
      loadBatch();
    });
    (async () => {
      const r = await call('inbox_preview', b.id, o);
      if (!r) return;
      IB.preview = r.rows;
      if (o.structure === 'multi') {
        if (!o.roles) { o.roles = r.roles || {}; o.neis = !!r.neis; }
        renderRoles(roleBox, o, lineOpts(), r.rows);
      }
      const roleOf = (k) => (o.structure === 'multi' && o.roles ? o.roles[String(k)] || '' : '');
      // 셀 색: 학번·이름 줄, 제목 줄, 학생별 내용, 빈 칸
      const lineOf = {};
      r.rows.forEach((x) => { lineOf[x.source_ref] = x.line; });
      const t = el('table', { class: 'grid-prev' });
      const width = Math.max(...IB.raw.map((x) => x.length));
      const badge = (k) => { const rl = roleOf(k); return rl ? el('span', { class: `role-badge r-${rl}`, text: IB_ROLE[rl] }) : null; };
      t.appendChild(el('tr', {}, [el('th', { text: '' }), ...Array.from({ length: width }, (_, j) => el('th', { class: o.orient !== 'cols' && o.structure === 'multi' && !roleOf(j) ? 'c-off' : '' }, [colName(j), o.orient !== 'cols' ? badge(j) : null]))]));
      IB.raw.forEach((row, i) => {
        const tr = el('tr', {}, [el('th', { class: o.orient === 'cols' && o.structure === 'multi' && !roleOf(i) ? 'c-off' : '' }, [String(i + 1), o.orient === 'cols' ? badge(i) : null])]);
        for (let j = 0; j < width; j++) {
          const v = row[j] || '';
          const ref = `${colName(j)}${i + 1}`;
          let cls = '';
          const lineIdx = o.orient === 'cols' ? j : i;
          const posIdx = o.orient === 'cols' ? i : j;
          if (o.header && lineIdx === 0 && (o.structure === 'multi' || i === 0)) cls = 'c-head';
          else if (o.structure === 'multi' && IB_ID_ROLES.includes(roleOf(posIdx))) cls = `c-id r-${roleOf(posIdx)}`;
          else if (ref in lineOf) cls = `c-l${(lineOf[ref] || 0) % 4}`;
          else if (o.structure === 'multi' && !roleOf(posIdx)) cls = 'c-off';
          else if (!v) cls = 'c-skip';
          tr.appendChild(el('td', { class: cls, title: v, text: v }));
        }
        t.appendChild(tr);
      });
      left.appendChild(t);
      r.rows.forEach((x) => right.appendChild(el('div', { class: 'mk' }, [el('b', { text: o.structure === 'single' ? (members.find((mm) => mm.student_no === o.student_no) || {}).name || '(학생 고르기)' : `${x.ext_no || x.ext_cls || '학번?'} ${x.ext_name || ''}`.trim() }),
        el('span', { class: 'tag', text: x.label }), x.date ? el('span', { class: 'muted', text: x.date + ' ' }) : null, x.content.slice(0, 70) + (x.content.length > 70 ? '…' : '')])));
      if (!r.rows.length) right.appendChild(el('p', { class: 'muted', text: '만들어질 기록이 없습니다.' }));
      const students = new Set(r.rows.map((x) => (o.structure === 'single' ? 's' : `${x.line}`))).size;
      const empty = IB.raw.reduce((a, row) => a + row.filter((v) => !v).length, 0);
      summary.innerHTML = '';
      summary.append(el('b', { text: `${o.structure === 'single' ? 1 : students}명 / ${r.rows.length}건 생성 예정` }), el('span', { class: 'muted', text: ` · 빈 셀 ${empty}개 제외 · 확정 전에는 항목에 아무것도 들어가지 않습니다` }));
      go.disabled = !r.rows.length || (o.structure === 'single' && !o.student_no);
    })();
  }
  // 인박스 열 역할: 열(한 열이 한 학생이면 행)마다 학번·학년·반·번호·반/번호·이름·학적변동·내용·안 씀
  const IB_ROLE = { student_no: '학번', grade: '학년', class_no: '반', number: '번호', clsnum: '반/번호', name: '이름', change: '학적변동', content: '내용' };
  const IB_ID_ROLES = ['student_no', 'grade', 'class_no', 'number', 'clsnum', 'name', 'change'];
  function renderRoles(box, o, lines, rows) {
    box.innerHTML = '';
    if (o.neis) box.appendChild(el('div', { class: 'info neis-note', text: '나이스 파일로 알아봤어요. 학년·반/번호·성명·특기사항 열을 맞췄고, 반/번호(1/1)는 반·번호로 나눠 명렬과 맞춥니다. 학생개인번호는 학번이 아니라서 쓰지 않습니다.' }));
    const roles = o.roles || {};
    const has = (r) => Object.values(roles).includes(r);
    if (has('student_no') && (has('grade') || has('class_no') || has('number') || has('clsnum'))) box.appendChild(el('div', { class: 'muted small-note', text: '학번과 학년·반·번호를 함께 고르면 둘 다 맞는지 확인합니다. 보통은 한쪽만 있으면 됩니다.' }));
    const sample = rows.find((x) => x.ext_cls);
    const grid = el('div', { class: 'role-grid' });
    lines.forEach(([j, label]) => {
      const cur = roles[String(j)] || '';
      const sel = el('select', { class: cur ? `r-${cur}` : '', onchange: (e) => {
        const v = e.target.value;
        const next = { ...roles };
        if (v && v !== 'content') Object.keys(next).forEach((k) => { if (next[k] === v) delete next[k]; }); // 내용 말고는 한 열만
        if (v) next[String(j)] = v; else delete next[String(j)];
        o.roles = next; o.neis = false;
        renderBatch();
      } }, [el('option', { value: '', text: '안 씀' }), ...Object.entries(IB_ROLE).map(([k, t]) => el('option', { value: k, text: t, selected: cur === k }))]);
      grid.appendChild(el('label', { class: 'role-cell' + (cur ? '' : ' off') }, [el('span', { class: 'role-name', text: label }), sel]));
    });
    box.append(el('div', { class: 'col-label', text: '열 고르기 — 학생을 찾을 열(학번 또는 학년·반·번호, 이름)과 내용 열' }), grid);
    if (sample) box.appendChild(el('div', { class: 'muted small-note', text: `읽은 예: ${sample.ext_cls}${sample.ext_name ? ' ' + sample.ext_name : ''}` }));
    if (!Object.values(roles).some((r) => IB_ID_ROLES.includes(r) && r !== 'change')) box.appendChild(el('div', { class: 'warn', text: '학생을 찾을 열(학번·이름 또는 학년·반·번호)을 골라 주세요. 한 학생의 자료라면 [한 학생에게 여러 건]을 고르세요.' }));
    else if (!has('content')) box.appendChild(el('div', { class: 'warn', text: '내용 열을 하나 이상 골라 주세요.' }));
  }
  // ① 가져오기: 한 문서 → 여러 학생(학번 없는 모둠·개인 보고서). 같은 원문을 고른 학생마다 한 건씩, 학생별 역할 메모는 원문 아래 한 줄로.
  function sharedState(b, saved) {
    const s = saved || {};
    return { bid: b.id, text: s.text || '', label: s.label || '', date: s.date || '', roles: new Map((s.picks || []).map((p) => [p.student_no, p.role || ''])), q: '', cls: '', tag: '', newTag: '' };
  }
  function renderShared(body) {
    const b = IB.view.batch, st = IB.shared;
    const members = IB.view.members.filter((m) => m.active);
    const ta = el('textarea', { rows: 10, class: 'sh-text', placeholder: '보고서 내용을 붙여넣거나 아래 버튼으로 파일에서 읽어 오세요(학번·이름이 없어도 됩니다).', 'aria-label': '문서 내용' });
    ta.value = st.text;
    const count = el('span', { class: 'muted' });
    const showCount = () => { count.textContent = `${ta.value.trim().length}자`; };
    ta.addEventListener('input', () => { st.text = ta.value; showCount(); });
    showCount();
    const put = (t) => { if (!t) return; st.text = t.trim(); ta.value = st.text; showCount(); };
    const label = el('input', { type: 'text', maxlength: 80, value: st.label, placeholder: '예: 기후 위기 모둠 보고서', oninput: (e) => { st.label = e.target.value; } });
    const date = el('input', { type: 'date', value: st.date, onchange: (e) => { st.date = e.target.value; } });
    // 태그: 고르거나 새로 만들기(보낼 때 붙고, 보낸 뒤 [🤖 태그로 AI 변환]으로 이어짐)
    const tagSel = el('select', { 'aria-label': '태그', onchange: (e) => { st.tag = e.target.value; newTag.hidden = st.tag !== 'new'; } },
      [el('option', { value: '', text: '태그 없음' }), ...(IB.tags || []).map((t) => el('option', { value: t.id, text: t.name, selected: String(t.id) === String(st.tag) })), el('option', { value: 'new', text: '+ 새 태그', selected: st.tag === 'new' })]);
    const newTag = el('input', { type: 'text', maxlength: 30, placeholder: '새 태그 이름', value: st.newTag, oninput: (e) => { st.newTag = e.target.value; } });
    newTag.hidden = st.tag !== 'new';
    // 학생 고르기
    const classes = [...new Set(members.map((m) => `${m.grade}-${m.class_no}`))];
    const clsSel = classes.length > 1 ? el('select', { 'aria-label': '반', onchange: (e) => { st.cls = e.target.value; drawList(); } },
      [el('option', { value: '', text: '모든 반' }), ...classes.map((c) => el('option', { value: c, selected: st.cls === c, text: `${c.replace('-', '학년 ')}반` }))]) : null;
    const q = el('input', { type: 'text', placeholder: '이름·학번 찾기', value: st.q, oninput: (e) => { st.q = e.target.value; drawList(); } });
    const list = el('div', { class: 'sh-list' });
    const picked = el('b', {});
    const visible = () => members.filter((m) => (!st.cls || `${m.grade}-${m.class_no}` === st.cls) && (!st.q.trim() || `${m.student_no} ${m.name}`.includes(st.q.trim())));
    const drawPicked = () => { picked.textContent = `고른 학생 ${st.roles.size}명`; go.disabled = !st.roles.size; };
    const drawList = () => {
      list.innerHTML = '';
      const vs = visible();
      if (!vs.length) list.appendChild(el('p', { class: 'muted', text: '맞는 학생이 없습니다.' }));
      vs.forEach((m) => {
        const on = st.roles.has(m.student_no);
        const role = el('input', { type: 'text', class: 'sh-role', maxlength: 200, disabled: !on, value: st.roles.get(m.student_no) || '', placeholder: on ? '역할·기여 메모(선택): 예) 자료 조사·발표' : '',
          'aria-label': `${m.name} 역할 메모`, oninput: (e) => { st.roles.set(m.student_no, e.target.value); } });
        const cb = el('input', { type: 'checkbox', checked: on, 'aria-label': `${m.name} 고르기`, onchange: (e) => {
          if (e.target.checked) st.roles.set(m.student_no, st.roles.get(m.student_no) || ''); else st.roles.delete(m.student_no);
          role.disabled = !e.target.checked; role.placeholder = e.target.checked ? '역할·기여 메모(선택): 예) 자료 조사·발표' : '';
          row.classList.toggle('on', e.target.checked); drawPicked();
          if (e.target.checked) role.focus();
        } });
        const row = el('div', { class: 'sh-row' + (on ? ' on' : '') }, [el('label', { class: 'inline', style: 'margin:0' }, [cb, el('span', { class: 'muted', text: m.student_no }), el('b', { text: m.name })]), role]);
        list.appendChild(row);
      });
    };
    const go = el('button', { type: 'button', class: 'primary', text: '확정하고 매칭으로' });
    go.addEventListener('click', async () => {
      if (!st.text.trim()) { toast('문서 내용을 넣어 주세요.'); ta.focus(); return; }
      if (!st.roles.size) { toast('넣을 학생을 골라 주세요.'); return; }
      let tagId = st.tag && st.tag !== 'new' ? +st.tag : null;
      if (st.tag === 'new') {
        const nm = st.newTag.trim();
        if (!nm) { toast('새 태그 이름을 적어 주세요.'); newTag.focus(); return; }
        const ex = (IB.tags || []).find((t) => t.name === nm);
        if (ex) tagId = ex.id; else { const t = await mutate('add_tag', nm); if (!t) return; tagId = t.id; IB.tags = t.tags; }
      }
      const order = members.map((m) => m.student_no).filter((n) => st.roles.has(n));
      const r = await mutate('inbox_shared', b.id, { text: st.text, label: st.label, date: st.date, picks: order.map((n) => ({ student_no: n, role: st.roles.get(n) || '' })) });
      if (!r) return;
      if (tagId && !(await mutate('inbox_update', b.id, { tag_ids: [tagId] }))) return;
      IB.shared = null;
      toast(`${r.count}명에게 같은 문서를 넣을 준비를 했습니다. 확인한 뒤 보내세요.`);
      await refreshInboxBadge();
      renderInboxList();
      loadBatch();
    });
    body.append(
      el('div', { class: 'tw-row' }, [el('b', { text: '📄 한 문서 → 여러 학생' }), el('span', { class: 'muted', text: '같은 문서를 고른 학생마다 학생관찰기록 한 건씩 넣습니다. 넣은 뒤에는 학생마다 따로 고칠 수 있습니다.' }), el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'link', text: '← 다른 방식으로 가져오기', onclick: () => { IB.shared = null; IB.sharedOff = b.id; renderBatch(); } })]),
      el('div', { class: 'sh-grid' }, [
        el('div', { class: 'sh-doc' }, [
          el('div', { class: 'tw-row' }, [el('div', { class: 'col-label', text: '문서 내용' }), count, el('span', { class: 'spacer' }),
            el('button', { type: 'button', class: 'small', text: '📋 붙여넣기', onclick: async () => { const c = await api.read_clipboard(); put(c && c.ok ? c.text : ''); } }),
            el('button', { type: 'button', class: 'small', text: '📄 PDF', title: '글자가 있는 PDF', onclick: async () => { const r2 = await call('standards_read_file', 'pdf'); if (r2) put(r2.text); } }),
            el('button', { type: 'button', class: 'small', text: '📝 한글(hwpx)', onclick: async () => { const r2 = await call('standards_read_file', 'hwpx'); if (r2) put(r2.text); } })]),
          ta,
          el('div', { class: 'tw-row' }, [el('label', { class: 'inline', style: 'margin:0' }, ['활동명', label]), el('label', { class: 'inline', style: 'margin:0' }, ['날짜', date])]),
          el('div', { class: 'tw-row' }, [el('label', { class: 'inline', style: 'margin:0' }, ['태그', tagSel]), newTag,
            el('span', { class: 'muted small-note', text: '보낸 뒤 [🤖 태그로 AI 변환]으로 학생마다 다르게 고칩니다.' })])]),
        el('div', { class: 'sh-pick' }, [
          el('div', { class: 'tw-row' }, [picked, el('span', { class: 'spacer' }), clsSel, q]),
          el('div', { class: 'tw-row' }, [
            el('button', { type: 'button', class: 'small', text: '보이는 학생 모두 고르기', onclick: () => { visible().forEach((m) => { if (!st.roles.has(m.student_no)) st.roles.set(m.student_no, ''); }); drawList(); drawPicked(); } }),
            el('button', { type: 'button', class: 'small', text: '모두 풀기', onclick: () => { st.roles.clear(); drawList(); drawPicked(); } })]),
          list,
          el('p', { class: 'hint', text: '역할 메모는 원문 아래 "[이 학생의 역할] …" 한 줄로 따로 붙어, AI 변환 때 학생마다 다르게 쓰는 근거가 됩니다.' })])]),
      el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), go]));
    drawList(); drawPicked();
  }
  async function loadSource(fn) {
    const r = await fn();
    if (!r) return;
    IB.raw = r.raw;
    IB.opts = Object.assign({ structure: IB.view.batch.structure || 'multi', order: 'row' }, r.opts);
    if (!IB.opts.found) IB.opts.structure = IB.view.members.length ? IB.opts.structure : 'multi';
    renderBatch();
  }

  // ② 학생 매칭
  function renderMatch(body) {
    const v = IB.view;
    const b = v.batch;
    const c = v.counts;
    const pending = c.suggested + c.none;
    if (!v.members.length) {
      body.appendChild(el('div', { class: 'warn' }, ['이 담당의 명렬이 비어 있어 학생을 연결할 수 없습니다. ',
        el('button', { type: 'button', class: 'primary', text: '명렬 등록하러 가기', onclick: () => { returnTo = { panel: 'inbox', bid: b.id }; rosterSel = b.group_id; showPanel('roster'); } })]));
    }
    body.appendChild(el('div', { class: 'toolbar' }, [
      el('b', { text: `확정 ${c.confirmed}` }), el('span', { class: pending ? 'danger-text' : 'muted', style: 'font-weight:800', text: `확인 필요 ${pending}` }), el('span', { class: 'muted', text: `제외 ${c.excluded}` }),
      el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', checked: IB.onlyPending, onchange: (e) => { IB.onlyPending = e.target.checked; renderBatch(); } }), '확인 필요만 보기']),
      el('span', { class: 'spacer' }),
      el('button', { type: 'button', disabled: !c.suggested, text: `추천 ${c.suggested}건 일괄 확정`, onclick: async () => {
        if (!(await confirmBox('추천은 학번·이름이 완전히 맞지 않아 앱이 짐작한 연결입니다. 원본과 대조해 보셨나요? 추천 모두를 확정합니다.', '확정'))) return;
        if (await mutate('inbox_confirm_suggested', b.id)) loadBatch();
      } }),
      el('button', { type: 'button', text: '명렬 등록·수정', onclick: () => { returnTo = { panel: 'inbox', bid: b.id }; rosterSel = b.group_id; showPanel('roster'); } }),
      b.source === 'scan' ? el('button', { type: 'button', text: '페이지 다시 묶기', onclick: async () => { if (!(await confirmBox('페이지 묶기로 돌아갑니다. OCR은 다시 하지 않지만 지금 매칭 결과는 새로 만들어집니다.', '돌아가기'))) return; if (await mutate('inbox_stage', b.id, 'import')) { SC.starts = null; loadBatch(); } } }) : null,
      el('button', { type: 'button', text: '다시 매칭', title: '확정·제외하지 않은 행을 명렬과 다시 맞춥니다', onclick: async () => { if (await mutate('inbox_rematch', b.id)) loadBatch(); } }),
    ]));
    const t = el('table', { class: 'tbl match-tbl' });
    t.appendChild(el('tr', {}, ['순서', '원본 위치', '읽은 학번·이름', '연결할 학생', '상태', '내용', ''].map((h) => el('th', { text: h }))));
    const sortItems = [];
    v.rows.filter((r) => !IB.onlyPending || r.state === 'none' || r.state === 'suggested').forEach((r) => {
      const sel = el('select', { disabled: r.state === 'excluded' || b.structure === 'single', onchange: async (e) => { if (await mutate('inbox_set_student', r.id, e.target.value)) loadBatch(); } },
        [el('option', { value: '', text: '학생 고르기' }), ...v.members.map((x) => el('option', { value: x.student_no, text: `${x.student_no} ${x.name}`, selected: x.student_no === r.student_no }))]);
      const stateTd = el('td', {}, [el('div', { class: `st-chip ${r.state}`, text: ST_CHIP[r.state] + (r.state === 'excluded' ? ` (${r.exclude_reason})` : '') }),
        r.note && r.state !== 'confirmed' ? el('div', { class: 'note', text: r.note }) : null,
        r.dup ? el('div', { class: 'note', text: '같은 학생이 원본의 다른 줄에도 있음(중복 의심)' }) : null,
        r.state === 'suggested' ? el('button', { type: 'button', class: 'small', text: '확정', onclick: async () => { if (await mutate('inbox_confirm_suggested', b.id, [r.id])) loadBatch(); } }) : null]);
      const holder = el('td', {});
      const tr = el('tr', { class: r.state === 'excluded' ? 'row-excluded' : (r.state === 'none' || r.state === 'suggested') ? 'row-pending' : '' }, [
        holder, el('td', { text: r.source_ref }), el('td', { text: `${r.ext_no || r.ext_cls || '-'} ${r.ext_name || ''}` }), el('td', {}, [sel]), stateTd,
        el('td', {}, [el('div', { class: 'snip', text: b.source === 'scan' ? r.content : `[${r.label}${r.date ? ' ' + r.date : ''}] ${r.content}` }),
          r.pages ? el('button', { type: 'button', class: 'small', text: '원본 보기', onclick: () => showOriginal(b.id, r.pages.split(',')) }) : null]),
        el('td', {}, [r.state === 'excluded'
          ? el('button', { type: 'button', class: 'small', text: '제외 취소', onclick: async () => { if (await mutate('inbox_exclude', [r.id], '', false)) loadBatch(); } })
          : el('button', { type: 'button', class: 'small', text: '제외', onclick: () => excludeRows([r.id]) })]),
      ]);
      sortItems.push({ id: r.id, el: tr, holder });
      t.appendChild(tr);
    });
    // 행 순서: ⠿ 끌기·▲▼ (확인 필요만 보기 중에는 끔)
    const rowHandle = sortable(sortItems, async (ids) => { if (await mutate('inbox_reorder', b.id, ids)) loadBatch(); }, IB.onlyPending || sortItems.length < 2);
    sortItems.forEach((x) => x.holder.appendChild(rowHandle(x.id)));
    body.appendChild(t);
    body.appendChild(el('p', { class: 'hint', text: '학번과 이름이 모두 명렬과 맞으면 자동 확정, 이름만 맞거나 비슷하면 "추천"입니다. 추천은 원본과 대조한 뒤 확정하세요. 백지·다른 반 자료처럼 보내지 않을 행은 [제외]하면 인박스에 남습니다.' }));
    body.appendChild(el('div', { class: 'sheet-foot' }, [
      el('button', { type: 'button', text: '← 가져오기 다시', onclick: async () => { if (!(await confirmBox('가져오기 단계로 돌아가면 지금 매칭 결과는 다시 만들어집니다.', '돌아가기'))) return; if (await mutate('inbox_stage', b.id, 'import')) { SC.starts = null; loadBatch(); } } }),
      el('span', { class: 'spacer' }),
      pending ? el('span', { class: 'danger-text', style: 'font-weight:700', text: `확인 필요 ${pending}건은 넘어가면 넣지 않습니다.` }) : null,
      el('button', { type: 'button', class: 'primary', text: '다음: AI 정제(선택)', onclick: async () => {
        if (pending) {
          const msg = `확인이 필요한 ${pending}건(추천 ${c.suggested}·찾지 못함 ${c.none})은 내용을 넣지 않습니다.\n이 행들은 '제외(매칭 미확인)'로 바뀌고, 매칭 단계로 돌아와 [제외 취소]하면 되살릴 수 있습니다.\n\n계속할까요?`;
          if (!(await confirmBox(msg, '넣지 않고 다음으로'))) return;
        }
        if (await mutate('inbox_stage', b.id, 'refine', !!pending)) loadBatch();
      } }),
    ]));
  }
  function excludeRows(ids) {
    openSheet((box) => {
      box.style.height = 'auto';
      box.style.width = 'min(480px, 92vw)';
      let reason = '백지';
      const seg = el('div', { class: 'tagpick' });
      const draw = () => { seg.innerHTML = ''; ['백지', '다른 반', '명렬에 없음(전입 등)', '중복', '기타'].forEach((x) => seg.appendChild(el('button', { type: 'button', class: x === reason ? 'on' : '', text: x, onclick: () => { reason = x; draw(); } }))); };
      draw();
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `제외 이유 · ${ids.length}건` })]), seg,
        el('p', { class: 'hint', text: '제외한 행은 보내지 않고 이 묶음에 남습니다. 보내기 검토에서 제외 건수가 표시됩니다.' }),
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', class: 'primary', text: '제외', onclick: async () => { if (await mutate('inbox_exclude', ids, reason, true)) { closeSheet(); loadBatch(); } } })]));
    });
  }

  // ③ AI 정제(선택)
  function renderRefine(body) {
    const v = IB.view;
    const b = v.batch;
    const rows = v.rows.filter((r) => r.state === 'confirmed');
    const model = el('select', {});
    fillModelSelect(model);
    IB.sel = new Set([...IB.sel].filter((id) => rows.some((r) => r.id === id)));
    body.appendChild(el('div', { class: 'toolbar' }, [
      el('label', { class: 'inline', style: 'margin:0' }, ['모델', model]),
      el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', checked: IB.sel.size && IB.sel.size === rows.length, onchange: (e) => { IB.sel = new Set(e.target.checked ? rows.map((r) => r.id) : []); renderBatch(); } }), '전체 선택']),
      (() => { const yet = rows.filter((r) => !(r.cands || []).length); return el('button', { type: 'button', disabled: !yet.length, title: '정제 결과가 아직 없는 행만 고릅니다', text: `정제 안 한 행만 선택 (${yet.length})`, onclick: () => { IB.sel = new Set(yet.map((r) => r.id)); renderBatch(); } }); })(),
      el('button', { type: 'button', class: 'primary ai-btn', disabled: !IB.sel.size, text: `선택 ${IB.sel.size}건 정제`, onclick: () => refineRows(rows.filter((r) => IB.sel.has(r.id)), model.value, null, modelName(model)) }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'hint', style: 'margin:0', text: `${slotLabel(b.group_id, b.item)}의 '정제' 지침을 씁니다. AI에는 명렬의 학번·이름은 보내지 않습니다(본문에 적힌 이름은 그대로 갑니다).` }),
    ]));
    rows.forEach((r) => {
      const card = el('div', { class: 'ref-card' });
      card.appendChild(el('div', { class: 'rcard-head' }, [el('input', { type: 'checkbox', checked: IB.sel.has(r.id), onchange: (e) => { if (e.target.checked) IB.sel.add(r.id); else IB.sel.delete(r.id); renderBatch(); } }),
        el('b', { text: `${r.student_no} ${r.matched_name}` }), el('span', { class: 'tag', text: r.label }), r.date ? el('span', { class: 'muted', text: r.date }) : null, el('span', { class: 'muted', text: r.source_ref }),
        el('span', { class: 'spacer' }), bytesEl(r.bytes, 0)]));
      const usingOrig = r.used_text === null || r.used_text === undefined;
      const pickBox = el('div', { class: 'use-pick' }, [el('span', { class: 'muted', text: '보낼 내용:' }),
        el('button', { type: 'button', class: usingOrig ? 'on' : '', text: '원문', onclick: async () => { if (await mutate('inbox_use_cand', r.id, null)) loadBatch(); } }),
        ...r.cands.map((cd, i) => el('button', { type: 'button', class: !usingOrig && r.used_text === cd.text ? 'on' : '', text: `정제 ${i + 1}`, onclick: async () => { if (await mutate('inbox_use_cand', r.id, cd.id)) loadBatch(); } }))]);
      const btn = el('button', { type: 'button', class: 'small ai-btn', text: r.cands.length ? '다시 정제' : '정제(AI)' });
      btn.addEventListener('click', () => refineRows([r], model.value, btn, modelName(model)));
      // 정제 결과 칸: 정제한 내용을 골랐을 때만 보이고, 원문을 쓰면 비워 둔다(원문이 그대로 들어간다는 안내만)
      const refined = usingOrig ? el('div', { class: 'rcard-body rcard-empty', text: r.cands.length ? '원문을 고름 — 원문이 그대로 들어갑니다' : '정제하지 않음 — 원문이 그대로 들어갑니다' })
        : el('div', { class: 'rcard-body', text: r.text });
      card.append(el('div', { class: 'ref-cols' }, [el('div', {}, [el('div', { class: 'muted', text: '원문' }), el('div', { class: 'rcard-body', text: r.content })]),
        el('div', {}, [el('div', { class: 'muted', text: '정제 결과' }), refined])]), el('div', { class: 'rcard-foot' }, [pickBox, el('span', { class: 'spacer' }), btn]));
      body.appendChild(card);
    });
    body.appendChild(el('div', { class: 'sheet-foot' }, [
      el('button', { type: 'button', text: '← 매칭', onclick: async () => { if (await mutate('inbox_stage', b.id, 'match')) loadBatch(); } }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'hint', style: 'margin:0', text: 'AI 정제는 선택입니다. 정제하지 않은 행은 원문 그대로 보냅니다.' }),
      el('button', { type: 'button', class: 'primary', text: '다음: 보내기 검토', onclick: async () => {
        const orig = rows.filter((r) => r.used_text === null || r.used_text === undefined);
        if (orig.length) {
          const picked = orig.filter((r) => r.cands.length).length;
          const msg = `정제하지 않은 ${orig.length}건은 원문 그대로 들어갑니다${picked ? `(정제 후보가 있는데 원문을 고른 ${picked}건 포함)` : ''}.\n\n계속할까요?`;
          if (!(await confirmBox(msg, '원문 그대로 다음으로'))) return;
        }
        if (await mutate('inbox_stage', b.id, 'review')) loadBatch();
      } }),
    ]));
  }
  const ibPromptKey = (b) => `sgb.ibPrompt.${ys.year}.${b.id}`;
  const ibPromptKeyUse = (b) => b.source === 'scan' || localStorage.getItem(ibPromptKey(b)) !== null;
  function ibPromptPref(b) {
    const saved = localStorage.getItem(ibPromptKey(b));
    if (saved) return saved;
    return b.source === 'scan' ? 'scan' : '';
  }
  async function refineRows(rows, modelIndex, btn, modelLabel) {
    if (!rows.length) return;
    const b = IB.view.batch;
    // 스캔 PDF 묶음은 처음 값이 '스캔 내용 정리', 묶음마다 마지막에 고른 프롬프트를 기억
    const conf = await aiConfirm('인박스 자료 정제', [['묶음', `${b.title} → ${slotLabel(b.group_id, b.item)}`], ['대상', `${rows.length}건 (${new Set(rows.map((r) => r.student_no)).size}명)`], ['모델', modelLabel || '-']],
      '원문은 그대로 남습니다. 정제 후보는 행마다 최근 3개까지 보관하고, 넘으면 가장 오래된 후보를 지웁니다. 새 정제 결과를 보낼 내용으로 바로 골라 둡니다.', 'refine', ibPromptPref(b));
    if (conf && ibPromptKeyUse(b)) localStorage.setItem(ibPromptKey(b), conf.prompt || '');
    if (!conf) return;
    if (btn) { btn.disabled = true; btn.classList.add('busy-btn'); }
    await jobStart();
    let out;
    try {
      const failedIds = [];
      out = await aiRun({ title: '인박스 자료 정제', skipConfirm: true, extra: conf.extra, prompt: conf.prompt, kind: 'refine', remember: !ibPromptKeyUse(b),
        jobs: rows.map((r) => ({ label: `${r.name || r.student_no || ''} ${(r.content || '').slice(0, 16)}`.trim(), run: () => api.ai_inbox_row(r.id, modelIndex), onFail: () => failedIds.push(r.id) })),
        after: (o) => { out = o; o.retry = [...failedIds, ...o.notRun.map((i) => rows[i].id)]; } });
    } finally { await jobEnd(); if (btn && btn.isConnected) { btn.disabled = false; btn.classList.remove('busy-btn'); } }
    refreshBalance();
    // 실패·미실행 행만 골라 두어 [선택 N건 정제]로 이어서 돌릴 수 있게(성공한 행은 다시 하지 않음)
    IB.sel = new Set(out ? out.retry : []);
    if (out && (out.fail || out.skipped)) toast(`실패 ${out.fail}건·미실행 ${out.skipped}건을 선택해 두었습니다. [선택 ${IB.sel.size}건 정제]로 이어서 돌릴 수 있습니다.`, 6000);
    else if (out) toast(`${out.done}건을 정제했습니다. 보낼 내용으로 바로 골라 두었습니다.`);
    loadBatch();
  }

  // ④ 보내기 검토
  async function renderReview(body) {
    const b = IB.view.batch;
    const r = await call('inbox_review', b.id);
    if (!r) return;
    const date = el('input', { type: 'date', value: b.date || todayStr() });
    date.addEventListener('change', () => mutate('inbox_update', b.id, { date: date.value }));
    const tagsBox = el('div', { class: 'tagpick' });
    const tagSet = new Set(b.tag_ids || []);
    const tags = await call('tags');
    const drawTags = () => {
      tagsBox.innerHTML = '';
      (tags ? tags.tags : []).forEach((t) => tagsBox.appendChild(el('button', { type: 'button', class: (tagSet.has(t.id) ? 'on' : '') + tagC(t.id), text: t.name, onclick: async () => { if (tagSet.has(t.id)) tagSet.delete(t.id); else tagSet.add(t.id); drawTags(); await mutate('inbox_update', b.id, { tag_ids: [...tagSet] }); } })));
      if (!tags || !tags.tags.length) tagsBox.appendChild(el('span', { class: 'muted', text: '태그가 없습니다(메뉴의 태그에서 만들기).' }));
    };
    drawTags();
    const itemSel = slotSelect(`${b.group_id}:${b.item}`, b.group_id);
    itemSel.addEventListener('change', async () => { const [, item] = itemSel.value.split(':'); if (await mutate('inbox_update', b.id, { item })) loadBatch(); });
    body.append(
      el('div', { class: 'map-row' }, [el('label', {}, ['보낼 항목', itemSel]), el('label', {}, ['기본 날짜', date]), el('span', { class: 'hint', style: 'margin:0', text: '(제목 줄에 날짜가 있으면 그 날짜를 씁니다)' })]),
      el('label', { text: '태그 (보내는 모든 기록에 붙임)' }), tagsBox,
      el('div', { class: 'wsection' }, [
        el('h3', { text: `${r.students.length}명 ${r.send_rows}건 추가` }),
        el('div', { class: 'muted', text: `기존 기록 덮어쓰기 없음 · 제외 ${r.excluded}건 · 회차는 학생마다 이어서 붙습니다` }),
        el('div', { style: 'margin-top:8px' }, r.students.map((s) => el('span', { class: 'tag', text: `${s.name} ${s.count}건` }))),
      ]),
    );
    const sendBtn = el('button', { type: 'button', class: 'primary', text: `${r.students.length}명 ${r.send_rows}건 보내기` });
    const doSend = async (action) => {
      if (!tagSet.size && !(await confirmBox('태그를 고르지 않았습니다. 태그 없이 보낼까요?\n\n보낸 뒤에도 보낸 묶음 화면의 [태그 지정]으로 이 묶음의 기록 전체에 한꺼번에 붙일 수 있습니다.', '태그 없이 보내기'))) return;
      const res = await mutate('inbox_send', b.id, action);
      if (!res) return;
      const tids = [...tagSet];
      if (tids.length) actionToast(`${res.students}명 ${res.records}건 보냈습니다.`, tids.length > 1 ? '태그 골라 AI 변환하기' : '이 태그로 AI 변환하기', () => batchTagWork(b, tids), 15000);
      else toast(`${res.students}명 ${res.records}건 보냈습니다.`);
      await refreshInboxBadge();
      renderInboxList();
      loadBatch();
    };
    if (r.closed.length) {
      body.appendChild(el('div', { class: 'warn', style: 'margin-top:12px' }, [
        el('b', { text: `마감된 학생 ${r.closed.length}명: ` }), r.closed.map((s) => `${s.student_no} ${s.name}`).join(', '), el('br'),
        '마감된 학생에게는 그대로 보낼 수 없습니다. ',
        el('button', { type: 'button', text: '마감 해제하고 보내기', onclick: async () => { if (await confirmBox(`${r.closed.length}명의 마감을 해제하고 보냅니다. 보낸 뒤 다시 검토·마감하세요.`, '보내기')) doSend('reopen'); } }), ' ',
        el('button', { type: 'button', text: '이 학생들은 제외하고 보내기', onclick: () => doSend('exclude') }),
      ]));
      sendBtn.disabled = true;
    }
    sendBtn.addEventListener('click', () => doSend('block'));
    body.appendChild(el('div', { class: 'sheet-foot' }, [
      el('button', { type: 'button', text: '← 정제', onclick: async () => { if (await mutate('inbox_stage', b.id, 'refine')) loadBatch(); } }),
      el('span', { class: 'spacer' }), sendBtn]));
  }
  // 보낸 묶음: 이 묶음으로 넣은 기록 전체(여러 학생)에 태그 붙이기·빼기(20초 되돌리기)
  async function sentTags(b) {
    const info = await call('inbox_sent_info', b.id);
    if (!info) return;
    if (!info.record_ids.length) { toast('이 항목에 남아 있는 기록이 없습니다.'); return; }
    const all = await call('tags');
    const names = Object.fromEntries(((all && all.tags) || []).map((t) => [String(t.id), t.name]));
    const now = Object.entries(info.tag_counts).map(([id, n]) => `${names[id] || '?'} ${n}건`).join(', ');
    openSheet((box) => {
      box.style.height = 'auto';
      box.style.width = 'min(600px, 92vw)';
      const tags = tagPicker([], (all && all.tags) || []);
      const run = async (mode) => {
        const tids = tags.value();
        if (!tids.length) { toast('태그를 고르세요.'); return; }
        const r = await mutate('tag_records_undoable', info.record_ids, tids, mode);
        if (!r) return;
        closeSheet();
        const n = new Set(r.pairs.map((p) => p[0])).size;
        actionToast(`${n}건에 태그를 ${mode === 'add' ? '붙였습니다' : '뺐습니다'}.`, '되돌리기', async () => {
          if (await mutate('undo_tag_records', r.pairs, mode)) toast('되돌렸습니다.');
        }, 20000);
      };
      addTo(box, el('div', { class: 'sheet-head' }, [el('h2', { text: `이 묶음 기록에 태그 · ${info.students}명 ${info.record_ids.length}건` })]),
        el('p', { class: 'muted', text: now ? `지금 붙은 태그: ${now}` : '지금 붙은 태그가 없습니다.' }),
        info.moved ? el('p', { class: 'hint', text: `다른 항목으로 옮긴 ${info.moved}건은 빼고 합니다.` }) : null,
        tags,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', text: '고른 태그 빼기', onclick: () => run('remove') }),
          el('button', { type: 'button', class: 'primary', text: '고른 태그 붙이기', onclick: () => run('add') })]));
    });
  }
  async function sentTagWork(b) {
    const info = await call('inbox_sent_info', b.id);
    if (!info) return;
    const ids = Object.entries(info.tag_counts || {}).sort((x, y) => y[1] - x[1]).map(([id]) => +id);
    if (!ids.length) { toast('이 묶음 기록에 붙은 태그가 없습니다. 먼저 [🏷 이 묶음 기록에 태그 지정]으로 태그를 붙이세요.', 6000); return; }
    batchTagWork(b, ids);
  }
  // 묶음의 담당·항목 범위로 태그 변환 열기. 태그가 여럿이면 고르게 한다.
  async function batchTagWork(b, ids) {
    const g = (ys.groups || []).find((x) => x.id === b.group_id);
    const scope = g && g.kind === 'homeroom' ? `c:${g.grade}-${g.class_no}` : '';
    const slot = g && g.kind === 'homeroom' ? `i:${b.item}` : `g:${b.group_id}:${b.item}`;
    let tid = ids[0];
    if (ids.length > 1) {
      const all = await call('tags');
      const names = Object.fromEntries(((all && all.tags) || []).map((t) => [t.id, t.name]));
      tid = await new Promise((resolve) => openSheet((box) => {
        box.style.height = 'auto'; box.style.width = 'min(480px, 92vw)';
        box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '어느 태그로 AI 변환할까요?' })]),
          el('p', { class: 'hint', text: `범위: ${g ? g.label || g.name : ''} · ${ITEM_LABELS[b.item] || b.item}` }),
          el('div', { class: 'tw-applied-list' }, ids.map((id) => el('button', { type: 'button', text: names[id] || `태그 ${id}`, onclick: () => { closeSheet(); resolve(id); } }))),
          el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => { closeSheet(); resolve(null); } })]));
      }));
      if (!tid) return;
    }
    goTagWork(tid, slot, 'trial', scope);
  }
  // 보낸 묶음: 이 묶음으로 넣은 기록을 모든 학생에서 지우기(되돌릴 수 없음 → '확인했어요' 입력)
  // 이미 보낸 행: 접어 두고 고칠 수 없게(회차·학생·보낸 내용만)
  function sentFold(open) {
    const v = IB.view;
    const rounds = (v.batch.meta.rounds || []);
    const t = el('table', { class: 'tbl match-tbl ib-sent-tbl' });
    t.appendChild(el('tr', {}, ['회차', '원본 위치', '학생', '보낸 내용'].map((h) => el('th', { text: h }))));
    v.sentRows.forEach((r) => t.appendChild(el('tr', {}, [el('td', { text: r.round ? `${r.round}회` : '-' }), el('td', { text: r.source_ref }),
      el('td', { text: `${r.student_no || '-'} ${r.matched_name || r.ext_name || ''}` }), el('td', {}, [el('div', { class: 'snip', text: r.text })])])));
    return el('details', { class: 'ib-sent-fold', open: !!open }, [
      el('summary', {}, [el('b', { text: `✔ 이미 보낸 행 ${v.sentRows.length}건` }),
        el('span', { class: 'muted', text: ` — ${rounds.map((x) => `${x.n}회 ${String(x.at || '').slice(5, 16)} · ${x.summary}`).join(' / ')} (고칠 수 없음, 다시 보내지 않음)` })]), t]);
  }
  async function sentDelete(b, rnd) {
    const info = await call('inbox_sent_info', b.id, rnd || null);
    if (!info) return;
    const n = info.deletable.length;
    if (!n) { alertBox('지울 수 있는 기록이 없습니다(마감된 학생이거나 다른 항목으로 옮긴 기록만 남음).'); return; }
    const lines = [`${rnd ? `${rnd}회로` : '이 묶음으로'} 넣은 기록 ${n}건을 모든 학생에서 지웁니다.`];
    if (info.edited) lines.push(`· 보낸 뒤 고친 기록 ${info.edited}건도 함께 지워집니다.`);
    if (info.with_cands) lines.push(`· 정제 후보가 있는 기록 ${info.with_cands}건의 후보도 함께 지워집니다.`);
    if (info.closed) lines.push(`· 마감된 학생 ${info.closed_students}명의 기록 ${info.closed}건은 지우지 않습니다.`);
    if (info.moved) lines.push(`· 다른 항목으로 옮긴 ${info.moved}건은 지우지 않습니다.`);
    lines.push(info.closed || info.moved ? '남는 기록이 있는 회차는 보낸 것으로 그대로 둡니다.' : '지운 행은 다시 \'안 보냄\'이 되어 ④ 보내기 검토에서 고쳐 다시 보낼 수 있습니다.');
    if (!(await typedConfirm(lines.join('\n'), rnd ? `${rnd}회 삭제` : '모두 삭제'))) return;
    const r = await mutate('inbox_delete_sent', b.id, TYPED_WORD, rnd || null);
    if (!r) return;
    $('actionToast').hidden = true; // 지운 기록의 태그 되돌리기는 더 쓸 수 없음
    toast(`${r.students}명 ${r.deleted}건을 지웠습니다.${r.reopened ? ' 보내기 검토로 돌아왔습니다.' : ''}`, 5000);
    await refreshInboxBadge();
    renderInboxList();
    loadBatch();
  }
  function renderSent(body) {
    const v = IB.view;
    const b = v.batch;
    const rounds = b.meta.rounds || [];
    const moreBtn = el('button', { type: 'button', class: 'primary', text: '+ 자료 더 넣기', title: '같은 묶음(같은 항목·태그)에 새 자료를 가져와 아직 안 보낸 것만 보냅니다', onclick: async () => {
      if (await mutate('inbox_stage', b.id, 'import')) { IB.raw = null; IB.shared = null; await refreshInboxBadge(); renderInboxList(); loadBatch(); }
    } });
    body.append(el('div', { class: 'wsection', style: 'margin-top:0' }, [el('h3', { text: `✔ 보낸 기록 ${b.sent_summary}` }),
      el('p', { class: 'hint', text: '나중에 같은 활동의 자료가 더 생기면 [+ 자료 더 넣기]로 이 묶음에 가져와 보내세요. 이미 보낸 행은 접어 두고 다시 보내지 않습니다(기록 중복 방지). 태그는 앞 회차와 같게 붙습니다. 하나씩 고칠 때는 항목별 기록에서 합니다.' }),
      el('div', { class: 'ib-rounds' }, rounds.map((x) => el('div', { class: 'ib-round' }, [el('b', { text: `${x.n}회` }), el('span', { class: 'muted', text: String(x.at || '') }), el('span', { text: x.summary }),
        el('span', { class: 'spacer' }), el('button', { type: 'button', class: 'small link danger-text', text: '이 회차 기록 지우기', onclick: () => sentDelete(b, x.n) })]))),
      el('div', { class: 'toolbar' }, [
        moreBtn,
        el('button', { type: 'button', text: '항목별 기록에서 보기', onclick: () => openRecords(b.group_id, b.item, (v.sentRows[0] || {}).student_no) }),
        el('button', { type: 'button', text: '🏷 이 묶음 기록에 태그 지정', onclick: () => sentTags(b) }),
        el('button', { type: 'button', class: 'ai-btn', text: '🤖 태그로 AI 변환', title: '이 묶음 기록에 붙은 태그로 태그별 기록의 AI 변환을 엽니다', onclick: () => sentTagWork(b) }),
        el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'danger-text', text: '보낸 기록 모두 삭제', onclick: () => sentDelete(b) }),
        el('button', { type: 'button', class: 'link danger-text', text: '이력에서 지우기', title: '인박스 이력만 지웁니다(항목에 들어간 기록은 그대로)', onclick: async () => {
          const msg = `'${b.title}' 묶음을 인박스 이력에서 지웁니다.\n· 지우는 것: 가져온 원본 표, 매칭·정제 결과\n· 남는 것: 항목에 들어간 기록(그대로 남음)\n· 지운 뒤에는 이 묶음 단위로 태그 지정·모두 삭제를 할 수 없습니다. 기록까지 지우려면 먼저 [보낸 기록 모두 삭제]를 쓰세요.`;
          if (!(await typedConfirm(msg, '이력에서 지우기'))) return;
          if (await mutate('inbox_delete', b.id)) { IB.bid = null; await refreshInboxBadge(); renderInboxList(); renderInboxEmpty(); toast('이력에서 지웠습니다. 보낸 기록은 그대로입니다.'); }
        } }),
      ])]));
    body.appendChild(sentFold(true));
    if (v.rows.length) body.appendChild(el('p', { class: 'muted small-note', text: `보내지 않은 행 ${v.rows.length}건(제외 등)은 [+ 자료 더 넣기] 뒤 다시 가져오면 정리됩니다.` }));
  }

  // =====================================================================
  // v0.4: 스캔 PDF — CLOVA OCR, 페이지 묶기, 학번·이름 규칙 추출, 원본 보기
  // =====================================================================
  const SC = { starts: null, skipped: null, per: 1, timer: null, start: 0, bid: null };
  async function startScanPick(b) {
    const ready = await call('clova_ready');
    if (!ready) return;
    if (!ready.ready) {
      const go = await modal(`스캔 PDF를 글자로 읽으려면 <b>CLOVA OCR 키</b>가 필요합니다.<br>네이버 클라우드 플랫폼에 가입하고 CLOVA OCR을 설정한 뒤, 설정 &gt; 연결·모델에 ${ready.missing.join(', ')}를 넣어 주세요.<br><span class="muted">가입·발급 안내가 설정 화면에 있습니다.</span>`, true, true, '설정으로 가기');
      if (go) { showPanel('settings'); showSettingsTab('conn'); $('clovaGuide').open = true; $('clovaGuide').scrollIntoView(); }
      return;
    }
    const r = await call('inbox_scan_pick', b.id);
    if (!r) return;
    SC.starts = null;
    loadBatch();
  }
  function renderScan(body) {
    const b = IB.view.batch;
    const sc = b.meta.scan;
    if (!sc.ocr) {
      const per = el('input', { type: 'number', class: 'num', min: 1, value: sc.per || 1 });
      const est = el('span', { class: 'muted' });
      const upd = () => {
        const n = Math.max(1, +per.value || 1);
        const rem = sc.pages % n;
        est.textContent = `약 ${Math.ceil(sc.pages / n)}명분${rem ? ` · 나누어떨어지지 않음(마지막 학생 ${rem}쪽) — 다음 단계에서 고칠 수 있습니다` : ''}`;
      };
      per.addEventListener('input', upd);
      upd();
      body.append(
        el('div', { class: 'wsection', style: 'margin-top:0' }, [el('h3', { text: `🖨 ${sc.filename} · ${sc.pages}쪽` }),
          el('div', { class: 'map-row' }, [el('label', {}, ['학생 1명당 페이지 수', per]), est]),
          el('div', { class: 'hint', text: '단면 스캔은 1, 양면 스캔은 2입니다. 백지가 섞여 있어도 다음 단계에서 페이지를 빼거나 경계를 옮길 수 있습니다.' })]),
        el('div', { class: 'warn', style: 'margin-top:12px', html: '⚠ <b>스캔 이미지가 그대로 네이버 CLOVA OCR로 전송됩니다.</b> 손으로 쓴 이름·학번도 함께 전송됩니다. 걱정되면 스캔하기 전에 인적사항을 직접 가려 주세요.<br><span class="muted">AI(OpenRouter)에는 인식한 글에서 학번·이름 줄을 뺀 내용만 보냅니다.</span>' }),
        el('div', { class: 'sheet-foot' }, [el('button', { type: 'button', text: '다른 PDF 고르기', onclick: () => startScanPick(b) }), el('span', { class: 'spacer' }),
          el('button', { type: 'button', class: 'primary', text: 'OCR 시작', onclick: () => runOcr(b, Math.max(1, +per.value || 1)) })]),
      );
      return;
    }
    if (SC.bid !== b.id || !SC.starts) { SC.bid = b.id; SC.starts = sc.starts.slice(); SC.skipped = (sc.skipped || []).slice(); SC.per = sc.per || 1; }
    const per = el('input', { type: 'number', class: 'num', min: 1, value: SC.per });
    body.appendChild(el('div', { class: 'map-row' }, [el('b', { text: `🖨 ${sc.filename} · ${sc.ocr.length}쪽 OCR 완료` }), el('span', { class: 'spacer' }),
      el('label', {}, ['학생당 페이지 수', per]),
      el('button', { type: 'button', text: '이 간격으로 다시 나누기', onclick: () => { SC.per = Math.max(1, +per.value || 1); SC.starts = []; for (let i = 0; i < sc.ocr.length; i += SC.per) SC.starts.push(i); SC.skipped = []; renderBatch(); } })]));
    body.appendChild(el('p', { class: 'hint', text: '학생 경계가 밀렸다면 페이지의 [여기서 새 학생]을 켜고 끄세요. 백지·표지는 [빼기]. 학번·이름은 각 학생 첫 페이지 머리글에서 규칙으로 읽습니다(AI 미사용).' }));
    const list = el('div', {});
    const summary = el('span', {});
    const go = el('button', { type: 'button', class: 'primary', text: '확정하고 매칭으로' });
    body.append(list, el('div', { class: 'sheet-foot' }, [summary, el('span', { class: 'spacer' }), go]));
    go.addEventListener('click', async () => {
      const r = await mutate('inbox_scan_confirm', b.id, SC.starts, SC.skipped);
      if (!r) return;
      toast(`${r.count}명분을 만들었습니다. 학생 매칭을 확인하세요.`);
      SC.starts = null;
      loadBatch();
    });
    (async () => {
      const r = await call('inbox_scan_groups', b.id, SC.starts, SC.skipped);
      if (!r) return;
      const firstOf = {};
      r.groups.forEach((g) => { firstOf[g.pages[0]] = g; });
      const skip = new Set(SC.skipped);
      const starts = new Set(SC.starts);
      r.page_texts.forEach((t, p) => {
        const g = firstOf[p];
        if (g) list.appendChild(el('div', { class: 'sec-title', style: 'margin-top:10px' }, [`학생 ${g.index + 1}`,
          g.ext_no || g.ext_name ? el('span', { class: 'tag', text: `읽은 값: ${g.ext_no || '학번?'} ${g.ext_name || '이름?'}` }) : el('span', { class: 'tag warn-tag', text: '학번·이름을 읽지 못함' }),
          el('span', { class: 'muted', text: `${g.pages.map((x) => x + 1).join('·')}쪽` })]));
        const isSkip = skip.has(p);
        list.appendChild(el('div', { class: 'ref-card', style: isSkip ? 'opacity:.5' : '' }, [
          el('div', { class: 'rcard-head' }, [el('b', { text: `${p + 1}쪽` }),
            el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', disabled: p === 0, checked: p === 0 || starts.has(p), onchange: (e) => { if (e.target.checked) SC.starts.push(p); else SC.starts = SC.starts.filter((x) => x !== p); renderBatch(); } }), '여기서 새 학생']),
            el('button', { type: 'button', class: 'small', text: isSkip ? '되살리기' : '빼기(백지 등)', onclick: () => { if (isSkip) SC.skipped = SC.skipped.filter((x) => x !== p); else SC.skipped.push(p); renderBatch(); } }),
            el('button', { type: 'button', class: 'small', text: '원본 보기', onclick: () => showOriginal(b.id, [p]) }),
            t.trim() ? null : el('span', { class: 'tag warn-tag', text: '글자 없음' })]),
          el('div', { class: 'snip', style: 'max-width:none', text: t.split('\n').slice(0, 3).join('\n') || '(인식된 글자 없음)' }),
        ]));
      });
      summary.innerHTML = '';
      summary.append(el('b', { text: `${r.groups.filter((g) => !g.empty).length}명분` }), el('span', { class: 'muted', text: ` · 뺀 쪽 ${SC.skipped.length}개` }));
    })();
  }
  function runOcr(b, per) {
    let stopped = false;
    const msg = el('div', { class: 'modal-msg', text: 'CLOVA OCR에 보내는 중…' });
    const time = el('b', { text: '0:00' });
    const stopBtn = el('button', { type: 'button', class: 'btn-danger', text: '중지', onclick: () => { stopped = true; stopBtn.disabled = true; stopBtn.textContent = '중지 중…'; api.inbox_ocr_stop(); } });
    openSheet((box) => {
      box.style.height = 'auto';
      box.style.width = 'min(460px, 92vw)';
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: 'OCR 진행 중' })]), msg,
        el('div', { class: 'sheet-foot' }, [el('span', {}, ['경과 시간 ', time, ' — 멈춘 게 아니니 기다려 주세요']), el('span', { class: 'spacer' }), stopBtn]));
    });
    SC.start = Date.now();
    clearInterval(SC.timer);
    SC.timer = setInterval(() => { const s = Math.floor((Date.now() - SC.start) / 1000); time.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }, 1000);
    SC.msg = msg;
    api.inbox_scan_ocr(b.id, per).then((r) => {
      if (!r || !r.ok) { clearInterval(SC.timer); closeSheet(); alertBox((r && r.error) || 'OCR을 시작하지 못했습니다.'); }
    });
  }
  function ocrEvent(ev) {
    if (ev.type === 'ocr_progress') {
      if (SC.msg) SC.msg.textContent = `${ev.pages}쪽을 10쪽씩 나눠 읽는 중: ${ev.done + 1} / ${ev.total} 구간`;
      return;
    }
    clearInterval(SC.timer);
    closeSheet();
    if (ev.type === 'ocr_done') { toast(`${ev.pages}쪽을 읽었습니다. 학생별로 묶인 것을 확인하세요.`); SC.starts = null; }
    else if (ev.type === 'ocr_stopped') toast('OCR을 중지했습니다. 다시 시작할 수 있습니다.');
    else alertBox('OCR 실패: ' + ev.message);
    if (IB.bid === ev.bid && panel === 'inbox') loadBatch();
  }
  function showOriginal(bid, pages) {
    openSheet(async (box) => {
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `원본 보기 · ${pages.map((p) => +p + 1).join('·')}쪽` }), el('span', { class: 'muted', text: '이 PC 안에서만 보여 줍니다' }), el('span', { class: 'spacer' }), el('button', { type: 'button', text: '닫기', onclick: closeSheet })]));
      const body = el('div', { class: 'sheet-body' });
      box.appendChild(body);
      const t = await call('inbox_scan_text', bid, pages);
      for (const p of pages) {
        const img = el('img', { alt: `${+p + 1}쪽`, style: 'width:100%;border:1px solid var(--border);border-radius:8px;background:#fff' });
        const txt = ((t && t.pages.find((x) => x.page === +p)) || {}).text || '';
        body.appendChild(el('div', { class: 'split2', style: 'margin-bottom:14px' }, [el('div', {}, [el('div', { class: 'col-label', text: `${+p + 1}쪽 스캔` }), img]),
          el('div', {}, [el('div', { class: 'col-label', text: 'OCR 글자(학번·이름 포함, AI로 보내지 않음)' }), el('div', { class: 'rcard-body', style: 'max-height:none;background:var(--input);border:1px solid var(--border);border-radius:8px;padding:8px', text: txt || '(글자 없음)' })])]));
        api.inbox_page_image(bid, p).then((r) => { if (r && r.ok) img.src = r.src; else img.alt = (r && r.error) || '그림을 불러오지 못했습니다'; });
      }
    });
  }

  // =====================================================================
  // v0.5: 성취기준(붙여넣기·PDF·hwpx) · 세특 종합에 반영 · 성취기준만으로 생성
  // =====================================================================
  const SD = { gid: null, item: 'subject', data: null };
  let stdReq = 0;
  async function renderStandards() {
    const r = await call('standards_overview');
    if (!r) return;
    const list = $('stdList');
    list.innerHTML = '';
    const outs = r.outlines || [];
    if (!r.subjects.length && !outs.length) {
      list.appendChild(el('p', { class: 'hint', text: '등록한 담당이 없습니다. 명렬·담당 관리에서 반·과목·동아리를 추가하세요.' }));
      $('stdMain').innerHTML = '';
      $('stdMain').appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '성취기준은 과목 세특에서, 활동 개요는 자율·진로·동아리에서 씁니다.' }), el('button', { type: 'button', class: 'primary', text: '명렬·담당 관리', onclick: () => showPanel('roster') })]));
      return;
    }
    // 고른 것: SD.item이 'subject'면 과목 성취기준, 아니면 (SD.gid, SD.item) 활동 개요
    const okSel = SD.item && SD.item !== 'subject' ? outs.some((x) => x.id === SD.gid && x.item === SD.item) : r.subjects.some((x) => x.id === SD.gid);
    if (!okSel) {
      if (r.subjects.length) { SD.gid = r.subjects[0].id; SD.item = 'subject'; } else { SD.gid = outs[0].id; SD.item = outs[0].item; }
    }
    if (!SD.item) SD.item = 'subject';
    const stdItems = {};
    const itemBtn = (x, key, title, active, onclick) => {
      const sub = el('span', { class: 's', text: x.has ? `✔ 입력됨 · ${x.updated_at.slice(0, 16)}` : '아직 없음' });
      const btn = el('button', { type: 'button', class: 'ib-item' + (active ? ' active' : '') + (x.has ? ' is-done' : ''), onclick }, [el('span', { class: 't', text: title }), sub]);
      stdItems[key] = { btn, sub };
      list.appendChild(btn);
    };
    list.appendChild(el('div', { class: 'sec-title', text: '과목 성취기준' }));
    if (!r.subjects.length) list.appendChild(el('p', { class: 'hint', text: '등록한 과목이 없습니다.' }));
    const pick = async (gid, item) => { if (!(await flushPending())) { alertBox(SAVE_FAIL_MSG); return; } SD.gid = gid; SD.item = item; renderStandards(); };
    r.subjects.forEach((x) => itemBtn(x, `subject:${x.id}`, x.label, SD.item === 'subject' && x.id === SD.gid, () => pick(x.id, 'subject')));
    if (outs.length) {
      list.appendChild(el('div', { class: 'sec-title', style: 'margin-top:12px', text: '활동 개요' }));
      outs.forEach((x) => itemBtn(x, `${x.item}:${x.id}`, `${{ autonomy: '자율활동', career: '진로활동', club: '동아리' }[x.item] || x.item} · ${x.label}`, SD.item === x.item && x.id === SD.gid, () => pick(x.id, x.item)));
    }
    const markStd = (gid, text, item) => {
      const it = stdItems[`${item || 'subject'}:${gid}`];
      if (!it || !it.btn.isConnected) return;
      const has = !!(text || '').trim();
      it.btn.classList.toggle('is-done', has);
      it.sub.textContent = has ? '✔ 입력됨 · 방금 저장' : '아직 없음';
    };
    list.appendChild(el('p', { class: 'hint', text: '모두 미리 넣을 필요는 없습니다. 기록 없이 생성할 담당만 넣으세요. 학년도마다 따로 저장됩니다.' }));
    if (SD.item !== 'subject') { renderOutlineMain(markStd); return; }
    const sreq = ++stdReq, gidAsk = SD.gid, yearAsk = ys.year;
    const d = await call('standards_get', gidAsk);
    if (!d || sreq !== stdReq || SD.gid !== gidAsk || ys.year !== yearAsk) return;
    SD.data = d;
    const g = (ys.groups || []).find((x) => x.id === SD.gid);
    const m = $('stdMain');
    m.innerHTML = '';
    const ta = el('textarea', { id: 'stdText', value: d.text, disabled: !!ys.archived, placeholder: '예)\n[10공수1-01-01] 다항식의 사칙연산을 할 수 있다.\n[10공수1-01-02] 항등식의 성질과 나머지정리를 이해한다.\n\n성취수준 A: …  B: …  C: …\n\n성취기준 코드와 문장, 필요하면 성취수준별 설명까지 넣으세요.' });
    const state = el('span', { class: 'muted', text: d.source ? `가져온 곳: ${d.source}` : '' });
    const gidNow = SD.gid, yearNow = ys.year, skey = `std:${yearNow}:${gidNow}`;
    ta.addEventListener('input', () => {
      state.textContent = '저장 중…';
      const text = ta.value;
      saveLater(skey, async () => { const r = await mutate('standards_save', gidNow, text, null, yearNow); if (r && state.isConnected) state.textContent = '저장됨'; if (r) markStd(gidNow, text); return r; }, 600);
    });
    const put = async (text, source) => {
      let mode = 'replace';
      if (ta.value.trim()) {
        mode = await new Promise((resolve) => openSheet((box) => {
          box.style.height = 'auto'; box.style.width = 'min(480px, 92vw)';
          box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '이미 내용이 있습니다' })]), el('p', { text: `읽어 온 글(${text.length}자)을 어떻게 넣을까요?` }),
            el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => { closeSheet(); resolve(null); } }),
              el('button', { type: 'button', text: '뒤에 붙이기', onclick: () => { closeSheet(); resolve('append'); } }),
              el('button', { type: 'button', class: 'primary', text: '바꾸기', onclick: () => { closeSheet(); resolve('replace'); } })]));
        }));
        if (!mode) return;
      }
      if (!(await runPending(skey))) { alertBox(SAVE_FAIL_MSG); return; } // 쓰던 글을 먼저 저장(실패하면 바꾸지 않음)
      const before = ta.value;
      const next = mode === 'append' ? `${before.trim()}\n\n${text}` : text;
      if (!(await mutate('standards_save', gidNow, next, source, yearNow))) return; // 실패하면 편집칸은 그대로
      if (ta.isConnected) ta.value = next;
      if (SD.gid !== gidNow || ys.year !== yearNow) return;
      toast(`${source}에서 읽어 넣었습니다. 필요 없는 부분은 지우세요.`);
      renderStandards();
    };
    // 보기 좋게 정리: 원문 글자는 그대로, 줄 배치만 바꾼다. 규칙으로 안 되는 줄만 AI에 역할을 묻는다.
    const fmtModel = el('select', { style: 'width:auto;max-width:260px' });
    fillModelSelect(fmtModel);
    const formatStd = async () => {
      const text = ta.value;
      if (!text.trim()) { toast('먼저 성취기준을 붙여넣으세요.'); return; }
      let r = await call('standards_format', gidNow, text, false);
      if (!r) return;
      if (r.unknown) {
        const msel = fmtModel;
        const out = await aiRun({
          title: '성취기준 정리',
          rows: [['과목', g ? g.label : ''], ['판단 못 한 줄', `${r.unknown}줄 (이 줄들의 역할만 AI에 묻습니다)`], ['모델', modelName(msel)]],
          warn: '역할 판단을 위해 원문 줄과 앞뒤 문맥을 AI에 보냅니다. AI는 문장을 새로 쓰거나 지우지 않고 줄의 역할(단원·성취기준·수준 설명 등)만 정합니다. 정리본은 원문 줄을 그대로 옮겨 만들고, 원문이 모두 들어 있는지 검사합니다.',
          jobs: [{ run: () => api.standards_format(gidNow, text, true, msel.value) }],
        });
        if (!out || !out.done) return;
        r = out.results[0];
      }
      const okv = !r.missing.length;
      openSheet((box) => {
        const info = el('div', { class: 'std-fmt-info' }, [
          el('div', { class: okv ? 'ok-text' : 'danger-text', text: okv ? '✔ 원문 내용 줄이 한 글자도 바뀌지 않고 모두 들어 있습니다.' : `✕ 원문 ${r.missing.length}줄이 정리본에서 확인되지 않아 적용할 수 없습니다.` }),
          el('div', { class: 'muted', text: '검사 범위: 원문 그대로 비교(빈칸 차이, A~E 기호만 있는 줄, 표 머리글 줄 "성취기준·성취기준별 성취수준" 등은 제외).' }),
          r.ai_headers && r.ai_headers.length ? el('div', { class: 'warn-text', style: 'cursor:default', text: `AI가 머리글로 본 줄 ${r.ai_headers.length}개는 지우지 않고 그대로 두었습니다. 필요 없으면 적용한 뒤 직접 지우세요: ${r.ai_headers.join(' / ')}` }) : null,
          r.check && r.check.length ? el('div', { class: 'warn-text', style: 'cursor:default', text: `AI 답이 줄 모양과 맞지 않아 역할을 정하지 못한 줄 ${r.check.length}개는 제자리에 그대로 두었습니다(확인 필요): ${r.check.join(' / ')}` }) : null,
          r.three_level.length ? el('div', { text: `3단계(A·C·E) 성취기준 ${r.three_level.length}개: ${r.three_level.join(', ')} — 학생 수준 B는 A 설명, D는 C 설명을 기준으로 씁니다.` }) : null,
          r.headers.length ? el('div', { class: 'muted', text: `표 머리글 ${r.headers.length}줄을 뺐습니다(${[...new Set(r.headers)].join(', ')}).` }) : null,
          r.ai_used ? el('div', { class: 'muted', text: `AI에 역할을 물은 줄 ${r.unknown}줄${r.check && r.check.length ? ` 중 확인 필요 ${r.check.length}줄` : ''}` }) : el('div', { class: 'muted', text: '규칙으로 모두 정리되어 AI를 쓰지 않았습니다(크레딧 없음).' }),
          r.gaps.length ? el('details', {}, [el('summary', { class: 'warn-text', text: `수식이 빠진 듯한 곳 ${r.gaps.length}줄 — 원문을 복사할 때 수식이 빠졌을 수 있습니다. 필요하면 직접 채우세요.` }),
            el('div', { class: 'cmp-text', text: r.gaps.join('\n') })]) : null,
          !okv ? el('div', { class: 'cmp-text danger-text', text: r.missing.join('\n') }) : null,
        ].filter(Boolean));
        const applyBtn = el('button', { type: 'button', class: 'primary', disabled: !okv, text: '정리본으로 바꾸기' });
        applyBtn.addEventListener('click', async () => {
          if (ta.value !== text) { alertBox('정리하는 사이에 성취기준 글이 바뀌었습니다. 다시 정리해 주세요.'); return; }
          // 저장에 성공한 뒤에만 편집칸을 바꾼다(실패하면 원문·저장 대기를 그대로 둔다)
          if (!(await mutate('standards_save', gidNow, r.text, null, yearNow))) return;
          dropPending(skey);
          ta.value = r.text;
          markStd(gidNow, r.text);
          closeSheet();
          actionToast('정리본으로 바꿨습니다. 원문 내용은 그대로입니다.', '정리 전으로 되돌리기', async () => {
            if (!(await mutate('standards_save', gidNow, text, null, yearNow))) return;
            toast('정리 전 글로 되돌렸습니다.');
            if (SD.gid === gidNow && ys.year === yearNow) renderStandards();
          }, 20000);
        });
        box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '성취기준 정리 — 바꾸기 전 확인' }), el('span', { class: 'muted', text: g ? g.label : '' })]),
          el('div', { class: 'sheet-body' }, [info, el('div', { class: 'cmp', style: 'margin-top:10px' }, [
            el('div', {}, [el('div', { class: 'col-label', text: '지금(원문)' }), el('div', { class: 'cmp-text tall', text: text })]),
            el('div', {}, [el('div', { class: 'col-label', text: '정리본' }), el('div', { class: 'cmp-text tall', text: r.text })])])]),
          el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), applyBtn]));
      });
    };
    // 수식이 빠진 빈 곳 채우기: 빈 곳이 있는 줄만 AI에 보내고, 원문 글자를 지우거나 바꾼 줄은 버린다(덧붙이기만 적용).
    const fillGaps = async () => {
      const text = ta.value;
      const gl = text.split('\n').filter((ln) => ln.trim() && GAP_RE.test(ln));
      if (!gl.length) { toast('수식이 빠진 듯한 빈 곳이 없습니다.'); return; }
      if (!(await runPending(skey))) { alertBox(SAVE_FAIL_MSG); return; }
      const out = await aiRun({
        title: '성취기준 빈 곳 채우기',
        rows: [['과목', g ? g.label : ''], ['빈 곳이 있는 줄', `${gl.length}줄 (이 줄들만 AI에 보냄)`], ['모델', modelName(fmtModel)]],
        warn: '수식이 있던 자리를 짧은 말로 채우거나 앞뒤를 잇습니다. 원문 글자는 지우거나 바꾸지 않게 하고, 그런 줄은 프로그램이 버립니다. 적용 전에 바뀐 줄을 보여 줍니다.',
        jobs: [{ run: () => api.standards_fill_gaps(gidNow, text, fmtModel.value) }],
      });
      if (!out || !out.done) return;
      const r = out.results[0];
      if (!r.changed.length) { alertBox(`AI가 고친 줄이 없습니다.${r.rejected.length ? ` (원문을 바꾼 ${r.rejected.length}줄은 버렸습니다)` : ''}`); return; }
      openSheet((box) => {
        const apply = el('button', { type: 'button', class: 'primary', text: `${r.changed.length}줄 적용` });
        apply.addEventListener('click', async () => {
          if (ta.value !== text) { alertBox('그사이 성취기준 글이 바뀌었습니다. 다시 해 주세요.'); return; }
          if (!(await mutate('standards_save', gidNow, r.text, null, yearNow))) return;
          dropPending(skey);
          ta.value = r.text;
          markStd(gidNow, r.text);
          closeSheet();
          actionToast(`빈 곳 ${r.changed.length}줄을 채웠습니다. 원문 글자는 그대로입니다.`, '채우기 전으로 되돌리기', async () => {
            if (!(await mutate('standards_save', gidNow, text, null, yearNow))) return;
            toast('채우기 전 글로 되돌렸습니다.');
            if (SD.gid === gidNow && ys.year === yearNow) renderStandards();
          }, 20000);
        });
        const t = el('table', { class: 'tbl' }, [el('tr', {}, [el('th', { text: '원문' }), el('th', { text: '채운 뒤 (덧붙인 부분 강조)' })])]);
        r.changed.forEach((c) => t.appendChild(el('tr', {}, [el('td', { text: c.before }), el('td', {}, [addedMarks(c.before, c.after)])])));
        box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '빈 곳 채우기 — 적용 전 확인' }), el('span', { class: 'muted', text: g ? g.label : '' })]),
          el('div', { class: 'sheet-body' }, [
            el('p', { class: 'hint', text: '원문 글자가 순서대로 모두 남아 있고 덧붙이기만 한 줄입니다. 수식은 생기부에 쓰지 않으므로 말로 바꿔 채웠습니다. 내용이 맞는지 확인하세요.' }),
            t,
            r.rejected.length ? el('details', {}, [el('summary', { class: 'warn-text', text: `원문을 지우거나 바꿔서 버린 줄 ${r.rejected.length}개` }), el('div', { class: 'cmp-text', text: r.rejected.map((c) => `${c.before}\n→ ${c.after}`).join('\n\n') })]) : null,
          ].filter(Boolean)),
          el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), apply]));
      });
    };
    const lv = Object.entries(d.levels).map(([k, n]) => `${k} ${n}명`).join(' · ');
    m.append(
      el('div', { class: 'card-head' }, [el('h2', { text: `성취기준 · ${g ? g.label : ''}` }), el('span', { class: 'tag', text: `성취수준 ${d.level_scale}단계` }),
        el('span', { class: 'muted', text: lv ? `명렬 수준: ${lv}` : '명렬에 성취수준 없음' }), el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'link', text: '단계·학생 수준 바꾸기', onclick: () => { rosterSel = SD.gid; showPanel('roster'); } })]),
      el('div', { class: 'toolbar edit-only' }, [
        el('button', { type: 'button', text: '📋 붙여넣기(클립보드)', onclick: async () => { const c = await api.read_clipboard(); const t = c && c.ok ? (c.text || '').trim() : ''; if (!t) { toast('클립보드가 비어 있습니다. 칸에 직접 붙여넣어도 됩니다.'); return; } put(t, '붙여넣기'); } }),
        el('button', { type: 'button', text: '📄 PDF 불러오기', title: '글자가 있는 교육과정 PDF', onclick: async () => { const r2 = await call('standards_read_file', 'pdf'); if (r2) put(r2.text, r2.file); } }),
        el('button', { type: 'button', text: '📝 한글(hwpx) 불러오기', onclick: async () => { const r2 = await call('standards_read_file', 'hwpx'); if (r2) put(r2.text, r2.file); } }),
        el('button', { type: 'button', class: 'primary', title: '단원·성취기준·수준(A~E)별로 줄을 맞춰 보기 좋게 정리합니다. 원문 글자는 바꾸지 않습니다.', text: '✨ 보기 좋게 정리', onclick: formatStd }),
        el('button', { type: 'button', class: 'ai-btn', title: '복사할 때 수식이 빠져 비어 보이는 곳만 AI로 채우거나 앞뒤를 잇습니다. 원문 글자는 그대로 둡니다.', text: '빈 곳 AI로 채우기', onclick: fillGaps }),
        el('label', { class: 'inline', style: 'margin:0', title: '규칙으로 판단 못 한 줄이 있을 때·빈 곳 채우기에 쓰는 모델' }, ['정리 모델', fmtModel]),
        el('span', { class: 'spacer' }), state,
      ]),
      ta,
      el('p', { class: 'hint', text: '읽어 온 글은 편집할 수 있습니다. 필요한 단원만 남기면 AI가 더 정확하게 씁니다. 세특 종합 창에서 [성취기준 사용]을 켜면 이 내용과 학생의 성취수준을 함께 보냅니다(학번·이름은 보내지 않음).' }),
    );
  }
  // 활동 개요(자율·진로·동아리): 학교에서 정한 활동을 한 줄에 하나씩. 기록 없는 학생을 [활동 개요로 생성]할 때 쓴다.
  // 활동 개요 표 줄: '월/일 · 제목 — 활동 내용' ↔ {date, title, content}
  function parseOutlineLine(ln) {
    const m = /^\s*(?:(\d{1,2}\s*[/.]\s*\d{1,2})\.?\s*(?:·\s*)?)?(.*?)\s+—\s+(.*)$/.exec(ln);
    if (m) return { date: (m[1] || '').replace(/\s+/g, '').replace('.', '/'), title: m[2].trim(), content: m[3].trim() };
    const d = /^\s*(\d{1,2}\s*[/.]\s*\d{1,2})\.?\s*·\s*(.*)$/.exec(ln);
    if (d) return { date: d[1].replace(/\s+/g, '').replace('.', '/'), title: d[2].trim(), content: '' };
    const c = /^\s*—\s+(.*)$/.exec(ln); // 내용만 있는 줄
    if (c) return { date: '', title: '', content: c[1].trim() };
    return { date: '', title: ln.trim(), content: '' }; // 구분이 없으면 제목으로(필요하면 열 바꾸기)
  }
  function outlineLineOf(r) {
    const head = [r.date.trim(), r.title.trim()].filter(Boolean).join(' · ');
    const c = r.content.trim().replace(/\s*\n\s*/g, ' ');
    return head && c ? `${head} — ${c}` : head || (c ? `— ${c}` : '');
  }
  // 한글·엑셀에서 복사한 표(탭으로 칸 구분) → 줄들. 열이 3개 이상이면 날짜·제목·내용(나머지), 2개면 제목·내용, 1개면 제목.
  function parseOutlineTable(text) {
    return String(text || '').replace(/\r/g, '').split('\n').filter((l) => l.trim()).map((l) => {
      const c = l.split('\t').map((x) => x.trim());
      if (c.length >= 3) return { date: c[0], title: c[1], content: c.slice(2).filter(Boolean).join(' ') };
      if (c.length === 2) return { date: '', title: c[0], content: c[1] };
      return parseOutlineLine(c[0]);
    }).filter((r) => r.date || r.title || r.content);
  }
  // 활동 개요(자율·진로·동아리): 학교에서 정한 활동을 한 줄에 하나씩. 입력은 [표로 입력](날짜·제목·활동 내용) 또는 [붙여넣기].
  // 어느 쪽이든 '월/일 · 제목 — 내용' 줄로 저장하므로 오가도 글이 사라지지 않는다. 기록 없는 학생 [활동 개요로 생성]에 쓴다.
  async function renderOutlineMain(markStd) {
    const gidNow = SD.gid, itemNow = SD.item, yearNow = ys.year;
    const sreq = ++stdReq;
    const d = await call('outline_get', gidNow, itemNow);
    if (!d || sreq !== stdReq || SD.gid !== gidNow || SD.item !== itemNow || ys.year !== yearNow) return;
    const g = (ys.groups || []).find((x) => x.id === gidNow);
    const name = { autonomy: '자율활동', career: '진로활동', club: '동아리활동' }[itemNow] || itemNow;
    const m = $('stdMain');
    m.innerHTML = '';
    const skey = `outline:${yearNow}:${gidNow}:${itemNow}`;
    const modeKey = `sgb.outlineMode:${gidNow}:${itemNow}`;
    let mode = (() => { try { return localStorage.getItem(modeKey) || 'table'; } catch (e) { return 'table'; } })();
    let text = d.text || '';
    const ro = !!ys.archived;
    const state = el('span', { class: 'muted', text: d.source ? `가져온 곳: ${d.source}` : '' });
    const cnt = el('span', { class: 'tag' });
    const upd = () => { cnt.textContent = `활동 ${outlineLines(text).length}개`; };
    const save = (t, source) => {
      text = t;
      upd();
      state.textContent = '저장 중…';
      saveLater(skey, async () => { const r = await mutate('outline_save', gidNow, itemNow, t, source || null, yearNow); if (r && state.isConnected) state.textContent = '저장됨'; if (r) markStd(gidNow, t, itemNow); return r; }, 600);
    };
    const saveNow = async (t, source) => {
      if (!(await runPending(skey))) { alertBox(SAVE_FAIL_MSG); return false; }
      if (!(await mutate('outline_save', gidNow, itemNow, t, source || null, yearNow))) return false;
      text = t; upd(); markStd(gidNow, t, itemNow); state.textContent = '저장됨';
      return true;
    };
    const body = el('div', { class: 'outline-body' });
    // ① 붙여넣기 모드
    const ta = el('textarea', { id: 'stdText', disabled: ro,
      placeholder: '한 줄에 활동 하나씩 적습니다. 예)\n3/15 · 학급 자치회 구성 — 학급 규칙 정하기, 1인 1역할 정하기\n4/12 · 과학의 날 행사 — 탐구 포스터 제작, 발표\n5월 진로 체험의 날 — 관심 직업 탐색 보고서 작성\n\n학교 서식이 달라도 그대로 붙여넣은 뒤 [✨ AI로 다듬기]로 한 줄에 하나씩 정리할 수 있습니다.' });
    ta.addEventListener('input', () => save(ta.value));
    // ② 표 모드
    let rows = [];
    const tbl = el('table', { class: 'tbl outline-tbl' });
    const syncFromRows = () => save(rows.map(outlineLineOf).filter(Boolean).join('\n'));
    const drawTable = () => {
      tbl.innerHTML = '';
      // 열 머리: [⇄](오른쪽 열과 내용 바꾸기)·[비우기](이 열 내용 지우기) — 둘 다 [되돌리기] 가능
      const COLS = [['date', '날짜(월/일)'], ['title', '제목'], ['content', '활동 내용']];
      const colOp = (msg, fn) => {
        const before = rows.map((r) => ({ ...r }));
        fn();
        syncFromRows(); drawTable();
        actionToast(msg, '되돌리기', () => { rows = before; syncFromRows(); drawTable(); toast('되돌렸습니다.'); }, 20000);
      };
      tbl.appendChild(el('tr', {}, [...COLS.map(([k, label], ci) => el('th', {}, [el('div', { class: 'o-colhead' }, [
        el('span', { text: label }),
        ro ? null : el('button', { type: 'button', class: 'link small', title: `이 열을 비웁니다(모든 줄의 ${label})`, text: '비우기', onclick: () => colOp(`'${label}' 열을 비웠습니다.`, () => rows.forEach((r) => { r[k] = ''; })) }),
        ro || ci === COLS.length - 1 ? null : el('button', { type: 'button', class: 'o-swap', title: `'${label}' 열과 '${COLS[ci + 1][1]}' 열의 내용을 서로 바꿉니다`, text: '⇄',
          onclick: () => colOp(`'${label}'과 '${COLS[ci + 1][1]}' 열을 바꿨습니다.`, () => rows.forEach((r) => { const k2 = COLS[ci + 1][0]; [r[k], r[k2]] = [r[k2], r[k]]; })) }),
      ].filter(Boolean))])), el('th', {})]));
      rows.forEach((r, i) => {
        const inp = (k, ph) => {
          const x = el(k === 'content' ? 'textarea' : 'input', { type: 'text', rows: 1, value: r[k], placeholder: ph, disabled: ro, class: `o-${k}` });
          x.addEventListener('input', () => { r[k] = x.value; syncFromRows(); });
          x.addEventListener('paste', (e) => {
            const t = (e.clipboardData && e.clipboardData.getData('text')) || '';
            if (!/[\t\n]/.test(t)) return;
            e.preventDefault();
            const add = parseOutlineTable(t);
            const blank = !(r.date || r.title || r.content).trim();
            rows.splice(blank ? i : i + 1, blank ? 1 : 0, ...add); // 빈 줄이면 그 자리에, 내용이 있으면 그 아래에(있던 줄은 지우지 않음)
            syncFromRows(); drawTable();
          });
          return x;
        };
        tbl.appendChild(el('tr', {}, [el('td', {}, [inp('date', '월/일')]), el('td', {}, [inp('title', '활동 제목')]), el('td', {}, [inp('content', '무엇을 했는지')]),
          el('td', {}, [el('button', { type: 'button', class: 'link danger-text small', disabled: ro, text: '삭제', onclick: () => { rows.splice(i, 1); syncFromRows(); drawTable(); } })])]));
      });
    };
    const addRow = el('button', { type: 'button', class: 'small edit-only', text: '+ 줄 추가', onclick: () => { rows.push({ date: '', title: '', content: '' }); drawTable(); const last = tbl.querySelector('tr:last-child input'); if (last) last.focus(); } });
    const pasteTable = el('button', { type: 'button', class: 'edit-only', title: '한글·엑셀 표를 복사한 뒤 누르면 칸에 맞춰 넣습니다(날짜·제목·활동 내용 순서)', text: '📋 표 붙여넣기(클립보드)', onclick: async () => {
      const c = await api.read_clipboard(); const t = c && c.ok ? c.text || '' : '';
      const add = parseOutlineTable(t);
      if (!add.length) { toast('클립보드에 표가 없습니다.'); return; }
      const keep = rows.filter((r) => r.date || r.title || r.content);
      let how = 'replace';
      if (keep.length) {
        how = await new Promise((resolve) => openSheet((box) => {
          box.style.height = 'auto'; box.style.width = 'min(480px, 92vw)';
          box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '이미 내용이 있습니다' })]), el('p', { text: `복사한 표 ${add.length}줄을 어떻게 넣을까요?` }),
            el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => { closeSheet(); resolve(null); } }),
              el('button', { type: 'button', text: '뒤에 붙이기', onclick: () => { closeSheet(); resolve('append'); } }),
              el('button', { type: 'button', class: 'primary', text: '바꾸기', onclick: () => { closeSheet(); resolve('replace'); } })]));
        }));
        if (!how) return;
      }
      const next = how === 'append' ? [...keep, ...add] : add;
      if (await saveNow(next.map(outlineLineOf).filter(Boolean).join('\n'), '표 붙여넣기')) { rows = next; drawTable(); toast(`표 ${add.length}줄을 넣었습니다.`); }
    } });
    const put = async (t, source) => { // 파일·클립보드 → 붙여넣기 모드 글에
      let how = 'replace';
      if (text.trim()) {
        how = await new Promise((resolve) => openSheet((box) => {
          box.style.height = 'auto'; box.style.width = 'min(480px, 92vw)';
          box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '이미 내용이 있습니다' })]), el('p', { text: `읽어 온 글(${t.length}자)을 어떻게 넣을까요?` }),
            el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: () => { closeSheet(); resolve(null); } }),
              el('button', { type: 'button', text: '뒤에 붙이기', onclick: () => { closeSheet(); resolve('append'); } }),
              el('button', { type: 'button', class: 'primary', text: '바꾸기', onclick: () => { closeSheet(); resolve('replace'); } })]));
        }));
        if (!how) return;
      }
      const next = how === 'append' ? `${text.trim()}\n${t}` : t;
      if (await saveNow(next, source)) { toast(`${source}에서 읽어 넣었습니다. [✨ AI로 다듬기]로 한 줄에 하나씩 정리할 수 있습니다.`); draw(); }
    };
    // AI 다듬기: 한 줄에 활동 하나·맞춤법만. 원문에 없던 낱말은 노랗게 알려 주고 [적용]을 눌러야 바뀐다.
    const tidyModel = el('select', { style: 'width:auto;max-width:240px' });
    fillModelSelect(tidyModel);
    const tidy = async () => {
      if (!(await runPending(skey))) { alertBox(SAVE_FAIL_MSG); return; }
      const before = text;
      if (!before.trim()) { toast('다듬을 내용이 없습니다.'); return; }
      const out = await aiRun({
        title: '활동 개요 다듬기',
        rows: [['담당', `${name} · ${g ? g.label : ''}`], ['글', `${before.length}자`], ['모델', modelName(tidyModel)]],
        warn: '한 줄에 활동 하나로 나누고 맞춤법·띄어쓰기만 고치게 합니다. 없는 내용은 더하지 않게 하며, 원문에 없던 낱말이 생기면 적용 전에 노랗게 알려 드립니다.',
        jobs: [{ run: () => api.outline_tidy(gidNow, itemNow, before, tidyModel.value) }],
      });
      if (!out || !out.done) return;
      const r = out.results[0];
      openSheet((box) => {
        const apply = el('button', { type: 'button', class: 'primary', text: '다듬은 글로 바꾸기' });
        apply.addEventListener('click', async () => {
          if (text !== before) { alertBox('그사이 활동 개요가 바뀌었습니다. 다시 해 주세요.'); return; }
          if (!(await saveNow(r.text, null))) return;
          closeSheet(); draw();
          actionToast('다듬은 글로 바꿨습니다.', '다듬기 전으로 되돌리기', async () => { if (await saveNow(before, null)) { toast('다듬기 전 글로 되돌렸습니다.'); draw(); } }, 20000);
        });
        const hi = el('div', { class: 'cmp-text tall' });
        const words = new Set(r.new_words);
        r.text.split(/([가-힣A-Za-z0-9]{2,})/).forEach((part) => hi.appendChild(words.has(part) ? el('mark', { text: part }) : document.createTextNode(part)));
        box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '활동 개요 다듬기 — 적용 전 확인' }), el('span', { class: 'muted', text: `${outlineLines(before).length}줄 → ${outlineLines(r.text).length}줄` })]),
          el('div', { class: 'sheet-body' }, [
            r.new_words.length ? el('div', { class: 'warn', text: `원문에 없던 낱말 ${r.new_words.length}개: ${r.new_words.slice(0, 20).join(', ')}${r.new_words.length > 20 ? ' 외' : ''} — 노란 부분이 맞는지 확인하세요(날짜를 월/일로 바꾼 숫자 등).` })
              : el('div', { class: 'ok-text', text: '✔ 원문에 없던 낱말이 없습니다.' }),
            el('div', { class: 'cmp', style: 'margin-top:10px' }, [
              el('div', {}, [el('div', { class: 'col-label', text: '지금(원문)' }), el('div', { class: 'cmp-text tall', text: before })]),
              el('div', {}, [el('div', { class: 'col-label', text: '다듬은 글' }), hi])])]),
          el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), apply]));
      });
    };
    const modeBtn = (k, label) => el('button', { type: 'button', class: mode === k ? 'on' : '', text: label, onclick: async () => {
      if (mode === k) return;
      if (!(await runPending(skey))) { alertBox(SAVE_FAIL_MSG); return; }
      mode = k; try { localStorage.setItem(modeKey, k); } catch (e) { /* 무시 */ }
      draw();
    } });
    const seg = el('div', { class: 'mode-seg' });
    const tools = el('div', { class: 'toolbar edit-only' });
    const draw = () => {
      seg.innerHTML = '';
      seg.append(modeBtn('table', '표로 입력'), modeBtn('paste', '붙여넣기'));
      tools.innerHTML = '';
      body.innerHTML = '';
      if (mode === 'table') {
        rows = outlineLines(text).map(parseOutlineLine);
        if (!rows.length) rows = [{ date: '', title: '', content: '' }];
        drawTable();
        tools.append(pasteTable, addRow);
        body.append(tbl, el('p', { class: 'hint', text: '한글·엑셀 표를 복사해 칸에 붙여넣거나 [📋 표 붙여넣기]를 누르면 날짜·제목·활동 내용 칸에 맞춰 들어갑니다(열이 2개면 제목·내용, 1개면 제목). 칸이 어긋나면 열 머리의 [⇄]로 옆 열과 바꾸고, [비우기]로 한 열을 지웁니다(둘 다 되돌리기 가능).' }));
      } else {
        ta.value = text;
        tools.append(
          el('button', { type: 'button', text: '📋 붙여넣기(클립보드)', onclick: async () => { const c = await api.read_clipboard(); const t = c && c.ok ? (c.text || '').trim() : ''; if (!t) { toast('클립보드가 비어 있습니다. 칸에 직접 붙여넣어도 됩니다.'); return; } put(t, '붙여넣기'); } }),
          el('button', { type: 'button', text: '📄 PDF 불러오기', onclick: async () => { const r2 = await call('standards_read_file', 'pdf'); if (r2) put(r2.text, r2.file); } }),
          el('button', { type: 'button', text: '📝 한글(hwpx) 불러오기', onclick: async () => { const r2 = await call('standards_read_file', 'hwpx'); if (r2) put(r2.text, r2.file); } }));
        body.append(ta);
      }
      tools.append(el('button', { type: 'button', class: 'ai-btn', title: '한 줄에 활동 하나로 나누고 맞춤법만 고칩니다. 없는 내용은 더하지 않습니다.', text: 'AI로 다듬기', onclick: tidy }),
        el('label', { class: 'inline', style: 'margin:0' }, ['모델', tidyModel]), el('span', { class: 'spacer' }), state);
    };
    upd();
    m.append(
      el('div', { class: 'card-head' }, [el('h2', { text: `활동 개요 · ${name} · ${g ? g.label : ''}` }), cnt, seg, el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'ai-btn', text: '이 개요로 생성하러 가기', title: '항목별 기록에서 [활동 개요로 여러 명 생성]을 엽니다', onclick: async () => { if (!(await saveAllPending())) { alertBox(SAVE_FAIL_MSG); return; } await openRecords(gidNow, itemNow); openBasisGen(null); } })]),
      tools, body,
      el('p', { class: 'hint', text: '학생관찰기록이 없는 학생을 [활동 개요로 생성]할 때 씁니다. 생성 창에서 학생마다 참여한 활동을 고를 수 있습니다(처음에는 모두). AI에는 고른 활동 줄만 보내고, 개요에 없는 사실은 지어내지 않도록 지시합니다(학번·이름은 보내지 않음).' }),
    );
    draw();
  }
  // 성취기준 수식 빈칸(stdformat.GAP_RE와 같게)
  const GAP_RE = /\S {2,}\S|^\s+(꼴|의|에)\s|\s(꼴|의|에)\s|(^|[\s,])축(,|\s|$)/;
  // before 글자를 순서대로 맞춰 보고, after에서 덧붙인 글자를 <mark>로 보인다
  function addedMarks(before, after) {
    const a = before.replace(/\s+/g, '');
    const box = el('span', { class: 'added-line' });
    let j = 0, buf = '', mark = false;
    const flush = () => { if (buf) box.appendChild(mark ? el('mark', { text: buf }) : document.createTextNode(buf)); buf = ''; };
    for (const ch of after) {
      const isAdd = !/\s/.test(ch) && !(j < a.length && ch === a[j]);
      if (!/\s/.test(ch) && !isAdd) j += 1;
      if (/\s/.test(ch)) { buf += ch; continue; }
      if (isAdd !== mark) { flush(); mark = isAdd; }
      buf += ch;
    }
    flush();
    return box;
  }
  function stdBadge(meta) {
    if (!meta || !meta.basis) return null;
    if (meta.basis === 'standards_only') return el('span', { class: 'badge stdonly', text: `관찰기록 없이 성취기준으로 생성${meta.level ? ` · 수준 ${meta.level}` : ''}` });
    if (meta.basis === 'outline_only') return el('span', { class: 'badge stdonly', title: (meta.outline_lines || []).join('\n'), text: `관찰기록 없이 활동 개요로 생성 · 활동 ${(meta.outline_lines || []).length}개` });
    return el('span', { class: 'badge std', text: `성취기준 반영${meta.level ? ` · 수준 ${meta.level}` : ''}` });
  }
  function levelSelect(scale, current) {
    const letters = scale === 3 ? 'ABC' : 'ABCDE';
    return el('select', {}, [el('option', { value: '', text: '(수준 없음)' }), ...letters.split('').map((x) => el('option', { value: x, text: x, selected: x === current }))]);
  }
  // ---------- 일괄 마감·해제 (항목별 기록 > 전체 작업) ----------
  // 최종안이 있는 학생만 마감할 수 있다. 확인 사항(채택 후 기록 변경·분량 초과)이 있으면 실행 전에 한 번 알린다. 끝나면 [되돌리기].
  async function openCloseBulk() {
    const s = R.slot;
    if (!s) return;
    const info = await call('close_info', s.group_id, s.item);
    if (!info) return;
    const yearNow = ys.year;
    const sel = new Set();
    const canClose = (x) => x.active && x.status === 'final';
    const canOpen = (x) => x.status === 'closed';
    openSheet((box) => {
      box.style.width = 'min(1000px, 96vw)';
      const body = el('div', { class: 'sheet-body' });
      const tbl = el('table', { class: 'tbl' });
      const head = el('div', { class: 'basis-acts' });
      const closeBtn = el('button', { type: 'button', class: 'primary' });
      const openBtn = el('button', { type: 'button' });
      const draw = () => {
        tbl.innerHTML = '';
        tbl.appendChild(el('tr', {}, ['', '학번', '이름', '상태', '최종안', '확인 사항'].map((h) => el('th', { text: h }))));
        info.students.forEach((x) => {
          const off = !canClose(x) && !canOpen(x);
          const st = STATUS[x.status] || STATUS.none;
          const why = !x.active ? '비활성' : x.status === 'none' || x.status === 'progress' ? '최종안 없음' : '';
          tbl.appendChild(el('tr', { class: off ? 'is-off' : '' }, [
            el('td', {}, [el('input', { type: 'checkbox', disabled: off, checked: sel.has(x.student_no), onchange: (e) => { if (e.target.checked) sel.add(x.student_no); else sel.delete(x.student_no); draw(); } })]),
            el('td', { text: x.student_no }), el('td', { text: x.name }),
            el('td', {}, [el('span', { class: 'stcell' }, [el('span', { class: `st ${st.cls}`, text: st.icon }), ' ', st.text]), why ? el('div', { class: 'muted small-note', text: why }) : null]),
            el('td', { text: x.final_bytes ? `${x.final_bytes}/${x.target}B` : '-' }),
            el('td', {}, x.notes.map((n) => el('span', { class: 'tag warn-tag', text: n }))),
          ]));
        });
        const picked = info.students.filter((x) => sel.has(x.student_no));
        const nClose = picked.filter(canClose).length, nOpen = picked.filter(canOpen).length;
        const allFinal = info.students.filter(canClose).length;
        const allClosed = info.students.filter(canOpen).length;
        head.innerHTML = '';
        head.append(el('button', { type: 'button', disabled: !allFinal, text: `최종안 있는 학생 모두 고르기 (${allFinal}명)`, onclick: () => { info.students.filter(canClose).forEach((x) => sel.add(x.student_no)); draw(); } }),
          el('button', { type: 'button', disabled: !allClosed, text: `마감된 학생 모두 고르기 (${allClosed}명)`, onclick: () => { info.students.filter(canOpen).forEach((x) => sel.add(x.student_no)); draw(); } }),
          el('button', { type: 'button', disabled: !sel.size, text: '모두 해제', onclick: () => { sel.clear(); draw(); } }));
        closeBtn.textContent = `● 선택 ${nClose}명 마감`;
        closeBtn.disabled = !nClose;
        openBtn.textContent = `선택 ${nOpen}명 마감 해제`;
        openBtn.disabled = !nOpen;
      };
      const run = async (closed) => {
        const picked = info.students.filter((x) => sel.has(x.student_no) && (closed ? canClose(x) : canOpen(x)));
        if (!picked.length) return;
        if (closed) {
          const warn = picked.filter((x) => x.notes.length);
          if (warn.length && !(await confirmBox(`확인 사항이 있는 학생이 ${warn.length}명 있습니다.\n${warn.slice(0, 8).map((x) => `${x.name}(${x.notes.join('·')})`).join(', ')}${warn.length > 8 ? ' 외' : ''}\n\n그래도 ${picked.length}명을 마감할까요?`, '마감'))) return;
        } else if (!(await confirmBox(`${picked.length}명의 마감을 해제합니다. 최종안은 그대로 두며, 다시 고친 뒤 마감하면 됩니다.`, '마감 해제'))) return;
        const r = await mutate('close_many', s.group_id, s.item, picked.map((x) => x.student_no), closed, yearNow);
        if (!r) return;
        closeSheet();
        await loadSlotStudents();
        if (R.sno) loadStudent(true);
        const msg = `${r.done.length}명 ${closed ? '마감' : '마감 해제'}했습니다.${r.skipped.length ? ` 건너뜀 ${r.skipped.length}명(${[...new Set(r.skipped.map((k) => k[1]))].join('·')})` : ''}`;
        if (!r.done.length) { toast(msg); return; }
        actionToast(msg, '되돌리기', async () => {
          const u = await mutate('close_many', s.group_id, s.item, r.done, !closed, yearNow);
          if (u) { toast('되돌렸습니다.'); await loadSlotStudents(); if (R.sno) loadStudent(true); }
        }, 20000);
      };
      closeBtn.addEventListener('click', () => run(true));
      openBtn.addEventListener('click', () => run(false));
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '마감 일괄' }), el('span', { class: 'muted', text: `${s.label} · 명렬 전체` })]), body,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'hint', style: 'margin:0', text: '마감은 최종안이 있는 학생만 됩니다. 마감하면 그 학생의 기록·최종안을 고칠 수 없습니다(해제하면 다시 고칠 수 있음).' }), el('span', { class: 'spacer' }),
          el('button', { type: 'button', text: '닫기', onclick: closeSheet }), openBtn, closeBtn]));
      body.append(el('div', { class: 'map-row' }, [head]), tbl);
      draw();
    });
  }

  // ---------- 기준 자료로 생성 (세특: 성취기준·성취수준 / 자율·진로·동아리: 활동 개요) ----------
  // 기록은 쓰지 않고 기준 자료만으로 후보를 만든다. 미입력자를 모으거나 체크한 학생만. 한 학생만 할 때도 이 창을 쓴다.
  // 서버가 같은 담당에서 먼저 만든 다른 학생 문장을 함께 보내 50% 이상 다르게 쓰게 하고, 끝나면 학생끼리 겹침을 계산해 50% 이상이면 '비슷함'으로 보인다.
  const BASIS_ITEMS = ['subject', 'autonomy', 'career', 'club'];
  const SIM_WARN = 0.5;
  const outlineLines = (t) => String(t || '').split('\n').map((x) => x.trim()).filter(Boolean);
  const basisWord = (item) => (item === 'subject' ? '성취기준' : '활동 개요');
  const basisRo = (item) => `${basisWord(item)}${item === 'subject' ? '으로' : '로'}`;
  async function openBasisGen(preselect) {
    const s = R.slot;
    if (!s || !BASIS_ITEMS.includes(s.item)) return;
    const isSub = s.item === 'subject';
    const what = basisWord(s.item);
    const [info0, basis] = await Promise.all([call('batch_info', s.group_id, s.item), isSub ? call('standards_get', s.group_id) : call('outline_get', s.group_id, s.item)]);
    if (!info0 || !basis) return;
    if (!(basis.text || '').trim()) {
      const go = await modal(`${s.label}의 ${what}이(가) 아직 없습니다. 메뉴의 <b>[성취기준·활동 개요]</b>에서 먼저 넣어 주세요.`, true, true, `${what} 넣으러 가기`);
      if (go) { SD.gid = s.group_id; SD.item = s.item; showPanel('standards'); }
      return;
    }
    let info = info0;
    const lines = isSub ? [] : outlineLines(basis.text);
    const sims0 = await call('basis_similarity', s.group_id, s.item, null);
    let sims = (sims0 && sims0.similar) || {};
    const nameOf = Object.fromEntries(info.students.map((x) => [x.student_no, x.name]));
    const blocked = (x) => (!x.active ? '비활성' : x.closed ? '마감' : x.all_locked ? '후보 3개 모두 잠김' : x.pair_total && x.target <= 0 ? '1학기 최종안이 합산을 다 씀' : '');
    const isEmpty = (x) => (x.status || 'none') === 'none'; // 공통 상태 '기록 없음'(기록·후보·최종안 없음)
    const sel = new Set(preselect && info.students.some((x) => x.student_no === preselect && !blocked(x)) ? [preselect] : []);
    const common = new Set(lines.map((_, i) => i)); // 공통 참여 활동(처음에는 모두)
    const own = {}; // 학번 → 이 학생만 다르게 고른 활동(없으면 공통을 따름)
    const pickOf = (sno) => own[sno] || common;
    const opened = new Set(); // 활동을 펼친 학생
    const levels = {}; // 학번 → 이번에 고른 성취수준(세특)
    const res = {}; // 학번 → { ok } / { ok:false, error } / { skipped:true }
    const showText = new Set(); // 후보 문장을 펼친 학생
    let running = false;
    openSheet((box) => {
      box.style.width = 'min(1120px, 96vw)';
      const body = el('div', { class: 'sheet-body' });
      const foot = el('div', { class: 'sheet-foot' });
      const model = el('select', {});
      fillModelSelect(model);
      model.value = $('recModel').value;
      const stdTa = isSub ? el('textarea', { class: 'fill', rows: 6, value: basis.text }) : null;
      const tbl = el('table', { class: 'tbl basis-tbl' });
      const count = el('b', {});
      const runBtn = el('button', { type: 'button', class: 'primary ai-btn' });
      const head = el('div', { class: 'basis-acts' });
      const commonBox = el('div', { class: 'basis-common' });
      const stCellOf = (x) => { const st = STATUS[x.status] || STATUS.none; return el('span', { class: 'stcell' }, [el('span', { class: `st ${st.cls}`, text: st.icon }), ' ', st.text]); };
      const draw = () => {
        const can = info.students.filter((x) => !blocked(x));
        [...sel].forEach((n) => { if (!can.some((x) => x.student_no === n)) sel.delete(n); });
        // ① 공통 참여 활동(활동 개요): 전체 이름으로 고르고, 학생별로 다른 점만 펼쳐 고친다
        commonBox.innerHTML = '';
        if (!isSub) {
          commonBox.append(el('div', { class: 'col-label', text: '① 공통 참여 활동 — 고른 학생 모두에게 적용됩니다. 참여하지 않은 활동은 눌러서 빼세요.' }),
            el('div', { class: 'basis-picks wide' }, lines.map((ln, i) => el('button', { type: 'button', class: 'small' + (common.has(i) ? ' on' : ''), disabled: running, text: `${i + 1}. ${ln}`,
              onclick: () => { if (common.has(i)) common.delete(i); else common.add(i); draw(); } }))));
        }
        tbl.innerHTML = '';
        tbl.appendChild(el('tr', {}, ['', '학번', '이름', '상태', isSub ? '성취수준' : '참여한 활동', '이번 생성'].map((h) => el('th', { text: h }))));
        info.students.forEach((x) => {
          const why = blocked(x);
          const cb = el('input', { type: 'checkbox', disabled: !!why || running, checked: sel.has(x.student_no), onchange: (e) => { if (e.target.checked) sel.add(x.student_no); else sel.delete(x.student_no); draw(); } });
          let basisCell;
          if (isSub) {
            const lv = levelSelect(info.group.level_scale || 5, levels[x.student_no] ?? x.level);
            lv.disabled = !!why || running;
            lv.addEventListener('change', () => { levels[x.student_no] = lv.value; if (lv.value) sel.add(x.student_no); draw(); });
            basisCell = lv;
          } else if (why) {
            basisCell = el('span', { class: 'muted', text: '-' });
          } else {
            const pk = pickOf(x.student_no);
            const same = !own[x.student_no];
            const summary = same ? `공통 활동 ${common.size}개` : `이 학생만: ${[...pk].sort((a, b) => a - b).map((i) => i + 1).join(', ') || '없음'}`;
            const toggle = el('button', { type: 'button', class: 'link small', disabled: running, text: opened.has(x.student_no) ? '접기' : '이 학생만 바꾸기',
              onclick: () => { if (opened.has(x.student_no)) opened.delete(x.student_no); else { opened.add(x.student_no); if (!own[x.student_no]) own[x.student_no] = new Set(common); } draw(); } });
            const reset = !same ? el('button', { type: 'button', class: 'link small', disabled: running, text: '공통으로 되돌리기', onclick: () => { delete own[x.student_no]; opened.delete(x.student_no); draw(); } }) : null;
            basisCell = el('div', {}, [el('div', { class: 'basis-sum' }, [el('span', { class: same ? 'muted' : 'warn-text', style: 'cursor:default', text: summary }), toggle, reset]),
              opened.has(x.student_no) ? el('div', { class: 'basis-picks' }, lines.map((ln, i) => el('button', { type: 'button', class: 'small' + (pk.has(i) ? ' on' : ''), disabled: running, title: ln,
                text: `${i + 1}. ${ln.length > 16 ? ln.slice(0, 16) + '…' : ln}`, onclick: () => { const o = own[x.student_no]; if (o.has(i)) o.delete(i); else o.add(i); draw(); } }))) : null]);
          }
          const r = res[x.student_no];
          const sm = sims[x.student_no];
          const out = [];
          if (r && r.ok) out.push(el('span', { class: 'gen-ok', text: '후보 생성됨' }));
          if (r && r.skipped) out.push(el('span', { class: 'muted', text: '중지로 안 함' }));
          if (r && r.ok === false && !r.skipped) out.push(el('span', { class: 'danger-text', text: r.error || '실패' }));
          if (sm && sm.text) out.push(el('button', { type: 'button', class: 'small', text: showText.has(x.student_no) ? '후보 접기' : '후보 보기', onclick: () => { if (showText.has(x.student_no)) showText.delete(x.student_no); else showText.add(x.student_no); draw(); } }));
          if (sm && sm.sim >= SIM_WARN) out.push(el('span', { class: 'tag warn-tag', title: `다른 학생(${nameOf[sm.with] || sm.with}) 후보와 표현이 ${Math.round(sm.sim * 100)}% 겹칩니다(글자 3개 묶음 기준 참고값). 뜻·내용이 같은지는 직접 비교하세요.`, text: `표현 겹침 높음 · ${nameOf[sm.with] || sm.with}` }));
          if (sm && sm.sim >= SIM_WARN && !why) out.push(el('button', { type: 'button', class: 'small ai-btn', disabled: running, title: '이 학생 후보를 새로 만듭니다(크레딧이 들고, 후보가 3개면 가장 오래된 후보가 지워짐)', text: '다시 생성', onclick: () => run([x]) }));
          tbl.appendChild(el('tr', { class: (sel.has(x.student_no) ? 'is-sel' : '') + (why ? ' is-off' : '') }, [el('td', {}, [cb]), el('td', { text: x.student_no }), el('td', { text: x.name }),
            el('td', {}, [stCellOf(x), why ? el('div', { class: 'muted small-note', text: why }) : x.records ? el('div', { class: 'muted small-note', text: `기록 ${x.records}건(쓰지 않음)` }) : null]),
            el('td', {}, [basisCell]), el('td', {}, [el('div', { class: 'basis-out' }, out)])]));
          if (sm && sm.text && showText.has(x.student_no)) {
            tbl.appendChild(el('tr', { class: 'basis-text-row' }, [el('td', { colspan: 6 }, [el('div', { class: 'two-col' }, [
              el('div', {}, [el('div', { class: 'col-label', text: `${x.name} 후보 (최근, 기준 자료로 생성)` }), el('div', { class: 'cmp-text', text: sm.text })]),
              sm.with_text ? el('div', {}, [el('div', { class: 'col-label', text: `가장 겹치는 학생: ${nameOf[sm.with] || sm.with}` }), el('div', { class: 'cmp-text', text: sm.with_text })]) : el('div', {})])])]));
          }
        });
        const empties = can.filter(isEmpty).length;
        const retry = can.filter((x) => res[x.student_no] && res[x.student_no].ok !== true);
        head.innerHTML = '';
        addTo(head, el('span', { class: 'col-label', style: 'margin:0', text: `${isSub ? '①' : '②'} 대상 학생` }),
          el('button', { type: 'button', disabled: running || !empties, text: `기록 없는 학생 모두 고르기 (${empties}명)`, onclick: () => { can.filter(isEmpty).forEach((x) => sel.add(x.student_no)); draw(); } }),
          retry.length ? el('button', { type: 'button', disabled: running, text: `실패·중지된 ${retry.length}명 고르기`, onclick: () => { sel.clear(); retry.forEach((x) => sel.add(x.student_no)); draw(); } }) : null,
          el('button', { type: 'button', disabled: running || !sel.size, text: '모두 해제', onclick: () => { sel.clear(); draw(); } }));
        count.textContent = `선택 ${sel.size}명`;
        runBtn.textContent = `${basisRo(s.item)} 생성: ${sel.size}명`;
        runBtn.disabled = running || !sel.size;
      };
      const run = async (students) => {
        if (!students.length || running) return;
        const lvOf = (x) => (levels[x.student_no] ?? x.level) || '';
        if (isSub) {
          if (!stdTa.value.trim()) { toast('성취기준이 비어 있습니다.'); return; }
          const miss = students.filter((x) => !lvOf(x));
          if (miss.length) { toast(`성취수준을 고르지 않은 학생이 있습니다: ${miss.slice(0, 5).map((x) => x.name).join(', ')}${miss.length > 5 ? ' 외' : ''}`); return; }
        } else {
          const miss = students.filter((x) => !pickOf(x.student_no).size);
          if (miss.length) { toast(`참여한 활동이 하나도 없는 학생이 있습니다: ${miss.slice(0, 5).map((x) => x.name).join(', ')}${miss.length > 5 ? ' 외' : ''}`); return; }
        }
        const lvChanged = isSub ? students.filter((x) => lvOf(x) !== (x.level || '')) : [];
        running = true;
        draw();
        let started = false;
        let out = null;
        try {
          out = await aiRun({
            title: `${basisRo(s.item)} 생성`, kind: 'synth',
            rows: [['담당', s.label], ['학생', `${students.length}명 (학생마다 AI를 한 번씩 부름)`], ['기준', isSub ? `성취기준 ${bytesOf(stdTa.value)}B · 학생별 성취수준` : `활동 개요 ${lines.length}개 중 공통 ${common.size}개${Object.keys(own).length ? ` · 따로 고른 학생 ${students.filter((x) => own[x.student_no]).length}명` : ''}`], ['모델', modelName(model)]],
            warn: `학생관찰기록은 쓰지 않고 ${what}만으로 만듭니다. ${DROP_WARN} 같은 담당에서 먼저 만든 다른 학생 후보(최대 3개, 학번·이름 없음)도 함께 보내 표현이 겹치지 않게 합니다.${lvChanged.length ? ` 고른 성취수준(${lvChanged.length}명)은 실행할 때 명렬에도 저장됩니다.` : ''}`,
            before: async () => {
              await jobStart(); // 여러 명 생성 동안 학년도 전환·복원·업데이트와 겹치지 않게
              started = true;
              for (const x of lvChanged) { if (!(await mutate('set_level', s.group_id, x.student_no, lvOf(x)))) return false; x.level = lvOf(x); }
              return true;
            },
            jobs: students.map((x) => ({
              label: `${x.student_no} ${x.name}`,
              run: () => api.ai_standards_only(s.group_id, s.item, x.student_no, isSub ? { text: stdTa.value, level: lvOf(x) } : { lines: [...pickOf(x.student_no)].sort((a, b) => a - b).map((i) => lines[i]) }, model.value),
              onDone: () => { res[x.student_no] = { ok: true }; },
              onFail: (r) => { res[x.student_no] = { ok: false, error: (r && r.error) || '실패' }; },
            })),
            concurrency: 1, // 앞 학생 후보를 보고 겹치지 않게 쓰므로 한 명씩
            after: (o) => { o.notRun.forEach((i) => { res[students[i].student_no] = { ok: false, skipped: true }; }); },
            summary: (o) => `${o.cancelled ? '바로 중지했습니다(처리 중이던 학생은 저장하지 않음). ' : ''}완료 ${o.done}명 · 실패 ${o.fail}명${o.skipped ? ` · 중지로 건너뜀 ${o.skipped}명` : ''}\n후보는 이 창의 [후보 보기]나 학생 화면의 '종합·다듬기 후보'에서 확인한 뒤 최종안으로 채택하세요.`,
          });
        } finally {
          if (started) await jobEnd();
          running = false;
        }
        if (out && (out.done || out.fail)) {
          const [sm, inf] = await Promise.all([call('basis_similarity', s.group_id, s.item, null), call('batch_info', s.group_id, s.item)]);
          if (sm) sims = sm.similar;
          if (inf) info = inf; // 상태(기록 없음 → 입력 중) 새로 읽기
          students.forEach((x) => { if (res[x.student_no] && res[x.student_no].ok) sel.delete(x.student_no); }); // 실패·중지 학생은 고른 채로 둠
          refreshBalance();
          if (R.sno && students.some((x) => x.student_no === R.sno)) { revealResults(); loadStudent(true); }
          const many = students.filter((x) => res[x.student_no] && res[x.student_no].ok && sims[x.student_no] && sims[x.student_no].sim >= SIM_WARN).length;
          if (many) toast(`${many}명의 후보가 다른 학생과 표현이 많이 겹칩니다. [후보 보기]로 비교해 보고 필요하면 [다시 생성]하세요.`, 6000);
        }
        if (box.isConnected) draw();
      };
      runBtn.addEventListener('click', () => run(info.students.filter((x) => sel.has(x.student_no) && !blocked(x))));
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: `${basisRo(s.item)} 생성` }), el('span', { class: 'muted', text: `${s.label} · 학생관찰기록은 쓰지 않음 · 명렬 전체` }), el('span', { class: 'spacer' }),
          el('button', { type: 'button', class: 'small', title: `[성취기준·활동 개요] 메뉴에서 이 담당의 ${what}을(를) 엽니다. 고친 뒤 마우스 뒤로 버튼으로 돌아오세요.`, text: `📚 ${what} 보기·고치기 ↗`,
            onclick: () => { if (running) return; closeSheet(); SD.gid = s.group_id; SD.item = s.item; showPanel('standards'); } })]),
        body, foot);
      addTo(body,
        el('p', { class: 'hint', text: isSub
          ? '고른 학생마다 성취기준과 학생의 성취수준만으로 세특 후보를 만듭니다. 기록이 있는 학생을 골라도 기록은 쓰지 않습니다. 결과에는 "관찰기록 없이 성취기준으로 생성" 표시가 남으니 실제 수업 모습과 맞는지 꼭 확인하세요.'
          : '고른 학생마다 참여한 활동만으로 후보를 만듭니다. 기록이 있는 학생을 골라도 기록은 쓰지 않습니다. 개요에 없는 사실은 지어내지 않도록 지시합니다. 학생마다 활동이 다르면 문장도 덜 겹칩니다.' }),
        isSub
          ? el('details', {}, [el('summary', { text: `이번에 쓸 성취기준 (${bytesOf(basis.text)}B, 필요한 부분만 남겨도 됩니다. 저장되지는 않음)` }), stdTa])
          : null,
        commonBox,
        el('div', { class: 'map-row' }, [head]),
        tbl);
      foot.append(count, el('label', { class: 'inline', style: 'margin:0 0 0 12px' }, ['모델', model]), el('span', { class: 'spacer' }), el('button', { type: 'button', text: '닫기', onclick: () => { if (!running) closeSheet(); } }), runBtn);
      draw();
    });
  }

  // =====================================================================
  // v0.6: 일괄 종합 · 문단 이동(되돌리기)
  // =====================================================================
  function actionToast(msg, label, fn, ms) {
    $('actionToastText').textContent = msg;
    const b = $('actionToastBtn');
    b.textContent = label;
    b.onclick = () => { $('actionToast').hidden = true; fn(); };
    $('actionToast').hidden = false;
    clearTimeout(actionToast._t);
    actionToast._t = setTimeout(() => { $('actionToast').hidden = true; }, ms || 9000);
  }
  async function openMove(recs) {
    if (!recs.length) return;
    const t = await call('move_targets', R.slot.group_id, R.slot.item, R.sno);
    if (!t) return;
    if (!t.targets.length) { alertBox('이 학생이 속한 다른 항목이 없습니다.'); return; }
    const single = recs.length === 1;
    const paras = single ? splitParas(recs[0].content) : null;
    const picks = paras ? paras.map(() => true) : null;
    openSheet((box) => {
      box.style.height = 'auto';
      box.style.width = 'min(760px, 94vw)';
      const dest = el('select', {}, t.targets.map((x) => el('option', { value: `${x.group_id}:${x.item}`, disabled: x.closed, text: x.label + (x.closed ? ' (마감됨)' : '') })));
      const first = t.targets.find((x) => !x.closed);
      if (first) dest.value = `${first.group_id}:${first.item}`;
      const summary = el('p', { class: 'hint' });
      const upd = () => {
        const n = picks ? picks.filter(Boolean).length : recs.length;
        summary.textContent = single
          ? `출발(${R.slot.label})에서 문단 ${n}개를 빼고, 도착 항목에 새 기록으로 추가합니다.${n === paras.length ? ' 문단을 모두 옮기면 원래 기록은 지워집니다.' : ''} 날짜·활동명·태그는 함께 옮깁니다.`
          : `기록 ${recs.length}건 전체를 도착 항목으로 옮깁니다. 원래 항목에서는 지워집니다.`;
        go.disabled = !first || (picks && !picks.some(Boolean));
      };
      const go = el('button', { type: 'button', class: 'primary', text: '이동' });
      go.addEventListener('click', async () => {
        const [gid, item] = dest.value.split(':');
        const moves = recs.map((r) => ({ record_id: r.id, paras: single ? paras.map((_, i) => i).filter((i) => picks[i]) : null }));
        if (single && moves[0].paras.length === paras.length) moves[0].paras = null;
        const r = await mutate('move_records', moves, +gid, item);
        if (!r) return;
        closeSheet();
        R.selected.clear();
        loadStudent(true);
        const label = dest.options[dest.selectedIndex].text;
        actionToast(`${label}(으)로 옮겼습니다. 두 항목의 최종안은 다시 확인하세요.`, '되돌리기', async () => { if (await mutate('undo_move')) { toast('되돌렸습니다.'); loadStudent(true); } });
      });
      const list = el('div', {});
      if (single) {
        paras.forEach((p, i) => list.appendChild(el('label', { class: 'para-pick' }, [el('input', { type: 'checkbox', checked: picks[i], onchange: (e) => { picks[i] = e.target.checked; upd(); } }), el('div', { text: p })])));
      } else {
        recs.forEach((r) => list.appendChild(el('div', { class: 'para-pick' }, [el('div', { text: `${r.kind === 'existing' ? '기존 완성문' : r.seq + '회'} ${r.title || ''} — ${r.content.slice(0, 80)}${r.content.length > 80 ? '…' : ''}` })])));
      }
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: `다른 항목으로 이동 · ${R.view.student.name}` })]),
        el('label', { text: single ? '옮길 문단 (빈 줄 또는 줄바꿈 기준)' : '옮길 기록' }), list,
        el('label', {}, ['도착 항목 (이 학생이 속한 곳만)', dest]),
        summary,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), go]));
      upd();
    });
  }
  function splitParas(text) {
    const t = (text || '').trim();
    let parts = t.split(/\n\s*\n/).map((x) => x.trim()).filter(Boolean);
    if (parts.length <= 1) parts = t.split('\n').map((x) => x.trim()).filter(Boolean);
    return parts.length ? parts : [t];
  }

  async function jobStart() { await api.job_begin(); $('yearSelect').disabled = true; }
  async function jobEnd() { await api.job_end(); $('yearSelect').disabled = false; }
  // ---------- 파이썬 → 화면 이벤트 ----------
  window.onAppEvent = function (ev) {
    switch (ev.type) {
      case 'update_available':
        showUpdate(ev);
        break;
      case 'update_progress':
        if (ev.stage === 'backup') $('updateText').textContent = '자료를 백업하는 중…';
        else if (ev.stage === 'download') $('updateText').textContent = `내려받는 중… ${Math.round((ev.done / ev.total) * 100)}%`;
        break;
      case 'update_ready':
        updateReady(ev.version);
        break;
      case 'ocr_progress':
      case 'ocr_done':
      case 'ocr_stopped':
      case 'ocr_error':
        ocrEvent(ev);
        break;
      case 'update_error':
        $('updateText').textContent = `업데이트 실패: ${ev.message} (자세한 기록: 자료 폴더의 업데이트_기록.txt) `;
        addTo($('updateText'), el('button', { type: 'button', class: 'link', text: '릴리스 페이지 열기', onclick: () => api.open_url('https://github.com/kkchori511/sgb-juicer/releases/latest') }));
        $('updateNowBtn').disabled = false;
        break;
    }
  };

  // ---------- 묶기 ----------
  function bind() {
    document.querySelectorAll('.nav').forEach((b) => b.addEventListener('click', () => showPanel(b.dataset.panel)));
    $('menuToggle').addEventListener('click', () => {
      const v = !$('app').classList.contains('collapsed');
      setCollapsed(v);
      saveCfg({ menu_collapsed: v });
    });
    $('verBtn').addEventListener('click', showAbout);
    $('savedAt').addEventListener('click', manualSave);
    setInterval(refreshSaveState, 300);
    $('yearSelect').addEventListener('change', async (e) => {
      const want = +e.target.value;
      if (!(await leaveOk())) { e.target.value = ys.year; return; }
      $('actionToast').hidden = true;
      if (await call('switch_year', want)) { finalDraft = null; await reloadYear(); toast(`${want}학년도로 바꿨습니다.`); } else e.target.value = ys.year;
    });
    document.querySelectorAll('#semesterSeg .seg').forEach((b) => b.addEventListener('click', () => {
      semester = +b.dataset.sem;
      document.querySelectorAll('#semesterSeg .seg').forEach((x) => x.classList.toggle('active', x === b));
      renderDashboard();
    }));
    $('addGroupBtn').addEventListener('click', () => openGroupForm());
    document.querySelectorAll('#settingsTabs .tab-btn').forEach((b) => b.addEventListener('click', () => showSettingsTab(b.dataset.stab)));
    $('schedAddBtn').addEventListener('click', () => addSchedule($('schedDate'), $('schedTitle'), renderSchedTable));
    $('newYearBtn').addEventListener('click', () => {
      const y = +$('newYear').value;
      if ((ys.years || []).includes(y)) { alertBox(`${y}학년도는 이미 있습니다.`); return; }
      openWizard('newyear', 2, y);
    });
    $('openDataBtn').addEventListener('click', () => call('open_data_dir'));
    $('backupNowBtn').addEventListener('click', async () => { const r = await mutate('backup_now'); if (r) { toast('백업했습니다.'); loadBackups(); } });
    $('delYearBtn').addEventListener('click', async () => {
      const typed = $('delYearText').value;
      if (typed.trim() !== `${ys.year}학년도`) { alertBox(`확인 칸에 '${ys.year}학년도'를 정확히 입력해 주세요.`); return; }
      if (!(await leaveOk())) return;
      if (!(await typedConfirm(`${ys.year}학년도의 명렬과 기록을 모두 지웁니다. 지우기 전에 백업을 하나 만듭니다(되돌리려면 그 백업으로 복원).`, '삭제'))) return;
      if (await mutate('delete_year', ys.year, typed)) {
        $('delYearText').value = '';
        cfg = (await api.load_config()).config;
        await reloadYear();
        if (!ys.year) openWizard('first', 2);
        else showPanel('dashboard');
      }
    });
    $('checkUpdateBtn').addEventListener('click', async () => {
      const out = $('updateCheckResult');
      out.textContent = '확인 중…';
      const r = await api.update_check();
      if (!r || !r.ok) { out.textContent = (r && r.error) || '확인하지 못했습니다.'; return; }
      if (r.available) { out.textContent = `새 버전 v${r.version}이(가) 있습니다.`; showUpdate(r); } else out.textContent = '최신 버전입니다.';
    });
    $('updateLaterBtn').addEventListener('click', () => { $('updateBar').hidden = true; });
    $('updateNotesBtn').addEventListener('click', () => alertBox(updateInfo && updateInfo.notes ? updateInfo.notes : '변경 내용이 없습니다.'));
    $('updateNowBtn').addEventListener('click', async () => {
      if (!updateInfo) return;
      if (!updateInfo.can_apply) { api.open_url('https://github.com/kkchori511/sgb-juicer/releases/latest'); return; }
      if (!(await leaveOk())) return;
      let typed = null;
      if (updateInfo.warning) {
        typed = await updateWarnSheet(updateInfo);
        if (!typed) return;
      } else if (!(await confirmBox(`v${updateInfo.version}로 업데이트합니다.\n자료를 먼저 백업한 뒤 새 버전을 내려받고 앱을 다시 시작합니다.`, '업데이트'))) return;
      $('updateNowBtn').disabled = true;
      let r = await api.update_apply(typed);
      if (r && !r.ok && r.code === 'need_confirm') {
        // 안내 글을 못 받은 채로 눌렀으면: 다시 확인해 안내와 입력 칸을 띄운다
        const c = await api.update_check();
        if (c && c.ok && c.available) { updateInfo = c; typed = c.warning ? await updateWarnSheet(c) : null; }
        r = typed ? await api.update_apply(typed) : null;
      }
      if (r && !r.ok) alertBox(r.error || '업데이트하지 못했습니다.');
      if (!r || !r.ok) $('updateNowBtn').disabled = false;
    });
    $('recSlot').addEventListener('change', async (e) => {
      const want = e.target.value;
      if (!(await leaveOk())) { e.target.value = R.slot ? slotKey(R.slot) : ''; return; }
      R.slot = R.slots.find((s) => slotKey(s) === want); R.sno = null; R.selected.clear(); R.filter = ''; loadSlotStudents();
      if (R.slot) localStorage.setItem(recSlotKey(), slotKey(R.slot));
    });
    $('recPrev').addEventListener('click', () => moveStudent(-1));
    $('recListToggle').addEventListener('click', () => { $('recBody').classList.toggle('list-hidden'); });
    $('recBulkRecord').addEventListener('click', () => openExistingBulk('record'));
    $('recBulkExisting').addEventListener('click', () => openExistingBulk('existing'));
    $('recBulkFinal').addEventListener('click', openFinalBulk);
    $('recBasisGen').addEventListener('click', () => openBasisGen(null));
    $('recBulkClose').addEventListener('click', async () => { if (await leaveOk()) openCloseBulk(); });
    $('recNext').addEventListener('click', () => moveStudent(1));
    ['expScopeRows', 'expOrder', 'expCombine'].forEach((id) => $(id).addEventListener('change', loadExport));
    $('expSlot').addEventListener('change', (e) => { E.slotKey = e.target.value; loadExport(); });
    $('expCopyBtn').addEventListener('click', () => doExport('copy'));
    $('expXlsxBtn').addEventListener('click', () => doExport('xlsx'));
    const addTag = async () => { if (await mutate('add_tag', $('tagNew').value)) { $('tagNew').value = ''; renderTags(); } };
    $('tagAddBtn').addEventListener('click', addTag);
    $('tagFromInboxBtn').addEventListener('click', tagsFromInbox);
    $('tvScope').addEventListener('change', (e) => tvSetFilter({ scope: e.target.value }));
    $('tvSlot').addEventListener('change', (e) => tvSetFilter({ slot: e.target.value }));
    $('tvStatus').addEventListener('change', (e) => tvSetFilter({ status: e.target.value }));
    $('tvInactive').addEventListener('change', (e) => tvSetFilter({ inactive: e.target.checked }));
    $('tvQ').addEventListener('input', debounce((e) => tvSetFilter({ q: e.target.value }), 400));
    $('tvQ').setAttribute('aria-label', '이름·학번·내용 찾기');
    $('tvClear').addEventListener('click', () => tvSetFilter({ scope: '', slot: '', status: 'all', q: '', inactive: false }));
    $('tvTagSel').addEventListener('change', (e) => { if (e.target.value !== '') tvPickTag(+e.target.value); });
    $('tvReload').addEventListener('click', async () => {
      if (await leaveOk()) { renderTagView(true); return; }
      const bad = [...TV.rec.values()].filter((st) => tvHasDiff(st));
      if (!bad.length) return;
      if (!(await confirmBox(`저장하지 못한 기록이 ${bad.length}건 있습니다. 이 기록들의 내 글을 클립보드에 모아 복사한 뒤 버리고, 지금 저장된 내용으로 새로 불러올까요?`, '복사하고 새로 불러오기'))) return;
      if (!(await tvCopy(bad.map((st) => `[${st.r.student_no} ${st.r.name} · ${tvSrcLabel(st.r)}]\n${st.draft.content}`).join('\n\n')))) return;
      bad.forEach((st) => { st.draft = { ...st.saved }; st.err = null; });
      renderTagView(true);
    });
    document.addEventListener('keydown', (e) => {
      if (panel !== 'tagrec' || !(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 's') return;
      e.preventDefault();
      flushTagView().then((ok) => toast(ok ? '모두 저장했습니다.' : '저장하지 못한 기록이 있습니다. 빨간 기록을 확인하세요.'));
    });
    $('tagNew').addEventListener('keydown', (e) => { if (e.key === 'Enter') addTag(); });
    $('prName').addEventListener('input', savePrompt);
    $('prPrompt').addEventListener('input', savePrompt);
    $('prExample').addEventListener('input', savePrompt);
    $('prNewBtn').addEventListener('click', () => newPrompt(null));
    // 후보 글에서 일부를 마우스로 고르면 [최종안에 넣기] 버튼을 띄운다
    const selBtn = el('button', { type: 'button', class: 'sel-insert', hidden: true, text: '⤵ 최종안에 넣기' });
    document.body.appendChild(selBtn);
    selBtn.addEventListener('mousedown', (e) => e.preventDefault()); // 고른 글이 풀리지 않게
    selBtn.addEventListener('click', () => {
      const t = String(window.getSelection() || '').trim();
      selBtn.hidden = true;
      if (t && insertToFinal(t)) { window.getSelection().removeAllRanges(); toast('고른 부분을 최종안에 넣었습니다. Ctrl+Z로 되돌릴 수 있습니다.'); }
    });
    document.addEventListener('mouseup', () => setTimeout(() => {
      const sel = window.getSelection();
      const t = String(sel || '').trim();
      const node = sel && sel.anchorNode ? (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement) : null;
      const body = node && node.closest ? node.closest('.cand-body') : null;
      if (!t || !body || panel !== 'records') { selBtn.hidden = true; return; }
      const rect = sel.getRangeAt(0).getBoundingClientRect();
      selBtn.style.left = `${Math.min(rect.right + 6, window.innerWidth - 150)}px`;
      selBtn.style.top = `${Math.max(rect.top - 34, 8)}px`;
      selBtn.hidden = false;
    }, 0));
    document.addEventListener('scroll', () => { selBtn.hidden = true; }, true);
    $('prWizBtn').addEventListener('click', () => openWizardMenu(null));
    $('prCopyBtn').addEventListener('click', () => newPrompt(P.id));
    $('prResetBtn').addEventListener('click', async () => {
      const cur = P.data.prompts.find((x) => x.id === P.id);
      if (!(await typedConfirm(`'${cur.name}'의 지침과 예시를 기본값으로 되돌립니다. 지금 쓴 지침·예시는 사라집니다(필요하면 먼저 [복사해서 새로]).`, '되돌리기'))) return;
      await flushPending();
      if (await mutate('prompt_reset', P.id)) renderPrompts();
    });
    $('prDelBtn').addEventListener('click', async () => {
      const cur = P.data.prompts.find((x) => x.id === P.id);
      if (!(await typedConfirm(`프롬프트 '${cur.name}'을(를) 지웁니다. 지운 프롬프트는 되살릴 수 없습니다. 이미 만든 결과에는 영향이 없습니다.`, '삭제'))) return;
      await flushPending();
      if (await mutate('prompt_delete', P.id)) { P.id = 'default'; renderPrompts(); }
    });
    document.addEventListener('keydown', (e) => {
      if (panel !== 'records' || !$('sheet').hidden || !$('modal').hidden || ($('aiProg') && !$('aiProg').hidden) || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
      if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); moveStudent(1); }
      if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); moveStudent(-1); }
    });
    $('helpBtn').addEventListener('click', () => openGuide(HELP[panel]));
    // 표의 체크 칸: 체크 칸이 든 칸(td)을 눌러도 체크된다
    document.addEventListener('click', (e) => {
      const td = e.target.closest && e.target.closest('td, th');
      if (!td || e.target !== td) return;
      const boxes = td.querySelectorAll('input[type=checkbox]');
      if (boxes.length === 1 && !boxes[0].disabled && td.children.length === 1) boxes[0].click();
    });
    // 마우스 뒤로·앞으로 버튼(그리고 Alt+←/→): 메뉴 화면을 오간 순서대로 돌아간다
    history.replaceState({ panel }, '');
    window.addEventListener('popstate', (e) => {
      const want = e.state && e.state.panel;
      if (!want) return;
      if (!$('sheet').hidden || !$('modal').hidden || !$('wizard').hidden) { history.pushState({ panel }, ''); return; } // 창이 열려 있으면 그대로
      if (want !== panel) showPanel(want, true);
    });
    const mouseNav = (e) => {
      if (e.button !== 3 && e.button !== 4) return;
      e.preventDefault();
      if (e.type === 'mouseup') { if (e.button === 3) history.back(); else history.forward(); }
    };
    window.addEventListener('mousedown', mouseNav);
    window.addEventListener('mouseup', mouseNav);
    // 창을 닫을 때: 남은 저장을 마치고 닫는다(파이썬이 닫기를 잠시 멈추고 이 함수를 부름)
    window.__beforeClose = async () => {
      const okSave = await saveAllPending();
      if (!okSave && !(await confirmBox('저장하지 못한 내용이 있습니다. 그래도 닫을까요?', '닫기'))) return;
      api.close_app();
    };
    document.querySelectorAll('#guideToc a').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); openGuide(a.getAttribute('href').slice(1)); }));
    $('wNext').addEventListener('click', wizardNext);
    $('wPrev').addEventListener('click', wizardPrev);
    // 바깥 링크는 기본 브라우저로
    document.addEventListener('click', (e) => {
      const a = e.target.closest('[data-url], a[href^="http"]');
      if (!a) return;
      e.preventDefault();
      api.open_url(a.dataset.url || a.getAttribute('href'));
    });
    bindConfigInputs();
  }

  // 실행 인트로를 닫고 본 창을 보인다(알림 창을 띄우기 전과 시작이 끝났을 때. 여러 번 불러도 한 번만)
  const appReady = () => { try { if (api && api.app_ready) api.app_ready(); } catch (e) { /* 인트로가 없으면 그만 */ } };
  async function init() {
    try { await initInner(); } finally { appReady(); }
  }
  async function initInner() {
    api = window.pywebview.api;
    info = await api.app_info();
    $('verText').textContent = 'v' + info.version.replace(/\.0$/, '');
    const c = await api.load_config();
    cfg = c.config;
    dataDir = c.data_dir || info.data_dir;
    const prob = c.problem || {};
    // 설정 파일이 있는데 읽지 못함: 처음 사용처럼 시작 설정을 띄우지 않고 알린 뒤 다시 시도
    if (prob.error) {
      appReady();
      await modal(`<b>설정 파일을 읽지 못했습니다.</b><br>${escHtml(prob.error)}<br><br>백신 프로그램이 파일을 잠깐 잡고 있거나, 업데이트 직후일 수 있습니다. 자료는 그대로 있습니다. 잠시 뒤 [다시 시도]를 눌러 주세요.<br><span class="muted">자료 폴더: ${escHtml(dataDir)}</span>`, false, true, '다시 시도');
      location.reload();
      return;
    }
    setCollapsed(cfg.menu_collapsed);
    fillSoon();
    bind();
    fillConfigInputs();
    loadClovaGuide();
    api.startup();
    refreshBalance();
    api.run_cost().then((r) => { if (r && r.ok) { runCost = r.run_cost; $('runCost').textContent = fmtCredit(runCost); } });
    const r = await api.year_state();
    if (!r || !r.ok) { // 학년도 자료를 열다 오류: 시작 설정으로 넘어가지 않는다
      appReady();
      await modal(`<b>학년도 자료를 읽지 못했습니다.</b><br>${escHtml((r && r.error) || '알 수 없는 오류')}<br><br>자료는 지우지 않았습니다. 잠시 뒤 [다시 시도]를 눌러 주세요. 계속되면 이 화면을 찍어 알려 주세요.<br><span class="muted">자료 폴더: ${escHtml(dataDir)}</span>`, false, true, '다시 시도');
      location.reload();
      return;
    }
    ys = r;
    if (prob.broken) alertBox(`설정 파일이 깨져 있어 새로 시작했습니다. 예전 파일은 자료 폴더에 '${prob.broken}'로 남겨 두었습니다.${ys.year ? ' 학년도 자료는 그대로 이어서 씁니다. OpenRouter 키 등 설정을 다시 확인해 주세요.' : ''}`);
    renderYearSelect();
    refreshInboxBadge();
    if (!cfg.setup_done || !ys.year) {
      showPanel('dashboard');
      openWizard('first', cfg.openrouter_key ? (ys.year ? 3 : 2) : 1);
      if (!cfg.openrouter_key) W.step = 1;
      renderWizard();
    } else if (!(cfg.openrouter_key || '').trim()) {
      showPanel('settings');
      showSettingsTab('conn');
      $('orGuide').open = true;
      actionToast('OpenRouter API 키가 없습니다. 키를 넣어야 AI 기능을 쓸 수 있습니다(자료 조회는 됩니다).', '현황판 보기', () => showPanel('dashboard'), 15000);
    } else {
      showPanel('dashboard');
    }
  }

  window.addEventListener('pywebviewready', init);
})();

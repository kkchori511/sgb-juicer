(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let api = null;
  let info = {};
  let cfg = {};
  let ys = { year: 0, years: [] }; // year_state
  let dash = null;
  let panel = 'dashboard';
  let dashSel = null;
  let semester = 1;
  let rosterSel = null;
  let showInactive = false;
  let runCost = 0;

  const PANEL_TITLES = {
    dashboard: '현황판', inbox: '자료 인박스', records: '항목별 기록', batch: '일괄 종합', export: '검토·내보내기',
    roster: '명렬·담당 관리', tags: '태그', standards: '성취기준', settings: '설정', notice: '유의 사항',
  };
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
  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
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
  function markSaved() {
    const d = new Date();
    $('savedAt').textContent = `저장됨 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
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
  function modal(message, withCancel, html, okText) {
    return new Promise((resolve) => {
      if (html) $('modalMsg').innerHTML = message;
      else $('modalMsg').textContent = message;
      $('modalCancel').hidden = !withCancel;
      $('modalOk').textContent = okText || '확인';
      $('modal').hidden = false;
      const done = (v) => {
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

  function openSheet(build) {
    const box = $('sheetBox');
    box.innerHTML = '';
    box.removeAttribute('style'); // 앞 창의 크기가 남지 않게
    build(box);
    $('sheet').hidden = false;
  }
  function closeSheet() { $('sheet').hidden = true; $('sheetBox').innerHTML = ''; }

  // ---------- 상단 바·메뉴 ----------
  function showPanel(name) {
    panel = name;
    document.querySelectorAll('.nav').forEach((b) => b.classList.toggle('active', b.dataset.panel === name));
    document.querySelectorAll('.panel').forEach((p) => p.classList.toggle('active', p.dataset.panelContent === name));
    $('crumb').textContent = `${ys.year ? ys.year + '학년도 › ' : ''}${PANEL_TITLES[name] || ''}`;
    $('main').scrollTop = 0;
    if (name === 'dashboard') loadDashboard();
    if (name === 'roster') renderRoster();
    if (name === 'settings') renderSettings();
    if (name === 'records') renderRecordsPanel();
    if (name === 'export') renderExport();
    if (name === 'tags') renderTags();
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
    modal(`<div class="about-box"><img src="icon.png" alt="" class="about-icon"><div class="about-title">생기부 착즙기</div><div class="muted">v${info.version} 베타</div>` +
      `<div class="about-tag">"${info.tagline}"</div><div>${info.maker}</div></div>`, false, true);
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
      cards.appendChild(el('button', { type: 'button', class: 'gcard' + (g.id === dashSel ? ' active' : ''), onclick: () => { dashSel = g.id; renderDashboard(); } }, [
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
        const g = groups.find((x) => x.id === dashSel) || groups[0];
        openRecords(g && g.id, g && g.items[0], null, { final: 'progress', close: 'final', stale: 'stale' }[t.kind]);
      } })));
    }
    renderDashTable(groups.find((g) => g.id === dashSel), groups.length);
  }
  function stCell(key) {
    const s = STATUS[key] || STATUS.none;
    return el('td', { class: 'stcell' }, [el('span', { class: `st ${s.cls}`, text: s.icon }), ' ', s.text]);
  }
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

    const head = el('div', { class: 'card-head' }, [el('h2', { text: g.label })]);
    card.appendChild(head);
    let rows = g.rows.slice();
    if (g.kind !== 'homeroom') {
      const s = g.summary;
      const pct = s.students ? Math.round((s.closed / s.students) * 100) : 0;
      head.appendChild(el('span', { class: 'muted', text: `마감 ${s.closed}/${s.students}명` }));
      head.appendChild(el('div', { class: 'bar', style: 'width:160px' }, [el('div', { class: 'bar-fill', style: `width:${pct}%` })]));
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
    rows.sort((a, b) => (b.active - a.active) || a.student_no.localeCompare(b.student_no));

    const wrap = el('div', { class: 'tbl-wrap' });
    const t = el('table', { class: 'tbl' });
    const th = (x) => el('th', { text: x });
    if (g.kind === 'homeroom') {
      t.appendChild(el('tr', {}, [th('학번'), th('이름'), th('자율(연간)'), th('진로(연간)'), th('행특(연간)'), th('내 과목·동아리'), th('확인 사항')]));
    } else {
      t.appendChild(el('tr', {}, [th('학번'), th('이름'), th('학년-반'), th('상태'), th('기록 수'), th(`최종안 (목표 ${target}B)`), th('확인 사항')]));
    }
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
      tabs.appendChild(el('button', { type: 'button', class: 'gtab' + (g.id === rosterSel ? ' active' : '') + (g.total ? '' : ' empty'), onclick: () => { rosterSel = g.id; renderRoster(); } }, [
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
      if (r) { ys.groups = r.groups; renderRoster(); }
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
      const tg = el('input', { type: 'number', class: 'num', value: g.target_bytes || '', placeholder: String(ys.targets[g.kind]) });
      row.append(el('label', {}, ['목표 분량', tg, 'B']),
        el('button', { type: 'button', text: '저장', onclick: () => save({ name: nm.value, semester: sem && sem.value, level_scale: sc && sc.value, target_bytes: tg.value }) }));
    }
    row.appendChild(el('span', { class: 'spacer' }));
    row.appendChild(el('button', { type: 'button', class: 'link danger-text', text: '담당 삭제', onclick: async () => {
      if (!(await confirmBox(`'${g.label}' 담당과 명렬(학생 ${g.total}명)을 지웁니다. 계속할까요?`, '삭제'))) return;
      const r = await mutate('delete_group', g.id);
      if (r) { ys.groups = r.groups; rosterSel = null; renderRoster(); }
    } }));
    box.appendChild(row);
    return box;
  }
  async function loadMembers(g, body) {
    const r = await call('members', g.id);
    if (!r || rosterSel !== g.id) return;
    const members = r.members;
    const toolbar = el('div', { class: 'toolbar' });
    toolbar.append(
      el('button', { type: 'button', class: 'primary edit-only', text: '📋 엑셀 붙여넣기', onclick: () => importFromClipboard(g) }),
      el('button', { type: 'button', class: 'edit-only', text: '📂 xlsx 불러오기', onclick: () => importFromXlsx(g) }),
    );
    if (!members.length) {
      body.appendChild(toolbar);
      body.appendChild(el('div', { class: 'empty-state' }, [
        el('p', { text: '명렬이 비어 있습니다.' }),
        el('p', { class: 'hint', text: '엑셀에서 학번·이름 칸(또는 학년·반·번호·이름 칸)을 드래그해 복사한 뒤 [엑셀 붙여넣기]를 누르세요. 과목은 성취수준 칸도 함께 넣을 수 있습니다.' }),
      ]));
      return;
    }
    const allAct = el('input', { type: 'checkbox' });
    toolbar.append(
      el('span', { class: 'spacer' }),
      el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', checked: showInactive, onchange: (e) => { showInactive = e.target.checked; renderRoster(); } }), '비활성 학생 보기']),
      el('span', { class: 'edit-only muted', text: '|' }),
      el('button', { type: 'button', class: 'edit-only', text: '선택 학생 비활성화', onclick: () => changeActive(false, allAct.checked) }),
      el('label', { class: 'inline edit-only', style: 'margin:0' }, [allAct, '모든 소속에서(전출)']),
      el('button', { type: 'button', class: 'edit-only', text: '다시 활성화', onclick: () => changeActive(true, allAct.checked) }),
    );
    body.appendChild(toolbar);
    const list = members.filter((m) => showInactive || m.active);
    const inactiveCount = members.length - members.filter((m) => m.active).length;
    body.appendChild(el('div', { class: 'hint', text: `활성 ${members.length - inactiveCount}명${inactiveCount ? ` · 비활성 ${inactiveCount}명${showInactive ? '' : '(숨김)'}` : ''}. 비활성 학생은 매칭 후보·일괄 처리·내보내기에서 빠지며, 기록은 지우지 않습니다.` }));
    const wrap = el('div', { class: 'tbl-wrap' });
    const t = el('table', { class: 'tbl' });
    const checkAll = el('input', { type: 'checkbox', onchange: (e) => t.querySelectorAll('.rowcheck').forEach((c) => { c.checked = e.target.checked; }) });
    const heads = [el('th', {}, [checkAll]), el('th', { text: '학번' }), el('th', { text: '이름' }), el('th', { text: '학년-반' })];
    if (g.kind === 'subject') heads.push(el('th', { text: `성취수준(${g.level_scale}단계)` }));
    heads.push(el('th', { text: '상태' }));
    t.appendChild(el('tr', {}, heads));
    const letters = g.level_scale === 3 ? 'ABC' : 'ABCDE';
    list.forEach((m) => {
      const tr = el('tr', { class: m.active ? '' : 'inactive' });
      tr.appendChild(el('td', {}, [el('input', { type: 'checkbox', class: 'rowcheck', 'data-no': m.student_no })]));
      tr.append(el('td', { text: m.student_no }), el('td', { text: m.name }), el('td', { text: `${m.grade}-${m.class_no}` }));
      if (g.kind === 'subject') {
        const opts = ['', ...letters.split('')];
        if (m.level && !letters.includes(m.level)) opts.push(m.level);
        const s = el('select', { class: 'narrow', disabled: !!ys.archived, onchange: async (e) => { if (await mutate('set_level', g.id, m.student_no, e.target.value)) m.level = e.target.value; } },
          opts.map((v) => el('option', { value: v, text: v || '-', selected: v === (m.level || '') })));
        if (m.level && !letters.includes(m.level)) s.style.background = 'var(--warn-bg)';
        tr.appendChild(el('td', {}, [s]));
      }
      tr.appendChild(el('td', { text: m.active ? '활성' : '비활성' }));
      t.appendChild(tr);
    });
    wrap.appendChild(t);
    body.appendChild(wrap);

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

  // 명렬 불러오기
  async function importFromClipboard(g, onDone) {
    const c = await api.read_clipboard();
    const text = c && c.ok ? (c.text || '') : '';
    if (text.trim()) {
      const r = await call('roster_from_text', text);
      if (r) openImport(g, r, '클립보드', onDone);
      return;
    }
    // 클립보드를 못 읽으면 직접 붙여넣는 칸
    openSheet((box) => {
      box.style.height = 'auto';
      const ta = el('textarea', { rows: 12, placeholder: '여기를 누르고 Ctrl+V로 붙여넣으세요.' });
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: `명렬 붙여넣기 · ${g.label}` })]),
        el('p', { class: 'hint', text: '클립보드가 비어 있습니다. 엑셀에서 학번·이름 칸을 복사한 뒤 아래에 붙여넣으세요.' }),
        ta,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', class: 'primary', text: '읽기', onclick: async () => { const r = await call('roster_from_text', ta.value); if (r) openImport(g, r, '붙여넣기', onDone); } })]),
      );
      setTimeout(() => ta.focus(), 50);
    });
  }
  async function importFromXlsx(g, onDone) {
    const r = await call('roster_from_xlsx');
    if (r) openImport(g, r, r.file || 'xlsx', onDone);
  }
  function openImport(g, parsed, source, onDone) {
    const st = { raw: parsed.raw, header: parsed.header, columns: Object.assign({}, parsed.columns), rows: [], onlyBad: false };
    const roles = [['student_no', '학번'], ['name', '이름'], ['grade', '학년'], ['class_no', '반'], ['number', '번호']];
    if (g.kind === 'subject') roles.push(['level', '성취수준']);
    let tableBox, summary, applyBtn, removedNote;

    openSheet((box) => {
      box.style.height = '';
      const headerChk = el('input', { type: 'checkbox', checked: st.header, onchange: (e) => { st.header = e.target.checked; rebuild(); } });
      const mapRow = el('div', { class: 'map-row' }, [el('label', {}, [headerChk, '첫 줄은 머리글'])]);
      const width = st.raw[0].length;
      const sample = (i) => { const r = st.raw[st.header ? 1 : 0] || []; return (r[i] || '').slice(0, 8); };
      const selects = {};
      roles.forEach(([key, label]) => {
        const s = el('select', { onchange: (e) => { st.columns[key] = e.target.value === '' ? null : +e.target.value; rebuild(); } });
        selects[key] = s;
        mapRow.appendChild(el('label', {}, [label, s]));
      });
      const fillSelects = () => roles.forEach(([key]) => {
        const s = selects[key];
        s.innerHTML = '';
        s.appendChild(el('option', { value: '', text: '(없음)' }));
        for (let i = 0; i < width; i++) s.appendChild(el('option', { value: i, text: `${colName(i)}열: ${sample(i)}`, selected: st.columns[key] === i }));
      });
      fillSelects();
      headerChk.addEventListener('change', fillSelects);
      tableBox = el('div', { class: 'sheet-body' });
      summary = el('span', {});
      removedNote = el('span', { class: 'muted' });
      applyBtn = el('button', { type: 'button', class: 'primary', text: '명렬 반영', onclick: apply });
      const onlyBad = el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', onchange: (e) => { st.onlyBad = e.target.checked; renderRows(); } }), '확인 필요만 보기']);
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: `명렬 불러오기 · ${g.label}` }), el('span', { class: 'muted', text: `(${source})` })]),
        el('div', { class: 'hint', text: '열 연결을 확인하세요. 학번이 없으면 학년·반·번호로 학번(5자리)을 만들고, 학번이 있으면 학년·반을 계산합니다. 칸을 눌러 직접 고칠 수 있습니다.' }),
        mapRow,
        tableBox,
        el('div', { class: 'sheet-foot' }, [summary, onlyBad, el('span', { class: 'spacer' }), removedNote, el('button', { type: 'button', text: '취소', onclick: closeSheet }), applyBtn]),
      );
    });

    function plainRow(r) { return { student_no: r.student_no, name: r.name, grade: r.grade, class_no: r.class_no, number: r.number, level: r.level }; }
    async function rebuild() {
      const r = await call('roster_build', g.id, st.raw, st.header, st.columns);
      if (!r) return;
      st.rows = r.rows;
      renderRows();
    }
    const revalidate = debounce(async () => {
      const r = await call('roster_validate', g.id, st.rows.map(plainRow));
      if (!r) return;
      r.rows.forEach((nr, i) => {
        const row = st.rows[i];
        if (!row) return;
        row.issues = nr.issues; row.notes = nr.notes;
        ['grade', 'class_no', 'number'].forEach((k) => { if (!row[k] && nr[k]) { row[k] = nr[k]; const inp = row._tr && row._tr.querySelector(`[data-k="${k}"]`); if (inp) inp.value = nr[k]; } });
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
      (row.notes || []).forEach((x) => td.appendChild(el('div', { class: 'note', text: x })));
      if (!(row.issues || []).length && !(row.notes || []).length) td.appendChild(el('span', { class: 'st st-closed', text: '✔ 정상' }));
    }
    function updateSummary() {
      const bad = st.rows.filter((r) => r.issues && r.issues.length).length;
      summary.innerHTML = '';
      summary.append(el('b', { text: `정상 ${st.rows.length - bad}` }), ' / ', el('b', { class: bad ? 'danger-text' : '', text: `확인 필요 ${bad}` }));
      applyBtn.disabled = bad > 0 || !st.rows.length;
      applyBtn.textContent = `명렬 반영 (${st.rows.length}명)`;
      const nos = new Set(st.rows.map((r) => r.student_no));
      const gNow = (ys.groups || []).find((x) => x.id === g.id) || g;
      if (gNow.total) {
        api.members(g.id).then((m) => {
          if (!m || !m.ok) return;
          const removed = m.members.filter((x) => !nos.has(x.student_no)).length;
          removedNote.textContent = `기존 ${m.members.length}명을 이 명렬로 바꿉니다${removed ? ` · 새 명렬에 없는 ${removed}명은 이 담당에서 빠집니다` : ''}.`;
        });
      }
    }
    function renderRows() {
      tableBox.innerHTML = '';
      const t = el('table', { class: 'tbl' });
      const hs = ['#', '학번', '이름', '학년', '반', '번호'];
      if (g.kind === 'subject') hs.push('성취수준');
      hs.push('확인', '');
      t.appendChild(el('tr', {}, hs.map((h) => el('th', { text: h }))));
      st.rows.forEach((row, idx) => {
        if (st.onlyBad && !(row.issues && row.issues.length)) return;
        const tr = el('tr', {});
        const inp = (key, cls) => el('td', {}, [el('input', { type: 'text', class: cls || '', 'data-k': key, value: row[key] || '', oninput: (e) => { row[key] = e.target.value.trim(); revalidate(); } })]);
        tr.append(el('td', { class: 'muted', text: String(idx + 1) }), inp('student_no'), inp('name'), inp('grade', 'narrow'), inp('class_no', 'narrow'), inp('number', 'narrow'));
        if (g.kind === 'subject') tr.appendChild(inp('level', 'narrow'));
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
    async function apply() {
      const clean = st.rows.map(plainRow);
      const r = await mutate('roster_apply', g.id, clean);
      if (!r) return;
      closeSheet();
      ys.groups = r.groups;
      toast(`${r.count}명을 반영했습니다.${r.removed ? ` (${r.removed}명 빠짐)` : ''}`);
      if (onDone) onDone();
      else renderRoster();
    }
    rebuild();
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
    if (name === 'prompt') renderPrompts();
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
  const saveCfg = debounce(async (patch) => {
    const r = await call('save_config', patch);
    if (r) markSaved();
  }, 400);
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
      if (!(await confirmBox('OpenRouter·CLOVA 키를 모두 지웁니다. 학생 자료와 다른 설정은 그대로 둡니다. 계속할까요?', '키 초기화'))) return;
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
  async function loadBackups() {
    const r = await call('backups');
    const t = $('backupTable');
    t.innerHTML = '';
    t.appendChild(el('tr', {}, ['백업', '파일', ''].map((h) => el('th', { text: h }))));
    if (!r || !r.backups.length) { t.appendChild(el('tr', {}, [el('td', { colspan: 3, class: 'muted', text: '아직 백업이 없습니다.' })])); return; }
    r.backups.forEach((b) => t.appendChild(el('tr', {}, [el('td', { text: b.name.replace('_', ' ') }), el('td', { text: b.files.join(', ') }),
      el('td', {}, [el('button', { type: 'button', text: '이 백업으로 복원', onclick: async () => {
        if (!(await confirmBox(`'${b.name}' 백업으로 되돌립니다. 지금 상태는 먼저 백업해 둡니다. 계속할까요?`, '복원'))) return;
        const x = await mutate('restore_backup', b.name);
        if (x) { toast('복원했습니다.'); await reloadYear(); loadBackups(); }
      } })])])));
  }

  // ---------- 업데이트 ----------
  let updateInfo = null;
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
        el('button', { type: 'button', class: g.total ? '' : 'primary', text: '📋 엑셀 붙여넣기', onclick: () => importFromClipboard(g, wizardAfterRoster) }),
        el('button', { type: 'button', text: '📂 xlsx', onclick: () => importFromXlsx(g, wizardAfterRoster) }),
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
    const key = gid ? `${gid}:${item}` : (R.slot ? slotKey(R.slot) : (R.slots[0] && slotKey(R.slots[0])));
    R.slot = R.slots.find((s) => slotKey(s) === key) || R.slots[0] || null;
    R.sno = sno || null;
    R.filter = filter || '';
    R.selected.clear();
    showPanel('records');
  }
  async function renderRecordsPanel() {
    if (!R.slots.length && !(await loadSlots())) return;
    if (!R.slot) R.slot = R.slots[0] || null;
    fillSlotSelect($('recSlot'), R.slot && slotKey(R.slot));
    fillModelSelect($('recModel'));
    if (!R.slot) {
      $('recList').innerHTML = ''; $('recFinal').innerHTML = '';
      $('recRecords').innerHTML = '';
      $('recRecords').appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '담당이 없습니다. 명렬·담당 관리에서 먼저 추가하세요.' }), el('button', { type: 'button', class: 'primary', text: '명렬·담당 관리', onclick: () => showPanel('roster') })]));
      return;
    }
    await loadSlotStudents();
  }
  async function loadSlotStudents() {
    const r = await call('slot_view', R.slot.group_id, R.slot.item);
    if (!r) return;
    R.students = r.students;
    R.target = r.target;
    if (!R.students.length) {
      R.sno = null;
      renderStudentList();
      $('recStudentHead').textContent = '';
      $('recFinal').innerHTML = '';
      $('recRecords').innerHTML = '';
      $('recRecords').appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '이 담당의 명렬이 없습니다.' }), el('button', { type: 'button', class: 'primary', text: '명렬 등록', onclick: () => { rosterSel = R.slot.group_id; showPanel('roster'); } })]));
      return;
    }
    const visible = filteredStudents();
    if (!R.sno || !R.students.find((s) => s.student_no === R.sno)) R.sno = (visible[0] || R.students[0]).student_no;
    renderStudentList();
    await loadStudent();
  }
  function filteredStudents() {
    const q = R.search.trim();
    return R.students.filter((s) => (!R.filter || s.status === R.filter || (R.filter === 'stale' && s.stale)) && (!q || s.name.includes(q) || s.student_no.includes(q)))
      .sort((a, b) => (b.active - a.active) || a.student_no.localeCompare(b.student_no));
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
    box.append(search, filter);
    const list = filteredStudents();
    list.forEach((s) => {
      const st = STATUS[s.status] || STATUS.none;
      box.appendChild(el('button', { type: 'button', class: 'stu' + (s.student_no === R.sno ? ' active' : '') + (s.active ? '' : ' inactive'), title: st.text, onclick: () => { R.sno = s.student_no; R.selected.clear(); renderStudentList(); loadStudent(); } }, [
        el('span', { class: `st ${st.cls}`, text: st.icon }), el('span', { class: 'no', text: s.student_no }), el('span', { text: s.name }),
        el('span', { class: 'cnt', text: (s.stale ? '! ' : '') + (s.records ? `${s.records}건` : '') + (s.active ? '' : ' 비활성') }),
      ]));
    });
    if (!list.length) box.appendChild(el('p', { class: 'muted', text: '조건에 맞는 학생이 없습니다.' }));
    const done = R.students.filter((s) => s.active && s.status === 'closed').length;
    box.appendChild(el('p', { class: 'hint', text: `마감 ${done}/${R.students.filter((s) => s.active).length}명` }));
  }
  function moveStudent(step) {
    const list = filteredStudents();
    const i = list.findIndex((s) => s.student_no === R.sno);
    const next = list[i + step];
    if (!next) { toast(step > 0 ? '마지막 학생입니다.' : '첫 학생입니다.'); return; }
    R.sno = next.student_no;
    R.selected.clear();
    renderStudentList();
    loadStudent();
  }
  async function loadStudent(keepScroll) {
    if (!R.sno) return;
    const scroll = [$('recRecords').scrollTop, $('recFinal').scrollTop];
    const r = await call('student_view', R.slot.group_id, R.slot.item, R.sno);
    if (!r) return;
    R.view = r;
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
  const closedNow = () => !!(R.view && R.view.final && R.view.final.closed) || !!ys.archived;

  function renderRecords() {
    const box = $('recRecords');
    box.innerHTML = '';
    const v = R.view;
    const locked = closedNow();
    const head = el('div', { class: 'sec-title' }, [`누가기록 ${v.records.length}건`, el('span', { class: 'spacer' }),
      el('button', { type: 'button', class: 'primary', disabled: locked, text: '+ 누가기록', onclick: () => recordForm(null, 'record') }),
      el('button', { type: 'button', disabled: locked, text: '이미 쓴 생기부 넣기', onclick: () => recordForm(null, 'existing') }),
      el('button', { type: 'button', disabled: !!ys.archived, title: '여러 학생의 이미 쓴 생기부를 엑셀에서 한 번에', text: '여러 학생 일괄 넣기', onclick: openExistingBulk }),
      R.slot.item === 'subject' ? el('button', { type: 'button', disabled: locked, title: '누가기록이 없는 학생을 성취기준과 성취수준으로', text: '성취기준만으로 생성', onclick: standardsOnlyDialog }) : null,
    ]);
    box.appendChild(head);
    if (locked && !ys.archived) box.appendChild(el('div', { class: 'stale', text: '● 마감된 항목입니다. 고치려면 오른쪽 [마감 해제]를 누르세요.' }));
    const sel = [...R.selected].filter((id) => v.records.some((r) => r.id === id));
    R.selected = new Set(sel);
    box.appendChild(el('div', { class: 'toolbar' }, [
      el('label', { class: 'inline', style: 'margin:0' }, [el('input', { type: 'checkbox', checked: sel.length && sel.length === v.records.length, onchange: (e) => { R.selected = new Set(e.target.checked ? v.records.map((r) => r.id) : []); renderRecords(); } }), '전체 선택']),
      el('span', { class: 'muted', text: `선택 ${sel.length}건` }),
      el('button', { type: 'button', class: 'primary', disabled: locked || !sel.length, text: `선택 기록 종합하기 (${sel.length})`, onclick: openSynth }),
      el('button', { type: 'button', disabled: locked || !sel.length, text: '태그 일괄 지정', onclick: bulkTag }),
    ]));
    if (!v.records.length) {
      box.appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '아직 기록이 없습니다.' }), R.slot.item === 'subject' ? el('button', { type: 'button', class: 'primary', disabled: locked, text: '기록 없이 성취기준만으로 생성', onclick: standardsOnlyDialog }) : null, el('p', { class: 'hint', text: '[+ 누가기록]으로 활동을 하나씩 쌓거나, 이미 쓴 생기부를 넣어 다듬을 수 있습니다. 여러 학생의 엑셀 자료는 자료 인박스에서 학생별로 나눠 한 번에 보낼 수 있습니다.' })]));
      return;
    }
    v.records.forEach((r) => box.appendChild(recordCard(r, locked)));
  }
  function recordCard(r, locked) {
    const isSel = R.selected.has(r.id);
    const card = el('div', { class: 'rcard' + (isSel ? ' sel' : '') });
    const label = r.kind === 'existing' ? el('span', { class: 'badge existing', text: '기존 완성문' }) : el('span', { class: 'seq', text: `${r.seq}회` });
    card.appendChild(el('div', { class: 'rcard-head' }, [
      el('input', { type: 'checkbox', checked: isSel, onchange: (e) => { if (e.target.checked) R.selected.add(r.id); else R.selected.delete(r.id); renderRecords(); } }),
      label, r.date ? el('span', { text: md(r.date) }) : null, r.title ? el('b', { text: r.title }) : null,
      ...r.tags.map((t) => el('span', { class: 'tag', text: t.name })),
      r.weight !== null && r.weight !== undefined ? el('span', { class: 'badge', text: `비중 ${r.weight}%` }) : null,
      r.original ? el('span', { class: 'badge src', title: '원문은 [수정]에서 볼 수 있습니다', text: 'AI 반영됨' }) : null,
    ]));
    card.appendChild(el('div', { class: 'rcard-body', text: r.content }));
    const aiBtn = el('button', { type: 'button', disabled: locked, text: r.kind === 'existing' ? '다듬기(AI)' : '정제(AI)' });
    aiBtn.addEventListener('click', () => aiRecord(r, aiBtn));
    card.appendChild(el('div', { class: 'rcard-foot' }, [
      bytesEl(r.bytes, r.kind === 'existing' ? R.target : 0), el('span', { class: 'spacer' }),
      aiBtn,
      r.kind === 'existing' ? el('button', { type: 'button', disabled: locked, text: '그대로 최종안으로', onclick: async () => { if (await mutate('adopt_record', r.id)) { toast('최종안으로 채택했습니다.'); loadStudent(true); } } }) : null,
      el('button', { type: 'button', disabled: locked, text: '수정', onclick: () => recordForm(r, r.kind) }),
      el('button', { type: 'button', class: 'link danger-text', disabled: locked, text: '삭제', onclick: async () => {
        if (!(await confirmBox(`이 기록을 지웁니다.${r.candidates.length ? ` 정제 후보 ${r.candidates.length}개도 함께 지워집니다.` : ''}`, '삭제'))) return;
        if (await mutate('delete_record', r.id)) loadStudent(true);
      } }),
    ]));
    if (r.candidates.length) {
      const c = el('div', { class: 'cands' }, [el('div', { class: 'hint', style: 'margin:0', text: `${r.kind === 'existing' ? '다듬기' : '정제'} 후보 ${r.candidates.length}/3 (잠금 포함 최근 3개 보관)` })]);
      r.candidates.slice().reverse().forEach((cd) => c.appendChild(candEl(cd, locked, [
        el('button', { type: 'button', class: 'small', disabled: locked, text: '이 내용으로 기록 바꾸기', onclick: async () => { if (await mutate('apply_candidate', cd.id)) { toast('기록을 바꿨습니다. 원문은 남겨 둡니다.'); loadStudent(true); } } }),
        r.kind === 'existing' ? el('button', { type: 'button', class: 'small', disabled: locked, text: '최종안으로 채택', onclick: async () => { if (await mutate('adopt_result', cd.id)) { toast('최종안으로 채택했습니다.'); loadStudent(true); } } }) : null,
      ])));
      card.appendChild(c);
    }
    return card;
  }
  function candEl(cd, locked, extra) {
    return el('div', { class: 'cand' + (cd.locked ? ' locked' : '') }, [
      el('div', { class: 'cand-head' }, [el('b', { text: OP_LABEL[cd.op] || cd.op }), stdBadge(cd.meta), cd.created_at.slice(5, 16), cd.meta.model ? `· ${cd.meta.model}` : '',
        cd.meta.ratios ? `· 비율 ${cd.meta.ratios.join('/')}%` : '', el('span', { class: 'spacer' }), bytesEl(cd.bytes, R.target)]),
      el('div', { class: 'cand-body', text: cd.text }),
      el('div', { class: 'rcard-foot' }, [...(extra || []), el('span', { class: 'spacer' }),
        el('button', { type: 'button', class: 'small', title: '새 결과가 생겨도 지우지 않음', text: cd.locked ? '🔒 보관 잠금됨' : '🔓 보관 잠금', onclick: async () => { if (await mutate('lock_result', cd.id, !cd.locked)) loadStudent(true); } }),
        el('button', { type: 'button', class: 'small link danger-text', disabled: locked, text: '삭제', onclick: async () => { if (await mutate('delete_result', cd.id)) loadStudent(true); } })]),
    ]);
  }
  async function aiRecord(r, btn) {
    const res = await busyRun(btn, `rec${r.id}`, () => call('ai_record', r.id, $('recModel').value));
    if (!res) return;
    setCredits(res);
    toast(res.dropped ? '새 후보를 만들고 가장 오래된 후보를 지웠습니다.' : '새 후보를 만들었습니다.');
    loadStudent(true);
  }

  function tagPicker(selected) {
    const box = el('div', { class: 'tagpick' });
    const set = new Set(selected || []);
    const draw = () => {
      box.innerHTML = '';
      (R.view.tags || []).forEach((t) => box.appendChild(el('button', { type: 'button', class: set.has(t.id) ? 'on' : '', text: t.name, onclick: () => { if (set.has(t.id)) set.delete(t.id); else set.add(t.id); draw(); } })));
      if (!(R.view.tags || []).length) box.appendChild(el('span', { class: 'muted', text: '태그가 없습니다. 메뉴의 [태그]에서 만드세요.' }));
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
      const date = el('input', { type: 'date', value: r ? r.date : todayStr() });
      const title = el('input', { type: 'text', class: 'grow', placeholder: existing ? '예: 1학기 작성본' : '예: 진로 독서 감상문', value: r ? r.title : (existing ? '이미 쓴 생기부' : '') });
      const content = el('textarea', { rows: 12, placeholder: existing ? '이미 작성한 생기부 문장을 붙여넣으세요.' : '활동 내용, 학생 글, 관찰 메모 등을 적으세요. 학번·이름은 적지 않아도 됩니다.', value: r ? r.content : '' });
      const bc = el('span', { class: 'bytes' });
      const upd = () => { bc.textContent = `${bytesOf(content.value)}B`; };
      content.addEventListener('input', upd);
      upd();
      const tags = tagPicker(r ? r.tags.map((t) => t.id) : []);
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: `${r ? '기록 수정' : existing ? '이미 쓴 생기부 넣기' : '누가기록 추가'} · ${R.view.student.name}` }), el('span', { class: 'muted', text: R.slot.label })]),
        existing ? null : el('div', { class: 'inline' }, [el('label', { style: 'margin:0' }, ['날짜']), date, el('label', { style: 'margin:0' }, ['활동명']), title]),
        existing ? el('div', { class: 'inline' }, [el('label', { style: 'margin:0' }, ['제목']), title]) : null,
        el('label', { text: '태그' }), tags,
        el('label', {}, ['내용 ', bc]), content,
        r && r.original ? el('details', { style: 'margin-top:8px' }, [el('summary', { text: 'AI 반영 전 원문 보기' }), el('div', { class: 'rcard-body', text: r.original })]) : null,
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', class: 'primary', text: '저장', onclick: async () => {
            const data = { date: existing ? '' : date.value, title: title.value, content: content.value, tag_ids: tags.value(), kind };
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
    if (ws.some((w) => w !== null && (isNaN(w) || w < 0))) return { error: '비중은 0 이상의 숫자로 입력하세요.' };
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
    const pr = await call('prompts_get');
    if (!pr) return;
    const p = pr.prompts[R.slot.item].synth;
    openSheet((box) => {
      const inputs = {};
      let sumCheck = !!R.view.weight_sum_check;
      const t = el('table', { class: 'tbl wtbl' });
      const sumLine = el('div', { class: 'sum-line' });
      const runBtn = el('button', { type: 'button', class: 'primary', text: `종합 실행` });
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
      const pp = el('textarea', { class: 'fill', rows: 9, value: p.prompt });
      const pe = el('textarea', { class: 'fill', rows: 9, value: p.example, placeholder: '원하는 결과 모양의 문장(비우면 지침만 보냄)' });
      runBtn.addEventListener('click', async () => {
        if (pp.value !== p.prompt || pe.value !== p.example) await call('prompts_save', R.slot.item, 'synth', pp.value, pe.value);
        const wm = {};
        recs.forEach((r) => { wm[r.id] = inputs[r.id].value; });
        const std = stdChk && stdChk.checked ? { text: stdTa.value, level: stdLvl.value } : null;
        const res = await busyRun(runBtn, `synth${R.sno}`, () => call('ai_synth', R.slot.group_id, R.slot.item, R.sno, recs.map((r) => r.id), wm, model.value, sumCheck, std));
        if (!res) return;
        setCredits(res);
        closeSheet();
        toast(res.dropped ? '종합 후보를 만들고 가장 오래된 후보를 지웠습니다.' : '종합 후보를 만들었습니다. 오른쪽에서 확인하세요.');
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
          el('div', { class: 'two-col', style: 'margin-top:8px' }, [el('div', {}, [el('div', { class: 'col-label', text: '종합 지침' }), pp]), el('div', {}, [el('div', { class: 'col-label', text: '예시 (있으면 반드시 따름)' }), pe])]),
          el('p', { class: 'hint', text: '여기서 고친 지침·예시는 이 항목의 종합 프롬프트로 저장됩니다. AI에는 학번·이름 없이 기록 내용과 비율만 보냅니다.' }),
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
    box.appendChild(el('div', { class: 'sec-title' }, ['최종안', el('span', { class: 'muted', text: `목표 ${R.target}B` }), stdBadge(fmeta)]));
    const fb = el('div', { class: 'final-box' + (f ? ' has' : '') + (closed ? ' closed' : '') });
    if (f && f.stale && !closed) fb.appendChild(el('div', { class: 'stale', text: '! 최종안을 채택한 뒤 기록이 바뀌었습니다. 다시 종합하거나 내용을 확인하세요.' }));
    const ta = el('textarea', { value: f ? f.text : '', placeholder: '아직 최종안이 없습니다. 아래 종합 후보에서 [최종안으로 채택]을 누르거나 여기에 직접 쓰세요.', disabled: ro });
    const bc = el('span', {});
    const upd = () => { bc.innerHTML = ''; bc.appendChild(bytesEl(bytesOf(ta.value), R.target)); };
    ta.addEventListener('input', () => { upd(); saveBtn.disabled = ta.value.trim() === (f ? f.text : '').trim(); });
    const saveBtn = el('button', { type: 'button', disabled: true, text: '직접 고친 내용 저장', onclick: async () => { if (await mutate('edit_final', v.student.group_id || R.slot.group_id, R.slot.item, R.sno, ta.value)) { toast('저장했습니다.'); loadStudent(true); } } });
    const polishBtn = el('button', { type: 'button', disabled: ro || !f, title: '최종안을 AI로 다듬어 후보로 만듭니다', text: '다듬기(AI)' });
    polishBtn.addEventListener('click', async () => {
      const res = await busyRun(polishBtn, `synth${R.sno}`, () => call('ai_polish_final', R.slot.group_id, R.slot.item, R.sno, $('recModel').value));
      if (res) { setCredits(res); toast('다듬기 후보를 만들었습니다.'); loadStudent(true); }
    });
    const closeBtn = closed
      ? el('button', { type: 'button', disabled: !!ys.archived, text: '마감 해제', onclick: async () => { if (await mutate('set_closed', R.slot.group_id, R.slot.item, R.sno, false)) { toast('마감을 해제했습니다.'); loadStudent(true); } } })
      : el('button', { type: 'button', class: 'primary', disabled: !f || !!ys.archived, text: '● 마감', title: f ? '검토를 끝내고 편집을 잠급니다' : '최종안이 있어야 마감할 수 있습니다', onclick: async () => {
        if (ta.value.trim() !== f.text.trim() && !(await confirmBox('저장하지 않은 수정이 있습니다. 저장한 최종안으로 마감할까요?', '마감'))) return;
        if (await mutate('set_closed', R.slot.group_id, R.slot.item, R.sno, true)) { toast('마감했습니다. 다음 학생으로 넘어가세요.'); loadStudent(true); }
      } });
    upd();
    fb.append(ta, el('div', { class: 'final-actions' }, [bc, el('span', { class: 'spacer' }), saveBtn, polishBtn, closeBtn]));
    if (closed) fb.appendChild(el('div', { class: 'hint', text: `● ${f.closed_at || ''} 마감 — 기록·AI·최종안 편집이 잠겼습니다. 조회·복사·내보내기는 됩니다.` }));
    box.appendChild(fb);

    box.appendChild(el('div', { class: 'sec-title' }, [`종합·다듬기 후보 ${v.results.length}/3`, el('span', { class: 'muted', text: '잠금 포함 최근 3개 보관, 4번째부터 잠기지 않은 가장 오래된 것 삭제' })]));
    if (!v.results.length) box.appendChild(el('p', { class: 'hint', text: '왼쪽에서 기록을 골라 [선택 기록 종합하기]를 누르면 여기에 후보가 생깁니다.' }));
    v.results.slice().reverse().forEach((cd) => box.appendChild(candEl(cd, ro, [
      el('button', { type: 'button', class: 'small primary', disabled: ro, text: '✔ 최종안으로 채택', onclick: async () => {
        if (f && f.text && ta.value.trim() !== cd.text.trim() && !(await confirmBox('지금 최종안을 이 후보로 바꿉니다. 계속할까요?', '채택'))) return;
        if (await mutate('adopt_result', cd.id)) { toast('최종안으로 채택했습니다.'); loadStudent(true); }
      } }),
      el('button', { type: 'button', class: 'small', text: '정보', onclick: () => alertBox(`작업: ${OP_LABEL[cd.op]}\n모델: ${cd.meta.model || '-'}\n만든 때: ${cd.created_at}\n비용: ${fmtCredit(cd.cost)} 크레딧${cd.meta.ratios ? `\n비율: ${cd.meta.ratios.join(' / ')}%` : ''}${cd.meta.record_ids ? `\n근거 기록: ${cd.meta.record_ids.length}건` : ''}\n\n[지침]\n${cd.meta.prompt || '-'}${cd.meta.example ? `\n\n[예시]\n${cd.meta.example}` : ''}`) }),
    ])));
  }

  // 이미 쓴 생기부 일괄 넣기(여러 학생)
  async function openExistingBulk() {
    const c = await api.read_clipboard();
    const text = c && c.ok ? c.text || '' : '';
    let parsed = null;
    if (text.includes('\t')) parsed = await call('existing_parse', R.slot.group_id, R.slot.item, text, false);
    openSheet((box) => {
      const body = el('div', { class: 'sheet-body' });
      const foot = el('div', { class: 'sheet-foot' });
      box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: '이미 쓴 생기부 일괄 넣기' }), el('span', { class: 'muted', text: R.slot.label })]), body, foot);
      const start = () => {
        body.innerHTML = '';
        foot.innerHTML = '';
        const ta = el('textarea', { rows: 10, placeholder: '엑셀에서 학번(·이름)·내용 칸을 함께 복사해 여기에 붙여넣으세요.' });
        body.append(el('p', { class: 'hint', text: '학번과 생기부 내용이 들어 있는 엑셀 칸을 복사해 붙여넣거나 xlsx를 불러오세요. 모든 행이 이 담당 명렬과 확실히 맞아야 넣을 수 있습니다.' }), ta);
        foot.append(el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }),
          el('button', { type: 'button', text: '📂 xlsx 불러오기', onclick: async () => { const r = await call('existing_parse', R.slot.group_id, R.slot.item, null, true); if (r) preview(r); } }),
          el('button', { type: 'button', class: 'primary', text: '읽기', onclick: async () => { const r = await call('existing_parse', R.slot.group_id, R.slot.item, ta.value, false); if (r) preview(r); } }));
      };
      const preview = async (pz) => {
        const st = { ...pz, rows: [] };
        body.innerHTML = '';
        foot.innerHTML = '';
        const width = st.raw[0].length;
        const sample = (i) => ((st.raw[st.header ? 1 : 0] || [])[i] || '').slice(0, 10);
        const mk = (key, label) => {
          const s = el('select', { onchange: (e) => { st[key] = e.target.value === '' ? null : +e.target.value; build(); } }, [el('option', { value: '', text: '(없음)' }),
            ...Array.from({ length: width }, (_, i) => el('option', { value: i, text: `${colName(i)}열: ${sample(i)}`, selected: st[key] === i }))]);
          return el('label', {}, [label, s]);
        };
        const tableBox = el('div', {});
        const summary = el('span', {});
        const applyBtn = el('button', { type: 'button', class: 'primary', text: '넣기' });
        body.append(el('div', { class: 'map-row' }, [el('label', {}, [el('input', { type: 'checkbox', checked: st.header, onchange: (e) => { st.header = e.target.checked; build(); } }), '첫 줄은 머리글']), mk('no_col', '학번'), mk('name_col', '이름'), mk('content_col', '내용')]), tableBox);
        foot.append(summary, el('span', { class: 'spacer' }), el('button', { type: 'button', text: '다시 붙여넣기', onclick: start }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), applyBtn);
        const draw = () => {
          tableBox.innerHTML = '';
          const t = el('table', { class: 'tbl' });
          t.appendChild(el('tr', {}, ['학번', '이름', '내용', '확인', ''].map((h) => el('th', { text: h }))));
          st.rows.forEach((r, i) => t.appendChild(el('tr', { class: r.issues.length ? 'bad' : '' }, [el('td', { text: r.student_no }), el('td', { text: r.matched_name || r.name }),
            el('td', {}, [el('div', { class: 'exp-text', text: r.content.slice(0, 160) + (r.content.length > 160 ? '…' : '') })]),
            el('td', {}, r.issues.length ? r.issues.map((x) => el('div', { class: 'issue', text: '! ' + x })) : [el('span', { class: 'st st-closed', text: '✔ 매칭됨' })]),
            el('td', {}, [el('button', { type: 'button', class: 'link', title: '이 행 빼기', text: '✕', onclick: () => { st.rows.splice(i, 1); draw(); } })])])));
          tableBox.appendChild(t);
          const bad = st.rows.filter((r) => r.issues.length).length;
          summary.innerHTML = '';
          summary.append(el('b', { text: `매칭 ${st.rows.length - bad}` }), ' / ', el('b', { class: bad ? 'danger-text' : '', text: `확인 필요 ${bad}` }), bad ? el('span', { class: 'muted', text: ' — 고칠 수 없는 행은 ✕로 빼세요' }) : '');
          applyBtn.disabled = !!bad || !st.rows.length;
          applyBtn.textContent = `${st.rows.length}명에게 넣기`;
        };
        const build = async () => {
          const r = await call('existing_build', R.slot.group_id, R.slot.item, st.raw, st.header, st.no_col, st.name_col, st.content_col);
          if (!r) return;
          st.rows = r.rows;
          draw();
        };
        applyBtn.addEventListener('click', async () => {
          const r = await mutate('existing_apply', R.slot.group_id, R.slot.item, st.rows.map((x) => ({ student_no: x.student_no, name: x.matched_name || x.name, content: x.content })));
          if (!r) return;
          closeSheet();
          toast(`${r.count}명에게 '기존 완성문'으로 넣었습니다.`);
          loadSlotStudents();
        });
        await build();
      };
      if (parsed) preview(parsed); else start();
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
  async function loadExport() {
    const s = R.slots.find((x) => slotKey(x) === E.slotKey);
    const box = $('expTable');
    box.innerHTML = '';
    if (!s) { box.appendChild(el('p', { class: 'muted', text: '담당이 없습니다.' })); return; }
    const r = await call('export_preview', s.group_id, s.item, $('expScopeRows').value === 'closed', $('expOrder').value);
    if (!r) return;
    E.rows = r.rows;
    const closed = r.rows.filter((x) => x.closed).length;
    const empty = r.rows.filter((x) => !x.text).length;
    $('expSummary').textContent = `${r.rows.length}명 · 마감 ${closed} · 미마감 ${r.rows.length - closed} · 최종안 없음 ${empty}(빈칸) · 비활성 학생 제외`;
    const t = el('table', { class: 'tbl' });
    t.appendChild(el('tr', {}, ['학번', '이름', '상태', '최종안', '바이트'].map((h) => el('th', { text: h }))));
    r.rows.forEach((x) => t.appendChild(el('tr', { class: x.closed ? '' : 'bad' }, [el('td', { text: x.student_no }), el('td', { text: x.name }),
      el('td', { text: x.closed ? '● 마감' : '미마감' }), el('td', {}, [el('div', { class: 'exp-text', text: x.text || '' })]), el('td', {}, [x.text ? bytesEl(x.bytes, r.target) : el('span', { class: 'muted', text: '-' })])])));
    if (!r.rows.length) t.appendChild(el('tr', {}, [el('td', { colspan: 5, class: 'muted', text: '내보낼 학생이 없습니다.' })]));
    box.appendChild(t);
    $('expCopyBtn').textContent = `클립보드 복사: ${r.rows.length}명`;
    $('expXlsxBtn').textContent = `xlsx 저장: ${r.rows.length}명`;
  }
  async function doExport(kind) {
    const s = R.slots.find((x) => slotKey(x) === E.slotKey);
    if (!s || !E.rows.length) { toast('내보낼 학생이 없습니다.'); return; }
    const onlyClosed = $('expScopeRows').value === 'closed';
    const open = E.rows.filter((x) => !x.closed).length;
    if (kind === 'copy') {
      const r = await call('export_copy', s.group_id, s.item, onlyClosed, $('expOrder').value, $('expCols').value, $('expHeader').checked);
      if (r) toast(`${r.count}명 최종안을 복사했습니다.${open ? ` (미마감 ${open}명 포함)` : ''}`);
    } else {
      const name = `${ys.year}_${s.label.replace(/[\\/:*?"<>|·]/g, ' ').replace(/\s+/g, '_')}.xlsx`;
      const r = await call('export_xlsx', s.group_id, s.item, onlyClosed, $('expOrder').value, $('expCols').value, name);
      if (r) alertBox(`저장했습니다. (${r.count}명${open ? `, 미마감 ${open}명은 노란색` : ''})\n${r.path}`);
    }
  }

  // ---------- 태그 ----------
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
      t.appendChild(el('tr', {}, [el('td', {}, [name]), el('td', { text: `${tg.used}건` }), el('td', {}, [el('button', { type: 'button', class: 'link danger-text edit-only', text: '삭제', onclick: async () => {
        if (tg.used && !(await confirmBox(`'${tg.name}' 태그가 기록 ${tg.used}건에서 쓰이고 있습니다. 지우면 그 기록들에서 태그가 빠집니다.`, '삭제'))) return;
        if (await mutate('delete_tag', tg.id)) renderTags();
      } })])]));
    });
  }

  // ---------- 프롬프트 설정 ----------
  const P = { data: null, item: 'career', op: 'synth' };
  async function renderPrompts() {
    const r = await call('prompts_get');
    if (!r) return;
    P.data = r;
    const items = ys.role === 'homeroom' ? ['autonomy', 'career', 'behavior', 'subject', 'club'] : ['subject', 'club'];
    if (!items.includes(P.item)) P.item = items[0];
    const sel = $('prItem');
    sel.innerHTML = '';
    items.forEach((k) => sel.appendChild(el('option', { value: k, text: r.items[k], selected: k === P.item })));
    const ops = $('prOps');
    ops.innerHTML = '';
    Object.entries(r.ops).forEach(([k, v]) => ops.appendChild(el('button', { type: 'button', class: 'seg' + (k === P.op ? ' active' : ''), text: v, onclick: () => { P.op = k; renderPrompts(); } })));
    const cur = r.prompts[P.item][P.op];
    $('prPrompt').value = cur.prompt;
    $('prExample').value = cur.example;
    const def = r.defaults[P.item][P.op];
    $('prState').textContent = cur.prompt === def.prompt && cur.example === def.example ? '기본값 사용 중' : '개인 프롬프트';
  }
  const savePrompt = debounce(async () => {
    if (await mutate('prompts_save', P.item, P.op, $('prPrompt').value, $('prExample').value)) $('prState').textContent = '개인 프롬프트 · 저장됨';
  }, 600);

  // =====================================================================
  // v0.3: 자료 인박스 — ① 가져오기 → ② 학생 매칭 → ③ AI 정제(선택) → ④ 보내기 검토
  // =====================================================================
  const IB = { list: [], bid: null, view: null, raw: null, opts: null, preview: [], onlyPending: false, sel: new Set(), stop: false };
  const STAGE_NAME = { import: '① 가져오기', match: '② 매칭 대기', refine: '③ 정제', review: '④ 보내기 대기', sent: '보내기 완료' };
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
    const open = IB.list.filter((b) => b.stage !== 'sent');
    const sent = IB.list.filter((b) => b.stage === 'sent');
    const item = (b) => el('button', { type: 'button', class: 'ib-item' + (b.id === IB.bid ? ' active' : ''), onclick: () => { IB.bid = b.id; IB.raw = null; IB.sel.clear(); renderInboxList(); loadBatch(); } }, [
      el('span', { class: 't', text: b.title }),
      el('span', { class: 's', text: slotLabel(b.group_id, b.item) }),
      el('span', { class: 's' }, [el('span', { class: 'stage-chip' + (b.stage === 'sent' ? ' sent' : ''), text: STAGE_NAME[b.stage] }),
        b.stage === 'sent' ? ` ${b.sent_summary} · ${b.sent_at}` : (b.n ? ` ${b.n}건${b.pending ? ` · 확인 필요 ${b.pending}` : ''}` : '')]),
    ]);
    if (!open.length) box.appendChild(el('p', { class: 'hint', text: '진행 중인 묶음이 없습니다. 학습지·엑셀 자료를 [+ 새 자료 묶음]으로 가져오세요.' }));
    open.forEach((b) => box.appendChild(item(b)));
    if (sent.length) {
      const d = el('details', { style: 'margin-top:10px' }, [el('summary', { text: `보내기 완료 이력 ${sent.length}` })]);
      sent.forEach((b) => d.appendChild(item(b)));
      box.appendChild(d);
    }
  }
  function renderInboxEmpty() {
    const m = $('ibMain');
    m.innerHTML = '';
    m.appendChild(el('div', { class: 'empty-state' }, [
      el('h2', { text: '자료 인박스' }),
      el('p', { text: '어떤 활동 자료든 여기로 가져와 학생별로 나눈 뒤 항목에 보냅니다.' }),
      el('p', { class: 'hint', text: '① 가져오기(엑셀 붙여넣기·xlsx·스캔 PDF) → ② 학생 매칭 → ③ AI 정제(선택) → ④ 보내기 검토. 스캔 PDF는 CLOVA OCR로 읽습니다. 한 학생씩 직접 쓰는 기록은 항목별 기록의 [+ 누가기록]을 쓰세요.' }),
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
  async function loadBatch() {
    const r = await call('inbox_view', IB.bid);
    if (!r) return;
    IB.view = r;
    refreshInboxBadge().then(renderInboxList);
    const b = r.batch;
    if (b.meta && b.meta.raw && !IB.raw) { IB.raw = b.meta.raw; IB.opts = Object.assign({ structure: b.structure }, b.meta.opts || {}); }
    renderBatch();
  }
  function stepsBar(stage) {
    const order = ['import', 'match', 'refine', 'review'];
    const idx = stage === 'sent' ? 4 : order.indexOf(stage);
    return el('div', { class: 'steps-bar' }, ['1 가져오기', '2 학생 매칭', '3 AI 정제(선택)', '4 보내기 검토'].map((t, i) => el('span', { class: i === idx ? 'active' : i < idx ? 'done' : '', text: t })));
  }
  function renderBatch() {
    const m = $('ibMain');
    m.innerHTML = '';
    const b = IB.view.batch;
    const sent = b.stage === 'sent';
    const title = el('input', { type: 'text', value: b.title, disabled: sent });
    title.addEventListener('change', async () => { if (await mutate('inbox_update', b.id, { title: title.value })) { refreshInboxBadge().then(renderInboxList); } });
    const slot = slotSelect(`${b.group_id}:${b.item}`);
    slot.disabled = sent;
    slot.addEventListener('change', async () => {
      const [gid, item] = slot.value.split(':');
      if (+gid !== b.group_id && IB.view.rows.length && !(await confirmBox('대상 명렬을 바꾸면 학생 매칭을 처음부터 다시 합니다. 계속할까요?', '바꾸기'))) { slot.value = `${b.group_id}:${b.item}`; return; }
      if (await mutate('inbox_update', b.id, { group_id: +gid, item })) { await refreshInboxBadge(); renderInboxList(); loadBatch(); }
    });
    m.appendChild(el('div', { class: 'ib-head' }, [title, el('span', { class: 'muted', text: '→' }), slot, el('span', { class: 'spacer' }),
      sent ? el('span', { class: 'stage-chip sent', text: `보내기 완료 ${b.sent_at} · ${b.sent_summary}` }) : el('button', { type: 'button', class: 'link danger-text', text: '묶음 삭제', onclick: async () => {
        if (!(await confirmBox(`'${b.title}' 묶음을 지웁니다. 아직 보내지 않은 자료는 사라집니다.`, '삭제'))) return;
        if (await mutate('inbox_delete', b.id)) { IB.bid = null; renderInbox(); }
      } })]));
    m.appendChild(stepsBar(b.stage));
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
    if (!IB.raw) {
      const ta = el('textarea', { rows: 8, placeholder: '또는 여기를 누르고 Ctrl+V로 붙여넣은 뒤 [읽기]' });
      body.append(
        el('p', { text: '자료를 가져오세요. 엑셀에서 학생 칸과 내용 칸을 드래그해 복사하면 셀마다 기록 한 건으로 나눕니다.' }),
        el('div', { class: 'src-btns' }, [
          el('button', { type: 'button', class: 'primary', text: '📋 엑셀 붙여넣기(클립보드)', onclick: async () => { const c = await api.read_clipboard(); const t = c && c.ok ? c.text : ''; if (!t.trim()) { toast('클립보드가 비어 있습니다. 아래 칸에 직접 붙여넣어도 됩니다.'); ta.focus(); return; } loadSource(() => call('inbox_source_text', b.id, t)); } }),
          el('button', { type: 'button', text: '📂 xlsx 불러오기', onclick: () => loadSource(() => call('inbox_source_xlsx', b.id)) }),
          el('button', { type: 'button', text: '🖨 스캔 PDF (CLOVA OCR)', onclick: () => startScanPick(b) }),
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
      return Array.from({ length: width }, (_, j) => [j, `${o.orient === 'cols' ? `${j + 1}행` : `${colName(j)}열`}: ${(first[j] || '').slice(0, 8)}`]);
    };
    const pick = (key, label) => el('label', {}, [label, el('select', { onchange: (e) => { o[key] = e.target.value === '' ? null : +e.target.value; renderBatch(); } },
      [el('option', { value: '', text: '(없음)' }), ...lineOpts().map(([v, t]) => el('option', { value: v, text: t, selected: o[key] === v }))])]);
    const ctrl = el('div', { class: 'map-row' }, [seg('structure', [['multi', '여러 학생에게'], ['single', '한 학생에게 여러 건']])]);
    if (o.structure === 'single') {
      ctrl.append(el('label', {}, ['학생', el('select', { onchange: (e) => { o.student_no = e.target.value; renderBatch(); } }, [el('option', { value: '', text: '학생 고르기' }), ...members.map((x) => el('option', { value: x.student_no, text: `${x.student_no} ${x.name}`, selected: o.student_no === x.student_no }))])]),
        el('span', { text: '읽는 순서' }), seg('order', [['row', '행 우선(→)'], ['col', '열 우선(↓)']]));
    } else {
      ctrl.append(seg('orient', [['rows', '한 행이 한 학생'], ['cols', '한 열이 한 학생']]),
        el('button', { type: 'button', text: '가로↔세로 바꾸기', onclick: () => { o.orient = o.orient === 'cols' ? 'rows' : 'cols'; o.no_idx = null; o.name_idx = null; renderBatch(); } }),
        pick('no_idx', '학번'), pick('name_idx', '이름'));
    }
    ctrl.append(el('label', {}, [el('input', { type: 'checkbox', checked: !!o.header, onchange: (e) => { o.header = e.target.checked; renderBatch(); } }), '첫 줄은 날짜·회차 제목']));
    body.appendChild(ctrl);
    if (o.structure === 'multi' && o.found === false && o.no_idx == null && o.name_idx == null) body.appendChild(el('div', { class: 'warn', text: '학번·이름 줄을 자동으로 찾지 못했습니다. 위에서 직접 고르거나, 한 학생의 자료라면 [한 학생에게 여러 건]을 고르세요.' }));
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
      // 셀 색: 학번·이름 줄, 제목 줄, 학생별 내용, 빈 칸
      const lineOf = {};
      r.rows.forEach((x) => { lineOf[x.source_ref] = x.line; });
      const t = el('table', { class: 'grid-prev' });
      const width = Math.max(...IB.raw.map((x) => x.length));
      t.appendChild(el('tr', {}, [el('th', { text: '' }), ...Array.from({ length: width }, (_, j) => el('th', { text: colName(j) }))]));
      IB.raw.forEach((row, i) => {
        const tr = el('tr', {}, [el('th', { text: String(i + 1) })]);
        for (let j = 0; j < width; j++) {
          const v = row[j] || '';
          const ref = `${colName(j)}${i + 1}`;
          let cls = '';
          const lineIdx = o.orient === 'cols' ? j : i;
          const posIdx = o.orient === 'cols' ? i : j;
          if (o.header && lineIdx === 0 && (o.structure === 'multi' || i === 0)) cls = 'c-head';
          else if (o.structure === 'multi' && (posIdx === o.no_idx || posIdx === o.name_idx)) cls = 'c-id';
          else if (ref in lineOf) cls = `c-l${(lineOf[ref] || 0) % 4}`;
          else if (!v) cls = 'c-skip';
          tr.appendChild(el('td', { class: cls, title: v, text: v }));
        }
        t.appendChild(tr);
      });
      left.appendChild(t);
      r.rows.forEach((x) => right.appendChild(el('div', { class: 'mk' }, [el('b', { text: o.structure === 'single' ? (members.find((mm) => mm.student_no === o.student_no) || {}).name || '(학생 고르기)' : `${x.ext_no || '학번?'} ${x.ext_name || ''}`.trim() }),
        el('span', { class: 'tag', text: x.label }), x.date ? el('span', { class: 'muted', text: x.date + ' ' }) : null, x.content.slice(0, 70) + (x.content.length > 70 ? '…' : '')])));
      if (!r.rows.length) right.appendChild(el('p', { class: 'muted', text: '만들어질 기록이 없습니다.' }));
      const students = new Set(r.rows.map((x) => (o.structure === 'single' ? 's' : `${x.line}`))).size;
      const empty = IB.raw.reduce((a, row) => a + row.filter((v) => !v).length, 0);
      summary.innerHTML = '';
      summary.append(el('b', { text: `${o.structure === 'single' ? 1 : students}명 / ${r.rows.length}건 생성 예정` }), el('span', { class: 'muted', text: ` · 빈 셀 ${empty}개 제외 · 확정 전에는 항목에 아무것도 들어가지 않습니다` }));
      go.disabled = !r.rows.length || (o.structure === 'single' && !o.student_no);
    })();
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
    t.appendChild(el('tr', {}, ['원본 위치', '읽은 학번·이름', '연결할 학생', '상태', '내용', ''].map((h) => el('th', { text: h }))));
    v.rows.filter((r) => !IB.onlyPending || r.state === 'none' || r.state === 'suggested').forEach((r) => {
      const sel = el('select', { disabled: r.state === 'excluded' || b.structure === 'single', onchange: async (e) => { if (await mutate('inbox_set_student', r.id, e.target.value)) loadBatch(); } },
        [el('option', { value: '', text: '학생 고르기' }), ...v.members.map((x) => el('option', { value: x.student_no, text: `${x.student_no} ${x.name}`, selected: x.student_no === r.student_no }))]);
      const stateTd = el('td', {}, [el('div', { class: `st-chip ${r.state}`, text: ST_CHIP[r.state] + (r.state === 'excluded' ? ` (${r.exclude_reason})` : '') }),
        r.note && r.state !== 'confirmed' ? el('div', { class: 'note', text: r.note }) : null,
        r.dup ? el('div', { class: 'note', text: '같은 학생이 원본의 다른 줄에도 있음(중복 의심)' }) : null,
        r.state === 'suggested' ? el('button', { type: 'button', class: 'small', text: '확정', onclick: async () => { if (await mutate('inbox_confirm_suggested', b.id, [r.id])) loadBatch(); } }) : null]);
      t.appendChild(el('tr', { class: r.state === 'excluded' ? 'row-excluded' : (r.state === 'none' || r.state === 'suggested') ? 'row-pending' : '' }, [
        el('td', { text: r.source_ref }), el('td', { text: `${r.ext_no || '-'} ${r.ext_name || ''}` }), el('td', {}, [sel]), stateTd,
        el('td', {}, [el('div', { class: 'snip', text: b.source === 'scan' ? r.content : `[${r.label}${r.date ? ' ' + r.date : ''}] ${r.content}` }),
          r.pages ? el('button', { type: 'button', class: 'small', text: '원본 보기', onclick: () => showOriginal(b.id, r.pages.split(',')) }) : null]),
        el('td', {}, [r.state === 'excluded'
          ? el('button', { type: 'button', class: 'small', text: '제외 취소', onclick: async () => { if (await mutate('inbox_exclude', [r.id], '', false)) loadBatch(); } })
          : el('button', { type: 'button', class: 'small', text: '제외', onclick: () => excludeRows([r.id]) })]),
      ]));
    });
    body.appendChild(t);
    body.appendChild(el('p', { class: 'hint', text: '학번과 이름이 모두 명렬과 맞으면 자동 확정, 이름만 맞거나 비슷하면 "추천"입니다. 추천은 원본과 대조한 뒤 확정하세요. 백지·다른 반 자료처럼 보내지 않을 행은 [제외]하면 인박스에 남습니다.' }));
    body.appendChild(el('div', { class: 'sheet-foot' }, [
      el('button', { type: 'button', text: '← 가져오기 다시', onclick: async () => { if (!(await confirmBox('가져오기 단계로 돌아가면 지금 매칭 결과는 다시 만들어집니다.', '돌아가기'))) return; if (await mutate('inbox_stage', b.id, 'import')) { SC.starts = null; loadBatch(); } } }),
      el('span', { class: 'spacer' }),
      pending ? el('span', { class: 'danger-text', style: 'font-weight:700', text: `확인 필요 ${pending}건을 확정하거나 제외해야 다음으로 갑니다.` }) : null,
      el('button', { type: 'button', class: 'primary', disabled: !!pending, text: '다음: AI 정제(선택)', onclick: async () => { if (await mutate('inbox_stage', b.id, 'refine')) loadBatch(); } }),
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
      el('button', { type: 'button', class: 'primary', disabled: !IB.sel.size, text: `선택 ${IB.sel.size}건 정제`, onclick: () => refineRows(rows.filter((r) => IB.sel.has(r.id)), model.value) }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'hint', style: 'margin:0', text: `${slotLabel(b.group_id, b.item)}의 '정제' 지침을 씁니다. AI에는 학번·이름 없이 내용만 보냅니다.` }),
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
      const btn = el('button', { type: 'button', class: 'small', text: r.cands.length ? '다시 정제' : '정제(AI)' });
      btn.addEventListener('click', () => refineRows([r], model.value, btn));
      card.append(el('div', { class: 'ref-cols' }, [el('div', {}, [el('div', { class: 'muted', text: '원문' }), el('div', { class: 'rcard-body', text: r.content })]),
        el('div', {}, [el('div', { class: 'muted', text: '보낼 내용' }), el('div', { class: 'rcard-body', text: r.text })])]), el('div', { class: 'rcard-foot' }, [pickBox, el('span', { class: 'spacer' }), btn]));
      body.appendChild(card);
    });
    body.appendChild(el('div', { class: 'sheet-foot' }, [
      el('button', { type: 'button', text: '← 매칭', onclick: async () => { if (await mutate('inbox_stage', b.id, 'match')) loadBatch(); } }),
      el('span', { class: 'spacer' }),
      el('span', { class: 'hint', style: 'margin:0', text: 'AI 정제는 선택입니다. 정제하지 않은 행은 원문 그대로 보냅니다.' }),
      el('button', { type: 'button', class: 'primary', text: '다음: 보내기 검토', onclick: async () => { if (await mutate('inbox_stage', b.id, 'review')) loadBatch(); } }),
    ]));
  }
  async function refineRows(rows, modelIndex, btn) {
    if (!rows.length) return;
    IB.stop = false;
    let done = 0, fail = 0;
    const msg = el('div', { class: 'modal-msg' });
    const stopBtn = el('button', { type: 'button', class: 'btn-danger', text: '중지', onclick: () => { IB.stop = true; stopBtn.disabled = true; stopBtn.textContent = '중지 중…'; } });
    if (rows.length > 1) {
      openSheet((box) => { box.style.height = 'auto'; box.style.width = 'min(440px, 92vw)'; box.append(el('div', { class: 'sheet-head' }, [el('h2', { text: 'AI 정제 중' })]), msg, el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), stopBtn])); });
    } else if (btn) { btn.disabled = true; btn.classList.add('busy-btn'); }
    const errors = [];
    for (const r of rows) {
      if (IB.stop) break;
      msg.textContent = `${done + fail + 1} / ${rows.length}건 — 실패 ${fail}건\n멈춘 게 아니니 기다려 주세요.`;
      const res = await api.ai_inbox_row(r.id, modelIndex);
      if (res && res.ok) { done += 1; runCost = res.run_cost; $('runCost').textContent = fmtCredit(runCost); }
      else { fail += 1; errors.push(res && res.error); }
    }
    closeSheet();
    refreshBalance();
    if (fail) alertBox(`정제 ${done}건 완료, 실패 ${fail}건.\n${errors[0] || ''}`);
    else if (IB.stop) toast(`중지했습니다. ${done}건은 정제했습니다.`);
    else toast(`${done}건을 정제했습니다. 보낼 내용으로 바로 골라 두었습니다.`);
    IB.sel.clear();
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
      (tags ? tags.tags : []).forEach((t) => tagsBox.appendChild(el('button', { type: 'button', class: tagSet.has(t.id) ? 'on' : '', text: t.name, onclick: async () => { if (tagSet.has(t.id)) tagSet.delete(t.id); else tagSet.add(t.id); drawTags(); await mutate('inbox_update', b.id, { tag_ids: [...tagSet] }); } })));
      if (!tags || !tags.tags.length) tagsBox.appendChild(el('span', { class: 'muted', text: '태그가 없습니다(메뉴의 태그에서 만들기).' }));
    };
    drawTags();
    const itemSel = slotSelect(`${b.group_id}:${b.item}`, b.group_id);
    itemSel.addEventListener('change', async () => { const [, item] = itemSel.value.split(':'); if (await mutate('inbox_update', b.id, { item })) loadBatch(); });
    body.append(
      el('div', { class: 'map-row' }, [el('label', {}, ['보낼 항목', itemSel]), el('label', {}, ['기본 날짜', date]), el('span', { class: 'hint', style: 'margin:0', text: '(제목 줄에 날짜가 있으면 그 날짜를 씁니다)' })]),
      el('label', { text: '태그 (보내는 모든 기록에 붙임)' }), tagsBox,
      el('div', { class: 'wsection' }, [
        el('h3', { text: `${r.students.length}명에게 ${r.send_rows}건 추가` }),
        el('div', { class: 'muted', text: `기존 기록 덮어쓰기 없음 · 제외 ${r.excluded}건 · 회차는 학생마다 이어서 붙습니다` }),
        el('div', { style: 'margin-top:8px' }, r.students.map((s) => el('span', { class: 'tag', text: `${s.name} ${s.count}건` }))),
      ]),
    );
    const sendBtn = el('button', { type: 'button', class: 'primary', text: `${r.students.length}명에게 ${r.send_rows}건 보내기` });
    const doSend = async (action) => {
      const res = await mutate('inbox_send', b.id, action);
      if (!res) return;
      toast(`${res.students}명에게 ${res.records}건을 보냈습니다.`);
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
  function renderSent(body) {
    const v = IB.view;
    const b = v.batch;
    body.append(el('div', { class: 'wsection', style: 'margin-top:0' }, [el('h3', { text: `✔ ${b.sent_at}에 ${b.sent_summary} 보냄` }),
      el('p', { class: 'hint', text: '보낸 묶음은 다시 보낼 수 없습니다(기록 중복 방지). 보낸 기록은 항목별 기록에서 고치세요.' }),
      el('button', { type: 'button', class: 'primary', text: '항목별 기록에서 보기', onclick: () => openRecords(b.group_id, b.item, (v.rows.find((r) => r.state === 'confirmed') || {}).student_no) })]));
    const t = el('table', { class: 'tbl match-tbl' });
    t.appendChild(el('tr', {}, ['원본 위치', '학생', '상태', '보낸 내용'].map((h) => el('th', { text: h }))));
    v.rows.forEach((r) => t.appendChild(el('tr', { class: r.state === 'excluded' ? 'row-excluded' : '' }, [el('td', { text: r.source_ref }), el('td', { text: `${r.student_no || '-'} ${r.matched_name || r.ext_name}` }),
      el('td', { text: r.state === 'excluded' ? `제외(${r.exclude_reason})` : '보냄' }), el('td', {}, [el('div', { class: 'snip', text: r.text })])])));
    body.appendChild(t);
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
  const SD = { gid: null, data: null };
  async function renderStandards() {
    const r = await call('standards_overview');
    if (!r) return;
    const list = $('stdList');
    list.innerHTML = '';
    list.appendChild(el('div', { class: 'sec-title', text: '과목' }));
    if (!r.subjects.length) {
      list.appendChild(el('p', { class: 'hint', text: '등록한 과목이 없습니다. 명렬·담당 관리에서 과목을 추가하세요.' }));
      $('stdMain').innerHTML = '';
      $('stdMain').appendChild(el('div', { class: 'empty-state' }, [el('p', { text: '성취기준은 과목 세특에서 씁니다.' }), el('button', { type: 'button', class: 'primary', text: '명렬·담당 관리', onclick: () => showPanel('roster') })]));
      return;
    }
    if (!r.subjects.find((x) => x.id === SD.gid)) SD.gid = r.subjects[0].id;
    r.subjects.forEach((x) => list.appendChild(el('button', { type: 'button', class: 'ib-item' + (x.id === SD.gid ? ' active' : ''), onclick: () => { SD.gid = x.id; renderStandards(); } }, [
      el('span', { class: 't', text: x.label }), el('span', { class: 's', text: x.has ? `✔ 입력됨 · ${x.updated_at.slice(0, 16)}` : '아직 없음' })])));
    list.appendChild(el('p', { class: 'hint', text: '모든 과목을 미리 넣을 필요는 없습니다. 세특에 성취기준을 쓸 과목만 넣으세요. 학년도마다 따로 저장됩니다.' }));
    const d = await call('standards_get', SD.gid);
    if (!d) return;
    SD.data = d;
    const g = (ys.groups || []).find((x) => x.id === SD.gid);
    const m = $('stdMain');
    m.innerHTML = '';
    const ta = el('textarea', { id: 'stdText', value: d.text, disabled: !!ys.archived, placeholder: '예)\n[10공수1-01-01] 다항식의 사칙연산을 할 수 있다.\n[10공수1-01-02] 항등식의 성질과 나머지정리를 이해한다.\n\n성취수준 A: …  B: …  C: …\n\n성취기준 코드와 문장, 필요하면 성취수준별 설명까지 넣으세요.' });
    const state = el('span', { class: 'muted', text: d.source ? `가져온 곳: ${d.source}` : '' });
    const save = debounce(async (source) => { if (await mutate('standards_save', SD.gid, ta.value, source || null)) { state.textContent = '저장됨'; } }, 600);
    ta.addEventListener('input', () => save());
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
      ta.value = mode === 'append' ? `${ta.value.trim()}\n\n${text}` : text;
      await mutate('standards_save', SD.gid, ta.value, source);
      toast(`${source}에서 읽어 넣었습니다. 필요 없는 부분은 지우세요.`);
      renderStandards();
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
        el('span', { class: 'spacer' }), state,
      ]),
      ta,
      el('p', { class: 'hint', text: '읽어 온 글은 편집할 수 있습니다. 필요한 단원만 남기면 AI가 더 정확하게 씁니다. 세특 종합 창에서 [성취기준 사용]을 켜면 이 내용과 학생의 성취수준을 함께 보냅니다(학번·이름은 보내지 않음).' }),
    );
  }
  function stdBadge(meta) {
    if (!meta || !meta.basis) return null;
    if (meta.basis === 'standards_only') return el('span', { class: 'badge stdonly', text: `기록 없음, 성취기준으로 생성${meta.level ? ` · 수준 ${meta.level}` : ''}` });
    return el('span', { class: 'badge std', text: `성취기준 반영${meta.level ? ` · 수준 ${meta.level}` : ''}` });
  }
  function levelSelect(scale, current) {
    const letters = scale === 3 ? 'ABC' : 'ABCDE';
    return el('select', {}, [el('option', { value: '', text: '(수준 없음)' }), ...letters.split('').map((x) => el('option', { value: x, text: x, selected: x === current }))]);
  }
  function standardsOnlyDialog() {
    const v = R.view;
    if (!v.standards || !v.standards.text.trim()) {
      modal('이 과목의 성취기준이 아직 없습니다. 메뉴의 <b>[성취기준]</b>에서 먼저 넣어 주세요.', true, true, '성취기준으로 가기').then((go) => { if (go) { SD.gid = R.slot.group_id; showPanel('standards'); } });
      return;
    }
    openSheet((box) => {
      const lvl = levelSelect(v.standards.level_scale, v.student.level);
      const ta = el('textarea', { class: 'fill', rows: 12, value: v.standards.text });
      const model = el('select', {});
      fillModelSelect(model);
      model.value = $('recModel').value;
      const run = el('button', { type: 'button', class: 'primary', text: '성취기준만으로 생성' });
      run.addEventListener('click', async () => {
        if (!lvl.value) { toast('성취수준을 골라 주세요.'); lvl.focus(); return; }
        const res = await busyRun(run, `synth${R.sno}`, () => call('ai_standards_only', R.slot.group_id, R.slot.item, R.sno, { text: ta.value, level: lvl.value }, model.value));
        if (!res) return;
        setCredits(res);
        closeSheet();
        toast('후보를 만들었습니다. "기록 없음, 성취기준으로 생성" 표시가 붙습니다. 실제 수업 모습과 맞는지 꼭 확인하세요.');
        loadStudent(true);
      });
      box.append(
        el('div', { class: 'sheet-head' }, [el('h2', { text: `성취기준만으로 생성 · ${v.student.name}` }), el('span', { class: 'muted', text: `${R.slot.label} · 목표 ${R.target}B` })]),
        el('div', { class: 'sheet-body' }, [
          el('div', { class: 'warn', text: '이 학생은 누가기록이 없어 성취기준만으로 문장을 만듭니다. 결과에는 "기록 없음, 성취기준으로 생성" 표시가 남습니다. 활동명·사건은 지어내지 않도록 지시합니다.' }),
          el('div', { class: 'map-row' }, [el('label', {}, [`성취수준(${v.standards.level_scale}단계)`, lvl]), el('span', { class: 'muted', text: v.student.level ? `명렬 값: ${v.student.level}` : '명렬에 수준이 없습니다' }), el('label', {}, ['모델', model])]),
          el('div', { class: 'col-label', text: '이번에 쓸 성취기준 (필요한 부분만 남겨도 됩니다)' }), ta,
        ]),
        el('div', { class: 'sheet-foot' }, [el('span', { class: 'spacer' }), el('button', { type: 'button', text: '취소', onclick: closeSheet }), run]),
      );
    });
  }

  // ---------- 파이썬 → 화면 이벤트 ----------
  window.onAppEvent = function (ev) {
    switch (ev.type) {
      case 'update_available':
        showUpdate(ev);
        break;
      case 'update_progress':
        if (ev.stage === 'backup') $('updateText').textContent = '자료를 백업하는 중…';
        else if (ev.stage === 'download') $('updateText').textContent = `내려받는 중… ${Math.round((ev.done / ev.total) * 100)}%`;
        else $('updateText').textContent = '곧 다시 시작합니다…';
        break;
      case 'ocr_progress':
      case 'ocr_done':
      case 'ocr_stopped':
      case 'ocr_error':
        ocrEvent(ev);
        break;
      case 'update_error':
        $('updateText').textContent = `업데이트 실패: ${ev.message} (자세한 기록: 자료 폴더의 업데이트_기록.txt)`;
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
    $('yearSelect').addEventListener('change', async (e) => { if (await call('switch_year', +e.target.value)) { await reloadYear(); toast(`${e.target.value}학년도로 바꿨습니다.`); } });
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
      if (!(await confirmBox(`${ys.year}학년도의 명렬과 기록을 모두 지웁니다. 지우기 전에 백업을 하나 만듭니다. 정말 지울까요?`, '삭제'))) return;
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
      if (!(await confirmBox(`v${updateInfo.version}로 업데이트합니다.\n자료를 먼저 백업한 뒤 새 버전을 내려받고 앱을 다시 시작합니다.`, '업데이트'))) return;
      $('updateNowBtn').disabled = true;
      const r = await call('update_apply');
      if (!r) $('updateNowBtn').disabled = false;
    });
    $('recSlot').addEventListener('change', (e) => { R.slot = R.slots.find((s) => slotKey(s) === e.target.value); R.sno = null; R.selected.clear(); R.filter = ''; loadSlotStudents(); });
    $('recPrev').addEventListener('click', () => moveStudent(-1));
    $('recNext').addEventListener('click', () => moveStudent(1));
    ['expScopeRows', 'expOrder'].forEach((id) => $(id).addEventListener('change', loadExport));
    $('expSlot').addEventListener('change', (e) => { E.slotKey = e.target.value; loadExport(); });
    $('expCopyBtn').addEventListener('click', () => doExport('copy'));
    $('expXlsxBtn').addEventListener('click', () => doExport('xlsx'));
    const addTag = async () => { if (await mutate('add_tag', $('tagNew').value)) { $('tagNew').value = ''; renderTags(); } };
    $('tagAddBtn').addEventListener('click', addTag);
    $('tagNew').addEventListener('keydown', (e) => { if (e.key === 'Enter') addTag(); });
    $('prItem').addEventListener('change', (e) => { P.item = e.target.value; renderPrompts(); });
    $('prPrompt').addEventListener('input', savePrompt);
    $('prExample').addEventListener('input', savePrompt);
    $('prResetBtn').addEventListener('click', async () => {
      if (!(await confirmBox(`'${P.data.items[P.item]} · ${P.data.ops[P.op]}'의 지침과 예시를 기본값으로 되돌립니다.`, '되돌리기'))) return;
      if (await mutate('prompts_reset', P.item, P.op)) renderPrompts();
    });
    document.addEventListener('keydown', (e) => {
      if (panel !== 'records' || !$('sheet').hidden || !$('modal').hidden || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
      if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); moveStudent(1); }
      if (e.altKey && e.key === 'ArrowUp') { e.preventDefault(); moveStudent(-1); }
    });
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

  async function init() {
    api = window.pywebview.api;
    info = await api.app_info();
    $('verText').textContent = 'v' + info.version.replace(/\.0$/, '');
    const c = await api.load_config();
    cfg = c.config;
    setCollapsed(cfg.menu_collapsed);
    fillSoon();
    bind();
    fillConfigInputs();
    loadClovaGuide();
    api.startup();
    refreshBalance();
    api.run_cost().then((r) => { if (r && r.ok) { runCost = r.run_cost; $('runCost').textContent = fmtCredit(runCost); } });
    const r = await api.year_state();
    ys = r && r.ok ? r : { year: 0, years: [] };
    renderYearSelect();
    refreshInboxBadge();
    if (!cfg.setup_done || !ys.year) {
      showPanel('dashboard');
      openWizard('first', cfg.openrouter_key ? (ys.year ? 3 : 2) : 1);
      if (!cfg.openrouter_key) W.step = 1;
      renderWizard();
    } else {
      showPanel('dashboard');
    }
  }

  window.addEventListener('pywebviewready', init);
})();

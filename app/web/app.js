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
    modal(`<div class="about-box"><div class="about-title">🍊 생기부 착즙기</div><div class="muted">v${info.version} 베타</div>` +
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
    renderYearSelect();
    $('crumb').textContent = `${ys.year ? ys.year + '학년도 › ' : ''}${PANEL_TITLES[panel] || ''}`;
    if (panel === 'dashboard') loadDashboard();
    if (panel === 'roster') renderRoster();
    if (panel === 'settings') renderSettings();
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
      dash.todo.forEach((t) => todo.appendChild(el('button', { type: 'button', text: t.label, onclick: () => { rosterSel = t.group_id; showPanel('roster'); } })));
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
      const tr = el('tr', { class: 'clickable' + (r.active ? '' : ' inactive'), onclick: () => toast('학생 편집 화면은 v0.2에서 제공합니다.') });
      tr.appendChild(el('td', { text: r.student_no }));
      tr.appendChild(el('td', { text: r.name }));
      if (g.kind === 'homeroom') {
        g.items.forEach((it) => tr.appendChild(stCell(r.status[it])));
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
    $('updateText').textContent = `🍊 새 버전 v${ev.version}이(가) 있습니다.`;
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
      case 'update_error':
        $('updateText').textContent = '업데이트 실패: ' + ev.message;
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
    const r = await api.year_state();
    ys = r && r.ok ? r : { year: 0, years: [] };
    renderYearSelect();
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

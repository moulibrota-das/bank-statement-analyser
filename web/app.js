/* Statement Analyser UI. Talks to the FastAPI backend over HTTP (same origin, or ?api=https://host). */
(function () {
  const { CATS, COLOR, inr } = window.SA;
  const API = (new URLSearchParams(location.search).get('api') || '').replace(/\/$/, '');
  const STEPS = ['Checking this is a bank statement', 'Extracting transactions', 'Categorising transactions',
    'Checking for unusual activity', 'Writing summary'];
  const EXT = ['.pdf', '.csv', '.xlsx', '.png', '.jpg', '.jpeg', '.webp'];
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const state = {
    stage: 'upload', fileName: '', fileSize: '', step: 0, report: null, view: null, overrides: {},
    filter: 'All', query: '', flaggedOnly: false, hl: [], error: '', useLlm: true, maxMb: 10, sampleIdx: 0, seq: 0
  };
  let timer = null;

  const ICON = {
    upload: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>',
    file: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z"/><path d="M14 3v5h5"/></svg>',
    check: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    dl: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12M7 11l5 5 5-5M5 20h14"/></svg>',
    search: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
    chev: '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#6B6F76" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
    warn: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.5l9 16H3l9-16z"/><path d="M12 10v4M12 17v.01"/></svg>'
  };

  // ------------------------------------------------------------------ API
  async function loadHealth() {
    try {
      const h = await (await fetch(API + '/health')).json();
      state.maxMb = h.max_upload_mb || state.maxMb;
      $('#mock').hidden = h.mode !== 'mock';
      if (state.stage === 'upload') render();
    } catch { /* API offline: surfaced on first request */ }
  }

  function fmtSize(bytes) {
    const mb = bytes / 1048576;
    return mb >= 1 ? mb.toFixed(1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB';
  }

  async function analyse(name, size, request) {
    const seq = ++state.seq;
    clearInterval(timer);
    Object.assign(state, { stage: 'analysing', fileName: name, fileSize: size, step: 0, error: '', report: null,
      overrides: {}, filter: 'All', query: '', flaggedOnly: false, hl: [] });
    window.scrollTo(0, 0);
    render();
    timer = setInterval(() => {  // pace the steps while the server works; never run ahead of it
      if (state.step < STEPS.length - 1) { state.step++; renderProgress(); }
    }, 900);
    try {
      const res = await request();
      if (seq !== state.seq) return;
      if (!res.ok) {
        let detail = 'Something went wrong while analysing this file.';
        try { detail = (await res.json()).detail || detail; } catch { /* non-JSON error */ }
        throw new Error(detail);
      }
      const report = await res.json();
      if (seq !== state.seq) return;
      clearInterval(timer);
      state.report = report;
      state.view = window.SA.buildView(report, {});
      state.step = STEPS.length;
      renderProgress();
      setTimeout(() => { if (seq === state.seq) { state.stage = 'results'; render(); window.scrollTo(0, 0); } }, 700);
    } catch (e) {
      if (seq !== state.seq) return;
      clearInterval(timer);
      state.stage = 'upload';
      state.error = e instanceof TypeError ? 'Could not reach the analysis service. Is the API running?' : e.message;
      render();
    }
  }

  function handleFile(f) {
    if (!f) return;
    const ext = '.' + f.name.split('.').pop().toLowerCase();
    if (!EXT.includes(ext)) { state.error = 'Unsupported file type. Upload a PDF, CSV, XLSX or image (PNG/JPG) of your statement.'; return render(); }
    if (f.size > state.maxMb * 1048576) { state.error = `File is larger than ${state.maxMb} MB.`; return render(); }
    const fd = new FormData();
    fd.append('file', f);
    analyse(f.name, fmtSize(f.size), () => fetch(`${API}/analyze?use_llm=${state.useLlm}`, { method: 'POST', body: fd }));
  }

  async function useSample() {
    try {
      const list = await (await fetch(API + '/samples')).json();
      if (!list.length) throw new Error('no samples');
      const s = list[state.sampleIdx++ % list.length];
      analyse(`${s.name}.${s.format}`, 'sample', () => fetch(`${API}/samples/${s.name}/analyze?use_llm=${state.useLlm}`));
    } catch { state.error = 'Could not load a sample. Is the API running?'; render(); }
  }

  function download(name, text, type) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ------------------------------------------------------------------ rendering
  function render() {
    const v = $('#view');
    if (state.stage === 'upload') v.innerHTML = uploadHtml();
    else if (state.stage === 'analysing') v.innerHTML = progressHtml();
    else v.innerHTML = resultsHtml();
    bind();
  }

  function uploadHtml() {
    return `<main class="upload">
  <div><h1>Make sense of your bank statement.</h1>
  <p class="lede">Upload a statement and we'll read the account details, extract every transaction, sort your spending into categories and flag anything that looks unusual.</p></div>
  <div class="drop" id="drop" tabindex="0" role="button" aria-label="Upload a statement">
    <div class="ico">${ICON.upload}</div>
    <div class="t">Drop your statement here</div>
    <div class="s">or <u>browse files</u> · PDF, CSV, XLSX or image, up to ${state.maxMb} MB</div>
    <input type="file" id="file" accept=".pdf,.csv,.xlsx,.png,.jpg,.jpeg,.webp" hidden>
  </div>
  ${state.error ? `<div class="err" role="alert">${esc(state.error)}</div>` : ''}
  <div class="opts">
    <span class="l">No statement handy?</span>
    <label class="llm" title="Off: deterministic rules and a template summary only"><input type="checkbox" id="llm" ${state.useLlm ? 'checked' : ''}>Use AI for ambiguous rows &amp; summary</label>
    <button class="btn" id="sample">Try a sample statement</button>
  </div>
  <div class="feats">
    <div><span class="n">01</span><b>Account &amp; period</b><span>Bank, holder, account number and statement dates.</span></div>
    <div><span class="n">02</span><b>Transactions</b><span>Every line extracted, cleaned and categorised.</span></div>
    <div><span class="n">03</span><b>Spending summary</b><span>Money in, money out and where it went.</span></div>
    <div><span class="n">04</span><b>Unusual activity</b><span>Duplicates, new payees, spikes and bounced charges.</span></div>
  </div></main>`;
  }

  function stepDetail(i) {
    const r = state.report;
    if (!r) return '';
    const phase = n => (r.processing.phases || []).find(p => p.name === n);
    const n = r.transactions.length, cats = new Set(r.transactions.map(t => t.category)).size;
    return [
      phase('document_check') ? phase('document_check').detail : 'Bank statement',
      phase('extraction') ? `${phase('extraction').method} · ${n} transactions` : n + ' transactions',
      cats + ' categories assigned',
      r.anomalies.length + (r.anomalies.length === 1 ? ' item' : ' items') + ' flagged for review',
      'Ready'][i];
  }

  function progressHtml() {
    const pct = Math.min(100, Math.round(state.step / STEPS.length * 100));
    return `<main class="analysing"><div class="card prog">
  <div class="hd"><div class="fi">${ICON.file}</div>
    <div class="nm"><b>${esc(state.fileName)}</b><span>${esc(state.fileSize)} · Analysing…</span></div>
    <span class="pct" id="pct">${pct}%</span></div>
  <div class="bar"><i id="barfill" style="width:${pct}%"></i></div>
  <div class="steps" id="steps">${stepsHtml()}</div></div></main>`;
  }

  function stepsHtml() {
    return STEPS.map((label, i) => {
      const done = i < state.step, active = i === state.step;
      const mark = done ? `<span class="done">${ICON.check}</span>` : active ? '<span class="spin"></span>' : '<span class="pend"></span>';
      return `<div class="step ${done || active ? '' : 'off'}"><div class="m">${mark}</div>
        <div class="tx"><b>${esc(label)}</b>${done && stepDetail(i) ? `<span>${esc(stepDetail(i))}</span>` : ''}</div></div>`;
    }).join('');
  }

  function renderProgress() {
    const s = $('#steps');
    if (!s) return;
    const pct = Math.min(100, Math.round(state.step / STEPS.length * 100));
    s.innerHTML = stepsHtml();
    $('#pct').textContent = pct + '%';
    $('#barfill').style.width = pct + '%';
  }

  function resultsHtml() {
    const v = state.view, r = state.report, a = v.account, rec = r.reconciliation;
    const status = rec.passed
      ? `<div class="status ok">${ICON.check.replace('width="12" height="12"', 'width="14" height="14"')} Balances reconcile: ${rec.rows_checked} running balances verified against the statement.</div>`
      : '';  // mismatches stay in the report/JSON export; the page does not display them
    const notes = [r.processing.mock_mode && r.summary.source !== 'template' ? 'Mock mode: AI classifications and the summary come from an offline stub, not a real model.' : '']
      .concat((r.warnings || []).filter(w => !/reconcil/i.test(w))).filter(Boolean)
      .map(w => `<div class="status note">${esc(w)}</div>`).join('');
    return `<main class="results">
  <div class="rhead"><div><h1>${esc(v.title)}</h1><span class="sub">${esc(state.fileName)} · analysed just now</span></div>
    <div class="acts"><button class="btn" id="csv">${ICON.dl}CSV</button><button class="btn" id="json">${ICON.dl}JSON</button>
    <button class="btn dark" id="again">Analyse another</button></div></div>
  ${status}${notes}
  <div class="row2">
    <section class="summary"><span class="k">Financial summary</span><div>${v.summaryLines.map(l => `<p>${esc(l)}</p>`).join('')}</div></section>
    <section class="card account"><div class="hd"><b>Account</b>${a.type ? `<span class="badge">${esc(a.type)}</span>` : ''}</div>
      <dl><dt>Holder</dt><dd class="b">${esc(a.holder || '—')}</dd><dt>Bank</dt><dd>${esc(a.bank || '—')}</dd>
      <dt>Account no.</dt><dd class="m">${esc(a.number || '—')}</dd><dt>IFSC</dt><dd class="m">${esc(a.ifsc || '—')}</dd>
      <dt>Period</dt><dd>${esc(v.periodText || '—')}</dd></dl>
      <div class="bal"><div><span>Opening balance</span><span>${v.opening == null ? '—' : inr(v.opening)}</span></div>
      <div><span>Closing balance</span><span>${v.closing == null ? '—' : inr(v.closing)}</span></div></div></section>
  </div>
  <div class="card metrics">${v.metrics.map(m => `<div><span class="l">${m.label}</span><span class="v" style="color:${m.color}">${esc(m.value)}</span><span class="n">${esc(m.note)}</span></div>`).join('')}</div>
  <div class="row3">
    <section class="card panel" style="flex:1 1 380px"><div class="hd"><b>Spending by category</b><span id="spendtot"></span></div>
      <div class="stack" id="stack"></div><div class="cats" id="cats"></div></section>
    <section class="card panel" style="flex:1.35 1 440px"><div class="hd"><b>Unusual activity</b><span style="font-family:inherit">${v.flags.length} ${v.flags.length === 1 ? 'item' : 'items'} to review</span></div>
      <div class="flags">${v.flags.length ? v.flags.map((f, i) => `<div class="flag"><div class="t"><span class="sev ${f.sev}">${f.sev}</span><b>${esc(f.title)}</b><span class="a">${esc(f.amtText)}</span></div>
        <p>${esc(f.detail)}</p><div class="f"><span>${esc(f.dateText)}</span><button class="link" data-flag="${i}">View transactions →</button></div></div>`).join('')
        : '<div class="empty">Nothing unusual found in this statement.</div>'}</div></section>
  </div>
  <section class="card tbl" id="table"><div class="hd">
    <div class="r1"><div class="tt"><b>Transactions</b><span id="count"></span></div>
      <div class="tools"><label><input type="checkbox" id="flagged" ${state.flaggedOnly ? 'checked' : ''}>Flagged only</label>
      <div class="search">${ICON.search}<input id="q" value="${esc(state.query)}" placeholder="Search merchant or reference"></div></div></div>
    <div class="chips" id="chips"></div></div>
    <div class="scroll"><table><thead><tr><th style="width:72px">Date</th><th>Description</th><th style="width:64px">Mode</th><th style="width:170px">Category</th>
      <th class="r" style="width:140px">Amount</th><th class="r" style="width:140px">Balance</th><th style="width:40px"></th></tr></thead><tbody id="rows"></tbody></table>
      <div class="none" id="none" hidden>No transactions match these filters.</div></div></section>
</main>`;
  }

  function currentView() { return window.SA.buildView(state.report, state.overrides); }

  function renderCategories() {
    const v = state.view;
    $('#spendtot').textContent = inr(v.spend, 0) + ' total';
    $('#stack').innerHTML = v.spendCats.map(c => `<span style="width:${c.w};background:${c.color}"></span>`).join('');
    $('#cats').innerHTML = v.spendCats.map(c => `<button class="cat" data-cat="${c.id}"><span class="dot" style="background:${c.color}"></span>
      <span class="n"><b>${c.id}</b><i>${c.countText}</i></span><span class="a">${c.amtText}</span><span class="p">${c.pctText}</span></button>`).join('');
  }

  function renderTable() {
    const v = state.view;
    const rows = window.SA.filterTxs(v.txs, state);
    $('#count').textContent = rows.length === v.txs.length ? v.txs.length + ' extracted' : rows.length + ' of ' + v.txs.length;
    $('#chips').innerHTML = window.SA.chipDefs(v.txs).map(c =>
      `<button class="chip ${state.filter === c.label ? 'on' : ''}" data-chip="${c.label}">${c.label}<i>${c.count}</i></button>`).join('');
    $('#none').hidden = rows.length > 0;
    $('#rows').innerHTML = rows.map(t => {
      const src = t.manual ? 'Set by you' : t.source === 'llm' ? `AI · ${Math.round(t.confidence * 100)}% · ${t.rationale || ''}` : `Rule · ${t.rationale || ''}`;
      return `<tr class="${state.hl.includes(t.id) ? 'hl' : ''}"><td class="d">${t.dayMon}</td>
      <td><div class="mer"><b>${esc(t.merchant)}</b><span>${esc(t.raw)}</span></div></td><td class="mode">${esc(t.mode)}</td>
      <td><div class="sel" title="${esc(src)}"><span class="dot2" style="background:${COLOR[t.cat]}"></span>
        <select data-tx="${t.id}">${CATS.map(c => `<option ${c.id === t.cat ? 'selected' : ''}>${c.id}</option>`).join('')}</select>${ICON.chev}${t.manual ? '<span class="man"></span>' : ''}</div></td>
      <td class="r am" style="color:${t.amt > 0 ? '#1F6B4F' : '#17181C'}">${t.amt > 0 ? '+' : '−'}${inr(t.amt)}</td>
      <td class="r ba">${t.bal == null ? '' : inr(t.bal)}</td>
      <td>${t.flag ? `<span title="${esc(t.flag.title)}" style="display:flex;color:${{ high: '#B42318', medium: '#B54708', low: '#4A5260' }[t.flag.sev]}">${ICON.warn}</span>` : ''}</td></tr>`;
    }).join('');
  }

  function scrollToTable() {
    const el = $('#table');
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 16, behavior: 'smooth' });
  }

  function bind() {
    $('#home').onclick = () => { state.seq++; clearInterval(timer); Object.assign(state, { stage: 'upload', error: '', step: 0 }); render(); };
    if (state.stage === 'upload') {
      const drop = $('#drop'), file = $('#file');
      drop.onclick = () => file.click();
      drop.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); file.click(); } };
      file.onchange = e => { handleFile(e.target.files[0]); e.target.value = ''; };
      drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
      drop.ondragleave = () => drop.classList.remove('over');
      drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); handleFile(e.dataTransfer.files[0]); };
      $('#sample').onclick = useSample;
      $('#llm').onchange = e => { state.useLlm = e.target.checked; };
    }
    if (state.stage === 'results') {
      state.view = currentView();
      renderCategories(); renderTable();
      $('#again').onclick = $('#home').onclick;
      $('#csv').onclick = () => download('transactions.csv', window.SA.toCsv(state.view.txs), 'text/csv');
      $('#json').onclick = () => download('analysis.json', window.SA.toJson(state.report, state.overrides), 'application/json');
      $('#flagged').onchange = e => { state.flaggedOnly = e.target.checked; state.hl = []; renderTable(); };
      $('#q').oninput = e => { state.query = e.target.value; state.hl = []; renderTable(); };
      $('#view').onclick = e => {
        const flag = e.target.closest('[data-flag]'), cat = e.target.closest('[data-cat]'), chip = e.target.closest('[data-chip]');
        if (flag) {
          Object.assign(state, { filter: 'All', query: '', flaggedOnly: true, hl: state.view.flags[+flag.dataset.flag].tx });
          $('#flagged').checked = true; $('#q').value = ''; renderTable(); scrollToTable();
        } else if (cat) {
          Object.assign(state, { filter: cat.dataset.cat, flaggedOnly: false, hl: [] });
          $('#flagged').checked = false; renderTable(); scrollToTable();
        } else if (chip) { state.filter = chip.dataset.chip; state.hl = []; renderTable(); }
      };
      $('#view').onchange = e => {
        const sel = e.target.closest('select[data-tx]');
        if (!sel) return;
        state.overrides[sel.dataset.tx] = sel.value;
        state.view = currentView();
        renderCategories(); renderTable();
      };
    }
  }

  render();
  loadHealth();
})();

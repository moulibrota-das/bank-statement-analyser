/* Pure view-model helpers (no DOM). Loaded by index.html and by node tests. */
(function (root) {
  const CATS = [
    { id: 'Salary', c: '#1F6B4F' }, { id: 'Rent', c: '#3D4FA1' }, { id: 'Utilities', c: '#0E7490' },
    { id: 'Shopping', c: '#B4537A' }, { id: 'Food', c: '#C2702A' }, { id: 'Travel', c: '#6D5BB8' },
    { id: 'Transfers', c: '#5B6B7A' }, { id: 'Other', c: '#9A9484' }];
  const COLOR = Object.fromEntries(CATS.map(c => [c.id, c.c]));
  const SEV_RANK = { high: 3, medium: 2, low: 1 };
  const FLAG_TITLES = {
    AMOUNT_OUTLIER: 'Unusually large payment', NEW_PAYEE_LARGE: 'Large payment to a new payee',
    ROUND_NUMBER_LARGE: 'Large round-number transfer', DUPLICATE: 'Possible duplicate charge',
    PASS_THROUGH: 'Money passing straight through', LOW_BALANCE: 'Balance near zero or negative',
    BOUNCE_PENALTY: 'Bounce or penalty charge', CASH_SPIKE: 'Spike in cash withdrawals'};
  const KEEP_UPPER = new Set(['ATM', 'UPI', 'IRCTC', 'LLP', 'IMPS', 'NEFT', 'RTGS', 'LIC', 'SIP', 'POS', 'ACH', 'AWS', 'EMEA']);
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const MONTH_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  const inr = (n, d = 2) => '₹' + Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d });
  const parseDate = s => { const [y, m, d] = s.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const dayMon = s => { const d = parseDate(s); return String(d.getUTCDate()).padStart(2, '0') + ' ' + MONTHS[d.getUTCMonth()]; };

  function titleCase(s) {
    if (!s) return '';
    if (s !== s.toUpperCase()) return s;
    return s.toLowerCase().split(/(\s+)/).map(w => KEEP_UPPER.has(w.toUpperCase()) ? w.toUpperCase()
      : w.charAt(0).toUpperCase() + w.slice(1)).join('');
  }

  function periodTitle(start, end) {
    if (!start || !end) return 'Statement';
    const a = parseDate(start), b = parseDate(end);
    if (a.getUTCFullYear() === b.getUTCFullYear() && a.getUTCMonth() === b.getUTCMonth())
      return MONTH_LONG[a.getUTCMonth()] + ' ' + a.getUTCFullYear() + ' statement';
    if (a.getUTCFullYear() === b.getUTCFullYear())
      return MONTHS[a.getUTCMonth()] + ' – ' + MONTHS[b.getUTCMonth()] + ' ' + a.getUTCFullYear() + ' statement';
    return MONTHS[a.getUTCMonth()] + ' ' + a.getUTCFullYear() + ' – ' + MONTHS[b.getUTCMonth()] + ' ' + b.getUTCFullYear() + ' statement';
  }

  function periodText(start, end) {
    if (!start || !end) return '';
    const a = parseDate(start), b = parseDate(end), days = Math.round((b - a) / 864e5) + 1;
    const f = d => String(d.getUTCDate()).padStart(2, '0') + ' ' + MONTHS[d.getUTCMonth()];
    return `${f(a)} – ${f(b)} ${b.getUTCFullYear()} · ${days} days`;
  }

  function sentences(text) {
    return (text || '').split(/(?<=[.!?])\s+(?=[A-Z₹\d])/).map(s => s.trim()).filter(Boolean);
  }

  function buildView(report, overrides = {}) {
    const flagsRaw = report.anomalies || [];
    const flagOf = {};
    flagsRaw.forEach((f, i) => f.txn_idx.forEach(idx => {
      const cur = flagOf[idx];
      if (!cur || SEV_RANK[f.severity] > SEV_RANK[flagsRaw[cur].severity]) flagOf[idx] = i;
    }));
    const txs = report.transactions.map(t => {
      const amt = (t.direction === 'credit' ? 1 : -1) * Number(t.amount);
      const fi = flagOf[t.idx];
      return {
        id: t.idx, date: t.date, dayMon: dayMon(t.date), merchant: titleCase(t.counterparty) || t.narration.slice(0, 28),
        raw: t.narration, mode: t.channel === 'OTHER' ? '' : t.channel, amt,
        cat: overrides[t.idx] || t.category, manual: overrides[t.idx] !== undefined,
        source: t.category_source, confidence: t.category_confidence, rationale: t.category_rationale,
        bal: t.balance === null || t.balance === undefined ? null : Number(t.balance),
        flag: fi === undefined ? null : { title: FLAG_TITLES[flagsRaw[fi].code] || flagsRaw[fi].code, sev: flagsRaw[fi].severity }
      };
    });
    const income = txs.filter(t => t.amt > 0).reduce((a, t) => a + t.amt, 0);
    const spend = txs.filter(t => t.amt < 0).reduce((a, t) => a - t.amt, 0);
    const net = income - spend;
    const meta = report.meta, rec = report.reconciliation;
    const lastBal = [...txs].reverse().find(t => t.bal !== null);
    const opening = meta.opening_balance != null ? Number(meta.opening_balance) : (rec.opening != null ? Number(rec.opening) : null);
    const closing = meta.closing_balance != null ? Number(meta.closing_balance) : (lastBal ? lastBal.bal : null);
    const dates = txs.map(t => t.date).sort();
    const start = meta.period_start || dates[0], end = meta.period_end || dates[dates.length - 1];
    const days = start && end ? Math.round((parseDate(end) - parseDate(start)) / 864e5) + 1 : 1;

    const spendCats = categoryBreakdown(txs, spend);
    const credits = txs.filter(t => t.amt > 0).length, debits = txs.filter(t => t.amt < 0).length;
    const metrics = [
      { label: 'Money in', value: inr(income, 0), note: credits + (credits === 1 ? ' credit' : ' credits'), color: '#1F6B4F' },
      { label: 'Money out', value: inr(spend, 0), note: debits + (debits === 1 ? ' debit' : ' debits'), color: '#17181C' },
      { label: 'Net', value: (net < 0 ? '−' : '+') + inr(net, 0),
        note: income > 0 ? 'Savings rate ' + Math.round(net / income * 100) + '%' : 'No income in period',
        color: net < 0 ? '#B42318' : '#1F6B4F' },
      { label: 'Avg. daily spend', value: inr(spend / days, 0),
        note: debits ? 'Largest: ' + inr(Math.max(...txs.filter(t => t.amt < 0).map(t => -t.amt)), 0) : '—', color: '#17181C' }];

    const flags = flagsRaw.map(f => {
      const items = f.txn_idx.map(i => txs.find(t => t.id === i)).filter(Boolean);
      const debitsSum = items.filter(t => t.amt < 0).reduce((a, t) => a - t.amt, 0);
      const amount = debitsSum || items.reduce((a, t) => a + Math.abs(t.amt), 0);
      const ds = items.map(t => t.date).sort();
      const range = !ds.length ? '' : ds[0] === ds[ds.length - 1] ? dayMon(ds[0]) : dayMon(ds[0]) + ' – ' + dayMon(ds[ds.length - 1]);
      return {
        sev: f.severity[0].toUpperCase() + f.severity.slice(1), title: FLAG_TITLES[f.code] || f.code, detail: f.reason,
        amtText: inr(amount, 0), dateText: range + (range ? ' · ' : '') + items.length + (items.length === 1 ? ' transaction' : ' transactions'),
        tx: f.txn_idx };
    });

    return {
      txs, income, spend, net, opening, closing, days, spendCats, metrics, flags,
      title: periodTitle(start, end), periodText: periodText(start, end),
      summaryLines: sentences(report.summary && report.summary.narrative),
      account: {
        holder: meta.account_holder, bank: [meta.bank_name, meta.branch].filter(Boolean).join(', '),
        number: meta.account_number_masked ? meta.account_number_masked.replace(/(?=(?:.{4})+$)/g, ' ').trim() : '',
        ifsc: meta.ifsc, type: (meta.source_type || '').toUpperCase() }
    };
  }

  function categoryBreakdown(txs, spend) {
    return CATS.map(c => {
      const list = txs.filter(t => t.cat === c.id && t.amt < 0);
      const amt = list.reduce((a, t) => a - t.amt, 0);
      return { id: c.id, color: c.c, amt, n: list.length };
    }).filter(c => c.amt > 0).sort((a, b) => b.amt - a.amt).map(c => ({
      ...c, w: (c.amt / spend * 100).toFixed(2) + '%', pctText: Math.round(c.amt / spend * 100) + '%',
      amtText: inr(c.amt, 0), countText: c.n + (c.n === 1 ? ' txn' : ' txns')}));
  }

  function chipDefs(txs) {
    return [{ label: 'All', count: txs.length }].concat(
      CATS.map(c => ({ label: c.id, count: txs.filter(t => t.cat === c.id).length })).filter(c => c.count > 0));
  }

  function filterTxs(txs, { filter = 'All', flaggedOnly = false, query = '' }) {
    const q = query.trim().toLowerCase();
    return txs.filter(t => (filter === 'All' || t.cat === filter) && (!flaggedOnly || t.flag) &&
      (!q || t.merchant.toLowerCase().includes(q) || t.raw.toLowerCase().includes(q)));
  }

  function toCsv(txs) {
    const q = v => '"' + String(v ?? '').replace(/"/g, '""') + '"';
    const head = ['date', 'merchant', 'reference', 'mode', 'category', 'amount', 'balance', 'flag'].join(',');
    return [head].concat(txs.map(t => [t.date, t.merchant, t.raw, t.mode, t.cat, t.amt.toFixed(2),
      t.bal === null ? '' : t.bal.toFixed(2), t.flag ? t.flag.title : ''].map(q).join(','))).join('\n');
  }

  function toJson(report, overrides) {
    const out = JSON.parse(JSON.stringify(report));
    out.transactions.forEach(t => {
      if (overrides[t.idx] !== undefined) { t.category = overrides[t.idx]; t.category_source = 'manual'; t.category_confidence = 1; }
    });
    return JSON.stringify(out, null, 2);
  }

  const api = { CATS, COLOR, inr, titleCase, periodTitle, periodText, sentences, buildView, categoryBreakdown,
    chipDefs, filterTxs, toCsv, toJson, FLAG_TITLES };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.SA = api;
})(typeof window !== 'undefined' ? window : globalThis);

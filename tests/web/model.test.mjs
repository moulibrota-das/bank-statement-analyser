import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const SA = createRequire(import.meta.url)('../../web/model.js');
const report = JSON.parse(readFileSync(process.env.REPORT_JSON, 'utf8'));

test('totals match the API analytics (display numbers)', () => {
  const v = SA.buildView(report);
  assert.equal(v.income.toFixed(2), Number(report.analytics.total_credits).toFixed(2));
  assert.equal(v.spend.toFixed(2), Number(report.analytics.total_debits).toFixed(2));
  assert.equal(v.txs.length, report.transactions.length);
  assert.equal(v.metrics.length, 4);
});

test('category breakdown sums to total spend and is sorted', () => {
  const v = SA.buildView(report);
  const sum = v.spendCats.reduce((a, c) => a + c.amt, 0);
  assert.ok(Math.abs(sum - v.spend) < 0.01);
  for (let i = 1; i < v.spendCats.length; i++) assert.ok(v.spendCats[i - 1].amt >= v.spendCats[i].amt);
});

test('category override recomputes breakdown, chips and is marked manual', () => {
  const food = report.transactions.find(t => t.category === 'Food' && t.direction === 'debit');
  const before = SA.buildView(report);
  const after = SA.buildView(report, { [food.idx]: 'Travel' });
  const tx = after.txs.find(t => t.id === food.idx);
  assert.equal(tx.cat, 'Travel'); assert.equal(tx.manual, true);
  const amt = c => (c.find(x => x.id === 'Travel') || { amt: 0 }).amt;
  assert.ok(Math.abs(amt(after.spendCats) - amt(before.spendCats) - Number(food.amount)) < 0.01);
  const chips = SA.chipDefs(after.txs);
  assert.equal(chips[0].count, after.txs.length);
});

test('flags map to transactions and drive the flagged-only filter', () => {
  const v = SA.buildView(report);
  assert.equal(v.flags.length, report.anomalies.length);
  const flagged = SA.filterTxs(v.txs, { flaggedOnly: true });
  assert.ok(flagged.length > 0 && flagged.every(t => t.flag));
  const ids = new Set(report.anomalies.flatMap(a => a.txn_idx));
  assert.deepEqual(new Set(flagged.map(t => t.id)), ids);
  assert.ok(v.flags.every(f => f.title && f.detail && /^₹/.test(f.amtText)));
});

test('search and category filters', () => {
  const v = SA.buildView(report);
  const food = SA.filterTxs(v.txs, { filter: 'Food' });
  assert.ok(food.every(t => t.cat === 'Food'));
  const q = v.txs[0].merchant.slice(0, 4).toLowerCase();
  assert.ok(SA.filterTxs(v.txs, { query: q }).length >= 1);
  assert.equal(SA.filterTxs(v.txs, { query: 'zzzz-no-match' }).length, 0);
});

test('summary lines come from the verified narrative; account is masked', () => {
  const v = SA.buildView(report);
  assert.ok(v.summaryLines.length >= 2);
  assert.equal(v.summaryLines.join(' '), report.summary.narrative);
  assert.match(v.account.number, /X/);
  assert.match(v.account.number, /^X{1,3}( X{4})* ?[X\d]{4}$|^(X{4} ?)+\d{4}$|^[X ]*\d{4}$/);
  assert.ok(!JSON.stringify(v.account).match(/\d{8}/));
});

test('exports: CSV has a row per transaction; JSON keeps manual overrides', () => {
  const v = SA.buildView(report);
  const csv = SA.toCsv(v.txs).split('\n');
  assert.equal(csv.length, v.txs.length + 1);
  assert.equal(csv[0], 'date,merchant,reference,mode,category,amount,balance,flag');
  const out = JSON.parse(SA.toJson(report, { 0: 'Other' }));
  assert.equal(out.transactions[0].category_source, 'manual');
  assert.equal(out.transactions[1].category_source, report.transactions[1].category_source);
});

test('formatting helpers', () => {
  assert.equal(SA.inr(245000, 2), '₹2,45,000.00');
  assert.equal(SA.inr(-1249, 0), '₹1,249');
  assert.equal(SA.titleCase('TECHNOVA SOLUTIONS PVT LTD'), 'Technova Solutions Pvt Ltd');
  assert.equal(SA.titleCase('ATM CASH'), 'ATM Cash');
  assert.equal(SA.periodTitle('2024-03-01', '2024-03-31'), 'March 2024 statement');
  assert.equal(SA.periodTitle('2024-01-01', '2024-02-29'), 'Jan – Feb 2024 statement');
  assert.deepEqual(SA.sentences('Spent ₹1,234.50 today. Saved more. Done.'), ['Spent ₹1,234.50 today.', 'Saved more.', 'Done.']);
});

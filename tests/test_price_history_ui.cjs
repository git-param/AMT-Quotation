const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend/quotation_tool/quotation.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'frontend/quotation_tool/quotation.html'), 'utf8');

function view(query, rows, unavailable = false) {
  const context = vm.createContext({
    window: {addEventListener() {}},
    document: {addEventListener() {}},
    console,
  });
  vm.runInContext(source, context);
  vm.runInContext(`_lastQuery = ${JSON.stringify(query)}; _priceHistory = ${JSON.stringify(rows)}; _priceHistoryUnavailable = ${unavailable};`, context);
  const grid = {innerHTML: ''};
  context.renderPriceHistory(grid);
  return grid.innerHTML;
}

test('price history is visible in the search modal and renders chronology', () => {
  assert.match(html, /data-src="price"/);
  const output = view('26733', [{date: '2026-10-01', prev_price: 100,
    price: 125, delta_pct: 25, by: 'System', automated: true,
    remarks: '<script>alert(1)</script>', ref: 'REF-1'}]);
  assert.match(output, /Price history for SKU 26733/);
  assert.match(output, /\+25\.0%/);
  assert.match(output, /Automated/);
  assert.doesNotMatch(output, /<script>/);
});

test('price history explains numeric SKU and unavailable catalog states', () => {
  assert.match(view('pump', []), /numeric SKU/);
  assert.match(view('26733', [], true), /database could not be reached/);
  assert.match(view('26733', []), /No price history found/);
});

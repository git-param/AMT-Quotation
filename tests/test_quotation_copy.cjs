const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../frontend/quotation_tool/quotation.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../frontend/quotation_tool/quotation.html'), 'utf8');

test('zero available quantity blocks every quotation copy format', async () => {
  let copies = 0;
  const status = {textContent: ''};
  const context = {
    window: {addEventListener() {}},
    document: {
      addEventListener() {},
      getElementById(id) { return id === 'copyStatus' ? status : null; },
      querySelectorAll() { return []; },
    },
    navigator: {clipboard: {
      write() { copies++; return Promise.resolve(); },
      writeText() { copies++; return Promise.resolve(); },
    }},
    setTimeout() {},
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  vm.runInContext(`_rows = [{found: true, qty: 0, price: 10, sku: 'A'}];
    copyFormal('USD'); copyFormalLetter('USD'); copyWA('USD');`, context);
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(copies, 0);
  assert.match(status.textContent, /zero available quantity/);
});

test('unselecting a zero-quantity SKU allows copying the selected SKUs', () => {
  const status = {textContent: ''};
  const checkboxes = [
    {checked: true, dataset: {sku: 'A'}},
    {checked: false, dataset: {sku: 'B'}},
  ];
  const context = {
    window: {addEventListener() {}},
    document: {
      addEventListener() {},
      getElementById(id) { return id === 'copyStatus' ? status : null; },
      querySelectorAll(selector) {
        if (selector === '.img-row-sel') return checkboxes;
        return [];
      },
    },

    setTimeout() {},
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  const copiedHtml = vm.runInContext(`_rows = [
    {found: true, qty: 2, price: 10, sku: 'A', title: 'Available part'},
    {found: true, qty: 0, price: 20, sku: 'B', title: 'Unavailable part'}
  ]; copyBlocked() ? 'blocked' : buildHTMLTable('USD');`, context);

  assert.equal(status.textContent, '');
  assert.match(copiedHtml, /Available part/);
  assert.doesNotMatch(copiedHtml, /Unavailable part/);
});

test('only quotation copy buttons are marked as copy actions', () => {
  assert.equal((html.match(/copy-action/g) || []).length, 6);
  assert.doesNotMatch(html, /id="imgDownBtn"[^>]*copy-action/);
});

// ── State ───────────────────────────────────────────────────────────────────
let _rows     = [];
const MAX_DISC_PCT = 7;
let _hasRecheckRows = false;
let _rate     = null;
let _urlMap   = {};   // sr -> url
let _imgSkus  = [];
let _imgMode  = 'all';
let _skuLookupLimit = null;

// ── Init ────────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {
  document.getElementById('skuInput').addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); lookupSKUs(); }
  });
  document.getElementById('refreshRate').addEventListener('click', e => {
    e.preventDefault(); loadRate();
  });
  loadRate();
  fetch('/api/sku-lookup-limit').then(response => response.json()).then(data => {
    if (!Number.isInteger(data.max_sku_lookup)) return;
    _skuLookupLimit = data.max_sku_lookup;
    document.getElementById('skuLookupLimitHint').textContent = `Maximum ${_skuLookupLimit} SKU${_skuLookupLimit === 1 ? '' : 's'} per lookup.`;
  }).catch(() => { document.getElementById('skuLookupLimitHint').textContent = ''; });
  // Load current user info
  fetch('/api/me').then(r => {
    if (!r.ok) throw new Error('Access denied');
    return r.json();
  }).then(u => {
    document.getElementById('hdrUser').textContent = '👤 ' + u.username;
    document.getElementById('sourcesLink').style.display = (u.permissions || []).includes('sources.manage') ? 'inline-block' : 'none';
    document.getElementById('accessLink').style.display = (u.permissions || []).includes('leads.share_manage') ? 'inline-block' : 'none';
    if ((u.permissions || []).includes('management.view')) document.getElementById('mgrLink').style.display = 'inline';
  }).catch(() => { window.location.href = '/login'; });
});

function loadRate() {
  fetch('/api/rate').then(r => r.json()).then(d => {
    _rate = d.rate;
    document.getElementById('rateDisplay').textContent = _rate ? `₹ ${_rate.toFixed(2)}` : 'N/A';
  }).catch(() => {});
}

function setStatus(msg, cls) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = cls || '';
}

function setCopyStatus(msg) {
  const el = document.getElementById('copyStatus');
  el.textContent = msg;
  setTimeout(() => el.textContent = '', 4000);
}

// ── Lookup ──────────────────────────────────────────────────────────────────
async function lookupSKUs() {
  const raw = document.getElementById('skuInput').value.trim();
  if (!raw) return;
  const skus = raw.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
  if (!skus.length) return;
  if (_skuLookupLimit !== null && skus.length > _skuLookupLimit) {
    setStatus(`You can look up at most ${_skuLookupLimit} SKU${_skuLookupLimit === 1 ? '' : 's'} at a time.`, 'status-err');
    return;
  }
  const seen = new Set(), duplicates = [];
  for (const sku of skus) {
    const key = sku.toLowerCase();
    if (seen.has(key)) duplicates.push(sku);
    seen.add(key);
  }
  if (duplicates.length) {
    setStatus(`Duplicate SKUs: ${duplicates.join(', ')}. Enter each SKU only once.`, 'status-err');
    return;
  }

  _rows = []; _urlMap = {};
  _hasRecheckRows = false;
  updateCopyButtonState();
  toggleImageDownloadButtons(false);
  const btn = document.getElementById('lookupBtn');
  btn.disabled = true;
  setStatus(`Fetching ${skus.length} SKU${skus.length > 1 ? 's' : ''}…`);
  showProgress(true);

  // Show placeholder rows
  renderPlaceholders(skus);

  try {
    const resp = await fetch('/api/lookup', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ skus })
    });
    if (!resp.ok) {
      const error = await resp.json().catch(() => ({}));
      setStatus(error.error || (resp.status === 401 ? 'Session ended. Please sign in again.' : 'Access denied.'), 'status-err');
      return;
    }
    const data = await resp.json();
    _rows = data.results || [];
    renderResults();
    const f = data.found, nf = data.not_found;
    setStatus(`Done — ${f} found, ${nf} not found`, f > 0 && nf === 0 ? 'status-ok' : nf > 0 ? 'status-warn' : '');
  } catch(e) {
    setStatus('Network error — check connection', 'status-err');
  } finally {
    btn.disabled = false;
    showProgress(false);
  }
}

function showProgress(on) {
  const el = document.getElementById('progress');
  const bar = document.getElementById('progressBar');
  if (on) {
    el.style.display = 'block';
    let w = 0;
    clearInterval(window._pgTimer);
    window._pgTimer = setInterval(() => {
      w = Math.min(w + Math.random() * 8, 88);
      bar.style.width = w + '%';
    }, 200);
  } else {
    clearInterval(window._pgTimer);
    bar.style.width = '100%';
    setTimeout(() => { el.style.display = 'none'; bar.style.width = '0'; }, 400);
  }
}

function renderPlaceholders(skus) {
  const tbody = document.getElementById('resultsBody');
  tbody.innerHTML = skus.map((sku, i) => `
    <tr class="row-wait">
      <td class="center">${esc(sku)}</td>
      <td class="center">${i+1}</td>
      <td class="left" colspan="8" style="color:#6B7280;font-style:italic">Fetching…</td>
    </tr>`).join('');
}

function renderResults() {
  const tbody = document.getElementById('resultsBody');
  if (!_rows.length) {
    tbody.innerHTML = '<tr><td colspan="12" class="empty-state">No results</td></tr>';
    toggleImageDownloadButtons(false);
    _hasRecheckRows = false;
    updateCopyButtonState();
    return;
  }
  tbody.innerHTML = _rows.map((r, i) => {
    const sr = i + 1;
    if (!r.found) {
      return `<tr class="row-err">
        <td class="center">—</td>
        <td class="center">${esc(r.sku_input)}</td>
        <td class="center">${sr}</td>
        <td class="left">${esc(r.error || 'SKU NOT FOUND')}</td>
        <td class="center">—</td>
        <td class="center">—</td>
        <td class="center">—</td>
        <td class="center">—</td>
        <td class="center">—</td>
        <td class="center">—</td>
        <td class="center">—</td>
        <td class="center">—</td>
      </tr>`;
    }
    function fmtDualUsd(r) {
      if (r.price == null) return 'N/A';
      if (r.sale_price != null) {
        const pct = Math.round((1 - r.sale_price / r.price) * 100);
        if (pct > MAX_DISC_PCT) return `$ ${r.price.toFixed(2)} <span style="color:#92400E;font-size:10px;">&#9888; recheck</span>`;
        return `<span style="text-decoration:line-through;color:#9ca3af;font-size:10px;">$ ${r.price.toFixed(2)}</span><br><strong>$ ${r.sale_price.toFixed(2)}</strong><br><span style="color:#16a34a;font-size:10px;font-weight:600;">${pct}% off</span>`;
      }
      return `$ ${r.price.toFixed(2)}`;
    }
    function fmtDualInr(r, rate) {
      if (!rate || r.price == null) return '—';
      if (r.sale_price != null) {
        const pct = Math.round((1 - r.sale_price / r.price) * 100);
        if (pct > MAX_DISC_PCT) return `₹ ${(r.price*rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})} <span style="color:#92400E;font-size:10px;">&#9888; recheck</span>`;
        const caInr = (r.price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
        const spInr = (r.sale_price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
        return `<span style="text-decoration:line-through;color:#9ca3af;font-size:10px;">₹ ${caInr}</span><br><strong>₹ ${spInr}</strong><br><span style="color:#16a34a;font-size:10px;font-weight:600;">${pct}% off</span>`;
      }
      return `₹ ${(r.price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
    }
    const usd = fmtDualUsd(r);
    const inr = fmtDualInr(r, _rate);
    const qty = r.qty !== '' && r.qty != null ? `${r.qty} Pcs` : '';
    const link = r.url ? `<a href="${esc(r.url)}" target="_blank">Click here</a>` : '';
    if (r.url) _urlMap[sr] = r.url;
    const skuVal = r.sku || r.sku_input;
    const safeSkuJs = esc(String(skuVal)).replace(/'/g, '&#39;');
    return `<tr class="row-ok" ondblclick="openURL(${sr})">
      <td class="center"><input type="checkbox" class="img-sel img-row-sel" data-sku="${esc(skuVal)}" checked onclick="event.stopPropagation();updateImageSelectionButtons()"></td>
      <td class="center">${esc(skuVal)}</td>
      <td class="center">${sr}</td>
      <td class="left">${esc(r.title || '')}</td>
      <td class="center">${esc(r.condition || '')}</td>
      <td class="center" style="white-space:nowrap">${link}</td>
      <td class="center">${esc(qty)}</td>
      <td class="center">${usd}</td>
      <td class="center">${inr}</td>
      <td class="center">Free</td>
      <td class="center">Ready Stock</td>
      <td class="center"><button class="img-mini-btn" onclick="event.stopPropagation();openImgModal('single','${safeSkuJs}')">Download</button></td>
    </tr>`;
  }).join('');
  // Show/hide image download buttons
  const hasFound = _rows.some(r => r.found);
  toggleImageDownloadButtons(hasFound);
  // Disable copy buttons if any row has discount > MAX_DISC_PCT
  _hasRecheckRows = _rows.some(r => r.found && r.sale_price != null && r.price != null
    && r.sale_price < r.price && Math.round((1 - r.sale_price / r.price) * 100) > MAX_DISC_PCT);
  updateCopyButtonState();
}

function updateCopyButtonState() {
  const warn = document.getElementById('recheckWarningBar');
  // All copy buttons are inside .copy-section — select by onclick attribute pattern
  document.querySelectorAll('.copy-section button').forEach(function(btn) {
    btn.disabled = _hasRecheckRows;
  });
  if (warn) {
    warn.style.display = _hasRecheckRows ? 'block' : 'none';
  }
}

function toggleImageDownloadButtons(show) {
  // Top row buttons (individual)
  ['imgDownTopBtn','imgDownSelTopBtn'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = show ? 'inline-flex' : 'none';
  });
  // Bottom bar group div
  const grp = document.getElementById('imgDownGroup');
  if (grp) grp.style.display = show ? 'flex' : 'none';
  updateImageSelectionButtons();
}

function foundImageSkus() {
  return [...new Set(_rows.filter(r => r.found).map(r => String(r.sku || r.sku_input || '').trim()).filter(Boolean))];
}
function selectedImageSkus() {
  return [...new Set([...document.querySelectorAll('.img-row-sel:checked')].map(cb => cb.dataset.sku).filter(Boolean))];
}
function toggleAllImageSelections(checked) {
  document.querySelectorAll('.img-row-sel').forEach(cb => { cb.checked = checked; });
  updateImageSelectionButtons();
}
function updateImageSelectionButtons() {
  const found = foundImageSkus().length;
  const selected = selectedImageSkus().length;
  const allBox = document.getElementById('imgSelAll');
  if (allBox) { allBox.checked = !!found && selected === found; allBox.indeterminate = selected > 0 && selected < found; }
  ['imgDownSelTopBtn','imgDownSelBtn'].forEach(id => { const b = document.getElementById(id); if (b) { b.disabled = selected === 0; b.textContent = selected ? `Download Selected (${selected})` : 'Download Selected'; } });
}

function openURL(sr) {
  if (_urlMap[sr]) window.open(_urlMap[sr], '_blank');
}

// ── HTML Quotation Builder (mirrors Python _build_html_quotation) ────────────
function buildHTMLTable(currency) {
  if (!_rows.length) return null;
  const isINR  = currency === 'INR';
  const rate   = _rate || 0;
  const GREY   = '#CCCCCC';
  const BLACK  = '#000000';
  const WHITE  = '#FFFFFF';
  const ERR_BG = '#FFFFFF';

  const th = `background:${GREY};color:${BLACK};font-family:Calibri,Arial,sans-serif;font-size:11pt;font-weight:bold;padding:8px 10px;border:1px solid #B8B8B8;text-align:center;`;
  const thw = (w, extra) => `${th}width:${w}%;${extra||''}`;

  // Only treat as discount when sale_price < price (markup is not a discount)
  const hasDiscount = _rows.some(r => r.found && r.sale_price != null && r.price != null && r.sale_price < r.price);
  // Separate valid discounts (≤7%) from error discounts (>7%)
  const _discPcts = _rows.filter(r => r.found && r.sale_price != null && r.price != null && r.sale_price < r.price)
                         .map(r => Math.round((1 - r.sale_price / r.price) * 100));
  const _validPcts = _discPcts.filter(p => p <= MAX_DISC_PCT);
  const _hasRecheckRows = _discPcts.some(p => p > MAX_DISC_PCT);
  const _discMaxPct = _validPcts.length ? Math.max(..._validPcts) : 0;
  const _multiDiscount = _validPcts.length > 1 && new Set(_validPcts).size > 1;
  const _discHeaderPct = _discMaxPct > 0 ? (_multiDiscount ? 'up to ' + _discMaxPct + '%' : _discMaxPct + '%') : '';
  const priceHdr = isINR ? 'Rate/Pcs (INR)' : 'Rate/Pcs (USD)';

  let html = `<table style="border-collapse:collapse;width:100%;">
<thead><tr>
<th style="${thw(5)}">SKU</th>
<th style="${thw(4)}">Sr No</th>
<th style="${thw(20)};text-align:left">Description</th>
<th style="${thw(9)}">Condition</th>
<th style="${thw(8)}">Product Details &amp; Pictures</th>
<th style="${thw(6)}">Available QTY</th>
<th style="${thw(hasDiscount?8:9)}">${priceHdr}</th>
${hasDiscount ? `<th style="${thw(7)}">Discount${_discHeaderPct ? '<br><span style="font-size:9pt;font-weight:normal;">' + _discHeaderPct + ' off</span>' : ''}</th><th style="${thw(8)}">Final Price</th>` : ''}
<th style="${thw(6)}">Shipping</th>
<th style="${thw(8)}">Lead Time</th>
</tr></thead><tbody>`;

  const tdC = `font-family:Calibri,Arial,sans-serif;font-size:11pt;color:${BLACK};padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:center;background:${WHITE};`;
  const tdL = `font-family:Calibri,Arial,sans-serif;font-size:11pt;color:${BLACK};padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:left;background:${WHITE};`;
  const tdE = `font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#111827;padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:left;background:${ERR_BG};`;
  const tdD = `font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#111827;padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:center;background:#F9F9F9;`;

  _rows.forEach((r, i) => {
    const sr = i + 1;
    if (!r.found) {
      html += `<tr>
<td style="${tdC}">${escH(r.sku_input)}</td>
<td style="${tdC}">${sr}</td>
<td style="${tdE}">${escH(r.error || 'SKU NOT FOUND')}</td>
<td style="${tdC}">—</td>
<td style="${tdC}">—</td>
<td style="${tdC}">—</td>
<td style="${tdC}">—</td>
${hasDiscount ? `<td style="${tdD}">—</td><td style="${tdC}">—</td>` : ''}
<td style="${tdC}">—</td>
<td style="${tdC}">—</td>
</tr>`;
      return;
    }

    let rateTd, discTd = '', finalTd = '';
    if (hasDiscount) {
      // Only show actual discount (sale_price < price); markup rows show — in discount/final
      if (r.sale_price != null && r.price != null && r.sale_price < r.price) {
        const rowPct = Math.round((1 - r.sale_price / r.price) * 100);
        if (rowPct > MAX_DISC_PCT) {
          // Discount exceeds max allowed — pricing error, show recheck warning
          const tdWarn = `font-family:Calibri,Arial,sans-serif;font-size:10pt;color:#92400E;padding:6px 10px;border:1px solid #E0E0E0;vertical-align:middle;text-align:center;background:#FEF3C7;`;
          let priceFmt = isINR && rate ? `&#8377;&nbsp;${(r.price*rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}` : `$&nbsp;${r.price.toFixed(2)}`;
          rateTd  = `<td style="${tdC}">${priceFmt}</td>`;
          discTd  = `<td style="${tdWarn}">&#9888; Price recheck needed</td>`;
          finalTd = `<td style="${tdC}">—</td>`;
        } else if (isINR && rate) {
          const caI  = (r.price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
          const spI  = (r.sale_price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
          const dscI = ((r.price - r.sale_price) * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
          rateTd  = `<td style="${tdC}">&#8377;&nbsp;${caI}</td>`;
          discTd  = `<td style="${tdD}"><strong>&#8377;&nbsp;${dscI}</strong></td>`;
          finalTd = `<td style="${tdC}"><strong>&#8377;&nbsp;${spI}</strong></td>`;
        } else {
          const dscU = (r.price - r.sale_price).toFixed(2);
          rateTd  = `<td style="${tdC}">$&nbsp;${r.price.toFixed(2)}</td>`;
          discTd  = `<td style="${tdD}"><strong>$&nbsp;${dscU}</strong></td>`;
          finalTd = `<td style="${tdC}"><strong>$&nbsp;${r.sale_price.toFixed(2)}</strong></td>`;
        }
      } else {
        let priceFmt = r.price != null
          ? (isINR && rate ? `&#8377;&nbsp;${(r.price*rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}` : `$&nbsp;${r.price.toFixed(2)}`)
          : 'N/A';
        rateTd  = `<td style="${tdC}">${priceFmt}</td>`;
        discTd  = `<td style="${tdD}">—</td>`;
        finalTd = `<td style="${tdC}">${priceFmt}</td>`;
      }
    } else {
      let priceStr;
      if (isINR && rate && r.price != null) {
        priceStr = `&#8377;&nbsp;${(r.price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
      } else if (r.price != null) {
        priceStr = `$&nbsp;${r.price.toFixed(2)}`;
      } else {
        priceStr = 'N/A';
      }
      rateTd = `<td style="${tdC}">${priceStr}</td>`;
    }

    const qty  = (r.qty !== '' && r.qty != null) ? `${r.qty} Pcs` : '';
    const link = r.url ? `<a href="${escH(r.url)}" style="color:#1155CC;text-decoration:underline;">Click here</a>` : '';
    html += `<tr>
<td style="${tdC}">${escH(r.sku || r.sku_input)}</td>
<td style="${tdC}">${sr}</td>
<td style="${tdL}">${escH(r.title || '')}</td>
<td style="${tdC}">${escH(r.condition || '')}</td>
<td style="${tdC};white-space:nowrap">${link}</td>
<td style="${tdC}">${escH(qty)}</td>
${rateTd}${discTd}${finalTd}
<td style="${tdC}">Free</td>
<td style="${tdC}">Ready Stock</td>
</tr>`;
  });

  const ft = `font-family:Calibri,Arial,sans-serif;font-size:10.5pt;font-weight:bold;color:${BLACK};text-align:center;padding:7px 10px;border:1px solid #CCCCCC;background:${WHITE};`;
  if (hasDiscount) {
    html += `<tr>
<td colspan="4" style="${ft}">Free worldwide shipping</td>
<td colspan="4" style="${ft}">30 days return/refund policy</td>
<td colspan="3" style="${ft}">Dispatch within 24 hours</td>
</tr></tbody></table>`;
  } else {
    html += `<tr>
<td colspan="3" style="${ft}">Free worldwide shipping</td>
<td colspan="3" style="${ft}">30 days return/refund policy</td>
<td colspan="3" style="${ft}">Dispatch within 24 hours</td>
</tr></tbody></table>`;
  }

  const tcItems = isINR ? [
    'Payment 100% advance via BANK TT with a purchase order.',
    'GST 18% at actual.',
    'HSN Code: 85371090.',
    'Offer subject to stock availability at the time of order confirmation.',
    'Our items are New/Surplus &amp; Used/Second Hand. We do not provide brand New Materials.',
    'Prices are valid for 7 days from the date of quotation.',
  ] : [
    'Payment Method: Bank TT / PayPal / Stripe [100% Advance].',
    'Import duties and destination country taxes not included.',
    'HSN Code: 85371090.',
    'Offer subject to stock availability at the time of order confirmation.',
    'Our items are New/Surplus &amp; Used/Second Hand. We do not provide brand New Materials.',
    'Prices are valid for 7 days from the date of quotation.',
  ];
  const ts = `font-family:Calibri,Arial,sans-serif;font-size:10pt;color:#000000;`;
  html += `<p style="${ts}margin-top:14px;"><strong>Terms &amp; Conditions</strong></p>
<ol style="${ts}margin:4px 0 0 18px;padding:0;">${tcItems.map(t => `<li>${t}</li>`).join('')}</ol>`;

  return html;
}

// ── Copy Formal ──────────────────────────────────────────────────────────────
async function copyFormal(currency) {
  if (!_rows.length) { setCopyStatus('Look up some SKUs first.'); return; }
  const html = buildHTMLTable(currency);
  try {
    await navigator.clipboard.write([
      new ClipboardItem({
        'text/html':  new Blob([html],       {type:'text/html'}),
        'text/plain': new Blob([stripTags(html)], {type:'text/plain'}),
      })
    ]);
    setCopyStatus(`✓ Formal ${currency} quotation copied — paste into Gmail / Outlook!`);
    logCopy('formal_' + currency.toLowerCase(), _rows.length);
  } catch(e) {
    // Fallback: plain text
    navigator.clipboard.writeText(stripTags(html)).catch(()=>{});
    setCopyStatus(`Copied as plain text (browser blocked HTML clipboard)`);
  }
}

// ── Copy Full Letter (greeting + same table as Formal Quote + date/sign-off) ──
async function copyFormalLetter(currency) {
  if (!_rows.length) { setCopyStatus('Look up some SKUs first.'); return; }
  const today = new Date().toLocaleDateString('en-GB', {day:'2-digit',month:'short',year:'numeric'});
  const F = 'font-family:Calibri,Arial,sans-serif;font-size:11pt;color:#000000;';

  // Reuse the exact same table (columns, styles, T&C) as the Formal Quote button
  const isINR = currency === 'INR';
  const tableHtml = buildHTMLTable(currency);

  const save5Line = !isINR
    ? `<p style="${F}margin:12px 0 8px 0;"><span style="background:#FFE0A0;padding:5px 14px;border-radius:3px;display:inline-block;"><strong>Save up to 7% instantly by ordering through our e-Store. Simply click the product link(s) in the quotation table and complete your purchase today to enjoy this exclusive online discount.</strong></span></p>`
    : '';

  const html = `<div style="${F}">
<p style="margin:0 0 10px 0;">Dear Sir/Madam,</p>
<p style="margin:0 0 10px 0;">Greetings from Aeliya Marine Tech!</p>
<p style="margin:0 0 10px 0;">Thank you for your inquiry.</p>
<p style="margin:0 0 10px 0;">Please find the following quotation with the product specification link or attached photos. Kindly review the details and discuss them with your technical team for compatibility.</p>
${tableHtml}
${save5Line}
<p style="${F}margin:8px 0 8px 0;"><strong>You are only buying what you see in the photos.</strong></p>
<p style="${F}margin:0 0 12px 0;">Feel free to reach out if you have any questions or need further information.</p>
<p style="${F}margin:0;">Best regards,</p>
</div>`;

  try {
    await navigator.clipboard.write([
      new ClipboardItem({
        'text/html':  new Blob([html],            {type:'text/html'}),
        'text/plain': new Blob([stripTags(html)], {type:'text/plain'}),
      })
    ]);
    setCopyStatus(`✓ Full letter (${currency}) copied — paste into Gmail / Outlook!`);
    logCopy('letter_' + currency.toLowerCase(), _rows.length);
  } catch(e) {
    navigator.clipboard.writeText(stripTags(html)).catch(()=>{});
    setCopyStatus('Copied as plain text (browser blocked HTML clipboard)');
  }
}

// ── Copy WhatsApp ────────────────────────────────────────────────────────────
function copyWA(currency) {
  if (!_rows.length) { setCopyStatus('Look up some SKUs first.'); return; }
  const isINR = currency === 'INR';
  const rate  = _rate || 0;
  const blocks = _rows.map(r => {
    if (!r.found) {
      return `Dear Sir/Madam,\nGreetings from Aeliya Marine Tech!\nBased on your request we are pleased to offer you the below product.\n\n*Product Name:* SKU ${r.sku_input} — NOT FOUND`;
    }
    let priceStr;
    if (isINR && rate && r.price != null) {
      if (r.sale_price != null) {
        const pct = Math.round((1 - r.sale_price / r.price) * 100);
        const caI = (r.price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
        const spI = (r.sale_price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
        priceStr = `~₹ ${caI}~ *₹ ${spI}* (${pct}% off)`;
      } else {
        priceStr = `₹ ${(r.price * rate).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
      }
    } else if (r.price != null) {
      if (r.sale_price != null) {
        const pct = Math.round((1 - r.sale_price / r.price) * 100);
        priceStr = `~$ ${r.price.toFixed(2)}~ *$ ${r.sale_price.toFixed(2)}* (${pct}% off)`;
      } else {
        priceStr = `$ ${r.price.toFixed(2)}`;
      }
    } else {
      priceStr = 'N/A';
    }
    const gst = isINR ? '\nGST 18% at actual' : '';
    return `Dear Sir/Madam,
Greetings from Aeliya Marine Tech!
Based on your request we are pleased to offer you the below product.

*Product Name:* ${r.title}
Product Details/Photos ${r.url || ''}

*Price: ${priceStr}*
Available Qty: ${r.qty ?? ''}
Condition: ${r.condition || ''}${gst}

*Shipping: Free*
Delivery time: 4 to 6 working days
You are only buying what you see in pictures

Warranty: 30-day technical; refund/replacement if faulty.
Payment: 100% advance via Bank TT, PayPal, or Stripe with PO

Thank you for showing your interest in our products.`;
  });
  const divider = '\n\n' + '─'.repeat(40) + '\n\n';
  navigator.clipboard.writeText(blocks.join(divider))
    .then(() => { setCopyStatus(`✓ WhatsApp ${currency} message copied!`); logCopy('wa_' + currency.toLowerCase(), _rows.length); })
    .catch(() => setCopyStatus('Copy failed — try again'));
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function logCopy(type, count) {
  fetch('/api/log-copy', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({copy_type: type, sku_count: count})
  }).catch(()=>{});
}

async function clearCache() {
  await fetch('/api/clear-cache', {method:'POST'}).catch(()=>{});
  setStatus('Cache cleared — next lookup fetches fresh data', 'status-warn');
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function escH(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function stripTags(html) {
  return html.replace(/<[^>]+>/g,' ').replace(/\s{2,}/g,' ').trim();
}

// ── Search Modal ─────────────────────────────────────────────────────────────
let _allResults   = [];
let _activeFilter = 'all';
let _lastQuery    = '';

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('searchInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') searchAll();
  });
});

function openSearchModal() {
  document.getElementById('searchModal').classList.add('open');
  document.body.style.overflow = 'hidden';
  setTimeout(() => document.getElementById('searchInput').focus(), 80);
}

function closeSearchModal() {
  document.getElementById('searchModal').classList.remove('open');
  document.body.style.overflow = '';
}

function srchModalBgClick(e) {
  if (e.target === document.getElementById('searchModal')) closeSearchModal();
}

function clearSearch() {
  _allResults = []; _lastQuery = ''; _activeFilter = 'all';
  document.getElementById('searchInput').value = '';
  document.getElementById('resultsGrid').innerHTML = '';
  document.getElementById('filterTabs').style.display = 'none';
  document.getElementById('copySkusBtn').style.display = 'none';
  document.getElementById('srchClear').style.display = 'none';
  document.getElementById('searchInput').focus();
}

async function searchAll() {
  const q = document.getElementById('searchInput').value.trim();
  if (!q) return;
  const btn = document.getElementById('searchBtn');
  btn.disabled = true; btn.textContent = 'Searching…';
  document.getElementById('searchLoading').style.display = 'block';
  document.getElementById('filterTabs').style.display = 'none';
  _allResults = []; _activeFilter = 'all'; _lastQuery = q;

  try {
    const resp = await fetch('/api/search-all?q=' + encodeURIComponent(q));
    const data = await resp.json();
    _allResults = data.results || [];
    const counts = data.counts || {};
    document.getElementById('cnt-all').textContent    = counts.total  || 0;
    document.getElementById('cnt-zoho').textContent   = counts.zoho   || 0;
    document.getElementById('cnt-atlas').textContent  = counts.atlas  || 0;
    document.getElementById('cnt-alreza').textContent = counts.alreza || 0;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.src === 'all'));
    _activeFilter = 'all';
    renderCards();
    document.getElementById('filterTabs').style.display = 'flex';
    document.getElementById('copySkusBtn').style.display = counts.zoho > 0 ? 'inline-flex' : 'none';
    document.getElementById('srchClear').style.display = 'inline-block';
  } catch(e) {
    _allResults = [];
    renderCards();
    document.getElementById('filterTabs').style.display = 'flex';
  } finally {
    btn.disabled = false; btn.textContent = 'Search All';
    document.getElementById('searchLoading').style.display = 'none';
  }
}

function filterResults(src) {
  _activeFilter = src;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.src === src));
  renderCards();
}

function renderCards() {
  const grid = document.getElementById('resultsGrid');
  const filtered = _activeFilter === 'all'
    ? _allResults
    : _allResults.filter(r => r.source === _activeFilter);

  if (!filtered.length) {
    grid.innerHTML = '<div class="search-empty">No results found — try a different search term</div>';
    return;
  }

  const badge = src => ({
    zoho:   '<span class="source-badge badge-zoho">Zoho</span>',
    atlas:  '<span class="source-badge badge-atlas">Atlas Ship</span>',
    alreza: '<span class="source-badge badge-alreza">Al Reza</span>',
  }[src] || '');

  const hdr = `<div class="list-hdr">
    <span></span>
    <span>Name</span>
    <span>SKU</span>
    <span style="text-align:center">Stock</span>
    <span>Condition</span>
    <span>Source</span>
    <span>Link</span>
  </div>`;

  const rows = filtered.map(r => {
    const safeImg  = escH(r.image || '');
    const safeTitle= escH(r.title);
    const safeSku  = escH(r.sku || '');

    const thumbHtml = r.image
      ? `<img class="row-thumb" src="${safeImg}" alt="" loading="lazy"
             onclick="openLightbox('${safeImg}','${safeTitle}')"
             onerror="this.outerHTML='<div class=row-thumb-placeholder>📦</div>'">`
      : `<div class="row-thumb-placeholder">📦</div>`;

    const skuHtml = r.sku
      ? `<span class="sku-chip" onclick="fillSKU('${safeSku}')" title="Add to quote">${safeSku}</span>`
      : '—';

    const stockHtml = r.source === 'zoho'
      ? (r.stock > 0
          ? `<span class="stock-pill stock-in">${r.stock}</span>`
          : `<span class="stock-pill stock-out">0</span>`)
      : '—';

    const snippet = r.source === 'zoho'
      ? [r.brand ? `Brand: ${r.brand}` : '', r.weight].filter(Boolean).join('  •  ')
      : (r.snippet || '');

    const linkHtml = r.url
      ? `<a href="${escH(r.url)}" target="_blank" class="row-link">View →</a>`
      : '—';

    return `<div class="list-row">
      <div style="display:flex;align-items:center">${thumbHtml}</div>
      <div class="row-cell">
        <div class="row-name">${escH(r.title)}</div>
        ${snippet ? `<div class="row-snippet">${escH(snippet)}</div>` : ''}
      </div>
      <div class="row-cell">${skuHtml}</div>
      <div class="row-cell" style="text-align:center">${stockHtml}</div>
      <div class="row-cell" style="font-size:12px;color:#374151">${escH(r.condition || '—')}</div>
      <div class="row-cell">${badge(r.source)}</div>
      <div class="row-cell">${linkHtml}</div>
    </div>`;
  }).join('');

  grid.innerHTML = hdr + rows;
}

function fillSKU(sku) {
  const box = document.getElementById('skuInput');
  const cur = box.value.trim();
  const skus = cur ? cur.split(/[\n,]+/).map(s=>s.trim()).filter(Boolean) : [];
  if (!skus.includes(sku)) { skus.push(sku); }
  box.value = skus.join('\n');
  setCopyStatus('SKU ' + sku + ' added to lookup ↑');
}

function copyAllSkus() {
  const skus = _allResults.filter(r => r.source === 'zoho' && r.sku).map(r => r.sku);
  if (!skus.length) return;
  const box = document.getElementById('skuInput');
  box.value = skus.join('\n');
  navigator.clipboard.writeText(skus.join('\n')).catch(()=>{});
  box.scrollIntoView({behavior:'smooth', block:'center'});

  const btn = document.getElementById('copySkusBtn');
  btn.textContent = `✓ ${skus.length} SKUs Copied`;
  btn.style.background = '#057A55';
  btn.style.borderColor = '#057A55';
  clearTimeout(btn._resetTimer);
  btn._resetTimer = setTimeout(() => {
    btn.textContent = '📋 Copy SKUs to Quote';
    btn.style.background = '';
    btn.style.borderColor = '';
  }, 3000);
}

// ── Lightbox ─────────────────────────────────────────────────────────────────
function openLightbox(imgSrc, caption) {
  // Swap thumbnail URL to full-size Blogger image
  const fullSrc = imgSrc.replace(/\/s\d+\//, '/s1600/');
  document.getElementById('lightbox-img').src     = fullSrc;
  document.getElementById('lightbox-caption').textContent = caption || '';
  document.getElementById('lightbox').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeLightbox(e) {
  if (e && e.target === document.getElementById('lightbox-img')) return;
  document.getElementById('lightbox').classList.remove('open');
  document.getElementById('lightbox-img').src = '';
  document.body.style.overflow = '';
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (document.getElementById('lightbox').classList.contains('open')) closeLightbox();
    else closeSearchModal();
  }
});
// ── Image Download ───────────────────────────────────────────────────────────
let _imgOpt = 'zip';

function openImgModal(mode='all', sku=null) {
  if (!_rows.length) return;
  _imgMode = mode;
  _imgSkus = mode === 'single' && sku ? [sku] : mode === 'selected' ? selectedImageSkus() : foundImageSkus();
  if (!_imgSkus.length) { alert(mode === 'selected' ? 'Select at least one SKU to download images.' : 'No found SKUs to download images for.'); return; }
  document.getElementById('imgModalSub').textContent =
    `${mode === 'single' ? 'Single SKU' : mode === 'selected' ? 'Selected SKUs' : 'All found SKUs'}: ${_imgSkus.length} SKU${_imgSkus.length > 1 ? 's' : ''}`;
  document.getElementById('imgProgress').textContent = '';
  document.getElementById('imgGoBtn').disabled = false;
  selectImgOpt('zip');
  document.getElementById('imgModal').classList.add('open');
}

function closeImgModal() {
  document.getElementById('imgModal').classList.remove('open');
}

function imgModalBgClick(e) {
  if (e.target === document.getElementById('imgModal')) closeImgModal();
}

function safeFilePart(v) {
  return String(v || 'SKU').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^[_\.]+|[_\.]+$/g, '') || 'SKU';
}

function selectImgOpt(opt) {
  _imgOpt = opt;
  document.getElementById('optZip').classList.toggle('selected', opt === 'zip');
  document.getElementById('optFolder').classList.toggle('selected', opt === 'folder');
}

async function startImgDownload() {
  const skus = _imgSkus.length ? _imgSkus : foundImageSkus();
  if (!skus.length) return;
  const btn = document.getElementById('imgGoBtn');
  const prog = document.getElementById('imgProgress');
  btn.disabled = true;

  if (_imgOpt === 'zip') {
    // Fetch image URLs first so the zip endpoint doesn't need to re-query Zoho
    prog.textContent = 'Getting image URLs…';
    let skuImages = [];
    try {
      const ir = await fetch('/api/images', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ skus }) });
      const id = await ir.json();
      (id.images || []).forEach(item => {
        const urls = Array.isArray(item.images) && item.images.length ? item.images : (item.image ? [item.image] : []);
        if (urls.length) skuImages.push({ sku: item.sku, urls });
      });
    } catch(e) { /* fall back to sku-only mode */ }
    prog.textContent = 'Packing images…';
    try {
      const resp = await fetch('/api/download-images-zip', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(skuImages.length ? { sku_images: skuImages } : { skus })
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        prog.textContent = '⚠ ' + (j.error || 'Download failed');
        btn.disabled = false;
        return;
      }
      const blob = await resp.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      const baseName = _imgMode === 'single' ? `images_${safeFilePart(skus[0])}.zip` : _imgMode === 'selected' ? 'selected_product_images.zip' : 'product_images.zip';
      a.href = url; a.download = baseName; a.click();
      URL.revokeObjectURL(url);
      prog.textContent = `✓ Downloaded ${blob.size > 0 ? Math.round(blob.size/1024) + ' KB' : ''}`;
      setTimeout(closeImgModal, 2000);
    } catch(e) {
      prog.textContent = '⚠ Network error: ' + e.message;
    }
    btn.disabled = false;

  } else {
    // Save to folder using File System Access API
    if (!('showDirectoryPicker' in window)) {
      alert('Save to Folder requires Chrome or Edge browser. Use ZIP download instead.');
      btn.disabled = false;
      return;
    }
    let dirHandle;
    try {
      dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
    } catch(e) {
      prog.textContent = 'Folder selection cancelled.';
      btn.disabled = false;
      return;
    }
    prog.textContent = 'Getting image URLs…';
    let imageList;
    try {
      const r = await fetch('/api/images', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ skus })
      });
      const d = await r.json();
      imageList = [];
      (d.images || []).forEach(item => {
        const urls = Array.isArray(item.images) && item.images.length ? item.images : (item.image ? [item.image] : []);
        urls.forEach((url, idx) => imageList.push({ sku: item.sku, image: url, index: idx + 1 }));
      });
    } catch(e) {
      prog.textContent = '⚠ Failed to get image URLs: ' + e.message;
      btn.disabled = false;
      return;
    }
    if (!imageList.length) {
      prog.textContent = '⚠ No images found for these SKUs.';
      btn.disabled = false;
      return;
    }
    let saved = 0, failed = 0;
    for (const item of imageList) {
      prog.textContent = `Saving ${saved + failed + 1} / ${imageList.length}: ${item.sku}…`;
      try {
        // Zoho internal URLs are fetched directly; external URLs go through image-proxy
        const imgResp = item.image.startsWith('/api/')
          ? await fetch(item.image)
          : await fetch('/api/image-proxy?url=' + encodeURIComponent(item.image));
        if (!imgResp.ok) { failed++; continue; }
        const blob = await imgResp.blob();
        const ct   = blob.type || 'image/jpeg';
        const ext  = ct.includes('png') ? 'png' : ct.includes('gif') ? 'gif'
                   : ct.includes('webp') ? 'webp' : 'jpg';
        const skuFolder = await dirHandle.getDirectoryHandle(safeFilePart(item.sku), { create: true });
        const fh   = await skuFolder.getFileHandle(`${safeFilePart(item.sku)}_${item.index || 1}.${ext}`, { create: true });
        const wr   = await fh.createWritable();
        await wr.write(blob);
        await wr.close();
        saved++;
      } catch(e) {
        failed++;
      }
    }
    prog.textContent = `✓ Saved ${saved} image${saved !== 1 ? 's' : ''}${failed ? ` (${failed} failed)` : ''}.`;
    setTimeout(closeImgModal, 3000);
    btn.disabled = false;
  }
}

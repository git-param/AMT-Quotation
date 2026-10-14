(() => {
  let enquiry = null;
  let editingLine = null;
  const bulkEditor=window.createSkuDraftEditor(document.getElementById('addSkus'),()=>({enquiry_id:enquiry.id}),()=>el('addCurrency').value,async lines=>{await call(`/api/enquiries/${enquiry.id}/lines/bulk`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines})});await loadLines();});
  const el = id => document.getElementById(id);
  function notice(text, error = false) { el('lineMessage').textContent = text; el('lineMessage').className = error ? 'line-error' : ''; }
  async function call(path, options = {}) {
    const response = await fetch(path, options); const result = await response.json();
    if (!response.ok) {
      if ([401,403,404].includes(response.status)) el('lineForm').hidden = true;
      throw new Error(result.error || 'Unable to complete line operation.');
    }
    return result;
  }
  function linePath(id = null) { return `/api/enquiries/${enquiry.id}/lines${id === null ? '' : '/' + id}`; }
  function reset() {
    editingLine = null; el('lineForm').reset(); el('lineQuantity').value = '1'; el('lookupInfo').textContent = ''; el('lineForm').hidden = true;
  }
  async function loadLines() {
    const id = enquiry.id; const data = await call(linePath()); if (enquiry.id !== id) return;
    el('lineRows').replaceChildren(); el('lineTotals').replaceChildren();
    data.lines.forEach(line => {
      const row = document.createElement('tr');
      [line.sku,line.description,Number.isInteger(Number(line.quantity))?String(Number(line.quantity)):line.quantity,line.unit_price,line.currency,line.line_total].forEach(value => { const td = document.createElement('td'); td.textContent = value; row.append(td); });
      const actions = document.createElement('td');
      if (enquiry.can_edit) {
        const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'btn-sm'; edit.textContent = 'Edit';
        edit.onclick = async () => {
          try {
            const current = (await call(linePath(line.id))).line;
            if (!current.is_active) throw new Error('This line has been removed.');
            editingLine = current.id; el('lineSku').value = current.sku; el('lineDescription').value = current.description; el('lineQuantity').value = Number.isInteger(Number(current.quantity))?String(Number(current.quantity)):current.quantity; el('linePrice').value = current.unit_price; el('lineCurrency').value = current.currency; el('lookupInfo').textContent = ''; el('lineForm').hidden = false; el('lineSku').focus();
          } catch (error) { notice(error.message,true); }
        };
        const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'btn-sm btn-del'; remove.textContent = 'Delete';
        remove.onclick = async () => {
          if (!window.confirm(`Delete SKU ${line.sku}? Its history will be retained.`)) return;
          remove.disabled = true;
          try { await call(linePath(line.id), {method:'DELETE'}); reset(); await loadLines(); notice('Line removed. Its ID and revisions are retained.'); }
          catch (error) { notice(error.message,true); } finally { remove.disabled = false; }
        };
        actions.append(edit);if(enquiry.can_delete)actions.append(remove);
      } else { actions.textContent = 'Read only'; }
      row.append(actions); el('lineRows').append(row);
    });
    if (!data.lines.length) { const row = document.createElement('tr'); const td = document.createElement('td'); td.colSpan = 7; td.textContent = 'No SKU lines yet.'; td.className = 'source-empty'; row.append(td); el('lineRows').append(row); }
    Object.entries(data.subtotals).forEach(([currency,total]) => { const badge = document.createElement('strong'); badge.textContent = `${currency} subtotal: ${total}`; el('lineTotals').append(badge); });
  }
  window.showEnquiryLines = async value => { enquiry = value; el('addCurrency').closest('.form-field').hidden=!enquiry.can_edit; reset(); el('addSkus').hidden=true; bulkEditor.reset(); notice(''); el('addLine').hidden = !enquiry.can_edit; await loadLines(); };
  el('addCurrency').onchange=()=>bulkEditor.currencyChanged();
  el('addLine').onclick = () => { reset(); el('addSkus').hidden = !el('addSkus').hidden; el('addCurrency').value=enquiry.deal_currency||'USD'; bulkEditor.reset(); };
  el('cancelLine').onclick = reset;
  el('lineForm').onsubmit = async event => {
    event.preventDefault(); el('saveLine').disabled = true;
    try {
      await call(linePath(editingLine), {method:editingLine === null ? 'POST' : 'PUT', headers:{'Content-Type':'application/json'},body:JSON.stringify({sku:el('lineSku').value,description:el('lineDescription').value,quantity:el('lineQuantity').value,unit_price:el('linePrice').value,currency:el('lineCurrency').value})});
      reset(); await loadLines(); notice('SKU line saved. Totals recalculated on the server.');
    } catch (error) { notice(error.message,true); } finally { el('saveLine').disabled = false; }
  };
  el('lookupLine').onclick = async () => {
    el('lookupLine').disabled = true;
    try {
      const data = await call(`/api/enquiries/${enquiry.id}/sku-lookup`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sku:el('lineSku').value})});
      el('lineSku').value = data.draft.sku; el('lineDescription').value = data.draft.description; el('linePrice').value = data.draft.unit_price; el('lineCurrency').value = data.draft.currency;
      el('lookupInfo').textContent = `Available stock: ${data.stock ?? '-'} / ${data.condition || 'Condition unavailable'}`;
      notice('SKU fetched. Review quantity and price, then save the line.');
    } catch (error) { notice(error.message,true); } finally { el('lookupLine').disabled = false; }
  };
})();

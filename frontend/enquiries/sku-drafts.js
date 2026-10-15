(() => {
  window.createSkuDraftEditor = (host, scope, currency, onSave = null, commercial = false) => {
    let rows = [];
    let fetching = false;
    let activeRow = 0;
    let displayRate = null;
    let sharedHsn = '';
    const uoms=['PCs','Lot','Kit','set'];
    function stockIssue(row){
      if(!commercial)return '';
      const quantity=Number(row.quantity);
      if(!Number.isInteger(quantity)||quantity<=0)return `SKU ${row.sku}: enter a quantity of at least 1 (whole numbers only).`;
      if(row.found&&row.stock!=null&&Number.isFinite(Number(row.stock))){
        const available=Number(row.stock);
        if(available<=0)return `SKU ${row.sku} cannot be added: out of stock (0 available).`;
        if(quantity>available)return `SKU ${row.sku} cannot be added: requested ${quantity}, but only ${available} available.`;
      }
      return '';
    }
    host.classList.add('sku-drafts');
    if(commercial)host.classList.add('sku-drafts--order');
    host.replaceChildren();
    const heading = document.createElement('h3'); heading.textContent = commercial ? 'Order SKU items' : 'Enquiry SKU items';
    const hint = document.createElement('p'); hint.textContent = 'Enter SKUs (one per line or comma-separated)';
    const input = document.createElement('textarea'); input.rows = 3; input.placeholder = '1258\n2456'; input.setAttribute('aria-label','SKU codes');
    const tools = document.createElement('div'); tools.className = 'draft-tools';
    const fetchButton = document.createElement('button'); fetchButton.type = 'button'; fetchButton.className = 'btn-sm btn-add'; fetchButton.textContent = 'Look Up SKUs';
    const manual = document.createElement('button'); manual.type = 'button'; manual.className = 'btn-sm'; manual.textContent = 'Add manual SKU';
    const status = document.createElement('p'); status.className='draft-status'; status.setAttribute('role','status');
    const lookup = document.createElement('div'); lookup.className='draft-lookup';
    const tableBox = document.createElement('div'); tableBox.className = 'source-table';
    const table = document.createElement('table'); table.className = 'tbl';
    const head = document.createElement('thead'); const headRow = document.createElement('tr');
    ['','SKU','Sr No','Description','Condition','Product Details & Pictures','Available QTY','Rate/Pcs (USD)','Rate/Pcs (INR)','Shipping','Lead Time','Image'].forEach(label => { const th = document.createElement('th'); th.textContent = label; headRow.append(th); }); head.append(headRow);
    const allBox = document.createElement('input'); allBox.type='checkbox'; allBox.checked=true; allBox.setAttribute('aria-label','Include all SKU items'); headRow.children[0].append(allBox);
    const body = document.createElement('tbody'); table.append(head,body); tableBox.append(table);
    tools.append(fetchButton,manual,status); lookup.append(hint,input,tools); host.append(heading,lookup,tableBox);
    const editBox = document.createElement('div'); editBox.className='draft-item-editor'; host.append(editBox);
    const note = document.createElement('p'); note.className='draft-note'; note.textContent='Checked items will be saved. Click a row or choose an item below to edit its details. Catalog prices are shown above; the agreed deal price is set below.'; host.append(note);
    if(commercial)note.textContent+=' HSN code and item condition must be completed before generating a PI.';
    const save = onSave ? document.createElement('button') : null;
    if (save) { save.type='button'; save.className='btn-sm btn-add'; save.textContent='Save all SKU lines'; host.append(save); }
    function priceCell(row, code) {
      const td=document.createElement('td');
      const amounts={...(row.catalog_prices?.[code] || {})};
      // Older lookup responses contain only the agreed price and currency.
      if (amounts.price == null && amounts.sale_price == null &&
          row.unit_price != null && row.unit_price !== '' && Number.isFinite(Number(row.unit_price))) {
        if (row.currency === code) amounts.price = row.unit_price;
        else if (displayRate) amounts.price = row.currency === 'USD'
          ? Number(row.unit_price) * displayRate : Number(row.unit_price) / displayRate;
      }
      const format=value=>`${code==='USD'?'$':'\u20b9'} ${Number(value).toLocaleString(code==='INR'?'en-IN':'en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
      if(amounts.sale_price != null && amounts.price != null) {
        const original=document.createElement('span'); original.className='catalog-original'; original.textContent=format(amounts.price);
        const sale=document.createElement('strong'); sale.textContent=format(amounts.sale_price);
        td.append(original,sale);
        if(Number(amounts.price)>0 && Number(amounts.sale_price)<Number(amounts.price)) {
          const discount=document.createElement('span'); discount.className='catalog-discount';
          discount.textContent=`${Math.round((1-Number(amounts.sale_price)/Number(amounts.price))*100)}% off`;td.append(discount);
        }
      } else if(amounts.price != null) { td.textContent=format(amounts.price); }
      else if(amounts.sale_price != null) { td.textContent=format(amounts.sale_price); }
      else { td.textContent='Unavailable'; }
      return td;
    }
    function renderTable() {
      body.replaceChildren();
      rows.forEach((row,index)=>{
        const tr=document.createElement('tr');
        tr.className='draft-product-row'+(activeRow===index?' is-active':'');
        tr.onclick=()=>{activeRow=index;renderTable();renderEditor();};
        const cell=value=>{const td=document.createElement('td');td.textContent=value;tr.append(td);return td;};
        const selection=cell('');const checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.checked=row.included!==false;
        checkbox.setAttribute('aria-label',`Include SKU ${row.sku || index+1}`);
        checkbox.onclick=event=>event.stopPropagation();
        checkbox.onchange=()=>{row.included=checkbox.checked;updateSelection();renderEditor();};selection.append(checkbox);
        cell(row.sku);cell(index+1);cell(row.description || row.error || 'Complete item details below');cell(row.condition || '\u2014');
        const product=cell('');
        if(row.url && /^https?:\/\//.test(row.url)){const link=document.createElement('a');link.href=row.url;link.target='_blank';link.rel='noopener';link.textContent='Click here';link.onclick=event=>event.stopPropagation();product.append(link);}else{product.textContent='\u2014';}
        cell(row.stock == null ? '\u2014' : `${row.stock} Pcs`);
        tr.append(priceCell(row,'USD'),priceCell(row,'INR'));
        cell(row.found?'Free':'\u2014');cell(row.found?'Ready Stock':'\u2014');
        const image=cell('');const download=document.createElement('button');download.type='button';download.className='draft-image-download';download.textContent='Download';download.disabled=true;download.title='Image downloads are not available in this installation.';image.append(download);
        body.append(tr);
      });
      if(!rows.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=12;td.className='draft-empty';td.textContent='Look up SKUs or add an item manually. Review the details before saving.';tr.append(td);body.append(tr);}
      updateSelection();
    }
    function updateSelection() {
      const included=rows.filter(row=>row.included!==false).length;
      allBox.checked=rows.length>0 && included===rows.length;
      allBox.indeterminate=included>0 && included<rows.length;
    }
    allBox.onchange=()=>{rows.forEach(row=>{row.included=allBox.checked;});render();};
    function renderEditor() {
      editBox.replaceChildren();editBox.hidden=!rows.length;
      if(!rows.length)return;
      activeRow=Math.min(activeRow,rows.length-1);
      const row=rows[activeRow];
      const toolbar=document.createElement('div');toolbar.className='draft-edit-toolbar';
      const label=document.createElement('span');label.textContent=commercial?'Edit order item':'Edit enquiry item';
      const picker=document.createElement('select');picker.setAttribute('aria-label','Choose SKU item to edit');
      rows.forEach((item,index)=>{const option=document.createElement('option');option.value=index;option.textContent=item.sku || 'Manual item';picker.append(option);});
      picker.value=activeRow;picker.onchange=()=>{activeRow=Number(picker.value);renderEditor();};toolbar.append(label,picker);
      const remove=document.createElement('button');remove.type='button';remove.className='btn-sm btn-del';remove.textContent='Remove item';remove.onclick=()=>{rows.splice(activeRow,1);render();};toolbar.append(remove);editBox.append(toolbar);
      const fields=document.createElement('div');fields.className='draft-edit-fields'+(commercial?' draft-commercial-fields':'');
      [['sku','SKU / item code','text',100],['description','Description','text',2000],['quantity','Quantity','number'],['unit_price',`Agreed unit price (${row.currency})`,'number'],...(commercial?[['hsn_code','HSN code','text',20],['item_condition','Item condition','text',100],['uom','Unit of measure','text',30]]:[])].forEach(([key,title,type,max])=>{
        const label=document.createElement('label');label.textContent=title;label.className='draft-field-'+key;
        const control=document.createElement(key==='uom'?'select':key==='description'?'textarea':'input');
        if(!['description','uom'].includes(key))control.type=type;
        if(key==='uom')for(const unit of uoms){const option=document.createElement('option');option.value=unit;option.textContent=unit;control.append(option);}
        control.value=row[key]||(key==='uom'?'PCs':'');control.required=row.included!==false&&(!commercial||!['hsn_code','item_condition'].includes(key));control.disabled=row.included===false;if(max)control.maxLength=max;
        if(type==='number'){control.min=key==='quantity'?'1':'0';control.step=key==='quantity'?'1':'0.01';}
        if(commercial&&key==='quantity'&&row.found&&row.stock!=null&&Number.isFinite(Number(row.stock)))control.max=String(row.stock);
        if(key==='hsn_code'&&sharedHsn){control.readOnly=true;control.title='Shared HSN code managed in Configuration';}
        control.setAttribute('aria-label',title);control.oninput=()=>{row[key]=control.value;renderTable();if(commercial){const issue=stockIssue(row);status.className='draft-status'+(issue?' error':'');status.textContent=issue||'Item updated. Selected items are ready to review.';}};label.append(control);fields.append(label);
      });
      editBox.append(fields);
    }
    function render() { renderTable();renderEditor(); }
    manual.onclick=()=>{const curr=currency();if(!['USD','INR'].includes(curr)){status.textContent='Choose a deal currency first.';return;}rows.push({sku:'',description:'',quantity:'1',unit_price:'',currency:curr,hsn_code:sharedHsn,uom:'PCs'});activeRow=rows.length-1;render();};
    fetchButton.onclick=async()=>{
      if(fetching)return;
      const curr=currency();const skus=[...new Set(input.value.split(/[\n,;]+/).map(v=>v.trim()).filter(Boolean))];
      if(!['USD','INR'].includes(curr)||!skus.length){status.textContent='Choose USD/INR and enter at least one SKU.';return;}
      fetching=true;fetchButton.disabled=true;status.className='draft-status';status.textContent='Fetching SKU details...';
      try {
        const target = scope();
        const keys = Object.keys(target);
        if (keys.length !== 1 || !['client_id','enquiry_id'].includes(keys[0]) ||
            !Number.isSafeInteger(target[keys[0]]) || target[keys[0]] <= 0) {
          throw new Error('Select a client or open an enquiry before looking up SKUs.');
        }
        const response=await fetch('/api/enquiries/sku-lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...target,skus,currency:curr})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Lookup failed.');
        if(target[keys[0]]!==scope()[keys[0]])throw new Error('Client or enquiry changed while fetching. Look up SKUs again.');
        if(curr!==currency())throw new Error('Currency changed while fetching. Fetch again.');
        const returnedRate = Number(data.usd_inr_rate);
        sharedHsn=data.shared_hsn_code||sharedHsn;
        if (Number.isFinite(returnedRate) && returnedRate > 0) displayRate = returnedRate;
        // Older running backends omit catalog prices and the USD display rate.
        if (!displayRate && data.drafts.some(row=>!row.catalog_prices)) {
          try {
            const rateResponse = await fetch('/api/rate');
            if (rateResponse.ok) {
              const rate = Number((await rateResponse.json()).rate);
              if (Number.isFinite(rate) && rate > 0) displayRate = rate;
            }
          } catch (_) { /* The original deal price can still be displayed. */ }
        }
        if(target[keys[0]]!==scope()[keys[0]] || curr!==currency())throw new Error('Client or currency changed while fetching. Look up SKUs again.');
        let added = 0;let updated = 0;
        for (const draft of data.drafts) {
          if(commercial){draft.item_condition=draft.condition||'';draft.hsn_code=sharedHsn||draft.hsn_code||'';draft.uom='PCs';}
          if (Number.isInteger(Number(draft.quantity))) draft.quantity = String(Number(draft.quantity));
          const existing = rows.find(row=>row.sku.trim()===draft.sku.trim());
          if (existing) {
            const edits = {sku:existing.sku, description:existing.description || draft.description,
              quantity:existing.quantity, unit_price:existing.unit_price || draft.unit_price,
              included:existing.included};
            if(commercial)Object.assign(edits,{
              hsn_code:sharedHsn||existing.hsn_code||draft.hsn_code,
              item_condition:existing.item_condition||draft.item_condition,
              uom:existing.uom||draft.uom,
            });
            Object.assign(existing,draft,edits);updated++;
          } else { rows.push({...draft});added++; }
        }
        render();status.textContent=`${added} draft rows added; ${updated} existing rows refreshed. Review each row; missing values must be completed.`;
        if(commercial){const issue=rows.filter(row=>row.included!==false).map(stockIssue).find(Boolean);if(issue){status.className='draft-status error';status.textContent=issue;}}
      }catch(error){status.textContent=error.message;}finally{fetching=false;fetchButton.disabled=false;}
    };
    const editor = {
      values() {
        if(fetching)throw new Error('Wait for SKU lookup to finish.');
        const selected=rows.filter(row=>row.included!==false);
        if(!selected.length)throw new Error('Select at least one complete SKU line.');
        if(selected.some(row=>row.currency!==currency()))throw new Error('Currency changed. Fetch again or review the draft prices.');
        for(const row of selected){const issue=stockIssue(row);if(issue){activeRow=rows.indexOf(row);renderEditor();status.className='draft-status error';status.textContent=issue;throw new Error(issue);}}
        for(const control of editBox.querySelectorAll('input,textarea,select'))if(!control.reportValidity())throw new Error('Complete all SKU row fields.');
        const invalid = selected.find(row =>
          !row.sku.trim() || !row.description.trim() ||
          !/^\d+$/.test(row.quantity) ||
          Number(row.quantity) <= 0 ||
          !/^(?:\d+(?:\.\d{1,2})?|\.\d{1,2})$/.test(row.unit_price)
        );
        if (invalid) {
          activeRow = rows.indexOf(invalid);
          renderEditor();
          throw new Error('Complete each selected item with a positive whole-number quantity and a valid price (up to 2 decimals).');
        }
        return selected.map(row=>Object.fromEntries(['sku','description','quantity','unit_price','currency',...(commercial?['hsn_code','item_condition','uom']:[])].map(key=>[key,row[key]||(key==='uom'?'PCs':'')])));
      },
      currencyChanged() { rows.forEach(row=>{row.currency=currency();row.unit_price='';});render();status.textContent='Currency changed. Fetch again or enter unit prices in the chosen currency.'; },
      reset() { rows=[];activeRow=0;input.value='';status.textContent='';render(); }
    };
    if(save)save.onclick=async()=>{save.disabled=true;try{await onSave(editor.values());editor.reset();status.textContent='SKU lines saved.';}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
    render();return editor;
  };
})();

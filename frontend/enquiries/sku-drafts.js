(() => {
  window.createSkuDraftEditor = (host, scope, currency, onSave = null) => {
    let rows = [];
    let fetching = false;
    host.classList.add('sku-drafts');
    host.replaceChildren();
    const heading = document.createElement('h3'); heading.textContent = 'Enquiry SKU items';
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
    ['SKU','Sr No','Description','Condition','Product details','Available qty','Quantity','Rate / pcs','Currency','Actions'].forEach(label => { const th = document.createElement('th'); th.textContent = label; headRow.append(th); }); head.append(headRow);
    const body = document.createElement('tbody'); table.append(head,body); tableBox.append(table);
    tools.append(fetchButton,manual,status); lookup.append(hint,input,tools); host.append(heading,lookup,tableBox);
    const save = onSave ? document.createElement('button') : null;
    if (save) { save.type='button'; save.className='btn-sm btn-add'; save.textContent='Save all SKU lines'; host.append(save); }
    function render() {
      body.replaceChildren();
      rows.forEach((row,index) => {
        const tr = document.createElement('tr');
        const field = (key,type,max) => {
          const td=document.createElement('td'); const control=document.createElement(key==='description'?'textarea':'input');
          if(key!=='description')control.type=type;
          control.value=row[key]; control.required=true; if(max)control.maxLength=max;
          if(type==='number'){control.min=key==='quantity'?'0.001':'0';control.step=key==='quantity'?'0.001':'0.01';}
          control.setAttribute('aria-label',`${key} for SKU row ${index+1}`);control.oninput=()=>{row[key]=control.value;};td.append(control);tr.append(td);
        };
        field('sku','text',100);
        const serial=document.createElement('td');serial.textContent=index+1;tr.append(serial);
        field('description','text',2000);
        const condition=document.createElement('td');condition.textContent=row.error || row.condition || 'Not specified';tr.append(condition);
        const product=document.createElement('td');
        if(row.url && /^https?:\/\//.test(row.url)){const link=document.createElement('a');link.href=row.url;link.target='_blank';link.rel='noopener';link.textContent='View product';product.append(link);}else{product.textContent='—';}tr.append(product);
        const stock=document.createElement('td');stock.textContent=row.stock == null ? '—' : `${row.stock} pcs`;tr.append(stock);
        field('quantity','number');field('unit_price','number');const curr=document.createElement('td');curr.textContent=row.currency;tr.append(curr);
        const actions=document.createElement('td');const remove=document.createElement('button');remove.type='button';remove.className='btn-sm btn-del';remove.textContent='Remove';remove.onclick=()=>{rows.splice(index,1);render();};actions.append(remove);tr.append(actions);body.append(tr);
      });
      if(!rows.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=10;td.className='draft-empty';td.textContent='Look up SKUs or add an item manually. Review the details before saving.';tr.append(td);body.append(tr);}
    }
    manual.onclick=()=>{const curr=currency();if(!['USD','INR'].includes(curr)){status.textContent='Choose a deal currency first.';return;}rows.push({sku:'',description:'',quantity:'1',unit_price:'',currency:curr});render();};
    fetchButton.onclick=async()=>{
      if(fetching)return;
      const curr=currency();const skus=input.value.split(/[\n,;]+/).map(v=>v.trim()).filter(Boolean);
      if(!['USD','INR'].includes(curr)||!skus.length){status.textContent='Choose USD/INR and enter at least one SKU.';return;}
      fetching=true;fetchButton.disabled=true;status.textContent='Fetching SKU details...';
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
        rows.push(...data.drafts);render();status.textContent=`${data.drafts.length} draft rows added${data.usd_inr_rate ? ' / USD to INR: '+data.usd_inr_rate : ''}. Review each row; missing values must be completed.`;
      }catch(error){status.textContent=error.message;}finally{fetching=false;fetchButton.disabled=false;}
    };
    const editor = {
      values() {
        if(fetching)throw new Error('Wait for SKU lookup to finish.');
        if(!rows.length)throw new Error('Add at least one complete SKU line.');
        if(rows.some(row=>row.currency!==currency()))throw new Error('Currency changed. Fetch again or review the draft prices.');
        for(const control of body.querySelectorAll('input,textarea'))if(!control.reportValidity())throw new Error('Complete all SKU row fields.');
        return rows.map(row=>Object.fromEntries(['sku','description','quantity','unit_price','currency'].map(key=>[key,row[key]])));
      },
      currencyChanged() { rows.forEach(row=>{row.currency=currency();row.unit_price='';});render();status.textContent='Currency changed. Fetch again or enter unit prices in the chosen currency.'; },
      reset() { rows=[];input.value='';status.textContent='';render(); }
    };
    if(save)save.onclick=async()=>{save.disabled=true;try{await onSave(editor.values());editor.reset();status.textContent='SKU lines saved.';}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
    render();return editor;
  };
})();

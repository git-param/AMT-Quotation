/* Editable commercial snapshot; the server owns identity, bank details and totals. */
window.createPiPreview = function (host, api, json, onIssued, onSaved = () => {}) {
  let state = null,
    issued = null,
    busy = false,
    inputs = [],
    paper,
    printFrame,
    status,
    toolbar;
  let printUrl=null;
  let calculationTimer=null,calculationVersion=0,calculated=[];
  let rateHeaders=[];
  function updateRateHeading(){
    const units=new Set(state.document.totals.lines.map((line,index)=>{
      const value=inputs.find(item=>item.path===`lines.${index}.uom`)?.input.value||line.uom||'PCs';
      return value.toLowerCase()==='set'?'Set':value;
    }));
    const heading=state.document.pi_format==='bulk'?'Rate / Lot':units.size<=1?'Rate / '+([...units][0]||'PCs'):units.has('PCs')?'Rate / PCs\nor\nRate / Lot':'Rate / Lot';
    rateHeaders.forEach(header=>{header.textContent=heading;});
  }
  function scheduleCalculation(){
    if(calculationTimer)clearTimeout(calculationTimer);
    const version=++calculationVersion;
    calculationTimer=setTimeout(async()=>{
      try{
        const data=collect();
        const result=await api(state.base+'/'+state.preview_id+'/calculate',json('POST',{lines:data.lines,shipping_charges:data.shipping_charges}));
        if(version!==calculationVersion||issued)return;
        state.document.totals=result.totals;
        for(const item of calculated){
          if(item.autoQuantity&&(state.document.annexure_quantity||inputs.find(entry=>entry.input===item.input)?.modified))continue;
          const value=item.path.split('.').reduce((target,key)=>target[key],result.totals);
          if(item.input)item.input.value=value;
          else item.node.textContent=item.accounting?Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):(item.amount?({USD:'$ ',INR:'\u20b9 ',AED:'AED ',GBP:'\u00a3 ',EUR:'\u20ac '})[state.document.currency]:'')+value;
        }
        status.textContent='Totals updated in '+state.document.currency+'. Use Update preview to save your changes.';
      }catch(error){if(version===calculationVersion)status.textContent=error.message;}
    },250);
  }
  function clearPrintUrl(){if(printUrl){URL.revokeObjectURL(printUrl);printUrl=null;}}
  const node = (tag, text, className) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (className) n.className = className;
    return n;
  };
  function valueOf(item) {
    return item.primaryInput ? window.orderLocations.joinParty(item.primaryInput.value,item.input.value) : item.input.value;
  }
  function fitText(input) {
    input.rows=Math.max(1,input.value.split('\n').length);
    input.style.height='auto';
    if(input.scrollHeight)input.style.height=input.scrollHeight+'px';
  }
  function field(parent, label, value, path, multiline = false, type = "text") {
    const wrap = node("label", undefined, "pi-field");
    wrap.append(node("span", label));
    const unit=path.endsWith('.uom');
    const input = node(unit?'select':multiline ? "textarea" : "input");
    if (!multiline&&!unit) input.type = type;
    if(unit)for(const value of ['PCs','Lot','Kit','set']){const option=node('option',value==='set'?'Set':value);option.value=value;input.append(option);}
    input.value = value ?? "";
    input.dataset.piField = path;
    input.setAttribute("aria-label", label);
    if (path === 'order.destination') {
      input.setAttribute('list', 'orderCountries');
      input.setAttribute('autocomplete', 'off');
      input.onchange = () => {
        input.value = input.value.trim().toUpperCase();
        const consignee = inputs.find(item => item.path === 'delivery.consignee_text');
        if (consignee) {
          const value=window.orderLocations.countryBlock(valueOf(consignee), input.value, [state.document.order.destination]);
          if(consignee.primaryInput){const [primary,secondary]=window.orderLocations.partyParts(value,input.value);consignee.primaryInput.value=primary;consignee.input.value=secondary;}
          else consignee.input.value=value;
        }
      };
    }
    if (multiline) input.rows = path.startsWith("delivery.") ? 9 : 3;
    if (type === "number") {
      input.min = "0";
      input.step = path.endsWith("quantity") ? "1" : "0.01";
    }
    input.oninput = () => {
      const entry=inputs.find(item=>item.input===input);if(entry)entry.modified=true;
      if(multiline)fitText(input);
      status.textContent =
        "Unsaved preview changes. Update preview to review calculated totals and the printed page.";
      printFrame.hidden = true;
      paper.hidden = false;
      if(path.endsWith('.line_total')){
        const base=path.slice(0,-'line_total'.length);
        const quantity=Number(inputs.find(item=>item.path===base+'quantity')?.input.value);
        const price=inputs.find(item=>item.path===base+'unit_price');
        if(quantity>0&&price&&Number.isFinite(Number(input.value)))price.input.value=(Number(input.value)/quantity).toFixed(2);
      }
      if(path.endsWith('.uom'))updateRateHeading();
      if(path==='shipping_charges'||/^lines\.\d+\.(quantity|unit_price|line_total|uom)$/.test(path))scheduleCalculation();
    };
    wrap.append(input);
    parent.append(wrap);
    inputs.push({ input, path });
    return input;
  }
  function partyField(parent, value, path) {
    const group=node('div',undefined,'pi-party-editor');parent.append(group);
    if(path!=='delivery.consignee_text'){
      const input=field(group,path==='delivery.buyer_text'?'Buyer details':'Notify details',value,path,true);
      fitText(input);return input;
    }
    const [primary,secondary]=window.orderLocations.partyParts(value,state.document.order.destination);
    const primaryInput=field(group,'Company / address details',primary,path+'.primary',true);inputs.pop();
    const input=field(group,'Country / GST / contact details',secondary,path,true);
    inputs.at(-1).primaryInput=primaryInput;
    fitText(primaryInput);fitText(input);
    return input;
  }
  function image(parent, name) {
    const img = node("img");
    img.src = "data:image/png;base64," + state.document.assets[name];
    img.alt = name.replace(".png", "").replaceAll("_", " ");
    parent.append(img);
  }
  function collect() {
    const doc = state.document;
    const data = {date:doc.date,prepared_phone:doc.prepared_phone||'',order:{},delivery:{},shipping_charges:doc.totals.shipping,
      lines:doc.totals.lines.map(line=>Object.fromEntries(["id","sku","description","hsn_code","item_condition","uom","quantity","unit_price"].map(key=>[key,line[key]])))};
    for(const item of inputs){if(item.path.endsWith('.line_total')||(item.path==='annexure_quantity'&&!item.modified&&!doc.annexure_quantity))continue;const keys=item.path.split('.');let target=data;for(const key of keys.slice(0,-1))target=target[key];target[keys.at(-1)]=valueOf(item);}
    if(String(data.shipping_charges).trim().toLowerCase()==='free')data.shipping_charges='0.00';
    return data;
  }
  async function save(forGeneration=false){
    const base=state.base;
    state={...await api(base+'/'+state.preview_id+(forGeneration?'?for_generation=1':''),json('PUT',collect())),base};
    onSaved(state.document);
    render();
  }
  async function run(callback){
    if(busy)return;busy=true;
    toolbar.querySelectorAll('button').forEach(button=>button.disabled=true);
    try{await callback();}catch(error){status.textContent=error.message;status.classList.add('error');status.focus();window.skuFeedback?.show(error.message,true);}
    finally{busy=false;toolbar.querySelectorAll('button').forEach(button=>button.disabled=false);}
  }
  function button(label,callback,primary=false){
    const control=node('button',label,'btn-sm'+(primary?' btn-add':''));control.type='button';
    control.onclick=()=>run(callback);toolbar.append(control);
  }
  function render(){
    if(calculationTimer)clearTimeout(calculationTimer);calculationVersion++;calculated=[];
    host.replaceChildren();host.hidden=false;inputs=[];rateHeaders=[];
    toolbar=node('div',undefined,'pi-preview-toolbar');host.append(toolbar);
    button('Close preview',async()=>{host.hidden=true;});
    if(!issued){
      button('Update preview',save);
      button('Edit invoice',async()=>{printFrame.hidden=true;paper.hidden=false;});
      button('PDF print preview',async()=>{
        const response=await fetch(state.base+'/'+state.preview_id+'/print',json('POST',collect()));
        if(!response.ok){const error=await response.json();throw new Error(error.error||'Unable to open print preview.');}
        const blob=await response.blob();clearPrintUrl();printUrl=URL.createObjectURL(blob);
        paper.hidden=true;printFrame.hidden=false;printFrame.src=printUrl;
        status.textContent='Print preview of current edits. Use Update preview to save changes.';
      });
    }
    for(const format of ['xlsx','pdf'])button('Generate '+format.toUpperCase(),async()=>{
      if(!issued){await save(true);issued=await api(state.base.replace('/preview','/issue'),json('POST',{preview_id:state.preview_id}));await onIssued(issued);render();}
      await window.downloadPiFile(issued[format+'_url'],issued[format+'_filename']||issued.reference.replace(/[<>:"/\\|?*\u0000-\u001f]/g,'-')+'.'+format);
    },true);
    status=node('p',issued?'PI '+issued.reference+' issued. Both downloads use this saved invoice.':'Edit fields directly below, then review the PDF print preview. Changes apply to this PI only.','pi-preview-status');
    status.role='status';status.tabIndex=-1;host.append(status);
    const scroll=node('div',undefined,'pi-paper-scroll');paper=node('article',undefined,'pi-paper');scroll.append(paper);host.append(scroll);
    printFrame=node('iframe');printFrame.title='Exact PI PDF print preview';printFrame.className='pi-print-frame';printFrame.hidden=true;host.append(printFrame);
    renderGrid();
  }
  function renderGrid() {
    const doc = state.document;
    const symbol = ({USD:'$',INR:'\u20b9',AED:'AED',GBP:'\u00a3',EUR:'\u20ac'})[doc.currency];
    const headerBox = node("div", undefined, "pi-header-box");
    const branding = node("div", undefined, "pi-branding");
    image(branding, "header.png");headerBox.append(branding);paper.append(headerBox);
    let annexurePaper=null;
    function footer(parent,includeAddress=true){
      const signatures=node('div',undefined,'pi-signatures');
      image(signatures,'payment_options.png');image(signatures,'signature.png');
      const box=node('div',undefined,'pi-footer-box');box.append(signatures);
      if(includeAddress)image(box,'address.png');parent.append(box);
    }
    for (const section of state.layout.sections) {
      if(section.annexure&&!annexurePaper){
        footer(paper);
        annexurePaper=node('div',undefined,'pi-annexure-page');
        annexurePaper.setAttribute('role','region');annexurePaper.setAttribute('aria-label','Annexure-1 product list');
        const annexureBranding=node('div',undefined,'pi-branding');image(annexureBranding,'header.png');
        annexurePaper.append(annexureBranding);paper.append(annexurePaper);
      }
      const table = node("table", undefined, "pi-company-grid pi-grid-" + section.name + (section.name === "bank" ? " pi-preview-totals" : ""));
      const columns = node("colgroup");
      const widths=section.widths||state.layout.widths;
      const width = widths.reduce((a, b) => a + b, 0);
      for (const size of widths) { const col = node("col"); col.style.width = (100 * size / width) + "%"; columns.append(col); }
      table.append(columns);
      const body = node("tbody");
      for (const [rowIndex,row] of section.rows.entries()) {
        if (row.every(cell => cell.preview_hidden)) continue;
        const tr = node("tr");
        if(section.row_heights)tr.style.height=section.row_heights[rowIndex]*1.1+'px';
        for (const cell of row) {
          if (section.name === "parties" && cell.placeholder) continue;
          const td = node("td", undefined, "pi-cell-" + (cell.style || "normal")); td.colSpan = cell.span;
          if (cell.rowspan) td.rowSpan = cell.rowspan;
          if (cell.total_cell) td.classList.add('pi-total-cell');
          if (cell.nowrap) td.classList.add('pi-nowrap');
          if (cell.open_left) td.classList.add('pi-open-left');
          if (cell.open_right) td.classList.add('pi-open-right');
          if (cell.line_top) td.classList.add("pi-border-top");
          if (cell.line_bottom) td.classList.add("pi-border-bottom");
          if (cell.editor_rows) td.rowSpan = cell.editor_rows;
          if (cell.party) {
            if(cell.bottom_contacts)td.classList.add('pi-consignee-cell');
            partyField(td,cell.value,cell.field);
          } else if (cell.field) {
            const amount = cell.style.includes("amount") && !cell.free;
            const input = field(td, cell.label || (amount ? symbol : cell.aria || cell.field.split(".").at(-1).replaceAll("_", " ")), cell.free ? 'Free' : cell.value, cell.field, cell.multiline, cell.free ? 'text' : cell.type || "text");
            if(cell.calculated)calculated.push({path:cell.calculated,input,autoQuantity:cell.auto_quantity});
            if(cell.auto_quantity){input.maxLength=200;input.title='Edit the displayed total quantity. Clear to restore the automatic total.';}
            if (cell.readonly) { input.readOnly = true; input.title = cell.field?.endsWith('.line_total')?'Calculated after discount. Edit quantity or unit price to change this amount.':'Shared HSN code managed in Configuration'; }
            if (!cell.label && !amount) td.lastChild.classList.add("pi-unlabelled");
            if (cell.editor_rows) input.rows = 12;
            else if (cell.multiline) input.rows = cell.field.startsWith("delivery.") ? 5 : 2;
            if (cell.field === 'terms') input.rows = Math.max(5, String(cell.value).split('\n').length);
            if (cell.uom_field) {field(td, "UOM", cell.uom==='Set'?'set':cell.uom, cell.uom_field);td.classList.add("pi-quantity-cell");}
            else if(cell.uom){const wrap=td.lastChild;wrap.classList.add('pi-quantity-inline');wrap.append(node('span',cell.uom,'pi-quantity-uom'));}
            if (cell.discount_note) td.append(node('small',cell.discount_note));
          } else {
            const content=node('div',undefined,'pi-cell-text');let value=content;
            if(cell.accounting){
              content.classList.add('pi-accounting');
              value=node('span',Number(cell.text).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}));
              content.append(node('span',symbol),value);
            }else content.textContent=(cell.style.includes('amount')?symbol+' ':'')+cell.text;
            td.append(content);
            if(cell.rate_heading){content.classList.add('pi-rate-heading');rateHeaders.push(content);}
            if(cell.calculated)calculated.push({path:cell.calculated,node:value,amount:!cell.accounting&&cell.style.includes('amount'),accounting:cell.accounting});
          }
          tr.append(td);
        }
        body.append(tr);
      }
      table.append(body);(section.annexure?annexurePaper:section.name === "header" ? headerBox : paper).append(table);
    }
    footer(annexurePaper||paper,!annexurePaper);
    for(const textarea of host.querySelectorAll('textarea'))fitText(textarea);
    if (issued) for (const { input, primaryInput } of inputs) {input.disabled = true;if(primaryInput)primaryInput.disabled=true;}
  }
  return {
    open(data, base) {
      clearPrintUrl();
      state = { ...data, base };
      issued = null;
      render();
      host.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    removeIssued(invoiceId) {
      if(issued?.id===invoiceId)this.reset();
    },
    reset() {
      if(calculationTimer)clearTimeout(calculationTimer);calculationVersion++;
      clearPrintUrl();
      host.hidden = true;
      host.replaceChildren();
      state = null;
      issued = null;
    },
  };
};

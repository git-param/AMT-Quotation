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
  const node = (tag, text, className) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (className) n.className = className;
    return n;
  };
  function valueOf(item) {
    return item.primaryInput ? window.orderLocations.joinParty(item.primaryInput.value,item.input.value) : item.input.value;
  }
  function field(parent, label, value, path, multiline = false, type = "text") {
    const wrap = node("label", undefined, "pi-field");
    wrap.append(node("span", label));
    const input = node(multiline ? "textarea" : "input");
    if (!multiline) input.type = type;
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
      status.textContent =
        "Unsaved preview changes. Update preview to review calculated totals and the printed page.";
      printFrame.hidden = true;
      paper.hidden = false;
    };
    wrap.append(input);
    parent.append(wrap);
    inputs.push({ input, path });
    return input;
  }
  function partyField(parent, value, path) {
    const group=node('div',undefined,'pi-party-editor');parent.append(group);
    const [primary,secondary]=window.orderLocations.partyParts(value,state.document.order.destination);
    const primaryInput=field(group,'Company / address details',primary,path+'.primary',true);inputs.pop();
    primaryInput.rows=4;
    const input=field(group,'Country / GST / contact details',secondary,path,true);
    inputs.at(-1).primaryInput=primaryInput;
    input.rows=5;
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
    for(const item of inputs){const keys=item.path.split('.');let target=data;for(const key of keys.slice(0,-1))target=target[key];target[keys.at(-1)]=valueOf(item);}
    if(String(data.shipping_charges).trim().toLowerCase()==='free')data.shipping_charges='0.00';
    return data;
  }
  async function save(){
    const base=state.base;
    state={...await api(base+'/'+state.preview_id,json('PUT',collect())),base};
    onSaved(state.document);
    render();
  }
  async function run(callback){
    if(busy)return;busy=true;
    toolbar.querySelectorAll('button').forEach(button=>button.disabled=true);
    try{await callback();}catch(error){status.textContent=error.message;status.classList.add('error');status.focus();}
    finally{busy=false;toolbar.querySelectorAll('button').forEach(button=>button.disabled=false);}
  }
  function button(label,callback,primary=false){
    const control=node('button',label,'btn-sm'+(primary?' btn-add':''));control.type='button';
    control.onclick=()=>run(callback);toolbar.append(control);
  }
  function render(){
    host.replaceChildren();host.hidden=false;inputs=[];
    toolbar=node('div',undefined,'pi-preview-toolbar');host.append(toolbar);
    button('Close preview',async()=>{host.hidden=true;});
    if(!issued){
      button('Update preview',save);
      button('Edit invoice',async()=>{printFrame.hidden=true;paper.hidden=false;});
      button('PDF print preview',async()=>{await save();paper.hidden=true;printFrame.hidden=false;printFrame.src=state.pdf_url+'?v='+Date.now();});
    }
    for(const format of ['xlsx','pdf'])button('Generate '+format.toUpperCase(),async()=>{
      if(!issued){await save();issued=await api(state.base.replace('/preview','/issue'),json('POST',{preview_id:state.preview_id}));await onIssued(issued);render();}
      const link=node('a');link.href=issued[format+'_url'];link.download='';host.append(link);link.click();link.remove();
    },true);
    status=node('p',issued?'PI '+issued.reference+' issued. Both downloads use this saved invoice.':'Edit fields directly below, then review the PDF print preview. Changes apply to this PI only.','pi-preview-status');
    status.role='status';status.tabIndex=-1;host.append(status);
    const scroll=node('div',undefined,'pi-paper-scroll');paper=node('article',undefined,'pi-paper');scroll.append(paper);host.append(scroll);
    printFrame=node('iframe');printFrame.title='Exact PI PDF print preview';printFrame.className='pi-print-frame';printFrame.hidden=true;host.append(printFrame);
    renderGrid();
  }
  function renderGrid() {
    const doc = state.document;
    const symbol = doc.currency === "INR" ? "₹" : "$";
    const headerBox = node("div", undefined, "pi-header-box");
    const branding = node("div", undefined, "pi-branding");
    image(branding, "header.png");headerBox.append(branding);paper.append(headerBox);
    for (const section of state.layout.sections) {
      const table = node("table", undefined, "pi-company-grid pi-grid-" + section.name + (section.name === "bank" ? " pi-preview-totals" : ""));
      const columns = node("colgroup");
      const width = state.layout.widths.reduce((a, b) => a + b, 0);
      for (const size of state.layout.widths) { const col = node("col"); col.style.width = (100 * size / width) + "%"; columns.append(col); }
      table.append(columns);
      const body = node("tbody");
      for (const row of section.rows) {
        if (row.every(cell => cell.preview_hidden)) continue;
        const tr = node("tr");
        for (const cell of row) {
          if (section.name === "parties" && cell.placeholder) continue;
          const td = node("td", undefined, "pi-cell-" + (cell.style || "normal")); td.colSpan = cell.span;
          if (cell.open_left) td.classList.add('pi-open-left');
          if (cell.open_right) td.classList.add('pi-open-right');
          if (cell.line_top) td.classList.add("pi-border-top");
          if (cell.line_bottom) td.classList.add("pi-border-bottom");
          if (cell.editor_rows) td.rowSpan = cell.editor_rows;
          if (cell.party) {
            if(cell.bottom_contacts)td.classList.add('pi-consignee-cell');
            partyField(td,cell.value,cell.field);
          } else if (cell.field) {
            if (cell.sku_field) field(td, "SKU", cell.sku, cell.sku_field);
            const amount = cell.style.includes("amount") && !cell.free;
            const input = field(td, cell.label || (amount ? symbol : cell.aria || cell.field.split(".").at(-1).replaceAll("_", " ")), cell.free ? 'Free' : cell.value, cell.field, cell.multiline, cell.free ? 'text' : cell.type || "text");
            if (cell.readonly) { input.readOnly = true; input.title = 'Shared HSN code managed in Configuration'; }
            if (!cell.label && !amount) td.lastChild.classList.add("pi-unlabelled");
            if (cell.editor_rows) input.rows = 12;
            else if (cell.multiline) input.rows = cell.field.startsWith("delivery.") ? 5 : 2;
            if (cell.field === 'terms') input.rows = Math.max(5, String(cell.value).split('\n').length);
            if (cell.uom_field) {field(td, "UOM", cell.uom, cell.uom_field);td.classList.add("pi-quantity-cell");}
          } else td.append(node("div", (cell.style.includes("amount") ? symbol + " " : "") + cell.text, "pi-cell-text"));
          tr.append(td);
        }
        body.append(tr);
      }
      table.append(body);(section.name === "header" ? headerBox : paper).append(table);
    }
    const signatures = node("div", undefined, "pi-signatures");
    image(signatures, "payment_options.png");image(signatures, "signature.png");
    const footerBox=node("div",undefined,"pi-footer-box");footerBox.append(signatures);
    image(footerBox, "address.png");paper.append(footerBox);
    if (issued) for (const { input, primaryInput } of inputs) {input.disabled = true;if(primaryInput)primaryInput.disabled=true;}
  }
  return {
    open(data, base) {
      state = { ...data, base };
      issued = null;
      render();
      host.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    reset() {
      host.hidden = true;
      host.replaceChildren();
      state = null;
      issued = null;
    },
  };
};

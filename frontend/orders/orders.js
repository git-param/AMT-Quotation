const el = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
const clientScope = params.get('client_id');
const enquiryScope = params.get('enquiry_id');
if(params.get('embedded')==='1')document.body.classList.add('embedded');
const headerFields = ['order_date','po_reference','pi_reference','delivery_terms','delivery_time','dispatch_method','currency','destination','shipping_charges'];
const addressFields = ['line1','line2','city','state','postal_code','country'];
let page=1, pages=0;
let current=null, editing=null, editingLine=null, clientData=null;
let detailVersion=0;
let formVersion=0;
let commercialInputs=[],savingCommercial=false;
function message(text,error=false){el('message').textContent=text;el('message').className=error?'error':'';}
async function api(url,options={}) {
  const response=await fetch(url,options);const data=await response.json();
  if(!response.ok){
    if([401,403,404].includes(response.status)){el('editor').hidden=true;el('detail').hidden=true;}
    const error=new Error(data.error||'Unable to complete request.');error.details=data;throw error;
  }
  return data;
}
const json = (method,data) => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function action(label,callback,danger=false){
  const button=document.createElement('button');button.type='button';button.className='btn-sm'+(danger?' btn-del':'');
  const icons={Details:'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',Edit:'m16 3 5 5-12 12-6 1 1-6L16 3Z M13 6l5 5',Delete:'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7'};
  if(icons[label]){
    button.className+=' order-action-icon';button.title=label;button.setAttribute('aria-label',label);
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.8','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(key,value);
    const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',icons[label]);svg.append(path);button.append(svg);
  }else button.textContent=label;
  button.onclick=()=>callback().catch(error=>message(error.message,true));return button;
}
function cell(row,value){const td=document.createElement('td');td.textContent=value??'';row.append(td);return td;}
function addressText(address){return addressFields.map(key=>address?.[key]).filter(Boolean).join('\n')||'Not provided';}
function formatPartyBlock(party={},address={}){
  const lines=[party.name,...addressFields.filter(key=>key!=='country').map(key=>address?.[key])].filter(Boolean);
  if(address?.country)lines.push('Country: '+address.country);
  lines.push('Tel: '+(party.phone||''),'PIC: '+(party.pic||''),'Email: '+(party.email||''));
  if(party.gst_number)lines.push('GST: '+party.gst_number);
  return lines.join('\n');
}
function showPartyFields(prefix){
  const [primary,secondary]=window.orderLocations.partyParts(el(prefix+'_text').value,el('destination').value);
  el(prefix+'_primary').value=primary;el(prefix+'_details').value=secondary;
}
function syncConsignee(){for(const prefix of ['buyer','notify'])if(el(prefix+'_same').checked){el(prefix+'_text').value=window.orderLocations.addressOnly(el('consignee_text').value);showPartyFields(prefix);}}
for(const prefix of ['consignee','buyer','notify']){
  const changed=()=>{
    el(prefix+'_text').value=window.orderLocations.joinParty(el(prefix+'_primary').value,el(prefix+'_details').value);
    el(prefix+'_text').oninput();
  };
  el(prefix+'_primary').oninput=changed;el(prefix+'_details').oninput=changed;
}
function refreshBuyerGst(){
  el('buyerGstField').hidden=el('destination').value.trim().toUpperCase()!=='INDIA';
  el('buyerGst').value=window.orderLocations.gstNumber(el('buyer_text').value);
}
el('destination').oninput=()=>{el('buyerGstField').hidden=el('destination').value.trim().toUpperCase()!=='INDIA';};
el('destination').onchange=()=>{
  el('destination').value=el('destination').value.trim().toUpperCase();
  el('consignee_text').value=window.orderLocations.countryBlock(el('consignee_text').value,el('destination').value);
  showPartyFields('consignee');
  syncConsignee();refreshBuyerGst();
};
el('buyerGst').oninput=()=>{
  el('buyer_text').value=window.orderLocations.withGst(el('buyer_text').value,el('buyerGst').value);
  showPartyFields('buyer');
  el('buyer_same').checked=el('buyer_text').value===window.orderLocations.addressOnly(el('consignee_text').value);
};
for(const prefix of ['buyer','notify']){
  el(prefix+'_text').oninput=()=>{el(prefix+'_same').checked=el(prefix+'_text').value===window.orderLocations.addressOnly(el('consignee_text').value);refreshBuyerGst();};
  el(prefix+'_same').onchange=()=>{if(el(prefix+'_same').checked)el(prefix+'_text').value=window.orderLocations.addressOnly(el('consignee_text').value);showPartyFields(prefix);refreshBuyerGst();};
}
el('consignee_text').oninput=()=>{syncConsignee();refreshBuyerGst();};
const initialDrafts=window.createSkuDraftEditor(el('initialDrafts'),()=>({client_id:Number(clientScope)}),()=>el('currency').value,null,true);
const lineDrafts=window.createSkuDraftEditor(el('lineDrafts'),()=>({client_id:current.order.client_id}),()=>current.order.currency,async lines=>{
  await api(`/api/orders/${current.order.id}/lines/bulk`,json('POST',{lines}));await showDetails(current.order.id);
},true);
el('currency').onchange=()=>initialDrafts.currencyChanged();


function selectOrderTab(name){
  for(const [key,button]of [['items','tabItems'],['details','tabDetails'],['history','tabHistory']]){
    el(key+'Tab').hidden=key!==name;el(button).setAttribute('aria-selected',String(key===name));el(button).tabIndex=key===name?0:-1;
  }
}
for(const [name,id]of [['items','tabItems'],['details','tabDetails'],['history','tabHistory']]){
  el(id).onclick=()=>selectOrderTab(name);
  el(id).onkeydown=event=>{
    const names=['items','details','history'];const index=names.indexOf(name);
    if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){
      event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3;
      selectOrderTab(names[next]);el(['tabItems','tabDetails','tabHistory'][next]).focus();
    }
  };
}
function commercialDirty(){return commercialInputs.some(item=>item.hsn.value.trim()!==item.originalHsn||item.condition.value.trim()!==item.originalCondition);}
function updatePiReadiness(){
  if(!current)return;
  const missing=current.lines.filter(line=>!line.hsn_code||!line.item_condition);
  const dirty=commercialDirty(),empty=!current.lines.length,legacy=Boolean(current.legacy_lines_requiring_review?.length);
  el('generatePi').disabled=dirty||empty||legacy||savingCommercial;
  el('saveItemDetails').hidden=!current.order.can_edit;el('saveItemDetails').disabled=!dirty||savingCommercial;
  el('completeItemDetails').hidden=!current.order.can_edit||!missing.length;
  el('piReadiness').className='pi-readiness'+(dirty||missing.length||empty||legacy?' needs-attention':' is-ready');
  el('readinessTitle').textContent=dirty?'Save your item changes':empty?'Add items to this order':missing.length?`${missing.length} item${missing.length===1?' needs':'s need'} PI details`:legacy?'Review historical quantities':'Item details are complete';
  el('readinessHint').textContent=dirty?'Save item details below before generating your PI.':empty?'Add SKU lines, quantities and agreed prices to get started.':missing.length?`Enter the missing HSN code and item condition in the highlighted fields (${missing.slice(0,3).map(line=>line.sku).join(', ')}${missing.length>3?' and '+(missing.length-3)+' more':''}).`:legacy?'Complete the outstanding historical quantity review below.':'Choose the invoice currency below. Amounts use your saved order prices and any exchange rate you enter.';
  el('itemDetailsHint').textContent=dirty?'You have unsaved item details.':current.shared_hsn_code?'HSN code is shared across all SKUs and managed by TLs/admins in Configuration. Review each item condition before saving.':'HSN code and item condition are required for PI generation. TLs/admins can set a shared HSN code in Configuration.';
}
el('completeItemDetails').onclick=()=>{
  selectOrderTab('items');const first=commercialInputs.flatMap(item=>[item.hsn,item.condition]).find(input=>!input.value.trim());
  if(first){first.scrollIntoView({behavior:'smooth',block:'center'});first.focus();}
};
el('saveItemDetails').onclick=async()=>{
  if(!commercialDirty())return;savingCommercial=true;updatePiReadiness();
  try{
    const lines=commercialInputs.filter(item=>item.hsn.value.trim()!==item.originalHsn||item.condition.value.trim()!==item.originalCondition).map(item=>({id:item.id,hsn_code:item.hsn.value.trim(),item_condition:item.condition.value.trim()}));
    await api(`/api/orders/${current.order.id}/line-commercial-details`,json('PUT',{lines}));
    await showDetails(current.order.id);message('Item details saved.');
  }catch(error){message(error.message,true);}finally{savingCommercial=false;updatePiReadiness();}
};

async function load() {
  const query=new URLSearchParams({page,page_size:25,q:el('search').value,status:el('filterStatus').value,sort:el('sort').value,direction:el('direction').value});
  if(clientScope)query.set('client_id',clientScope);if(enquiryScope)query.set('enquiry_id',enquiryScope);
  const data=await api('/api/orders?'+query);pages=data.pages;
  if(page>Math.max(1,pages)){page=Math.max(1,pages);return load();}
  el('summary').textContent=`${data.total} matching orders`;
  el('pageInfo').textContent=`Page ${page} of ${Math.max(1,pages)}`;
  el('previous').disabled=page<=1;el('next').disabled=page>=pages;el('orders').replaceChildren();
  data.orders.forEach(order=>{
    const row=document.createElement('tr');
    const reference=cell(row,'');reference.append(action(order.reference,()=>showDetails(order.id)));
    [order.client_name,order.enquiry_reference,order.order_date,order.status,order.currency,order.creator_name].forEach(value=>cell(row,value));
    const actions=cell(row,'');actions.append(action('Details',()=>showDetails(order.id)));
    if(order.can_edit)actions.append(action('Edit',()=>editOrder(order.id)));
    el('orders').append(row);
  });
  if(!data.orders.length){const row=document.createElement('tr');const td=cell(row,'No orders match your filters.');td.colSpan=8;el('orders').append(row);}
}

async function prepareClient(clientId,delivery=null,version=formVersion) {
  const result=await api(`/api/leads/${clientId}`);if(version!==formVersion)return false;
  clientData=result;const client=result.lead;
  const saved=client.shipping_address?.line1?client.shipping_address:client.billing_address||{};
  const contact=client.contact_persons?.[0]||{};
  const base={name:client.company||client.name,email:client.email||client.emails?.[0]||contact.email,
    phone:client.phone||client.phones?.[0]||contact.phone,pic:contact.name};
  let defaults=formatPartyBlock(base,saved);
  if(client.location){
    defaults=[base.name,client.location,saved.country?'Country: '+saved.country:null,
      'Tel: '+(base.phone||''),'PIC: '+(base.pic||''),'Email: '+(base.email||'')].filter(value=>value!==null&&value!==undefined).join('\n');
  }
  const consignee=delivery?.consignee_text??(delivery?.consignee?.name?
    formatPartyBlock(delivery.consignee,delivery.shipping_address):defaults);
  el('consignee_text').value=consignee;
  for(const [prefix,key,party,address]of [
    ['buyer','buyer_text',delivery?.buyer,delivery?.billing_address],
    ['notify','notify_text',delivery?.notify_party,delivery?.notify_party?.address],
  ]){
    let value=delivery?.[key]??(party?.name?formatPartyBlock(party,address):window.orderLocations.addressOnly(consignee));
    if(value===consignee)value=window.orderLocations.addressOnly(value);
    el(prefix+'_text').value=value;el(prefix+'_same').checked=value===window.orderLocations.addressOnly(consignee);
  }
  for(const prefix of ['consignee','buyer','notify'])showPartyFields(prefix);
  if(!delivery)el('destination').value=saved.country||'';
  refreshBuyerGst();
  return true;
}
async function createOrder() {
  if(!clientScope)throw new Error('Open a client in Clients & Orders to add an order.');
  const version=++formVersion;editing=null;el('orderForm').reset();initialDrafts.reset();
  el('initialDrafts').hidden=true;el('initialLines').hidden=false;
  el('formTitle').textContent='New order / pending draft';el('referenceHint').textContent='Order reference is generated when saved.';
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(part=>[part.type,part.value]));
  el('order_date').value=`${parts.year}-${parts.month}-${parts.day}`;
  el('shipping_charges').value='0.00';
  el('delivery_terms').value='DAP';el('delivery_time').value='4 to 6 days';el('dispatch_method').value='DHL/Fedex/Aramex';
  el('pi_reference').value='';el('pi_reference').readOnly=false;
  if(!await prepareClient(Number(clientScope),null,version))return;
  if(!clientData.lead.can_edit||!clientData.lead.is_active)throw new Error('Choose an editable, active client.');
  el('editor').hidden=false;el('detail').hidden=true;el('editor').scrollIntoView({behavior:'smooth'});
}
async function editOrder(id) {
  const version=++formVersion;
  const data=await api(`/api/orders/${id}`);if(!data.order.can_edit)throw new Error('Client access is read-only.');
  if(version!==formVersion)return;
  editing=id;initialDrafts.reset();el('initialLines').hidden=true;
  headerFields.forEach(key=>{el(key).value=data.order[key];});if(!await prepareClient(data.order.client_id,data.delivery,version))return;
  el('pi_reference').readOnly=Boolean(data.invoices?.some(invoice=>invoice.workbook_format==='xlsm'));
  el('detail').hidden=true;el('formTitle').textContent='Edit order';el('referenceHint').textContent=data.order.reference;el('editor').hidden=false;el('editor').scrollIntoView({behavior:'smooth'});
}
el('orderForm').onsubmit=async event=>{
  event.preventDefault();el('save').disabled=true;
  try {
    if(!clientData)throw new Error('Choose a client before saving.');
    el('destination').value=el('destination').value.trim().toUpperCase();
    el('consignee_text').value=window.orderLocations.countryBlock(el('consignee_text').value,el('destination').value);
    syncConsignee();
    const data=Object.fromEntries(headerFields.map(key=>[key,el(key).value]));
    data.delivery={consignee_text:el('consignee_text').value,buyer_text:el('buyer_text').value,
      notify_text:el('notify_text').value};
    if(editing===null){data.client_id=Number(clientScope);data.lines=el('initialDrafts').hidden?[]:initialDrafts.values();}
    const result=await api(editing===null?'/api/orders':`/api/orders/${editing}`,json(editing===null?'POST':'PUT',data));
    el('editor').hidden=true;await load();await showDetails(result.order.id);message('Order saved.');
  }catch(error){message(error.message,true);}finally{el('save').disabled=false;}
};

async function showDetails(id) {
  const version=++detailVersion;const data=await api(`/api/orders/${id}`);if(version!==detailVersion)return;
  if((clientScope&&String(data.order.client_id)!==clientScope)||(enquiryScope&&String(data.order.enquiry_id)!==enquiryScope))throw new Error('Order does not belong to the selected record.');
  current=data;commercialInputs=[];editingLine=null;el('editor').hidden=true;el('piError').hidden=true;el('lineForm').hidden=true;el('lineDrafts').hidden=true;el('copyPanel').hidden=true;lineDrafts.reset();
  const order=data.order;
  el('conversionHint').textContent='Choose the currency for this proforma invoice.';
  el('piForm').hidden=!order.can_edit||order.status==='cancelled';el('piCurrency').value='';el('piRate').value='';el('piRate').required=false;el('rateField').hidden=true;
  el('invoiceList').replaceChildren();
  invoicePreview.reset();
  for(const invoice of data.invoices||[])appendInvoice(invoice,id);
  if(data.legacy_lines_requiring_review?.length)message('Historical fractional quantities need review before PI generation. Original lines remain preserved in the enquiry history.',true);
  el('legacyReview').replaceChildren();
  for(const source of data.legacy_lines_requiring_review||[]){
    const panel=document.createElement('section');panel.className='order-items';
    const label=document.createElement('p');label.textContent=`Review historical quantity: ${source.sku} / ${source.quantity}. Add a whole-unit replacement line, then explicitly link it here. The original record is preserved.`;panel.append(label);
    if(order.can_edit){
      const select=document.createElement('select');select.setAttribute('aria-label',`Replacement for historical SKU ${source.sku}`);
      select.add(new Option('Choose reviewed replacement line',''));
      for(const line of data.lines)select.add(new Option(`${line.sku} / ${line.quantity}`,line.id));
      const button=action('Confirm reviewed replacement',async()=>{
        await api(`/api/orders/${id}/legacy-lines/${source.id}/review`,json('POST',{replacement_line_id:Number(select.value)}));await showDetails(id);
      });panel.append(select,button);
    }
    el('legacyReview').append(panel);
  }
  el('legacyHistory').hidden=!order.enquiry_id;el('legacyHistory').open=false;el('legacyBody').replaceChildren();
  el('legacyHistory').ontoggle=async()=>{
    if(!el('legacyHistory').open||el('legacyBody').children.length)return;
    try{
      const history=await api(`/api/orders/${id}/legacy-enquiry`);if(version!==detailVersion)return;
      const text=document.createElement('p');text.textContent=`${history.enquiry.reference} / ${history.enquiry.subject} / ${history.enquiry.status}\n${history.enquiry.description}`;el('legacyBody').append(text);
      for(const line of history.lines){const row=document.createElement('p');row.textContent=`${line.sku} / ${line.description} / ${line.quantity} x ${line.currency} ${line.unit_price}${line.is_active?'':' (removed)'}`;el('legacyBody').append(row);}
    }catch(error){message(error.message,true);}
  };
  el('detailTitle').textContent=order.reference;
  el('detailAccess').textContent=`${order.status} / ${order.currency} / ${order.can_edit?'Editable':'Read only'}`;
  el('editOrder').hidden=!order.can_edit;el('addLine').hidden=!order.can_edit;
  el('recordLinks').replaceChildren();
  for(const [label,url] of [[`Client: ${order.client_name}`,`/clients-orders?client_id=${order.client_id}`]]){const link=document.createElement('a');link.textContent=label;link.href=url;el('recordLinks').append(link);}
  el('detailBody').replaceChildren();
  const section=(label,value)=>{const block=document.createElement('section');const title=document.createElement('h3');title.textContent=label;const text=document.createElement('p');text.textContent=value||'Not provided';block.append(title,text);el('detailBody').append(block);};
  section('Order and PO / PI references',[order.order_date,order.po_reference&&`PO: ${order.po_reference}`,order.pi_reference&&`PI: ${order.pi_reference}`,order.pi_date&&`PI date: ${order.pi_date}`].filter(Boolean).join('\n'));
  section('Payment and delivery terms',[order.payment_terms,order.delivery_terms,order.delivery_time,order.dispatch_method].filter(Boolean).join('\n'));
  el('ownershipHistory').textContent=`Client owner: ${order.owner_name} / Order created by ${order.creator_name} / ${new Date(order.created_at).toLocaleString()}`;
  section('Destination / shipping',[order.destination,`${order.currency} ${order.shipping_charges}`].filter(Boolean).join(' / '));
  const destination=data.delivery||{};
  section('Consignee',destination.consignee_text??formatPartyBlock(destination.consignee,destination.shipping_address));
  section('Buyer Details',destination.buyer_text??(destination.buyer?.name?formatPartyBlock(destination.buyer,destination.billing_address):'Same as consignee'));
  section('Notify Details',destination.notify_text??(destination.notify_party?.name?formatPartyBlock(destination.notify_party,destination.notify_party?.address):'Same as consignee'));
  el('lineRows').replaceChildren();
  data.lines.forEach(line=>{
    const row=document.createElement('tr');
    const product=cell(row,'');product.setAttribute('data-label','Item');const sku=document.createElement('strong');sku.textContent=line.sku;
    const description=document.createElement('span');description.className='item-description';description.textContent=line.description;product.append(sku,description);
    if(line.source_enquiry_line_id){const source=document.createElement('small');source.textContent=`Imported enquiry item #${line.source_enquiry_line_id}`;product.append(source);}
    [line.quantity+' '+(line.uom||'PCs'),line.currency+' '+line.unit_price,line.currency+' '+line.line_total].forEach((value,index)=>cell(row,value).setAttribute('data-label',['Quantity','Unit price','Amount'][index]));
    const inputs={id:line.id,originalHsn:line.hsn_code||'',originalCondition:line.item_condition||''};
    for(const [key,label,limit,slot]of [['hsn_code','HSN code',20,'hsn'],['item_condition','Item condition',100,'condition']]){
      const td=cell(row,'');td.setAttribute('data-label',label);
      if(order.can_edit){
        const input=document.createElement('input');input.type='text';input.maxLength=limit;input.value=line[key]||'';
        input.placeholder=label==='HSN code'?'Enter HSN code':'Select or enter condition';input.className='commercial-input';
        input.setAttribute('aria-label',`${label} for ${line.sku}`);input.setAttribute('aria-invalid',String(!input.value));
        if(key==='hsn_code'&&current.shared_hsn_code){input.readOnly=true;input.title='Shared HSN code managed in Configuration';}
        if(key==='item_condition')input.setAttribute('list','itemConditions');
        input.oninput=()=>{input.setAttribute('aria-invalid',String(!input.value.trim()));updatePiReadiness();};
        td.append(input);inputs[slot]=input;
      }else{td.textContent=line[key]||'Not set';}
    }
    if(order.can_edit)commercialInputs.push(inputs);
    const actions=cell(row,'');actions.setAttribute('data-label','Actions');
    if(order.can_edit)actions.append(action('Edit',async()=>{if(commercialDirty())throw new Error('Save item details before opening the full line editor.');const latest=(await api(`/api/orders/${id}/lines/${line.id}`)).line;if(!latest.is_active)throw new Error('This line was removed.');editingLine=line.id;for(const [key,value] of Object.entries({lineSku:latest.sku,lineDescription:latest.description,lineQuantity:latest.quantity,linePrice:latest.unit_price,lineCurrency:latest.currency,lineHsn:current.shared_hsn_code||latest.hsn_code||'',lineCondition:latest.item_condition||'',lineUom:latest.uom||'PCs'}))el(key).value=value;el('lineHsn').readOnly=Boolean(current.shared_hsn_code);el('lineForm').hidden=false;el('lineForm').scrollIntoView({behavior:'smooth'});}));
    if(order.can_delete)actions.append(action('Delete',async()=>{if(!window.confirm(`Delete SKU ${line.sku}? History will be retained.`))return;await api(`/api/orders/${id}/lines/${line.id}`,{method:'DELETE'});await showDetails(id);},true));
    el('lineRows').append(row);
  });
  if(!data.lines.length){const row=document.createElement('tr');cell(row,'No active order items.').colSpan=7;el('lineRows').append(row);}
  el('totals').replaceChildren();Object.entries(data.subtotals).forEach(([code,total])=>{const label=document.createElement('strong');label.textContent=`${code} subtotal: ${total}`;el('totals').append(label);});
  el('deliveryHistory').replaceChildren();data.delivery_history.forEach(item=>{const p=document.createElement('p');p.textContent=`${new Date(item.recorded_at).toLocaleString()} / version ${item.id}\nShipping: ${addressText(item.shipping_address)}\nBilling: ${addressText(item.billing_address)}`;el('deliveryHistory').append(p);});
  el('revisions').replaceChildren();data.revisions.forEach(item=>{const p=document.createElement('p');p.textContent=`${new Date(item.created_at).toLocaleString()} / ${item.action.replaceAll('_',' ')} / actor #${item.actor_user_id}`;el('revisions').append(p);});
  selectOrderTab('items');updatePiReadiness();
  el('detail').hidden=false;el('detail').scrollIntoView({behavior:'smooth'});
}
el('lineForm').onsubmit=async event=>{event.preventDefault();try{await api(`/api/orders/${current.order.id}/lines/${editingLine}`,json('PUT',{sku:el('lineSku').value,description:el('lineDescription').value,quantity:el('lineQuantity').value,unit_price:el('linePrice').value,currency:el('lineCurrency').value,hsn_code:el('lineHsn').value,item_condition:el('lineCondition').value,uom:el('lineUom').value}));await showDetails(current.order.id);message('Order line saved.');}catch(error){message(error.message,true);}};
el('addLine').onclick=()=>{lineDrafts.reset();el('lineDrafts').hidden=!el('lineDrafts').hidden;};
el('cancelLine').onclick=()=>{el('lineForm').hidden=true;};
el('manualToggle').onclick=()=>{el('initialDrafts').hidden=!el('initialDrafts').hidden;};

el('newOrder').onclick=()=>createOrder().catch(error=>message(error.message,true));
el('editOrder').onclick=()=>editOrder(current.order.id).catch(error=>message(error.message,true));
el('cancel').onclick=()=>{formVersion++;el('editor').hidden=true;if(params.get('embedded')==='1')window.parent.postMessage({type:'amt-order-close'},location.origin);};el('closeDetail').onclick=()=>{detailVersion++;el('detail').hidden=true;};
el('refresh').onclick=()=>load().catch(error=>message(error.message,true));
el('filters').onsubmit=event=>{event.preventDefault();page=1;load().catch(error=>message(error.message,true));};
el('previous').onclick=()=>{if(page>1){page--;load().catch(error=>message(error.message,true));}};
el('next').onclick=()=>{if(page<pages){page++;load().catch(error=>message(error.message,true));}};
el('piCurrency').onchange=()=>{
  const currency=el('piCurrency').value;
  const convert=Boolean(currency)&&[current.order.currency,...current.lines.map(line=>line.currency)].some(code=>code!==currency);
  el('rateField').hidden=!convert;el('piRate').required=convert;
  if(!convert)el('piRate').value='';
  el('conversionHint').textContent=convert?'Enter INR per 1 USD. USD to INR multiplies; INR to USD divides. Unit rates round to 2 decimals before multiplying quantities. Shipping is converted separately.':'Amounts already in the selected currency use their saved prices.';
};
function appendInvoice(invoice,id){
  const row=document.createElement('div');row.className='pi-download-row';
  const title=document.createElement('span');title.textContent=`${invoice.reference} / ${invoice.currency} / ${(invoice.created_at||'').slice(0,10)}`;row.append(title);
  for(const format of [invoice.workbook_format||'xlsm',...(invoice.has_pdf?['pdf']:[])]){const link=document.createElement('a');link.textContent='Download '+format.toUpperCase();link.href=`/api/orders/${id}/invoices/${invoice.id}/download?format=${format}`;row.append(link);}
  el('invoiceList').append(row);
}
const invoicePreview=window.createPiPreview(el('piPreview'),api,json,async result=>{
  appendInvoice({...result,currency:el('piCurrency').value,workbook_format:'xlsx',has_pdf:true},current.order.id);
  message(`PI ${result.reference} generated. Excel and PDF are ready.`);
});
el('piForm').onsubmit=async event=>{
  event.preventDefault();
  if(commercialDirty()||!current.lines.length){updatePiReadiness();el('completeItemDetails').onclick();return;}
  el('piError').hidden=true;el('generatePi').disabled=true;
  try{
    const data={currency:el('piCurrency').value};if(!el('rateField').hidden)data.usd_inr_rate=el('piRate').value;
    const base=`/api/orders/${current.order.id}/invoices/preview`;
    const result=await api(base,json('POST',data));
    invoicePreview.open(result,base);
  }catch(error){
    if(error.details?.code==='pi_lines_incomplete')await showDetails(current.order.id);
    el('piError').textContent=error.message;el('piError').hidden=false;message(error.message,true);
  }finally{updatePiReadiness();}
};
(async()=>{try{
  if(enquiryScope){const e=(await api(`/api/enquiries/${enquiryScope}`)).enquiry;el('context').textContent=`Orders for ${e.reference} / ${e.client_name}`;el('newOrder').hidden=!e.can_edit||!e.client_active;}
  else if(clientScope){const c=(await api(`/api/leads/${clientScope}`)).lead;el('context').textContent=`Orders for ${c.name}`;el('newOrder').hidden=!c.can_edit||!c.is_active;}
  if(!clientScope)el('newOrder').hidden=true;
  await load();if(params.get('order_id'))await showDetails(Number(params.get('order_id')));if(params.get('new')==='1')await createOrder();
}catch(error){message(error.message,true);}})();

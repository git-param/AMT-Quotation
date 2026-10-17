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
let statusOrder=null,statusSaving=false;
function updateOrderStatusUI(order){
  statusOrder=order;
  const canChange=Boolean(order?.can_edit&&order.status!=='cancelled');
  for(const id of ['composerStatus','toggleOrderStatus']){
    el(id).hidden=!canChange||params.get('embedded')==='1';
    el(id).disabled=statusSaving;
    el(id).textContent=order?.status==='completed'?'Move to pending':'Complete';
    el(id).title='Generating a PI automatically marks this order complete.';
  }
  if(params.get('embedded')==='1')window.parent.postMessage({type:'amt-order-state',order:order?{id:order.id,status:order.status,can_edit:canChange}:null,busy:statusSaving},location.origin);
}
async function toggleOrderCompletion(){
  if(!statusOrder?.can_edit||statusOrder.status==='cancelled'||statusSaving)return;
  const orderId=statusOrder.id,target=statusOrder.status==='completed'?'draft':'completed';
  statusSaving=true;updateOrderStatusUI(statusOrder);
  try{
    const result=await api(`/api/orders/${orderId}/status`,json('PUT',{status:target}));
    if(statusOrder?.id!==orderId)return;
    if(current?.order.id===orderId)current.order.status=result.order.status;
    updateOrderStatusUI(result.order);
    if(current?.order.id===orderId)el('detailAccess').textContent=`${result.order.status==='completed'?'Complete':'Pending'} / ${current.order.currency} / Editable`;
    await load();message(target==='completed'?'Order moved to complete orders.':'Order moved to pending orders.');
  }catch(error){message(error.message,true);}
  finally{statusSaving=false;updateOrderStatusUI(statusOrder);}
}
el('composerStatus').onclick=toggleOrderCompletion;el('toggleOrderStatus').onclick=toggleOrderCompletion;
window.addEventListener('message',event=>{
  if(params.get('embedded')==='1'&&event.origin===location.origin&&event.source===window.parent&&event.data?.type==='amt-order-toggle-status')toggleOrderCompletion();
});
function updateComposer(){
  for(const prefix of ['buyer','notify']){
    el(prefix+'Summary').textContent=el(prefix+'_text').value.trim()||'No address added yet';
  }
}
function openPartyEditor(prefix,open){
  el(prefix+'Editor').hidden=!open;
  el(prefix+'Summary').hidden=open;
  el(prefix+'Toggle').setAttribute('aria-expanded',String(open));
  el(prefix+'Toggle').textContent=open?'Hide details':'Review / edit';
}
function resetComposer(){
  el('formError').hidden=true;
  el('cancel').hidden=params.get('embedded')==='1';
  el('referenceHint').textContent=(clientData.lead.company||clientData.lead.name)+' · '+(editing===null?'Reference created on save.':el('referenceHint').textContent);
  for(const prefix of ['buyer','notify'])openPartyEditor(prefix,!el(prefix+'_same').checked);
  el('editingItemsHint').hidden=editing===null;
  el('save').textContent=editing===null?'Save draft':'Save changes';
  el('saveHint').textContent=editing===null?'Progress is saved when you choose Save draft.':'Changes are saved when you choose Save changes.';
  el('manualToggle').hidden=false;
  updateComposer();
}
function revealInvalidControl(control){
  for(let parent=control.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
  control.focus();control.reportValidity();
}
el('orderForm').oninput=()=>{el('formError').hidden=true;updateComposer();};
el('orderForm').onchange=updateComposer;
for(const prefix of ['buyer','notify'])el(prefix+'Toggle').onclick=()=>{
  openPartyEditor(prefix,el(prefix+'Editor').hidden);
  if(!el(prefix+'Editor').hidden)el(prefix+'_primary').focus();
};
function message(text,error=false){
  if(window.skuFeedback){el('message').textContent='';window.skuFeedback.show(text,error);return;}
  el('message').textContent=text;el('message').className=error?'error':'';
}
async function api(url,options={}) {
  const finish=window.skuFeedback?.startRequest(url,options);
  try{
  const response=await fetch(url,options);const data=await response.json();
  if(!response.ok){
    if([401,403,404].includes(response.status)){el('editor').hidden=true;el('detail').hidden=true;}
    const error=new Error(data.error||'Unable to complete request.');error.details=data;throw error;
  }
  return data;
  }finally{finish?.();}
}
const json = (method,data) => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function formattedAmount(value){
  const [whole,decimal='']=String(value??'0').split('.');
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+'.'+decimal.padEnd(2,'0');
}
let discountChoices=[];
function updateDiscountSelection(){
  const selected=discountChoices.filter(input=>input.checked).length;
  el('discountSelectionCount').textContent=selected?`${selected} of ${discountChoices.length} items selected`:
    el('discountScope').value==='single'?'Select one item to discount.':'Select the items you want to discount.';
}
function discountControls(){
  const amount=el('discountType').value==='amount',total=el('discountScope').value==='total';
  el('discountValueLabel').textContent=amount?`Discount (${current.order.currency}${total?'':' per SKU line'})`:'Discount (%)';
  el('discountValue').max=amount?'999999999.99':'100';
  el('discountSkus').hidden=['all','total'].includes(el('discountScope').value);
  el('discountHint').textContent=total?'Deducted once from the goods subtotal, before shipping and GST.':amount?'The amount is in order currency and applies once per selected SKU line, before shipping and GST.':'Percentage applies to each selected SKU line, before shipping and GST.';
  for(const input of discountChoices)input.type=el('discountScope').value==='single'?'radio':'checkbox';
  el('discountSkuLegend').textContent=el('discountScope').value==='single'?'Choose one item':'Choose items';
  updateDiscountSelection();
}
el('discountType').onchange=discountControls;
el('discountScope').onchange=()=>{for(const input of discountChoices)input.checked=false;discountControls();};
el('giveDiscount').onclick=()=>{
  const discount=current.order.discount;
  el('discountType').value=discount?.type||'percent';el('discountScope').value=discount?.scope||'all';
  el('discountValue').value=discount?.value||'';el('discountShow').checked=discount?.show_on_pi??true;
  el('discountSkuChoices').replaceChildren();discountChoices=[];
  for(const line of current.lines){
    const label=document.createElement('label'),input=document.createElement('input');input.name='discountSku';input.value=String(line.id);input.checked=Boolean(discount?.line_ids.includes(line.id));
    label.className='discount-sku-card';input.onchange=updateDiscountSelection;
    const details=document.createElement('span');details.className='discount-sku-details';
    const sku=document.createElement('strong');sku.textContent=line.sku;
    const description=document.createElement('small');description.textContent=line.description||'Order item';details.append(sku,description);
    const amount=document.createElement('span');amount.className='discount-sku-amount';
    const caption=document.createElement('small');caption.textContent='Line total';
    const price=document.createElement('strong');price.textContent=`${line.currency} ${formattedAmount(line.line_total)}`;
    amount.append(caption,price);label.append(input,details,amount);el('discountSkuChoices').append(label);discountChoices.push(input);
  }
  discountControls();el('discountError').hidden=true;el('removeDiscount').hidden=!discount;el('discountForm').hidden=false;el('giveDiscount').setAttribute('aria-expanded','true');el('discountValue').focus();
};
el('cancelDiscount').onclick=()=>{el('discountForm').hidden=true;el('giveDiscount').setAttribute('aria-expanded','false');};
async function persistDiscount(remove=false){
  el('applyDiscount').disabled=true;el('removeDiscount').disabled=true;
  try{
    const scope=el('discountScope').value;
    const data={type:el('discountType').value,value:el('discountValue').value,scope,line_ids:['all','total'].includes(scope)?[]:discountChoices.filter(input=>input.checked).map(input=>Number(input.value)),show_on_pi:el('discountShow').checked};
    await api(`/api/orders/${current.order.id}/discount`,remove?{method:'DELETE'}:json('PUT',data));
    await showDetails(current.order.id);message(remove?'Discount removed.':'Discount saved. PI amounts will include this discount.');
  }catch(error){el('discountError').textContent=error.message;el('discountError').hidden=false;}
  finally{el('applyDiscount').disabled=false;el('removeDiscount').disabled=false;}
}
el('discountForm').onsubmit=event=>{event.preventDefault();persistDiscount();};
el('removeDiscount').onclick=()=>persistDiscount(true);
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
async function deleteOrder(order){
  if(!window.confirm(`Are you sure you want to delete order ${order.reference}? The order will be removed from active lists. Its history and who deleted it will be retained.`))return;
  await api(`/api/orders/${order.id}`,{method:'DELETE'});
  detailVersion++;formVersion++;current=null;invoicePreview.reset();el('detail').hidden=true;el('editor').hidden=true;
  await load();message(`Order ${order.reference} deleted. Deletion recorded in the order deletion log.`);
  if(params.get('embedded')==='1')window.parent.postMessage({type:'amt-order-close'},location.origin);
}
function addressText(address){return addressFields.map(key=>address?.[key]).filter(Boolean).join('\n')||'Not provided';}
function formatPartyBlock(party={},address={}){
  const lines=[party.name,...addressFields.filter(key=>key!=='country').map(key=>address?.[key])].filter(Boolean);
  if(address?.country)lines.push('Country: '+address.country);
  lines.push('Tel/Phone: '+(party.phone||''),'PIC: '+(party.pic||''),'Email: '+(party.email||''));
  if(party.gst_number)lines.push('GST: '+party.gst_number);
  return lines.join('\n');
}
function showPartyFields(prefix){
  if(prefix!=='consignee'){el(prefix+'_text').value=window.orderLocations.withGst(el(prefix+'_text').value,'');el(prefix+'_primary').value=el(prefix+'_text').value;return;}
  const [primary,secondary]=window.orderLocations.partyParts(el(prefix+'_text').value,el('destination').value);
  el(prefix+'_primary').value=primary;el(prefix+'_details').value=secondary;
}
function syncConsignee(){for(const prefix of ['buyer','notify'])if(el(prefix+'_same').checked){el(prefix+'_text').value=window.orderLocations.addressOnly(el('consignee_text').value,el('destination').value);showPartyFields(prefix);}updateComposer();}
for(const prefix of ['consignee','buyer','notify']){
  const changed=()=>{
    el(prefix+'_text').value=prefix==='consignee'?window.orderLocations.joinParty(el(prefix+'_primary').value,el(prefix+'_details').value):el(prefix+'_primary').value;
    el(prefix+'_text').oninput();
  };
  el(prefix+'_primary').oninput=changed;if(prefix==='consignee')el(prefix+'_details').oninput=changed;
}
function refreshConsigneeGst(){
  el('consigneeGstField').hidden=el('destination').value.trim().toUpperCase()!=='INDIA';
  el('consigneeGst').value=window.orderLocations.gstNumber(el('consignee_text').value);
}
function setIndiaCurrency(){if(el('destination').value.trim().toUpperCase()==='INDIA'&&el('currency').value!=='INR'){el('currency').value='INR';initialDrafts.currencyChanged();}}
el('destination').oninput=()=>{setIndiaCurrency();el('consigneeGstField').hidden=el('destination').value.trim().toUpperCase()!=='INDIA';};
el('destination').onchange=()=>{
  el('destination').value=el('destination').value.trim().toUpperCase();setIndiaCurrency();
  el('consignee_text').value=window.orderLocations.countryBlock(el('consignee_text').value,el('destination').value);
  showPartyFields('consignee');
  syncConsignee();refreshConsigneeGst();
};
el('consigneeGst').oninput=()=>{
  el('consignee_text').value=window.orderLocations.withGst(el('consignee_text').value,el('consigneeGst').value);
  showPartyFields('consignee');syncConsignee();
};
for(const prefix of ['buyer','notify']){
  el(prefix+'_text').oninput=()=>{el(prefix+'_same').checked=el(prefix+'_text').value===window.orderLocations.addressOnly(el('consignee_text').value,el('destination').value);refreshConsigneeGst();updateComposer();};
  el(prefix+'_same').onchange=()=>{if(el(prefix+'_same').checked)el(prefix+'_text').value=window.orderLocations.addressOnly(el('consignee_text').value,el('destination').value);showPartyFields(prefix);refreshConsigneeGst();openPartyEditor(prefix,!el(prefix+'_same').checked);updateComposer();if(!el(prefix+'_same').checked)el(prefix+'_primary').focus();};
}
el('consignee_text').oninput=()=>{syncConsignee();refreshConsigneeGst();};
const initialDrafts=window.createSkuDraftEditor(el('initialDrafts'),()=>({client_id:Number(clientScope)}),()=>el('currency').value,null,true);
const lineDrafts=window.createSkuDraftEditor(el('lineDrafts'),()=>({client_id:current.order.client_id}),()=>current.order.currency,async lines=>{
  await api(`/api/orders/${current.order.id}/lines/bulk`,json('POST',{lines}));await showDetails(current.order.id);
},true,()=>current?.lines||[]);
el('currency').onchange=()=>{setIndiaCurrency();initialDrafts.currencyChanged();};


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
  el('generatePi').disabled=dirty||savingCommercial;
  el('saveItemDetails').hidden=!current.order.can_edit;el('saveItemDetails').disabled=!dirty||savingCommercial;
  el('completeItemDetails').hidden=!current.order.can_edit||!missing.length;
  el('piReadiness').className='pi-readiness'+(dirty||missing.length||empty||legacy?' needs-attention':' is-ready');
  el('readinessTitle').textContent=dirty?'Save your item changes':empty?'Add items to this order':missing.length?`${missing.length} item${missing.length===1?' needs':'s need'} PI details`:legacy?'Review historical quantities':'Item details are complete';
  el('readinessHint').textContent=dirty?'Save item details below before generating your PI.':empty?'You can add SKU lines, quantities and agreed prices, or generate an invoice using the PI and purchase order numbers.':missing.length?`Optional: complete HSN code and item condition in the highlighted fields (${missing.slice(0,3).map(line=>line.sku).join(', ')}${missing.length>3?' and '+(missing.length-3)+' more':''}).`:legacy?'Historical quantities are available to review below.':'Choose the invoice currency below. Amounts use your saved order prices and the quotation tool exchange rate.';
  el('itemDetailsHint').textContent=dirty?'You have unsaved item details.':current.shared_hsn_code?'HSN code is shared across all SKUs and managed by TLs/admins in Configuration. Review each item condition before saving.':'TLs/admins can set a shared HSN code in Configuration. Only PI number and purchase order number are required for generation.';
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
    if(order.can_delete_order)actions.append(action('Delete',()=>deleteOrder(order),true));
    el('orders').append(row);
  });
  if(!data.orders.length){const row=document.createElement('tr');const td=cell(row,'No orders match your filters.');td.colSpan=8;el('orders').append(row);}
}

async function prepareClient(clientId,delivery=null,version=formVersion) {
  await window.orderLocations.ready;
  const result=await api(`/api/leads/${clientId}`);if(version!==formVersion)return false;
  clientData=result;const client=result.lead;
  const saved=client.shipping_address?.line1?client.shipping_address:client.billing_address||{};
  const contact=client.contact_persons?.[0]||{};
  const base={name:client.company||client.name,email:client.email||client.emails?.[0]||contact.email,
    phone:client.phone||client.phones?.[0]||contact.phone,pic:contact.name};
  const defaults=formatPartyBlock(base,saved);
  let consignee=delivery?.consignee_text??(delivery?.consignee?.name?
    formatPartyBlock(delivery.consignee,delivery.shipping_address):defaults);
  consignee=window.orderLocations.phoneBlock(consignee,delivery?el('destination').value:saved.country||'');
  el('consignee_text').value=window.orderLocations.withGst(consignee,window.orderLocations.gstNumber(consignee));
  for(const [prefix,key,party,address]of [
    ['buyer','buyer_text',delivery?.buyer,delivery?.billing_address],
    ['notify','notify_text',delivery?.notify_party,delivery?.notify_party?.address],
  ]){
    let value=delivery?.[key]??(party?.name?formatPartyBlock(party,address):window.orderLocations.addressOnly(consignee,el('destination').value));
    if(value===consignee||(window.orderLocations.addressOnly(value)===window.orderLocations.addressOnly(consignee,el('destination').value)&&
      !/^\s*(?:GST(?:IN|\s*(?:No\.?|Number))?|Tel(?:\/Phone)?|Telephone|Phone|PIC|E-?mail)\s*:/im.test(value)))value=window.orderLocations.addressOnly(value);
    el(prefix+'_text').value=value;el(prefix+'_same').checked=value===window.orderLocations.addressOnly(consignee,el('destination').value);
  }
  for(const prefix of ['consignee','buyer','notify'])showPartyFields(prefix);
  if(!delivery)el('destination').value=saved.country||'';
  setIndiaCurrency();refreshConsigneeGst();
  return true;
}
async function createOrder() {
  if(!clientScope)throw new Error('Open a client in Clients & Orders to add an order.');
  const version=++formVersion;editing=null;el('orderForm').reset();initialDrafts.reset();
  updateOrderStatusUI(null);
  el('initialDrafts').hidden=true;el('initialLines').hidden=false;
  el('formTitle').textContent='New order';el('referenceHint').textContent='Your order reference will be created when you save.';
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(part=>[part.type,part.value]));
  el('order_date').value=`${parts.year}-${parts.month}-${parts.day}`;
  el('shipping_charges').value='0.00';
  el('delivery_terms').value='DAP';el('delivery_time').value='4 to 6 days';el('dispatch_method').value='DHL/Fedex/Aramex';
  el('pi_reference').value='';el('pi_reference').readOnly=false;
  const piDefaults=await api('/api/orders/pi-defaults');
  if(version!==formVersion)return;
  el('pi_reference').value=piDefaults.pi_prefix?piDefaults.pi_prefix+'/':'';
  if(!await prepareClient(Number(clientScope),null,version))return;
  if(!clientData.lead.can_edit||!clientData.lead.is_active)throw new Error('Choose an editable, active client.');
  el('editor').hidden=false;el('detail').hidden=true;resetComposer();el('editor').scrollIntoView({behavior:'smooth'});
}
async function editOrder(id) {
  const version=++formVersion;
  const data=await api(`/api/orders/${id}`);if(!data.order.can_edit)throw new Error('Client access is read-only.');
  if((clientScope&&String(data.order.client_id)!==clientScope)||(enquiryScope&&String(data.order.enquiry_id)!==enquiryScope))throw new Error('Order does not belong to the selected record.');
  if(version!==formVersion)return;
  updateOrderStatusUI(data.order);
  editing=id;initialDrafts.reset();el('initialLines').hidden=true;
  headerFields.forEach(key=>{el(key).value=data.order[key];});if(!await prepareClient(data.order.client_id,data.delivery,version))return;
  if(!data.order.pi_reference&&data.pi_defaults?.pi_prefix&&!data.invoices?.length)el('pi_reference').value=data.pi_defaults.pi_prefix+'/';
  el('pi_reference').readOnly=Boolean(data.invoices?.some(invoice=>invoice.workbook_format==='xlsm'));
  el('detail').hidden=true;el('formTitle').textContent='Edit order';el('referenceHint').textContent=data.order.reference;el('editor').hidden=false;resetComposer();el('editor').scrollIntoView({behavior:'smooth'});
}
el('orderForm').onsubmit=async event=>{
  event.preventDefault();
  const invalid=el('orderForm').querySelector?.('input:invalid,textarea:invalid,select:invalid');
  if(invalid){revealInvalidControl(invalid);return;}
  el('save').disabled=true;el('save').textContent='Saving…';el('formError').hidden=true;
  try {
    if(!clientData)throw new Error('Choose a client before saving.');
    el('destination').value=el('destination').value.trim().toUpperCase();setIndiaCurrency();
    el('consignee_text').value=window.orderLocations.countryBlock(el('consignee_text').value,el('destination').value);
    el('consignee_text').value=window.orderLocations.withGst(el('consignee_text').value,window.orderLocations.gstNumber(el('consignee_text').value));
    syncConsignee();
    const data=Object.fromEntries(headerFields.map(key=>[key,el(key).value]));
    data.delivery={consignee_text:el('consignee_text').value,buyer_text:el('buyer_text').value,
      notify_text:el('notify_text').value};
    if(editing===null){data.client_id=Number(clientScope);data.lines=el('initialDrafts').hidden?[]:initialDrafts.values();}
    const result=await api(editing===null?'/api/orders':`/api/orders/${editing}`,json(editing===null?'POST':'PUT',data));
    el('editor').hidden=true;await load();await showDetails(result.order.id);message('Order saved.');
  }catch(error){if(window.skuFeedback){el('formError').hidden=true;}else{el('formError').textContent=error.message;el('formError').hidden=false;el('formError').focus();}message(error.message,true);}finally{el('save').disabled=false;el('save').textContent=editing===null?'Save draft':'Save changes';}
};

async function showDetails(id) {
  const version=++detailVersion;const data=await api(`/api/orders/${id}`);if(version!==detailVersion)return;
  if((clientScope&&String(data.order.client_id)!==clientScope)||(enquiryScope&&String(data.order.enquiry_id)!==enquiryScope))throw new Error('Order does not belong to the selected record.');
  current=data;commercialInputs=[];editingLine=null;el('editor').hidden=true;el('piError').hidden=true;el('lineForm').hidden=true;el('lineDrafts').hidden=true;el('copyPanel').hidden=true;lineDrafts.reset();
  const order=data.order;
  updateOrderStatusUI(order);
  el('discountForm').hidden=true;el('giveDiscount').hidden=!order.can_edit;el('giveDiscount').disabled=!data.lines.length&&!order.discount;el('giveDiscount').setAttribute('aria-expanded','false');
  const discount=order.discount;
  el('giveDiscount').textContent=discount?'Edit discount':'Give discount';
  const target=discount?.scope==='total'?'order total':discount?.scope==='all'?'all SKUs':data.lines.filter(line=>discount?.line_ids.includes(line.id)).map(line=>line.sku).join(', ');
  el('discountSummary').textContent=discount?`Discount: ${discount.type==='percent'?discount.value+'%':order.currency+' '+discount.value+(discount.scope==='total'?'':' per SKU line')} on ${target}. ${discount.show_on_pi?'Shown in PI.':'Hidden in PI; reduced amounts still apply.'}`:'';
  el('conversionHint').textContent='Choose the currency for this proforma invoice.';
  el('piForm').hidden=!order.can_edit||order.status==='cancelled';el('piCurrency').value='';
  el('bulkDescriptionField').hidden=data.lines.length<=4;
  el('bulkDescription').required=data.lines.length>4;el('bulkDescription').value='';
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
  el('detailAccess').textContent=`${order.status==='completed'?'Complete':order.status==='draft'?'Pending':order.status} / ${order.currency} / ${order.can_edit?'Editable':'Read only'}`;
  el('editOrder').hidden=!order.can_edit;el('addLine').hidden=!order.can_edit;
  el('deleteOrder').hidden=!order.can_delete_order;
  el('deleteOrder').onclick=()=>deleteOrder(order).catch(error=>message(error.message,true));
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
    const product=cell(row,'');product.setAttribute('data-label','Item');const sku=document.createElement('strong');sku.className='order-item-sku';sku.textContent=line.sku;
    const description=document.createElement('span');description.className='item-description';description.textContent=line.description;product.append(sku,description);
    if(line.source_enquiry_line_id){const source=document.createElement('small');source.textContent=`Imported enquiry item #${line.source_enquiry_line_id}`;product.append(source);}
    const quantity=cell(row,'');quantity.setAttribute('data-label','Quantity');
    const badge=document.createElement('span');badge.className='order-item-quantity';badge.textContent=line.quantity+' '+(line.uom||'PCs');quantity.append(badge);
    for(const [label,value]of [['Unit price',line.unit_price],['Amount',line.line_total]]){
      const td=cell(row,'');td.setAttribute('data-label',label);td.className='order-item-money';
      const code=document.createElement('span');code.className='order-item-currency';code.textContent=line.currency+' ';
      const number=document.createElement('strong');number.textContent=formattedAmount(value);td.append(code,number);
    }
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
    const actions=cell(row,'');actions.className='order-item-row-actions';actions.setAttribute('data-label','Actions');
    if(order.can_edit)actions.append(action('Edit',async()=>{if(commercialDirty())throw new Error('Save item details before opening the full line editor.');const latest=(await api(`/api/orders/${id}/lines/${line.id}`)).line;if(!latest.is_active)throw new Error('This line was removed.');editingLine=line.id;for(const [key,value] of Object.entries({lineSku:latest.sku,lineDescription:latest.description,lineQuantity:latest.quantity,linePrice:latest.unit_price,lineCurrency:latest.currency,lineHsn:current.shared_hsn_code||latest.hsn_code||'',lineCondition:latest.item_condition||'',lineUom:latest.uom||'PCs'}))el(key).value=value;el('lineHsn').readOnly=Boolean(current.shared_hsn_code);el('lineForm').hidden=false;el('lineForm').scrollIntoView({behavior:'smooth'});}));
    if(order.can_delete)actions.append(action('Delete',async()=>{if(!window.confirm(`Delete SKU ${line.sku}? History will be retained.`))return;await api(`/api/orders/${id}/lines/${line.id}`,{method:'DELETE'});await showDetails(id);},true));
    el('lineRows').append(row);
  });
  if(!data.lines.length){const row=document.createElement('tr');cell(row,'No active order items.').colSpan=7;el('lineRows').append(row);}
  el('totals').replaceChildren();Object.entries(data.subtotals).forEach(([code,total])=>{
    const card=document.createElement('div');card.className='order-subtotal-card';
    const label=document.createElement('span');label.textContent=order.discount?'Subtotal before discount':'Goods subtotal';
    const amount=document.createElement('strong');amount.textContent=`${code} ${formattedAmount(total)}`;
    card.append(label,amount);el('totals').append(card);
  });
  el('deliveryHistory').replaceChildren();data.delivery_history.forEach(item=>{const p=document.createElement('p');p.textContent=`${new Date(item.recorded_at).toLocaleString()} / version ${item.id}\nShipping: ${addressText(item.shipping_address)}\nBilling: ${addressText(item.billing_address)}`;el('deliveryHistory').append(p);});
  el('revisions').replaceChildren();data.revisions.forEach(item=>{const p=document.createElement('p');p.textContent=`${new Date(item.created_at).toLocaleString()} / ${item.action.replaceAll('_',' ')} / actor #${item.actor_user_id}`;el('revisions').append(p);});
  selectOrderTab('items');updatePiReadiness();
  el('detail').hidden=false;el('detail').scrollIntoView({behavior:'smooth'});
}
el('lineForm').onsubmit=async event=>{event.preventDefault();const button=el('lineForm').querySelector?.('button[type="submit"]');if(button?.disabled)return;if(button)button.disabled=true;try{await api(`/api/orders/${current.order.id}/lines/${editingLine}`,json('PUT',{sku:el('lineSku').value,description:el('lineDescription').value,quantity:el('lineQuantity').value,unit_price:el('linePrice').value,currency:el('lineCurrency').value,hsn_code:el('lineHsn').value,item_condition:el('lineCondition').value,uom:el('lineUom').value}));await showDetails(current.order.id);message('Order line saved.');}catch(error){message(error.message,true);}finally{if(button)button.disabled=false;}};
el('addLine').onclick=()=>{lineDrafts.reset();el('lineDrafts').hidden=!el('lineDrafts').hidden;};
el('cancelLine').onclick=()=>{el('lineForm').hidden=true;};
el('manualToggle').onclick=()=>{el('initialDrafts').hidden=false;el('manualToggle').hidden=true;};

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
  el('conversionHint').textContent=convert?'The quotation tool exchange rate will be applied automatically.':'Amounts already in the selected currency use their saved prices.';
};
function appendInvoice(invoice,id){
  const row=document.createElement('div');row.className='pi-download-row';
  const title=document.createElement('span');title.textContent=`${invoice.reference} / ${invoice.currency} / ${(invoice.created_at||'').slice(0,10)}`;row.append(title);
  for(const format of [invoice.workbook_format||'xlsm',...(invoice.has_pdf?['pdf']:[])]){const link=document.createElement('a');link.textContent='Download '+format.toUpperCase();link.href=`/api/orders/${id}/invoices/${invoice.id}/download?format=${format}`;link.onclick=async event=>{event.preventDefault();try{await window.downloadPiFile(link.href,invoice.reference.replace(/[<>:"/\\|?*]/g,'-')+'.'+format);}catch(error){message(error.message,true);}};row.append(link);}
  if(current?.order.can_edit&&current.order.can_delete_order){
    const remove=document.createElement('button');remove.type='button';remove.className='pi-remove-button';remove.textContent='\u2212';remove.title='Remove PI';remove.setAttribute('aria-label','Remove PI '+invoice.reference);
    remove.onclick=async()=>{
      if(!window.confirm(`Remove PI ${invoice.reference} from the invoice records?`))return;
      remove.disabled=true;
      try{
        await api(`/api/orders/${id}/invoices/${invoice.id}`,{method:'DELETE'});
        row.remove();if(current?.order.id===id)current.invoices=(current.invoices||[]).filter(item=>item.id!==invoice.id);
        invoicePreview.removeIssued?.(invoice.id);
        message('PI removed.');
      }catch(error){remove.disabled=false;message(error.message,true);}
    };
    row.append(remove);
  }
  el('invoiceList').append(row);
}
const invoicePreview=window.createPiPreview(el('piPreview'),api,json,async result=>{
  appendInvoice({...result,currency:el('piCurrency').value,workbook_format:'xlsx',has_pdf:true},current.order.id);
  current.order.status=result.order_status||'completed';updateOrderStatusUI(current.order);
  el('detailAccess').textContent=`${current.order.status==='completed'?'Complete':'Pending'} / ${current.order.currency} / Editable`;
  await load();message(`PI ${result.reference} generated. ${current.order.status==='completed'?'Order marked complete.':'Order remains pending.'} Excel and PDF are ready.`);
},doc=>{
  if(current)current.order.pi_reference=doc.reference;
  el('pi_reference').value=doc.reference;
  if(doc.pi_format==='bulk')el('bulkDescription').value=doc.bulk_description;
});
el('piForm').onsubmit=async event=>{
  event.preventDefault();
  if(commercialDirty()){updatePiReadiness();el('completeItemDetails').onclick();return;}
  el('piError').hidden=true;el('generatePi').disabled=true;
  try{
    const data={currency:el('piCurrency').value};
    if(current.lines.length>4)data.bulk_description=el('bulkDescription').value;
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
  await load();if(params.get('order_id')){if(params.get('edit')==='1')await editOrder(Number(params.get('order_id')));else await showDetails(Number(params.get('order_id')));}if(params.get('new')==='1')await createOrder();
}catch(error){message(error.message,true);}})();

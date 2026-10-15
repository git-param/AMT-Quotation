const el = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
const clientScope = params.get('client_id');
const enquiryScope = params.get('enquiry_id');
if(params.get('embedded')==='1')document.body.classList.add('embedded');
const headerFields = ['order_date','pi_date','po_reference','pi_reference','payment_terms','delivery_terms','delivery_time','dispatch_method','notes','status','currency','destination','shipping_charges'];
const addressFields = ['line1','line2','city','state','postal_code','country'];
const partyFields = ['name','pic','email','phone','gst_number'];
let page=1, pages=0;
let current=null, editing=null, editingLine=null, clientData=null;
let detailVersion=0;
let formVersion=0;
function message(text,error=false){el('message').textContent=text;el('message').className=error?'error':'';}
async function api(url,options={}) {
  const response=await fetch(url,options);const data=await response.json();
  if(!response.ok){if([401,403,404].includes(response.status)){el('editor').hidden=true;el('detail').hidden=true;}throw new Error(data.error||'Unable to complete request.');}
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
function addressValue(prefix){return Object.fromEntries(addressFields.map(key=>[key,el(`${prefix}_${key}`).value.trim()]).filter(([,value])=>value));}
function setAddress(prefix,address){addressFields.forEach(key=>{el(`${prefix}_${key}`).value=address?.[key]||'';});}
function partyValue(prefix){return Object.fromEntries(partyFields.map(key=>[key,el(`${prefix}_${key}`).value]));}
function setParty(prefix,party){partyFields.forEach(key=>{el(`${prefix}_${key}`).value=party?.[key]||'';});}
function addressText(address){return addressFields.map(key=>address?.[key]).filter(Boolean).join('\n')||'Not provided';}
function partyText(party){const labels={name:'',pic:'PIC: ',email:'Email: ',phone:'Phone: ',gst_number:'GST: '};return partyFields.filter(key=>party?.[key]).map(key=>labels[key]+party[key]).join('\n')||'Not provided';}
const initialDrafts=window.createSkuDraftEditor(el('initialDrafts'),()=>({client_id:Number(clientScope)}),()=>el('currency').value,null,true);
const lineDrafts=window.createSkuDraftEditor(el('lineDrafts'),()=>({client_id:current.order.client_id}),()=>current.order.currency,async lines=>{
  await api(`/api/orders/${current.order.id}/lines/bulk`,json('POST',{lines}));await showDetails(current.order.id);
},true);
el('currency').onchange=()=>initialDrafts.currencyChanged();

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

function savedAddressChanged() {
  const choice=el('savedAddress').value;
  const custom=choice==='custom';
  if(!custom){const [id,kind]=choice.split(':');const version=clientData.address_history.find(item=>String(item.id)===id);setAddress('shipping',kind==='billing'?version.billing_address:version.default_shipping_address);}
  addressFields.forEach(key=>{const field=el('shipping_'+key);field.disabled=!custom;field.required=false;});
}
async function prepareClient(clientId,delivery=null,version=formVersion) {
  const result=await api(`/api/leads/${clientId}`);if(version!==formVersion)return false;
  clientData=result;
  const client=clientData.lead;
  el('savedAddress').replaceChildren(new Option('Different address for this order','custom'));
  clientData.address_history.forEach(version=>{
    for(const kind of ['billing','shipping']) {
      const address=kind==='billing'?version.billing_address:version.default_shipping_address;
      if(address.line1)el('savedAddress').add(new Option(`${kind==='billing'?'Billing':'Default shipping'} / ${address.line1} / ${new Date(version.recorded_at).toLocaleDateString()}`,`${version.id}:${kind}`));
    }
  });
  setAddress('billing',delivery?.billing_address||client.billing_address);
  setAddress('shipping',delivery?.shipping_address||client.shipping_address);
  setParty('consignee',delivery?.consignee||{name:client.company||client.name,email:client.email,phone:client.phone});
  setParty('buyer',delivery?.buyer);setParty('notify',delivery?.notify_party);el('instructions').value=delivery?.instructions||'';
  if(delivery?.saved_address_id)el('savedAddress').value=`${delivery.saved_address_id}:${delivery.saved_address_kind}`;
  else if(!delivery){const shipping=[...el('savedAddress').options].find(option=>option.value.endsWith(':shipping'));if(shipping)el('savedAddress').value=shipping.value;}
  savedAddressChanged();
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
  el('formTitle').textContent='Edit order';el('referenceHint').textContent=data.order.reference;el('editor').hidden=false;el('editor').scrollIntoView({behavior:'smooth'});
}
el('orderForm').onsubmit=async event=>{
  event.preventDefault();el('save').disabled=true;
  try {
    if(!clientData)throw new Error('Choose a client before saving.');
    const data=Object.fromEntries(headerFields.map(key=>[key,el(key).value]));
    data.delivery={billing_address:addressValue('billing'),consignee:partyValue('consignee'),buyer:partyValue('buyer'),notify_party:partyValue('notify'),instructions:el('instructions').value};
    const addressChoice=el('savedAddress').value;
    if(addressChoice==='custom')data.delivery.shipping_address=addressValue('shipping');
    else {const [id,kind]=addressChoice.split(':');data.delivery.saved_address_id=Number(id);data.delivery.saved_address_kind=kind;}
    if(editing===null){data.client_id=Number(clientScope);data.lines=el('initialDrafts').hidden?[]:initialDrafts.values();}
    const result=await api(editing===null?'/api/orders':`/api/orders/${editing}`,json(editing===null?'POST':'PUT',data));
    el('editor').hidden=true;await load();await showDetails(result.order.id);message('Order saved.');
  }catch(error){message(error.message,true);}finally{el('save').disabled=false;}
};

async function showDetails(id) {
  const version=++detailVersion;const data=await api(`/api/orders/${id}`);if(version!==detailVersion)return;
  if((clientScope&&String(data.order.client_id)!==clientScope)||(enquiryScope&&String(data.order.enquiry_id)!==enquiryScope))throw new Error('Order does not belong to the selected record.');
  current=data;editingLine=null;el('lineForm').hidden=true;el('lineDrafts').hidden=true;el('copyPanel').hidden=true;lineDrafts.reset();
  const order=data.order;
  el('piForm').hidden=!order.can_edit||order.status==='cancelled';el('piCurrency').value='';el('piRate').value='';el('rateField').hidden=true;
  el('invoiceList').replaceChildren();
  for(const invoice of data.invoices||[]){const link=document.createElement('a');link.textContent=`${invoice.reference} ? ${invoice.currency} ? ${invoice.created_at.slice(0,10)} ? Download PI`;link.href=`/api/orders/${id}/invoices/${invoice.id}/download`;el('invoiceList').append(link);}
  if(data.legacy_lines_requiring_review?.length)message('Historical fractional quantities need review before PI generation. Original lines remain preserved in the enquiry history.',true);
  el('detailTitle').textContent=order.reference;
  el('detailAccess').textContent=`${order.status} / ${order.currency} / ${order.can_edit?'Editable':'Read only'}`;
  el('editOrder').hidden=!order.can_edit;el('addLine').hidden=!order.can_edit;
  el('recordLinks').replaceChildren();
  for(const [label,url] of [[`Client: ${order.client_name}`,`/clients-orders?client_id=${order.client_id}`]]){const link=document.createElement('a');link.textContent=label;link.href=url;el('recordLinks').append(link);}
  el('detailBody').replaceChildren();
  const section=(label,value)=>{const block=document.createElement('section');const title=document.createElement('h3');title.textContent=label;const text=document.createElement('p');text.textContent=value||'Not provided';block.append(title,text);el('detailBody').append(block);};
  section('Order and PO / PI references',[order.order_date,order.po_reference&&`PO: ${order.po_reference}`,order.pi_reference&&`PI: ${order.pi_reference}`,order.pi_date&&`PI date: ${order.pi_date}`].filter(Boolean).join('\n'));
  section('Payment and delivery terms',[order.payment_terms,order.delivery_terms,order.delivery_time,order.dispatch_method].filter(Boolean).join('\n'));
  section('Ownership and creation',`${order.owner_name} (client owner)\n${order.creator_name} (order creator)\n${new Date(order.created_at).toLocaleString()}`);
  section('Destination / shipping',[order.destination,`${order.currency} ${order.shipping_charges}`].filter(Boolean).join(' / '));
  const destination=data.delivery||{};section('Order billing address',addressText(destination.billing_address));section('Order shipping address',addressText(destination.shipping_address));
  section('Consignee',partyText(destination.consignee));section('Buyer / billing party',partyText(destination.buyer));section('Notify party',partyText(destination.notify_party));section('Delivery instructions',destination.instructions);section('Notes',order.notes);
  el('lineRows').replaceChildren();
  data.lines.forEach(line=>{
    const row=document.createElement('tr');[line.sku,[line.description,line.hsn_code,line.item_condition].filter(Boolean).join(' / '),`${line.quantity} ${line.uom||'PCs'}`,line.unit_price,line.currency,line.line_total,line.source_enquiry_line_id?`Enquiry line #${line.source_enquiry_line_id}`:'Manual'].forEach(value=>cell(row,value));
    const actions=cell(row,'');
    if(order.can_edit)actions.append(action('Edit',async()=>{const latest=(await api(`/api/orders/${id}/lines/${line.id}`)).line;if(!latest.is_active)throw new Error('This line was removed.');editingLine=line.id;for(const [key,value] of Object.entries({lineSku:latest.sku,lineDescription:latest.description,lineQuantity:latest.quantity,linePrice:latest.unit_price,lineCurrency:latest.currency,lineHsn:latest.hsn_code||'',lineCondition:latest.item_condition||'',lineUom:latest.uom||'PCs'}))el(key).value=value;el('lineForm').hidden=false;el('lineForm').scrollIntoView({behavior:'smooth'});}));
    if(order.can_delete)actions.append(action('Delete',async()=>{if(!window.confirm(`Delete SKU ${line.sku}? History will be retained.`))return;await api(`/api/orders/${id}/lines/${line.id}`,{method:'DELETE'});await showDetails(id);},true));
    el('lineRows').append(row);
  });
  if(!data.lines.length){const row=document.createElement('tr');cell(row,'No active order items.').colSpan=8;el('lineRows').append(row);}
  el('totals').replaceChildren();Object.entries(data.subtotals).forEach(([code,total])=>{const label=document.createElement('strong');label.textContent=`${code} subtotal: ${total}`;el('totals').append(label);});
  el('deliveryHistory').replaceChildren();data.delivery_history.forEach(item=>{const p=document.createElement('p');p.textContent=`${new Date(item.recorded_at).toLocaleString()} / version ${item.id}\nShipping: ${addressText(item.shipping_address)}\nBilling: ${addressText(item.billing_address)}`;el('deliveryHistory').append(p);});
  el('revisions').replaceChildren();data.revisions.forEach(item=>{const p=document.createElement('p');p.textContent=`${new Date(item.created_at).toLocaleString()} / ${item.action.replaceAll('_',' ')} / actor #${item.actor_user_id}`;el('revisions').append(p);});
  el('detail').hidden=false;el('detail').scrollIntoView({behavior:'smooth'});
}
el('lineForm').onsubmit=async event=>{event.preventDefault();try{await api(`/api/orders/${current.order.id}/lines/${editingLine}`,json('PUT',{sku:el('lineSku').value,description:el('lineDescription').value,quantity:el('lineQuantity').value,unit_price:el('linePrice').value,currency:el('lineCurrency').value,hsn_code:el('lineHsn').value,item_condition:el('lineCondition').value,uom:el('lineUom').value}));await showDetails(current.order.id);message('Order line saved.');}catch(error){message(error.message,true);}};
el('addLine').onclick=()=>{lineDrafts.reset();el('lineDrafts').hidden=!el('lineDrafts').hidden;};
el('cancelLine').onclick=()=>{el('lineForm').hidden=true;};
el('manualToggle').onclick=()=>{el('initialDrafts').hidden=!el('initialDrafts').hidden;};
el('savedAddress').onchange=savedAddressChanged;

el('newOrder').onclick=()=>createOrder().catch(error=>message(error.message,true));
el('editOrder').onclick=()=>editOrder(current.order.id).catch(error=>message(error.message,true));
el('cancel').onclick=()=>{formVersion++;el('editor').hidden=true;};el('closeDetail').onclick=()=>{detailVersion++;el('detail').hidden=true;};
el('refresh').onclick=()=>load().catch(error=>message(error.message,true));
el('filters').onsubmit=event=>{event.preventDefault();page=1;load().catch(error=>message(error.message,true));};
el('previous').onclick=()=>{if(page>1){page--;load().catch(error=>message(error.message,true));}};
el('next').onclick=()=>{if(page<pages){page++;load().catch(error=>message(error.message,true));}};
el('piCurrency').onchange=()=>{
  const currency=el('piCurrency').value;
  const convert=Boolean(currency)&&[current.order.currency,...current.lines.map(line=>line.currency)].some(code=>code!==currency);
  el('rateField').hidden=!convert;el('piRate').required=convert;
  if(!convert)el('piRate').value='';
  el('conversionHint').textContent=convert?'Enter INR per 1 USD. USD ? INR multiplies; INR ? USD divides. Unit rates round to 2 decimals before multiplying quantities. Shipping is converted separately.':'Amounts already in the selected currency use their saved prices. Company bank details are taken from the template.';
};
el('piForm').onsubmit=async event=>{
  event.preventDefault();el('generatePi').disabled=true;
  try{
    const data={currency:el('piCurrency').value};if(!el('rateField').hidden)data.usd_inr_rate=el('piRate').value;
    const result=await api(`/api/orders/${current.order.id}/invoices`,json('POST',data));
    await showDetails(current.order.id);message(`PI ${result.reference} generated. Download it below.`);
  }catch(error){message(error.message,true);}finally{el('generatePi').disabled=false;}
};
(async()=>{try{
  if(enquiryScope){const e=(await api(`/api/enquiries/${enquiryScope}`)).enquiry;el('context').textContent=`Orders for ${e.reference} / ${e.client_name}`;el('newOrder').hidden=!e.can_edit||!e.client_active;}
  else if(clientScope){const c=(await api(`/api/leads/${clientScope}`)).lead;el('context').textContent=`Orders for ${c.name}`;el('newOrder').hidden=!c.can_edit||!c.is_active;}
  if(!clientScope)el('newOrder').hidden=true;
  await load();if(params.get('order_id'))await showDetails(Number(params.get('order_id')));if(params.get('new')==='1')await createOrder();
}catch(error){message(error.message,true);}})();

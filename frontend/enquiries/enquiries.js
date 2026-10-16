const byId = id => document.getElementById(id);
function enquiryActionButton(action, name) {
  const icons = {
    details: ['View details', 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z'],
    edit: ['Edit', 'm16 3 5 5-12 12-6 1 1-6L16 3Z M13 6l5 5'],
    delete: ['Delete', 'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7'],
  };
  const [label, path] = icons[action];
  const button=document.createElement('button');button.type='button';
  button.className=`btn-sm enquiry-action-icon ${action==='delete'?'btn-del':''}`;
  button.title=label;button.setAttribute('aria-label',`${label}: ${name}`);
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.8','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(key,value);
  const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d',path);svg.append(shape);button.append(svg);
  return button;
}
window.enquiryActionButton=enquiryActionButton;
const query = new URLSearchParams(location.search);
const clientFilter = query.get('client_id');
let scopedClient = null;
let editing = null; let page = 1; let pages = 0; let clientPage = 1; let clientPages = 0;
const fields = ['reference','enquiry_date','subject','description','status'];
function creationScope() {
  const client = byId('client');
  const clientId = Number(client.value);
  if (!Number.isSafeInteger(clientId) || clientId <= 0 || client.selectedOptions[0]?.disabled) {
    client.focus();
    throw new Error('Select an editable client above before looking up SKUs.');
  }
  return {client_id: clientId};
}
const initialSkuEditor=window.createSkuDraftEditor(byId('creationSkus'),creationScope,()=>byId('dealCurrency').value);
byId('dealCurrency').onchange=()=>initialSkuEditor.currencyChanged();
function message(text,error=false) { if(window.skuFeedback){byId('message').textContent='';window.skuFeedback.show(text,error);return;}byId('message').textContent=text; byId('message').className=error?'error':''; }
async function api(path,options={}) {
  const finish=window.skuFeedback?.startRequest(path,options);
  try{
  const response=await fetch(path,options); const data=await response.json();
  if(!response.ok) { if(response.status===401){byId('editor').hidden=true;byId('detail').hidden=true;} throw new Error(data.error||'Unable to complete request.'); }
  return data;
  }finally{finish?.();}
}
function cell(row,value){const td=document.createElement('td');td.textContent=value;row.append(td);}
async function clients() {
  const selected=byId('client').value;
  const data=await api('/api/leads?'+new URLSearchParams({q:byId('clientSearch').value,page:clientPage,page_size:25,sort:'name',direction:'asc'}));
  byId('hdrUser').textContent=data.username;clientPages=data.pages;
  byId('client').replaceChildren(new Option('Choose a client',''));
  data.leads.forEach(c=>{const option=new Option(c.name+(c.can_edit&&c.is_active?'':' (read only / inactive)'),c.id);option.disabled=!c.can_edit||!c.is_active;byId('client').add(option);});
  if([...byId('client').options].some(o=>o.value===selected))byId('client').value=selected;
  byId('clientPage').textContent=`Client page ${clientPage} of ${Math.max(1,clientPages)}`;
  byId('clientPrev').disabled=clientPage<=1;byId('clientNext').disabled=clientPage>=clientPages;
}
async function load(){
  const params=new URLSearchParams({page,page_size:25,q:byId('search').value,status:byId('filterStatus').value,sort:byId('sort').value,direction:byId('direction').value});
  if(clientFilter)params.set('client_id',clientFilter);
  const data=await api('/api/enquiries?'+params);pages=data.pages;
  byId('summary').textContent=`${data.total} enquiries${scopedClient ? ' for ' + scopedClient.name : ''}`;
  byId('pageInfo').textContent=`Page ${page} of ${Math.max(1,pages)}`;
  byId('previous').disabled=page<=1;byId('next').disabled=page>=pages;byId('rows').replaceChildren();
  data.enquiries.forEach(e=>{
    const row=document.createElement('tr');[e.reference,e.client_name,e.enquiry_date,e.subject,e.status,e.creator_name].forEach(v=>cell(row,v));
    const referenceButton=document.createElement('button');referenceButton.type='button';referenceButton.className='enquiry-reference';referenceButton.textContent=e.reference;referenceButton.onclick=()=>details(e.id).catch(error=>message(error.message,true));row.firstElementChild.replaceChildren(referenceButton);
    const actions=document.createElement('td');actions.className='enquiry-row-actions';
    const view=enquiryActionButton('details',e.reference);view.onclick=()=>details(e.id).catch(error=>message(error.message,true));actions.append(view);
    if(e.can_edit){const edit=enquiryActionButton('edit',e.reference);edit.onclick=()=>editEnquiry(e.id).catch(error=>message(error.message,true));actions.append(edit);}
    if(e.can_delete){const remove=enquiryActionButton('delete',e.reference);remove.onclick=()=>deleteEnquiry(e).catch(error=>message(error.message,true));actions.append(remove);}
    row.append(actions);byId('rows').append(row);
  });
  if(!data.enquiries.length){const row=document.createElement('tr');cell(row,'No enquiries match your filters.');row.firstChild.colSpan=7;byId('rows').append(row);}
}
async function details(id){
  const e=(await api(`/api/enquiries/${id}`)).enquiry;
  byId('deleteEnquiry').hidden=!e.can_delete;
  byId('deleteEnquiry').onclick=()=>deleteEnquiry(e).catch(error=>message(error.message,true));
  if(clientFilter && String(e.client_id)!==String(clientFilter))throw new Error('This enquiry does not belong to the selected client.');
  byId('detailTitle').textContent=e.reference;byId('detailBody').replaceChildren();
  byId('detailSubtitle').textContent=[e.client_name,e.client_company].filter(Boolean).join(' / ');
  byId('detailBadges').replaceChildren();
  for(const label of [e.status.replaceAll('_',' '),e.deal_currency||'Currency not set',e.can_edit?'Editable':'Read only']){const badge=document.createElement('span');badge.textContent=label;byId('detailBadges').append(badge);}
  [['Client',e.client_name],['Company',e.client_company],['Enquiry date',e.enquiry_date],['Subject',e.subject],['Description',e.description],['Creator',e.creator_name],['Created',new Date(e.created_at).toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short'})],['Last updated',`${new Date(e.updated_at).toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short'})} / ${e.updated_by_name}`]].forEach(([label,value])=>{
    const block=document.createElement('section'); if(label==='Description'||label==='Subject')block.className='detail-wide';
    const title=document.createElement('h3');title.textContent=label;const text=document.createElement('p');text.textContent=value||'Not provided';block.append(title,text);byId('detailBody').append(block);
  });
  const link=document.createElement('a');link.href=`/leads?client_id=${e.client_id}`;link.textContent='View client details';byId('detailBody').append(link);byId('detail').hidden=false;await window.showEnquiryLines(e);byId('detail').scrollIntoView({behavior:'smooth'});
}
async function deleteEnquiry(enquiry) {
  if (!window.confirm(`Delete enquiry ${enquiry.reference}? Its SKU lines and history will be retained.`)) return;
  await api(`/api/enquiries/${enquiry.id}`, {method:'DELETE'});
  byId('editor').hidden=true;byId('detail').hidden=true;
  await load();message('Enquiry deleted. History retained.');
}
async function createForm(){
  editing=null;byId('form').reset();initialSkuEditor.reset();byId('creationSkus').hidden=false;await clients();byId('client').disabled=false;byId('chooseClient').hidden=false;
  if(clientFilter){const c=(await api(`/api/leads/${clientFilter}`)).lead;if(!c.can_edit||!c.is_active)throw new Error('This client cannot receive a new enquiry.');if(![...byId('client').options].some(o=>Number(o.value)===c.id))byId('client').add(new Option(c.name,c.id));byId('client').value=c.id;byId('client').disabled=true;byId('chooseClient').hidden=true;}
  const dateParts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(p=>[p.type,p.value]));
  byId('enquiry_date').value=`${dateParts.year}-${dateParts.month}-${dateParts.day}`;
  byId('formTitle').textContent='Create enquiry';byId('editor').hidden=false;byId('reference').focus();
}
async function editEnquiry(id){
  const e=(await api(`/api/enquiries/${id}`)).enquiry;if(!e.can_edit)throw new Error('Client access is read-only.');
  editing=id;initialSkuEditor.reset();byId('creationSkus').hidden=true;byId('dealCurrency').value=e.deal_currency||'';fields.forEach(f=>{byId(f).value=e[f];});byId('client').replaceChildren(new Option(e.client_name,e.client_id,true,true));byId('client').disabled=true;byId('chooseClient').hidden=true;byId('formTitle').textContent='Edit enquiry';byId('editor').hidden=false;await details(id);byId('editor').scrollIntoView({behavior:'smooth'});
}
byId('form').onsubmit=async event=>{event.preventDefault();byId('save').disabled=true;try{const data=Object.fromEntries(fields.map(f=>[f,byId(f).value]));data.deal_currency=byId('dealCurrency').value||null;if(editing===null){data.client_id=Number(byId('client').value);data.lines=initialSkuEditor.values();}await api(editing===null?'/api/enquiries':`/api/enquiries/${editing}`,{method:editing===null?'POST':'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});byId('editor').hidden=true;byId('detail').hidden=true;await load();message('Enquiry saved.');}catch(error){message(error.message,true);}finally{byId('save').disabled=false;}};
byId('add').onclick=()=>createForm().catch(error=>message(error.message,true));byId('cancel').onclick=()=>{byId('editor').hidden=true;};byId('closeDetail').onclick=()=>{byId('detail').hidden=true;};
byId('filters').onsubmit=event=>{event.preventDefault();page=1;load().catch(error=>message(error.message,true));};
byId('previous').onclick=()=>{if(page>1){page--;load().catch(error=>message(error.message,true));}};byId('next').onclick=()=>{if(page<pages){page++;load().catch(error=>message(error.message,true));}};
byId('findClient').onclick=()=>{clientPage=1;clients().catch(error=>message(error.message,true));};byId('clientSearch').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();byId('findClient').click();}});byId('clientPrev').onclick=()=>{if(clientPage>1){clientPage--;clients().catch(error=>message(error.message,true));}};byId('clientNext').onclick=()=>{if(clientPage<clientPages){clientPage++;clients().catch(error=>message(error.message,true));}};
(async()=>{try{
  if(clientFilter){
    scopedClient=(await api(`/api/leads/${clientFilter}`)).lead;
    byId('pageTitle').textContent=`Enquiries for ${scopedClient.name}`;
    byId('clientContext').textContent='Showing enquiries for this client only.';
    byId('allEnquiries').hidden=true;
    byId('add').hidden=!scopedClient.can_edit||!scopedClient.is_active;
  }
  await clients();await load();
  if(query.get('enquiry_id'))await details(query.get('enquiry_id'));
  if(query.get('new')==='1')await createForm();
}catch(error){message(error.message,true);}})();

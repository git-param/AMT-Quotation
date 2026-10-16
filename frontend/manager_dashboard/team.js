(() => {
  const el=id=>document.getElementById(id),node=(tag,text,className)=>{const item=document.createElement(tag);if(text!=null)item.textContent=text;if(className)item.className=className;return item;};
  const roles={sales_tl:'Sales TL',sales_executive:'Sales Executive',admin:'Admin',manager:'Admin (legacy)',user:'Sales Executive (legacy)'};
  let filters={user_id:'',from:'',to:''},lookupPage=1,lookupPages=0,piPage=1,piPages=0,piUser=null,piOpen=false;
  let summaryVersion=0,lookupVersion=0,piVersion=0,filterVersion=0;
  const format=new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Kolkata'});
  function timestamp(value,local=false){const text=local&&/^\d{4}-\d{2}-\d{2} \d{2}:/.test(value)?value.replace(' ','T')+'+05:30':value;const date=new Date(text);return Number.isNaN(date.getTime())?'—':format.format(date);}
  async function api(url,options={}){const response=await fetch(url,options);const data=await response.json();if(!response.ok)throw new Error(data.error||'Unable to load dashboard.');return data;}
  function notify(error){window.skuFeedback.show(error.message||error,true);}
  function state(id,text,columns,loading=false){const row=node('tr'),cell=node('td',null,'tl-empty');cell.colSpan=columns;if(loading){const spinner=node('span',null,'tl-spinner');spinner.setAttribute('aria-hidden','true');cell.append(spinner);}cell.append(node('span',text));row.append(cell);el(id).replaceChildren(row);}
  function pager(prefix,page,pages,total){el(prefix+'Previous').disabled=page<=1;el(prefix+'Next').disabled=page>=pages;el(prefix+'Page').textContent=`Page ${page} of ${Math.max(1,pages)}`;el(prefix+'Count').textContent=`${total} ${prefix==='tlPi'?'invoices':'user / SKU combinations'}`;}
  function parameters(extra={}){return new URLSearchParams({...filters,...extra});}
  async function summary(){
    const version=++summaryVersion;el('tlTeamResults').setAttribute('aria-busy','true');state('tlTeamRows','Loading team performance...',5,true);
    try{
      const data=await api('/api/tl-dashboard/summary?'+parameters());if(version!==summaryVersion)return;
      el('tlScope').textContent=data.scope;el('tlCleanup').hidden=!data.can_cleanup;el('tlCleanupBefore').max=data.today;
      el('tlClients').textContent=data.totals.clients.toLocaleString();el('tlPis').textContent=data.totals.pis.toLocaleString();el('tlTeamCount').textContent=`${data.rows.length} users`;
      el('tlUser').replaceChildren(node('option','All accessible users'));el('tlUser').children[0].value='';
      for(const user of data.users){const option=node('option',user.username+(user.is_active?'':' (inactive)'));option.value=user.id;el('tlUser').append(option);}el('tlUser').value=filters.user_id;
      el('tlTeamRows').replaceChildren();
      for(const user of data.rows){
        const row=node('tr'),name=node('td');name.append(node('strong',user.username));if(!user.is_active)name.append(node('span','Inactive','tl-inactive'));row.append(name);
        const role=node('td');role.append(node('span',roles[user.role]||user.role,'tl-role'));row.append(role,node('td',user.clients.toLocaleString(),'tl-number'),node('td',user.pis.toLocaleString(),'tl-number'));
        const action=node('td'),button=node('button','See PI list','tl-pi-button');button.type='button';button.disabled=!user.pis;button.setAttribute('aria-label','See PI list for '+user.username);button.onclick=()=>openPis(user);action.append(button);row.append(action);el('tlTeamRows').append(row);
      }
      if(!data.rows.length)state('tlTeamRows','No users match these filters.',5);
    }catch(error){if(version===summaryVersion){state('tlTeamRows','Could not load team performance. Apply filters to retry.',5);notify(error);}}
    finally{if(version===summaryVersion)el('tlTeamResults').setAttribute('aria-busy','false');}
  }
  async function lookups(){
    const version=++lookupVersion;el('tlLookupResults').setAttribute('aria-busy','true');el('tlLookupPrevious').disabled=true;el('tlLookupNext').disabled=true;state('tlLookupRows','Loading SKU lookup history...',4,true);
    try{
      const data=await api('/api/tl-dashboard/lookups?'+parameters({page:lookupPage,sku:el('tlSkuSearch').value.trim()}));if(version!==lookupVersion)return;
      lookupPages=data.pages;if(lookupPage>Math.max(1,lookupPages)){lookupPage=Math.max(1,lookupPages);return lookups();}
      el('tlRequests').textContent=data.requests.toLocaleString();el('tlSkus').textContent=data.unique_skus.toLocaleString();el('tlLookupRows').replaceChildren();
      for(const item of data.rows){const row=node('tr');row.append(node('td',item.user_name));const sku=node('td');sku.append(node('span',item.sku,'tl-sku'));row.append(sku,node('td',item.searches.toLocaleString(),'tl-number'),node('td',timestamp(item.last_lookup,true)));el('tlLookupRows').append(row);}
      if(!data.rows.length)state('tlLookupRows','No SKU lookups match these filters.',4);pager('tlLookup',lookupPage,lookupPages,data.total);
    }catch(error){if(version===lookupVersion){state('tlLookupRows','Could not load lookup history. Search again to retry.',4);notify(error);}}
    finally{if(version===lookupVersion)el('tlLookupResults').setAttribute('aria-busy','false');}
  }
  async function load(){const version=++filterVersion;el('tlApply').disabled=true;await Promise.all([summary(),lookups()]);if(version===filterVersion)el('tlApply').disabled=false;}
  function file(label,url){const link=node('a',label);link.href=url;link.setAttribute('download','');return link;}
  async function loadPis(){
    const version=++piVersion;el('tlPiResults').setAttribute('aria-busy','true');el('tlPiPrevious').disabled=true;el('tlPiNext').disabled=true;state('tlPiRows','Loading PIs by client...',4,true);
    try{
      const data=await api('/api/tl-dashboard/pis?'+parameters({user_id:piUser.id,page:piPage}));if(version!==piVersion||!piOpen)return;
      piPages=data.pages;if(piPage>Math.max(1,piPages)){piPage=Math.max(1,piPages);return loadPis();}
      el('tlPiTitle').textContent=data.username+' · PI list';el('tlPiSummary').textContent=`${data.total} invoices across ${data.clients} clients`;el('tlPiRows').replaceChildren();let lastClient=null;
      for(const item of data.rows){
        if(item.client_id!==lastClient){lastClient=item.client_id;const group=node('tr',null,'tl-client-group'),cell=node('td');cell.colSpan=4;const link=node('a',item.client_name);link.href='/clients-orders?'+new URLSearchParams({client_id:item.client_id});cell.append(link,node('small',[item.client_company,`${item.client_pis} PIs`].filter(Boolean).join(' · ')));group.append(cell);el('tlPiRows').append(group);}
        const row=node('tr'),ref=node('td');ref.append(node('strong',item.reference),node('small',' · '+item.currency));const order=node('td'),link=node('a',item.order_reference);link.href='/orders?'+new URLSearchParams({client_id:item.client_id,order_id:item.order_id});order.append(link);row.append(ref,order,node('td',timestamp(item.created_at)));
        const cell=node('td'),downloads=node('div',null,'tl-downloads');downloads.append(file(item.workbook_format==='xlsm'?'Excel (.xlsm)':'Excel',item.excel_url));if(item.pdf_url)downloads.append(file('PDF',item.pdf_url));else downloads.append(node('span','PDF unavailable','tl-unavailable'));cell.append(downloads);row.append(cell);el('tlPiRows').append(row);
      }
      if(!data.rows.length)state('tlPiRows','No PIs for this user in the selected dates.',4);pager('tlPi',piPage,piPages,data.total);
    }catch(error){if(version===piVersion){state('tlPiRows','Could not load this PI list.',4);notify(error);}}
    finally{if(version===piVersion)el('tlPiResults').setAttribute('aria-busy','false');}
  }
  function openPis(user){piUser=user;piPage=1;piOpen=true;el('tlPiTitle').textContent=user.username+' · PI list';el('tlPiSummary').textContent='Loading client distribution...';el('tlPiDialog').showModal();loadPis();}
  el('tlPiClose').onclick=()=>el('tlPiDialog').close();el('tlPiDialog').onclose=()=>{piOpen=false;piVersion++;};
  el('tlPiPrevious').onclick=()=>{if(piPage>1){piPage--;loadPis();}};el('tlPiNext').onclick=()=>{if(piPage<piPages){piPage++;loadPis();}};
  el('tlFilters').onsubmit=event=>{event.preventDefault();filters={user_id:el('tlUser').value,from:el('tlFrom').value,to:el('tlTo').value};lookupPage=1;load();};
  el('tlClear').onclick=()=>{el('tlUser').value='';el('tlFrom').value='';el('tlTo').value='';el('tlSkuSearch').value='';filters={user_id:'',from:'',to:''};lookupPage=1;load();};
  el('tlSkuFilter').onsubmit=event=>{event.preventDefault();lookupPage=1;lookups();};
  el('tlLookupPrevious').onclick=()=>{if(lookupPage>1){lookupPage--;lookups();}};el('tlLookupNext').onclick=()=>{if(lookupPage<lookupPages){lookupPage++;lookups();}};
  el('tlCleanupForm').onsubmit=async event=>{
    event.preventDefault();const before=el('tlCleanupBefore').value;if(!before)return;el('tlCleanupReview').disabled=true;
    const done=window.skuFeedback.loading('Reviewing lookup history','Counting records older than the selected cutoff date.');
    try{
      const preview=await api('/api/tl-dashboard/lookup-cleanup?'+new URLSearchParams({before}));done();
      if(!preview.count){window.skuFeedback.show('No lookup records are older than the selected date.');return;}
      if(!window.confirm(`Permanently delete ${preview.count} lookup records from all users dated before ${before} (IST)? This cannot be undone.`))return;
      const finish=window.skuFeedback.loading('Removing older lookup records','Deleting the reviewed records and updating dashboard counts.');
      try{const result=await api('/api/tl-dashboard/lookup-cleanup',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({before,expected_count:preview.count})});lookupPage=1;await load();window.skuFeedback.show(`${result.count} lookup records deleted.`);}finally{finish();}
    }catch(error){notify(error);}finally{done();el('tlCleanupReview').disabled=false;}
  };
  load();
})();

(() => {
  const byId=id=>document.getElementById(id);
  const filters=byId('auditFilters');
  const rowHost=byId('auditRows');
  const status=byId('auditStatus');
  let page=1,pages=1,events=[];
  const filterIds={action:'filterAction',user:'filterUser',role:'filterRole',ip:'filterIp',from:'filterFrom',to:'filterTo',q:'filterQuery'};
  const readable=value=>String(value||'').replaceAll('_',' ').replace(/\b\w/g,letter=>letter.toUpperCase());
  const roleLabel=value=>({admin:'Admin',manager:'Admin (legacy)',sales_tl:'Sales TL',sales_executive:'Sales Executive',user:'Sales Executive (legacy)'})[value]||readable(value);
  function option(select,label,value){const node=document.createElement('option');node.value=value;node.textContent=label;select.append(node);}
  function updateOptions(data){
    for(const [key,values,label]of [['action',data.actions,'All actions'],['user',data.users,'All users'],['role',data.roles,'All roles']]){
      const select=byId(filterIds[key]),previous=select.value;select.replaceChildren();option(select,label,'');
      for(const value of values)option(select,key==='action'?readable(value):key==='role'?roleLabel(value):value,value);
      if([...select.options].some(item=>item.value===previous))select.value=previous;
    }
  }
  function detailText(event){
    let detail={};try{detail=JSON.parse(event.details||'{}');}catch{}
    const parts=[];
    if(detail.sku_count!=null)parts.push(`${detail.sku_count} SKU${Number(detail.sku_count)===1?'':'s'}`);
    if(detail.found!=null)parts.push(`${detail.found} found`);
    if(detail.not_found!=null&&Number(detail.not_found))parts.push(`${detail.not_found} not found`);
    if(detail.reference)parts.push(`Reference ${detail.reference}`);
    if(detail.copy_type)parts.push(`Copy: ${detail.copy_type}`);
    if(event.entity_id)parts.push(`${readable(event.entity_type)} #${event.entity_id}`);
    if(detail.endpoint)parts.push(detail.endpoint);
    if(detail.method)parts.push(detail.method);
    return parts.join(' · ')||event.entity_type||'';
  }
  function localParts(value){
    if(!value)return ['—','—'];
    let normalized=value;
    if(!/[zZ]|[+-]\d\d:\d\d$/.test(value))normalized=value.replace(' ','T')+'+05:30';
    const parsed=new Date(normalized);if(Number.isNaN(parsed.getTime()))return [value,'—'];
    const date=new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(parsed);
    const time=new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:true}).format(parsed);
    return [date,time];
  }
  function render(){
    rowHost.replaceChildren();
    if(!events.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=7;cell.textContent='No activity found for these filters.';row.append(cell);rowHost.append(row);return;}
    for(const event of events){
      const row=document.createElement('tr'),parts=localParts(event.created_at);
      for(const value of [readable(event.action),event.username||'Unknown',event.role?roleLabel(event.role):'—',parts[0],parts[1],event.ip_address||'—']){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}
      const detail=document.createElement('td');detail.className='audit-detail';detail.textContent=detailText(event);row.append(detail);rowHost.append(row);
    }
  }
  async function load(){
    status.textContent='Loading activity…';byId('refreshAudit').disabled=true;
    const params=new URLSearchParams({page:String(page),page_size:'50'});
    for(const [key,id]of Object.entries(filterIds)){const value=byId(id).value.trim();if(value)params.set(key,value);}
    try{
      const response=await fetch('/api/audit-logs?'+params);const data=await response.json();
      if(!response.ok)throw new Error(data.error||'Unable to load audit activity.');
      events=data.events;pages=data.pages;updateOptions(data);render();
      byId('auditCount').textContent=`${data.total} record${data.total===1?'':'s'}`;
      byId('auditPage').textContent=`Page ${data.page} of ${data.pages}`;
      byId('auditPrev').disabled=data.page<=1;byId('auditNext').disabled=data.page>=data.pages;
      status.textContent='Times are shown in India Standard Time.';
    }catch(error){status.textContent=error.message;rowHost.replaceChildren();}
    finally{byId('refreshAudit').disabled=false;}
  }
  filters.onsubmit=event=>{event.preventDefault();page=1;load();};
  byId('clearFilters').onclick=()=>{filters.reset();page=1;load();};
  byId('refreshAudit').onclick=load;
  byId('auditPrev').onclick=()=>{if(page>1){page--;load();}};
  byId('auditNext').onclick=()=>{if(page<pages){page++;load();}};
  load();
})();

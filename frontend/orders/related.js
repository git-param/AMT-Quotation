/* Client-scoped cards and an order editor inside the Clients & PI workspace. */
window.renderRelatedOrders = async (host, scope, canCreate) => {
  const section=document.createElement('section');section.className='related-orders';
  const toolbar=document.createElement('div');toolbar.className='source-toolbar';
  const title=document.createElement('h3');title.textContent='Proforma Invoices';toolbar.append(title);section.append(toolbar);host.append(section);
  const dialog=document.createElement('dialog');dialog.className='order-dialog';dialog.setAttribute('aria-label','Client order workspace');
  const header=document.createElement('div');header.className='order-dialog-header';
  const heading=document.createElement('div');
  const name=document.createElement('strong');name.textContent='PI workspace';
  const hint=document.createElement('span');hint.textContent='PI details, items and proforma invoices';heading.append(name,hint);
  const close=document.createElement('button');close.type='button';close.className='btn-sm';close.textContent='Close';close.setAttribute('aria-label','Close order workspace');
  const statusToggle=document.createElement('button');statusToggle.type='button';statusToggle.className='btn-sm order-status-toggle';statusToggle.hidden=true;
  const headerActions=document.createElement('div');headerActions.className='order-dialog-actions';headerActions.append(statusToggle,close);header.append(heading,headerActions);
  const frame=document.createElement('iframe');frame.title='Client order workspace';dialog.append(header,frame);section.append(dialog);
  let refresh=()=>{};
  let activeOrder=null;
  const onMessage=event=>{
    if(event.origin!==location.origin||event.source!==frame.contentWindow)return;
    if(event.data?.type==='amt-order-close')dialog.close();
    if(event.data?.type==='amt-order-state'){
      const order=event.data.order;
      const changed=activeOrder&&order&&activeOrder.id===order.id&&activeOrder.status!==order.status;
      activeOrder=order;statusToggle.hidden=!order?.can_edit;statusToggle.disabled=Boolean(event.data.busy);
      statusToggle.textContent=order?.status==='completed'?'Move to pending':'Complete';
      hint.textContent=order?'Generating a PI automatically marks the PI order complete.':'PI details, items and proforma invoices';
      if(changed)refresh();
    }
  };
  statusToggle.onclick=()=>{statusToggle.disabled=true;frame.contentWindow.postMessage({type:'amt-order-toggle-status'},location.origin);};
  function open(extra){
    activeOrder=null;statusToggle.hidden=true;
    frame.src='/orders?'+new URLSearchParams({...scope,embedded:1,...extra});
    window.addEventListener('message',onMessage);document.body.classList.add('order-modal-open');dialog.showModal();
  }
  close.onclick=()=>dialog.close();
  dialog.onclose=()=>{window.removeEventListener('message',onMessage);document.body.classList.remove('order-modal-open');frame.src='about:blank';refresh();};
  if(canCreate){const add=document.createElement('button');add.type='button';add.className='btn-sm btn-add';add.textContent='+ Add order';add.onclick=()=>open({new:1});toolbar.append(add);}
  const loaders=[];
  for(const pending of [true,false]){
    const group=document.createElement('section');group.className='order-card-group '+(pending?'order-group-pending':'order-group-complete');
    const heading=document.createElement('h4');heading.textContent=pending?'Pending PI':'Completed PI';
    const cards=document.createElement('div');cards.className='order-cards';
    const paging=document.createElement('div');paging.className='picker order-group-paging';
    const previous=document.createElement('button'),next=document.createElement('button'),status=document.createElement('span');
    for(const button of [previous,next]){button.type='button';button.className='btn-sm';}
    previous.textContent='Previous';next.textContent='Next';paging.append(previous,status,next);group.append(heading,cards,paging);section.append(group);
    let page=1;
    async function load(){
      const response=await fetch('/api/orders?'+new URLSearchParams({...scope,completion:pending?'pending':'complete',page,page_size:6}));
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Unable to load orders.');
      if(page>Math.max(1,data.pages)){page=Math.max(1,data.pages);return load();}
      const label=document.createElement('span');label.textContent=pending?'Pending PI':'Completed PI';
      const count=document.createElement('span');count.className='order-group-count';count.textContent=String(data.total);
      heading.replaceChildren(label,count);paging.hidden=data.pages<=1;
      previous.disabled=page<=1;next.disabled=page>=data.pages;status.textContent=`${page} / ${Math.max(1,data.pages)}`;
      cards.replaceChildren();
      for(const order of data.orders){
        const resume=pending&&order.can_edit;
        const card=document.createElement('button');card.type='button';card.className='related-order-card';card.onclick=()=>open({order_id:order.id,...(resume?{edit:1}:{})});
        const ref=document.createElement('strong');ref.className='order-card-reference';ref.textContent=order.reference;
        const meta=document.createElement('span');meta.className='order-card-meta';
        const date=document.createElement('span');date.textContent=/^\d{4}-\d{2}-\d{2}$/.test(order.order_date)?new Date(order.order_date+'T00:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}):order.order_date;
        const state=document.createElement('span');state.className='order-card-status';state.textContent=order.status==='completed'?'Complete':order.status==='draft'?'Pending':order.status;
        const currency=document.createElement('span');currency.className='order-card-currency';currency.textContent=order.currency;meta.append(date,state,currency);
        const pi=document.createElement('span');pi.className='order-card-pi';pi.textContent=order.pi_reference?`PI: ${order.pi_reference}`:'PI not generated';
        const link=document.createElement('span');link.className='order-card-open';link.textContent=resume?'Continue order \u2192':'View PI \u2192';
        card.append(ref,meta,pi,link);
        if(order.can_delete_order){
          const entry=document.createElement('div');entry.className='order-card-entry';
          const remove=document.createElement('button');remove.type='button';remove.className='btn-sm btn-del order-card-delete';remove.title='Delete PI';remove.setAttribute('aria-label','Delete PI '+order.reference);
          const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
          for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.8','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))icon.setAttribute(key,value);
          const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d','M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7');icon.append(path);remove.append(icon);
          remove.onclick=async()=>{
            if(!window.confirm(`Are you sure you want to Delete PI ${order.reference}? Its history and deletion log will be retained.`))return;
            remove.disabled=true;
            try{
              const response=await fetch('/api/orders/'+order.id,{method:'DELETE'});const result=await response.json();
              if(!response.ok)throw new Error(result.error||'Unable to Delete PI.');
              await refresh();
            }catch(error){paging.hidden=false;status.textContent=error.message;remove.disabled=false;}
          };
          entry.append(card,remove);cards.append(entry);
        }else cards.append(card);
      }
      if(!data.orders.length){
        const empty=document.createElement('div');empty.className='order-group-empty';
        const icon=document.createElement('span');icon.className='order-empty-icon';icon.textContent=pending?'\u2713':'\u2014';icon.setAttribute('aria-hidden','true');
        const content=document.createElement('span'),title=document.createElement('strong'),hint=document.createElement('span');
        title.textContent=pending?'No Pending PI':'No Completed PI yet';
        hint.textContent=pending?'New orders stay here until they are marked complete.':'Generate a PI or mark an order complete to move it here.';
        content.append(title,hint);empty.append(icon,content);cards.append(empty);
      }
    }
    const safeLoad=()=>load().catch(error=>{paging.hidden=false;status.textContent=error.message;});
    previous.onclick=()=>{page--;safeLoad();};next.onclick=()=>{page++;safeLoad();};loaders.push(safeLoad);
  }
  const log=document.createElement('details');log.className='order-deletion-log';
  const summary=document.createElement('summary');summary.textContent='PI deletion log';
  const history=document.createElement('div');history.setAttribute('aria-live','polite');log.append(summary,history);section.append(log);
  log.ontoggle=async()=>{
    if(!log.open)return;
    history.replaceChildren();
    try{
      const response=await fetch('/api/orders/deletions?'+new URLSearchParams(scope));const data=await response.json();
      if(!response.ok)throw new Error(data.error||'Unable to load deletion log.');
      for(const row of data.deletions){const item=document.createElement('p');item.textContent=`${row.reference} — deleted by ${row.actor_name} — ${new Date(row.deleted_at).toLocaleString()}`;history.append(item);}
      if(!data.deletions.length)history.textContent='No orders have been deleted.';
    }catch(error){history.textContent=error.message;}
  };
  refresh=async()=>{await Promise.all(loaders.map(load=>load()));if(log.open)await log.ontoggle();};await refresh();
};

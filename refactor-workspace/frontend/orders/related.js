/* Client-scoped cards and an order editor inside the Clients & Orders workspace. */
window.renderRelatedOrders = async (host, scope, canCreate) => {
  const section=document.createElement('section');section.className='related-orders';
  const toolbar=document.createElement('div');toolbar.className='source-toolbar';
  const title=document.createElement('h3');title.textContent='Orders & Proforma Invoices';toolbar.append(title);section.append(toolbar);host.append(section);
  const dialog=document.createElement('dialog');dialog.className='order-dialog';
  const close=document.createElement('button');close.type='button';close.className='btn-sm';close.textContent='Close order workspace';
  const frame=document.createElement('iframe');frame.title='Client order workspace';dialog.append(close,frame);section.append(dialog);
  let refresh=()=>{};
  function open(extra){frame.src='/orders?'+new URLSearchParams({...scope,embedded:1,...extra});dialog.showModal();}
  close.onclick=()=>dialog.close();
  dialog.onclose=()=>{frame.src='about:blank';refresh();};
  if(canCreate){const add=document.createElement('button');add.type='button';add.className='btn-sm btn-add';add.textContent='+ Add order';add.onclick=()=>open({new:1});toolbar.append(add);}
  const loaders=[];
  for(const pending of [true,false]){
    const group=document.createElement('section');group.className='order-card-group';
    const heading=document.createElement('h4');heading.textContent=pending?'Pending drafts':'Existing orders & PI references';
    const cards=document.createElement('div');cards.className='order-cards';
    const paging=document.createElement('div');paging.className='picker';
    const previous=document.createElement('button'),next=document.createElement('button'),status=document.createElement('span');
    for(const button of [previous,next]){button.type='button';button.className='btn-sm';}
    previous.textContent='Previous';next.textContent='Next';paging.append(previous,status,next);group.append(heading,cards,paging);section.append(group);
    let page=1;
    async function load(){
      const response=await fetch('/api/orders?'+new URLSearchParams({...scope,status:pending?'draft':'all',exclude_drafts:pending?'0':'1',page,page_size:6}));
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Unable to load orders.');
      if(page>Math.max(1,data.pages)){page=Math.max(1,data.pages);return load();}
      heading.textContent=(pending?'Pending drafts':'Existing orders & PI references')+` (${data.total})`;
      previous.disabled=page<=1;next.disabled=page>=data.pages;status.textContent=`${page} / ${Math.max(1,data.pages)}`;
      cards.replaceChildren();
      for(const order of data.orders){
        const card=document.createElement('button');card.type='button';card.className='related-order-card';card.onclick=()=>open({order_id:order.id});
        const ref=document.createElement('strong');ref.textContent=order.reference;
        const meta=document.createElement('span');meta.textContent=`${order.order_date} ? ${order.status} ? ${order.currency}`;
        const pi=document.createElement('span');pi.textContent=order.pi_reference?`PI: ${order.pi_reference}`:'PI not generated';
        card.append(ref,meta,pi);cards.append(card);
      }
      if(!data.orders.length){const empty=document.createElement('p');empty.textContent=pending?'No pending drafts.':'No existing orders yet.';cards.append(empty);}
    }
    const safeLoad=()=>load().catch(error=>{status.textContent=error.message;});
    previous.onclick=()=>{page--;safeLoad();};next.onclick=()=>{page++;safeLoad();};loaders.push(safeLoad);
  }
  refresh=()=>Promise.all(loaders.map(load=>load()));await refresh();
};

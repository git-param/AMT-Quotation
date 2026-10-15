/* Reusable, server-scoped order summaries for client and enquiry details. */
window.renderRelatedOrders = async (host, scope, canCreate) => {
  const section=document.createElement('section');section.className='related-orders';
  const toolbar=document.createElement('div');toolbar.className='source-toolbar';
  const heading=document.createElement('h3');heading.textContent='Orders';toolbar.append(heading);
  const controls=document.createElement('div');
  const query=new URLSearchParams(scope);
  const all=document.createElement('a');all.className='btn-sm enquiry-link';all.textContent='View all orders';all.href='/orders?'+query;controls.append(all);
  if(canCreate){const add=document.createElement('a');add.className='btn-sm btn-add';add.textContent='Add Order';add.href='/orders?'+query+'&new=1';controls.append(add);}
  toolbar.append(controls);section.append(toolbar);host.append(section);
  query.set('page_size','5');
  const response=await fetch('/api/orders?'+query);const data=await response.json();
  if(!response.ok)throw new Error(data.error||'Unable to load orders.');
  heading.textContent=`Orders (${data.total})`;
  data.orders.forEach(order=>{
    const link=document.createElement('a');link.className='related-order-card';
    link.href=`/orders?${new URLSearchParams({...scope,order_id:order.id})}`;
    const title=document.createElement('strong');title.textContent=order.reference;
    const meta=document.createElement('span');meta.textContent=`${order.order_date} / ${order.status} / ${order.currency}`;
    link.append(title,meta);section.append(link);
  });
  if(!data.orders.length){const empty=document.createElement('p');empty.textContent='No orders for this record yet.';section.append(empty);}
};

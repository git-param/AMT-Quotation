(() => {
  const el=id=>document.getElementById(id);
  const initial=new URLSearchParams(location.search);
  let page=Math.max(1,Number(initial.get('page'))||1),pages=0,version=0,controller=null;
  el('piSearch').value=initial.get('q')||'';
  el('piCurrency').value=['USD','INR'].includes(initial.get('currency'))?initial.get('currency'):'all';
  const node=(tag,text,className)=>{const item=document.createElement(tag);if(text!=null)item.textContent=text;if(className)item.className=className;return item;};
  const dateFormat=new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeZone:'Asia/Kolkata'});
  function stateRow(title,hint,loading=false){
    const row=node('tr'),cell=node('td',null,'pi-search-empty');cell.colSpan=6;
    if(loading){const spinner=node('span',null,'pi-search-spinner');spinner.setAttribute('aria-hidden','true');cell.append(spinner);}
    cell.append(node('strong',title),node('p',hint));row.append(cell);el('piSearchRows').replaceChildren(row);
  }
  function download(label,url,className){
    const link=node('a',null,className);link.href=url;link.setAttribute('download','');
    link.onclick=async event=>{event.preventDefault();try{await window.downloadPiFile(url);}catch(error){window.skuFeedback?.show(error.message,true);}};
    const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-width','1.7');icon.setAttribute('aria-hidden','true');
    const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d','M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5');icon.append(shape);link.append(icon,node('span',label));return link;
  }
  function render(invoices){
    el('piSearchRows').replaceChildren();
    for(const invoice of invoices){
      const row=node('tr'),cell=()=>{const td=node('td');row.append(td);return td;};
      cell().append(node('strong',invoice.reference,'pi-search-reference'));
      const client=cell(),clientLink=node('a',invoice.client_name);clientLink.href='/clients-orders?'+new URLSearchParams({client_id:invoice.client_id});client.append(clientLink);
      if(invoice.client_company)client.append(node('span',invoice.client_company,'pi-search-company'));
      const order=cell(),orderLink=node('a',invoice.order_reference);orderLink.href='/orders?'+new URLSearchParams({client_id:invoice.client_id,order_id:invoice.order_id});order.append(orderLink);
      if(invoice.po_reference)order.append(node('span','PO: '+invoice.po_reference,'pi-search-po'));
      const date=new Date(invoice.created_at);cell().textContent=Number.isNaN(date.getTime())?'—':dateFormat.format(date);
      cell().append(node('span',invoice.currency,'pi-search-currency'));
      const files=node('div',null,'pi-search-downloads');files.append(download(invoice.workbook_format==='xlsm'?'Excel (.xlsm)':'Excel',invoice.excel_url));
      if(invoice.pdf_url)files.append(download('PDF',invoice.pdf_url,'pi-search-pdf'));
      else{const unavailable=node('span','PDF unavailable','pi-search-unavailable');unavailable.title='This historical PI has no saved PDF.';files.append(unavailable);}
      cell().append(files);el('piSearchRows').append(row);
    }
    if(!invoices.length)stateRow('No matching invoices','Try a different PI number, client or order, or clear the filters.');
  }
  async function load(){
    const request=++version;controller?.abort();controller=new AbortController();
    const query=new URLSearchParams({q:el('piSearch').value.trim(),currency:el('piCurrency').value,page,page_size:25});
    history.replaceState(null,'','/search-pi?'+query);
    el('piSearchResults').setAttribute('aria-busy','true');el('piSearchButton').disabled=true;el('piSearchButton').textContent='Searching...';el('piPrevious').disabled=true;el('piNext').disabled=true;
    el('piSearchSummary').textContent='Searching saved invoices...';stateRow('Searching invoices','Finding matching PIs and their available downloads.',true);
    try{
      const response=await fetch('/api/pi-search?'+query,{signal:controller.signal});const data=await response.json();
      if(request!==version)return;
      if(!response.ok)throw new Error(data.error||'Unable to search invoices.');
      pages=data.pages;
      if(page>Math.max(1,pages)){page=Math.max(1,pages);return load();}
      render(data.invoices);
      const first=data.total?(page-1)*25+1:0,last=Math.min(page*25,data.total);
      el('piSearchSummary').textContent=data.total?`${first}–${last} of ${data.total} invoices`:'0 invoices found';
      el('piPageInfo').textContent=`Page ${page} of ${Math.max(1,pages)}`;
      el('piPrevious').disabled=page<=1;el('piNext').disabled=page>=pages;
    }catch(error){
      if(request!==version||error.name==='AbortError')return;
      stateRow('Could not load invoices','Choose Search to try again.');el('piSearchSummary').textContent='Search failed';el('piPageInfo').textContent='Results unavailable';window.skuFeedback?.show(error.message,true);
    }finally{
      if(request===version){el('piSearchResults').setAttribute('aria-busy','false');el('piSearchButton').disabled=false;el('piSearchButton').textContent='Search';}
    }
  }
  el('piSearchForm').onsubmit=event=>{event.preventDefault();page=1;load();};
  el('piCurrency').onchange=()=>{page=1;load();};
  el('piSearchReset').onclick=()=>{el('piSearch').value='';el('piCurrency').value='all';page=1;load();};
  el('piPrevious').onclick=()=>{if(page>1){page--;load();}};
  el('piNext').onclick=()=>{if(page<pages){page++;load();}};
  load();
})();

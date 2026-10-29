/* Attach the server-issued synchronizer token to every state-changing request. */
(() => {
  const originalFetch=fetch.bind(globalThis);
  window.fetch=(input,options={})=>{
    const isRequest=typeof Request!=='undefined'&&input instanceof Request;
    const method=String(options.method||(isRequest?input.method:'GET')).toUpperCase();
    if(['POST','PUT','PATCH','DELETE'].includes(method)){
      const match=document.cookie.match(/(?:^|; )amt_csrf_v2=([^;]*)/);
      if(match){
        const headers=new Headers(options.headers||(isRequest?input.headers:undefined));
        headers.set('X-CSRF-Token',decodeURIComponent(match[1]));
        options={...options,headers};
      }
    }
    return originalFetch(input,options);
  };
})();

/* Shared navigation preserves existing link IDs and page permission handlers. */
(() => {
  if(new URLSearchParams(location.search).get('embedded')==='1')return;
  const header=document.querySelector('.hdr');
  if(!header)return;
  const entries=[
    ['Quotation Tool','/','M4 3h16v18H4z M8 7h8 M8 11h8 M8 15h5'],
    ['Clients & PI','/clients-orders','M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z M4 21v-2a8 8 0 0 1 16 0v2'],
    ['Search PI','/search-pi','M14 3H5v18h14V8l-5-5Z M14 3v5h5 M15 14a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z M14 16l3 3'],
    ['TL Dashboard','/tl-dashboard','M3 20h18 M6 16v-5 M12 16V5 M18 16V8','management.view'],
    ['Client Access / Sharing','/client-access','M15 5a3 3 0 1 1 6 0 3 3 0 0 1-6 0Z M3 12a3 3 0 1 1 6 0 3 3 0 0 1-6 0Z M15 19a3 3 0 1 1 6 0 3 3 0 0 1-6 0Z M9 11l6-5 M9 13l6 5','leads.share_manage'],
    ['Enquiry Sources','/sources','M3 5h18v14H3z m0 0 9 8 9-8','sources.manage'],
    ['Dashboard','/manager','M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z','management.view'],
    ['Configuration','/configuration','M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6','settings.manage'],
    ['Audit Logs','/audit-logs','M4 4h16v16H4z M8 8h8 M8 12h8 M8 16h5','audit.view'],
    ['Sign Out','/logout','M10 3H4v18h6 M13 7l5 5-5 5 M8 12h13'],
  ];
  const sidebar=document.createElement('aside');sidebar.id='appSidebar';sidebar.className='app-sidebar';sidebar.setAttribute('aria-label','Application navigation');
  const brand=document.createElement('a');brand.href='/';brand.className='sidebar-brand';
  const name=document.createElement('strong');name.textContent='AMT Quotation';
  const subtitle=document.createElement('span');subtitle.textContent='Sales & client workspace';brand.append(name,subtitle);sidebar.append(brand);
  const nav=document.createElement('nav');nav.setAttribute('aria-label','Main navigation');sidebar.append(nav);
  const original=[...header.querySelectorAll('a[href]')];
  for(const link of original)if(['/leads','/enquiries','/orders'].includes(link.getAttribute('href')))link.remove();
  const restricted=[],quotationOnly=[];
  for(const [label,url,path,permission] of entries){
    const link=original.find(item=>item.getAttribute('href')===url)||document.createElement('a');
    link.href=url;link.className='sidebar-link';link.replaceChildren();
    link.removeAttribute('target');
    link.removeAttribute('onmouseover');link.removeAttribute('onmouseout');
    link.style.removeProperty('color');link.style.removeProperty('border-color');link.style.removeProperty('background');
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    for(const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.7','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(key,value);
    const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d',path);svg.append(shape);
    const text=document.createElement('span');text.textContent=label;link.append(svg,text);
    if(location.pathname===url||(url==='/clients-orders'&&['/leads','/orders','/enquiries'].includes(location.pathname))){link.classList.add('is-current');link.setAttribute('aria-current','page');}
    const row=document.createElement('div');row.className='sidebar-item';row.append(link);nav.append(row);
    if(url==='/logout')row.classList.add('sidebar-signout');
    if(url==='/logout')link.onclick=async event=>{
      event.preventDefault();
      const response=await fetch('/logout',{method:'POST'});
      location.href=response.redirected?response.url:'/login';
    };
    if(permission){row.hidden=true;restricted.push({row,link,permission,url});}
    if(url!=='/'&&url!=='/logout')quotationOnly.push(row);
  }
  document.body.classList.add('has-sidebar');document.body.prepend(sidebar);
  const toggle=document.createElement('button');toggle.type='button';toggle.className='sidebar-toggle';toggle.textContent='Menu';toggle.setAttribute('aria-label','Open navigation');toggle.setAttribute('aria-controls',sidebar.id);toggle.setAttribute('aria-expanded','false');header.prepend(toggle);
  const backdrop=document.createElement('button');backdrop.type='button';backdrop.className='sidebar-backdrop';backdrop.setAttribute('aria-label','Close navigation');backdrop.tabIndex=-1;document.body.append(backdrop);
  const mobile=window.matchMedia('(max-width:900px)');
  function setOpen(open){
    document.body.classList.toggle('sidebar-open',open);toggle.setAttribute('aria-expanded',String(open));toggle.setAttribute('aria-label',open?'Close navigation':'Open navigation');sidebar.inert=mobile.matches&&!open;
    if(open)nav.querySelector('a')?.focus();
  }
  toggle.onclick=()=>setOpen(!document.body.classList.contains('sidebar-open'));
  backdrop.onclick=()=>{setOpen(false);toggle.focus();};
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('sidebar-open')){setOpen(false);toggle.focus();}});
  mobile.addEventListener('change',()=>setOpen(false));setOpen(false);
  fetch('/api/me').then(async response=>{
    if(!response.ok)return;
    const user=await response.json();
    if(user.role==='user')for(const row of quotationOnly)row.hidden=true;
    for(const item of restricted){
      const roleAllowed=(item.permission!=='leads.share_manage'&&item.url!=='/tl-dashboard')||['admin','manager','sales_tl'].includes(user.role);
      item.row.hidden=!roleAllowed||!(user.permissions||[]).includes(item.permission);
    }
  }).catch(()=>{});
})();

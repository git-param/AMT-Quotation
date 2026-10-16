const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
class Element{
  constructor(tag='div'){this.tag=tag;this.children=[];this.value='';this.attributes={};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(key,value){this.attributes[key]=value;}
  showModal(){this.open=true;}
  close(){this.open=false;this.onclose?.();}
}
const user={id:4,username:'Alex <fixture>',role:'sales_executive',is_active:1,clients:2,pis:3};
const data={summary:{users:[user],rows:[user],totals:{clients:2,pis:3},scope:'All users',can_cleanup:true,today:'2026-10-16'},
  lookups:{rows:[{user_name:user.username,sku:'SKU-1',searches:5,last_lookup:'2026-10-16 12:00:00'}],requests:5,unique_skus:1,total:1,pages:1},
  pis:{rows:[1,2].map(id=>({id,reference:'PI-1',currency:'USD',created_at:'2026-10-16T09:00:00Z',client_id:2,client_name:'Marine <fixture>',client_company:'Marine',client_pis:2,order_id:3,order_reference:'ORD-3',workbook_format:'xlsx',excel_url:'/excel/'+id,pdf_url:'/pdf/'+id})),total:2,clients:1,pages:1,username:user.username},
  'lookup-cleanup':{count:2,before:'2020-01-01'}};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup(fetcher,confirm=true){
  const nodes=new Map(),requests=[],messages=[],confirmations=[],loading=[];
  const el=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const context={document:{getElementById:el,createElement:tag=>new Element(tag)},URLSearchParams,Intl,Date,
    window:{confirm:message=>{confirmations.push(message);return confirm;},skuFeedback:{show:message=>messages.push(message),loading:(...args)=>{loading.push(args);return ()=>{};}}},
    fetch:async(url,options)=>{requests.push({url,options});return fetcher?fetcher(url,options):{ok:true,json:async()=>data[url.split('?')[0].split('/').at(-1)]};}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/manager_dashboard/team.js'),'utf8'),context);
  return {el,requests,messages,confirmations,loading};
}
test('performance and lookup counts render with safe user text and loading reasons',async()=>{
  const f=setup();
  assert.equal(f.el('tlTeamResults').attributes['aria-busy'],'true');
  assert.equal(f.el('tlTeamRows').children[0].children[0].children[1].textContent,'Loading team performance...');
  await settle();
  assert.equal(f.el('tlTeamRows').children[0].children[0].children[0].textContent,user.username);
  assert.equal(f.el('tlClients').textContent,'2');assert.equal(f.el('tlPis').textContent,'3');
  assert.equal(f.el('tlLookupRows').children[0].children[2].textContent,'5');
  assert.equal(f.el('tlCleanup').hidden,false);assert.equal(f.el('tlApply').disabled,false);
});
test('user and date filters apply to both sections and SKU search preserves them',async()=>{
  const f=setup();await settle();
  f.el('tlUser').value='4';f.el('tlFrom').value='2026-10-01';f.el('tlTo').value='2026-10-16';
  f.el('tlFilters').onsubmit({preventDefault(){}});await settle();
  for(const {url} of f.requests.slice(-2)){const q=new URLSearchParams(url.split('?')[1]);assert.equal(q.get('user_id'),'4');assert.equal(q.get('from'),'2026-10-01');assert.equal(q.get('to'),'2026-10-16');}
  f.el('tlSkuSearch').value=' PART ';f.el('tlSkuFilter').onsubmit({preventDefault(){}});await settle();
  const q=new URLSearchParams(f.requests.at(-1).url.split('?')[1]);assert.equal(q.get('sku'),'PART');assert.equal(q.get('user_id'),'4');
  f.el('tlClear').onclick();await settle();assert.equal(f.el('tlUser').value,'');assert.equal(f.el('tlSkuSearch').value,'');
});
test('PI dialog groups invoices by client and provides downloads without a new page',async()=>{
  const f=setup();await settle();f.el('tlTeamRows').children[0].children[4].children[0].onclick();await settle();
  assert.equal(f.el('tlPiDialog').open,true);assert.equal(f.el('tlPiSummary').textContent,'2 invoices across 1 client');
  const rows=f.el('tlPiRows').children;assert.equal(rows.length,3);assert.equal(rows[0].className,'tl-client-group');
  assert.equal(rows[0].children[0].children[0].textContent,'Marine <fixture>');
  assert.equal(rows[1].children[3].children[0].children[0].href,'/excel/1');
  assert.equal(rows[1].children[3].children[0].children[1].href,'/pdf/1');
  assert.equal(new URLSearchParams(f.requests.at(-1).url.split('?')[1]).get('user_id'),'4');
  f.el('tlPiClose').onclick();assert.equal(f.el('tlPiDialog').open,false);
});
test('cleanup previews the cutoff and only deletes after confirmation with expected count',async()=>{
  const f=setup();await settle();f.el('tlCleanupBefore').value='2020-01-01';
  await f.el('tlCleanupForm').onsubmit({preventDefault(){}});
  const deletion=f.requests.find(item=>item.options?.method==='DELETE');
  assert.deepEqual(JSON.parse(deletion.options.body),{before:'2020-01-01',expected_count:2});
  assert.match(f.confirmations[0],/2 lookup records from all users/);assert.equal(f.loading.length,2);
  assert.equal(f.el('tlCleanupReview').disabled,false);assert.ok(f.messages.includes('2 lookup records deleted.'));
  const cancelled=setup(undefined,false);await settle();cancelled.el('tlCleanupBefore').value='2020-01-01';
  await cancelled.el('tlCleanupForm').onsubmit({preventDefault(){}});
  assert.ok(!cancelled.requests.some(item=>item.options?.method==='DELETE'));
});
test('failed filters clear stale tables, end loading and display a popup error',async()=>{
  const f=setup(()=>({ok:false,json:async()=>({error:'Access denied'})}));await settle();
  assert.equal(f.el('tlApply').disabled,false);assert.equal(f.el('tlTeamResults').attributes['aria-busy'],'false');
  assert.equal(f.el('tlLookupResults').attributes['aria-busy'],'false');assert.ok(f.messages.includes('Access denied'));
  assert.equal(f.el('tlTeamRows').children.length,1);assert.equal(f.el('tlClients').textContent,'—');
});

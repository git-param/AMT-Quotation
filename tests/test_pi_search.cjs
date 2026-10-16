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
}
const invoice={id:7,reference:'PI/<fixture>',currency:'USD',created_at:'2026-10-16T09:00:00Z',
  workbook_format:'xlsx',client_id:1,client_name:'Client <fixture>',client_company:'Marine Company',
  order_id:3,order_reference:'ORD-000003',po_reference:'PO-1',
  excel_url:'/api/orders/3/invoices/7/download?format=xlsx',pdf_url:'/api/orders/3/invoices/7/download?format=pdf'};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup(fetcher,search=''){
  const nodes=new Map(),requests=[],urls=[],errors=[];
  const el=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const context={document:{getElementById:el,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)},
    window:{skuFeedback:{show:message=>errors.push(message)}},location:{search},history:{replaceState:(_,__,url)=>urls.push(url)},
    URLSearchParams,AbortController,Intl,Date,
    fetch:async(url,options)=>{requests.push(url);return fetcher(url,options);}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/orders/pi-search.js'),'utf8'),context);
  return {el,requests,urls,errors};
}
const response=(invoices=[invoice],total=invoices.length,pages=1)=>({ok:true,json:async()=>({invoices,total,pages})});

test('saved PIs render safe client/order links and both download formats',async()=>{
  const f=setup(()=>response());await settle();
  const cells=f.el('piSearchRows').children[0].children;
  assert.equal(cells.length,6);assert.equal(cells[0].children[0].textContent,'PI/<fixture>');
  assert.equal(cells[1].children[0].textContent,'Client <fixture>');
  assert.match(cells[1].children[0].href,/client_id=1/);assert.match(cells[2].children[0].href,/order_id=3/);
  const links=cells[5].children[0].children;
  assert.equal(links[0].href,invoice.excel_url);assert.equal(links[1].href,invoice.pdf_url);
  assert.equal(f.el('piSearchResults').attributes['aria-busy'],'false');
  assert.equal(f.el('piSearchSummary').textContent,'1–1 of 1 invoices');
});

test('search, currency and clear controls request the correct filters',async()=>{
  const f=setup(()=>response());await settle();
  f.el('piSearch').value=' PI 123 ';f.el('piCurrency').value='INR';
  f.el('piSearchForm').onsubmit({preventDefault(){}});await settle();
  const query=new URLSearchParams(f.requests.at(-1).split('?')[1]);
  assert.equal(query.get('q'),'PI 123');assert.equal(query.get('currency'),'INR');
  f.el('piSearchReset').onclick();await settle();
  assert.equal(new URLSearchParams(f.requests.at(-1).split('?')[1]).get('q'),'');
  assert.equal(f.el('piCurrency').value,'all');
});

test('pagination requests the next page and historical PDFs are marked unavailable',async()=>{
  const f=setup(()=>response([{...invoice,workbook_format:'xlsm',pdf_url:null}],26,2));await settle();
  const files=f.el('piSearchRows').children[0].children[5].children[0].children;
  assert.equal(files[0].children[1].textContent,'Excel (.xlsm)');assert.equal(files[1].textContent,'PDF unavailable');
  assert.equal(f.el('piNext').disabled,false);f.el('piNext').onclick();await settle();
  assert.equal(new URLSearchParams(f.requests.at(-1).split('?')[1]).get('page'),'2');
  assert.equal(f.el('piPrevious').disabled,false);
});

test('failed searches stop loading and remove old download links',async()=>{
  let fail=false;
  const f=setup(()=>fail?{ok:false,json:async()=>({error:'Please sign in again.'})}:response());await settle();
  fail=true;f.el('piSearchForm').onsubmit({preventDefault(){}});await settle();
  assert.equal(f.el('piSearchButton').disabled,false);assert.equal(f.el('piSearchResults').attributes['aria-busy'],'false');
  assert.equal(f.errors[0],'Please sign in again.');
  assert.equal(f.el('piSearchRows').children[0].children[0].children[0].textContent,'Could not load invoices');
});

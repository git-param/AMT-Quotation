/* Waiting and confirmation behavior for serialized PI generation. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.style={};this.attributes={};this.classList={add(){},remove(){},toggle(){}};}
  append(...items){for(const item of items)item.parentElement=this;this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  addEventListener(event,handler){this["on"+event]=handler;}
  get firstChild(){return this.children[0];}
  get lastChild(){return this.children.at(-1);}
  setAttribute(key,value){this.attributes[key]=value;}
  querySelectorAll(tag){return this.children.flatMap(child=>[...(child.tag===tag?[child]:[]),...child.querySelectorAll(tag)]);}
  replaceWith(node){const parent=this.parentElement;const index=parent.children.indexOf(this);parent.children.splice(index,1,node);node.parentElement=parent;this.parentElement=null;}
  scrollIntoView(){}
  focus(){}
}

test('generation waits visibly and replaces the pending number only after confirmation',async()=>{
  const host=new Element('section'),timers=[],downloads=[];
  const state={preview_id:'pending',document:{reference:'PI-PENDING',reference_pending:true,
    date:'2026-10-28',currency:'USD',order:{pi_reference:'PI-PENDING'},delivery:{},assets:{},
    totals:{shipping:'0',lines:[]}},layout:{widths:[1],sections:[{name:'header',rows:[[
      {col:0,span:1,style:'bold',field:'order.pi_reference',value:'PI-PENDING',readonly:true}
    ]]}]}};
  let attempts=0;
  const context={window:{downloadPiFile:async(...args)=>downloads.push(args)},
    document:{createTextNode:text=>Object.assign(new Element('#text'),{textContent:text}),createElement:tag=>new Element(tag)},Date,
    setTimeout:callback=>{timers.push(callback);return timers.length;},clearTimeout(){}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/orders/pi-preview.js'),'utf8'),context);
  const widget=context.window.createPiPreview(host,async(url)=>{
    if(url.includes('?for_generation=1'))return state;
    attempts++;
    if(attempts===1)return {status:'waiting',message:'Another PI is being generated. Waiting…',retry_after_ms:1000};
    return {id:1,reference:'AMT/42',pdf_url:'/confirmed.pdf',pdf_filename:'PI-42.pdf',xlsx_url:'/confirmed.xlsx',xlsx_filename:'PI-42.xlsx'};
  },(method,data)=>({method,body:JSON.stringify(data)}),async()=>{});
  widget.open(state,'/api/orders/7/invoices/preview');
  const generation=host.querySelectorAll('button').find(button=>button.textContent==='Generate PDF').onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(host.attributes['aria-busy'],'true');
  assert.ok(host.querySelectorAll('button').every(button=>button.disabled));
  assert.ok(host.querySelectorAll('p').some(node=>/Another PI is being generated/.test(node.textContent)));
  assert.equal(state.document.reference,'PI-PENDING');
  assert.equal(downloads.length,0);
  timers.shift()();await generation;
  assert.equal(attempts,2);
  assert.equal(host.attributes['aria-busy'],'false');
  assert.equal(downloads[0][0],'/confirmed.pdf');
  assert.equal(host.querySelectorAll('input').find(input=>input.dataset.piField==='order.pi_reference').value,'AMT/42');
  assert.ok(host.querySelectorAll('button').every(button=>!button.disabled));
  await host.querySelectorAll('button').find(button=>button.textContent==='Generate XLSX').onclick();
  assert.equal(attempts,2);assert.equal(downloads[1][0],'/confirmed.xlsx');
});


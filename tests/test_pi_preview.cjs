/* Separate party inputs must still save one compatible party block. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');

class Element {
  constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.style={};this.attributes={};this.classList={add(){}};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(key,value){this.attributes[key]=value;}
  querySelectorAll(tag){return this.children.flatMap(child=>[...(child.tag===tag?[child]:[]),...child.querySelectorAll(tag)]);}
  scrollIntoView(){}
  focus(){}
}

test('PI party textareas keep multiline address and contact sections in one container',async()=>{
  const host=new Element('section');const requests=[];
  const state={preview_id:'preview',pdf_url:'/preview.pdf',document:{date:'2026-10-15',currency:'USD',prepared_phone:'',
    order:{destination:'USA'},delivery:{},assets:{},totals:{shipping:'0.00',lines:[]}},layout:{widths:[1],sections:[
      {name:'header',rows:[[{span:1,style:'',field:'order.destination',value:'USA',label:'Destination'}]]},
      {name:'parties',rows:[[{span:1,style:'',party:true,field:'delivery.consignee_text',value:'Original company\nStreet\nUSA\nTel: 1234567'},
        {span:1,style:'',party:true,field:'delivery.buyer_text',value:'Buyer company\nBuyer street\nUSA'}]]}
    ]}};
  const context={window:{},document:{createElement:tag=>new Element(tag),getElementById:()=>null},Date,
    fetch:async()=>({ok:true,json:async()=>['USA','INDIA']})};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/common/order-locations.js'),'utf8'),context);
  await context.window.orderLocations.ready;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/orders/pi-preview.js'),'utf8'),context);
  const preview=context.window.createPiPreview(host,async(url,options)=>{
    requests.push({url,body:JSON.parse(options.body)});return state;
  },(method,data)=>({method,body:JSON.stringify(data)}),async()=>{});
  preview.open(state,'/api/preview');
  const inputs=host.querySelectorAll('input');
  const [primary,details]=host.querySelectorAll('textarea');
  assert.equal(primary.value,'Original company\nStreet');
  assert.equal(details.value,'USA\nTel: 1234567');
  const group=host.querySelectorAll('div').find(item=>item.className==='pi-party-editor');
  assert.ok(group.querySelectorAll('textarea').includes(primary));
  assert.ok(group.querySelectorAll('textarea').includes(details));
  const buyerGroup=host.querySelectorAll('div').filter(item=>item.className==='pi-party-editor')[1];
  assert.equal(buyerGroup.querySelectorAll('textarea').length,1);
  assert.equal(buyerGroup.querySelectorAll('textarea')[0].value,'Buyer company\nBuyer street\nUSA');
  assert.equal(buyerGroup.querySelectorAll('details').length,0);
  primary.value='Updated company\nUpdated street\nCity, state 12345';details.value='USA\nTel: 1234567';primary.oninput();
  const country=inputs.find(input=>input.dataset.piField==='order.destination');
  country.value='INDIA';country.onchange();
  assert.equal(primary.value,'Updated company\nUpdated street\nCity, state 12345');assert.match(details.value,/^INDIA\n/);
  await host.querySelectorAll('button').find(button=>button.textContent==='Update preview').onclick();
  assert.equal(requests[0].body.delivery.consignee_text,'Updated company\nUpdated street\nCity, state 12345\n\nINDIA\nTel: 1234567');
  const printed=[];
  context.URL={createObjectURL:()=> 'blob:print-preview',revokeObjectURL(){}};
  context.fetch=async(url,options)=>{printed.push({url,body:JSON.parse(options.body)});return {ok:true,blob:async()=>({})};};
  const blank=host.querySelectorAll('textarea');blank.forEach(input=>{input.value='';});
  await host.querySelectorAll('button').find(button=>button.textContent==='PDF print preview').onclick();
  assert.equal(requests.length,1); // Printing bypasses the validated save API.
  assert.equal(printed[0].url,'/api/preview/preview/print');
  assert.equal(printed[0].body.delivery.consignee_text,'');
  assert.equal(host.querySelectorAll('iframe')[0].src,'blob:print-preview');
});

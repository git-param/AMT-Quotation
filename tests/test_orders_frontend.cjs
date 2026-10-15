/* Order workflow checks using a small DOM fixture and mocked scoped APIs. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tag = tag;this.children = [];this.value = '';this.hidden = true;
    this.classList = {add() {}};
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) {
    this.children = items;
    if (this.tag === 'select') this.value = items[0]?.value || '';
  }
  get options() { return this.children; }
  add(item) { this.children.push(item); }
  setAttribute() {}
  reset() {}
  scrollIntoView() {}
  focus(){this.focused=true;}
  querySelectorAll(selector) {
    const nodes = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === 'input:checked') return nodes.filter(node => node.tag === 'input' && node.checked);
    return nodes;
  }
}

function setup(search = '?client_id=9') {
  const nodes = new Map();
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, new Element(['enquiry','savedAddress'].includes(id) ? 'select' : 'div'));
    return nodes.get(id);
  };
  for (const [id,value] of [['currency','USD'],['status','draft'],['filterStatus','all'],['sort','date'],['direction','desc']]) element(id).value = value;
  const client = {id:9,name:'Client',company:'Company',email:'pic@example.com',phone:'+12345678901',can_edit:true,is_active:true,
    billing_address:{line1:'Billing',country:'India'},shipping_address:{line1:'Saved shipping',country:'India'}};
  const history = [{id:4,recorded_at:'2026-10-14T00:00:00Z',billing_address:client.billing_address,default_shipping_address:client.shipping_address}];
  const enquiry = {id:1,client_id:9,client_name:'Client',reference:'ENQ-001',deal_currency:'USD',can_edit:true,client_active:true};
  const order = {id:7,reference:'ORD-000007',client_id:9,enquiry_id:1,client_name:'Client',enquiry_reference:'ENQ-001',can_edit:true,can_delete:false,currency:'USD',status:'draft',order_date:'2026-10-14',created_at:'2026-10-14T00:00:00Z',owner_name:'Owner',creator_name:'Creator'};
  const data = {order,lines:[],subtotals:{},delivery:{billing_address:client.billing_address,shipping_address:client.shipping_address,consignee:{name:'Company'},buyer:{},notify_party:{}},delivery_history:[],revisions:[]};
  const requests = [];
  const listing = {orders:[],total:0,page:1,pages:0};
  let denied = false;
  const context = {
    window:{addEventListener(){},createPiPreview:()=>({reset(){},open(){}}),createSkuDraftEditor:()=>({reset(){},currencyChanged(){},values(){return [];} }),confirm:()=>true},
    document:{body:new Element(),getElementById:element,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)},
    location:{search},URLSearchParams,Intl,Date,
    Option: class extends Element { constructor(label,value){super('option');this.textContent=label;this.value=String(value);} },
    fetch:async (url,options={})=>{
      requests.push({url,options});
      if(denied)return {ok:false,status:403,json:async()=>({error:'Client access is read-only.'})};
      let response;
      if(url.startsWith('/api/orders?'))response=listing;
      else if(url==='/api/orders' && options.method==='POST')response=data;
      else if(url==='/api/orders/7')response=data;
      else if(url==='/api/orders/7/line-commercial-details'){const body=JSON.parse(options.body);for(const item of body.lines)Object.assign(data.lines.find(line=>line.id===item.id),item);response=data;}
      else if(url.startsWith('/api/enquiries?'))response={enquiries:[enquiry],pages:1};
      else if(url==='/api/enquiries/1')response={enquiry};
      else if(url==='/api/enquiries/1/lines')response={lines:[{id:2,sku:'SKU-A',description:'Part',quantity:'1',unit_price:'10.00',currency:'USD'}]};
      else if(url==='/api/leads/9')response={lead:client,address_history:history};
      else throw new Error('Unexpected request: '+url);
      return {ok:true,status:200,json:async()=>response};
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/orders/orders.js'),'utf8'),context);
  return {context,element,requests,data,listing,deny(){denied=true;}};
}
const settle = () => new Promise(resolve=>setImmediate(resolve));

test('party blocks are prefilled from editable client data without removed order header fields',async()=>{
  const fixture=setup();await settle();await fixture.context.createOrder();
  const block=fixture.element('consignee_text').value;
  assert.match(block,/Company/);assert.match(block,/Saved shipping/);assert.match(block,/Tel: \+12345678901/);assert.match(block,/Email: pic@example.com/);
  assert.equal(fixture.element('buyer_text').value,block);assert.equal(fixture.element('notify_text').value,block);
  fixture.element('consignee_text').value=block+'\nOrder-only instruction';fixture.element('consignee_text').oninput();
  await fixture.element('orderForm').onsubmit({preventDefault(){}});
  const request=fixture.requests.find(item=>item.url==='/api/orders'&&item.options.method==='POST');
  const body=JSON.parse(request.options.body);
  assert.equal(body.client_id,9);assert.deepEqual(body.lines,[]);
  for(const key of ['status','payment_terms','pi_reference','pi_date','enquiry_id'])assert.equal(body[key],undefined);
  assert.match(body.delivery.consignee_text,/Order-only instruction/);
  assert.equal(body.delivery.buyer_text,body.delivery.consignee_text);assert.equal(body.delivery.shipping_address,undefined);
});

test('buyer and notify stay editable and can independently follow or diverge from consignee',async()=>{
  const fixture=setup();await settle();await fixture.context.createOrder();
  const original=fixture.element('consignee_text').value;
  fixture.element('buyer_text').value=original+'\nBuyer-specific registration';fixture.element('buyer_text').oninput();
  assert.equal(fixture.element('buyer_same').checked,false);
  fixture.element('consignee_text').value=original+'\nConsignee revision';fixture.element('consignee_text').oninput();
  assert.match(fixture.element('buyer_text').value,/Buyer-specific registration/);
  assert.equal(fixture.element('notify_text').value,fixture.element('consignee_text').value);
  fixture.element('buyer_same').checked=true;fixture.element('buyer_same').onchange();
  assert.equal(fixture.element('buyer_text').value,fixture.element('consignee_text').value);
});

test('VIEW order detail hides editing and management controls',async()=>{
  const fixture=setup();await settle();fixture.data.order.can_edit=false;
  await fixture.context.showDetails(7);
  for(const id of ['editOrder','addLine','piForm'])assert.equal(fixture.element(id).hidden,true);
  await assert.rejects(()=>fixture.context.editOrder(7),/read-only/);
  assert.equal(fixture.element('recordLinks').children.length,1);
});

test('client scope constrains listing and rejects unrelated order details',async()=>{
  const fixture=setup('?client_id=9');await settle();
  assert.ok(fixture.requests.some(item=>item.url.startsWith('/api/orders?')&&item.url.includes('client_id=9')));
  fixture.data.order.client_id=10;
  await assert.rejects(()=>fixture.context.showDetails(7),/selected record/);
  fixture.deny();
  await assert.rejects(()=>fixture.context.showDetails(7),/read-only/);
  assert.equal(fixture.element('detail').hidden,true);
});

test('related order summaries preserve client scope and read-only navigation',async()=>{
  const fixture=setup();await settle();
  fixture.listing.orders=[fixture.data.order];fixture.listing.total=1;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/orders/related.js'),'utf8'),fixture.context);
  const host=new Element();
  await fixture.context.window.renderRelatedOrders(host,{client_id:9},false);
  const section=host.children[0];
  assert.equal(section.children[0].children[0].textContent,'Orders & Proforma Invoices');
  assert.equal(section.children[0].children.length,1); // VIEW has no Add order.
  assert.equal(section.children[2].children[0].textContent,'Pending drafts (1)');
  assert.equal(section.children[3].children[0].textContent,'Existing orders & PI references (1)');
  assert.ok(fixture.requests.some(item=>item.url.includes('client_id=9')&&item.url.includes('status=draft')));
  assert.ok(fixture.requests.some(item=>item.url.includes('exclude_drafts=1')));
});

 test('PI conversion asks for one explicit INR-per-USD rate and resets it for same-currency issuance',async()=>{
  const fixture=setup();await settle();await fixture.context.showDetails(7);
  fixture.element('piCurrency').value='INR';fixture.element('piCurrency').onchange();
  assert.equal(fixture.element('rateField').hidden,false);assert.equal(fixture.element('piRate').required,true);
  fixture.element('piRate').value='84.50';
  fixture.element('piCurrency').value='USD';fixture.element('piCurrency').onchange();
  assert.equal(fixture.element('rateField').hidden,true);assert.equal(fixture.element('piRate').value,'');
});


test('missing HSN and condition are editable in the item table and must be saved before PI',async()=>{
  const fixture=setup();await settle();
  fixture.data.lines=[{id:10,sku:'LEGACY-PART',description:'Imported part',quantity:'1',unit_price:'10.00',currency:'USD',line_total:'10.00',hsn_code:'',item_condition:''}];
  await fixture.context.showDetails(7);
  assert.equal(fixture.element('generatePi').disabled,false); // Metadata can be completed in the editable PI preview.
  assert.match(fixture.element('readinessTitle').textContent,/1 item needs PI details/);
  const row=fixture.element('lineRows').children[0];
  const hsn=row.children[4].children[0],condition=row.children[5].children[0];
  fixture.element('completeItemDetails').onclick();assert.equal(hsn.focused,true);
  hsn.value='85371090';hsn.oninput();condition.value='Used';condition.oninput();
  assert.equal(fixture.element('generatePi').disabled,true);assert.equal(fixture.element('saveItemDetails').disabled,false);
  await fixture.element('saveItemDetails').onclick();
  assert.equal(fixture.element('generatePi').disabled,false);
  assert.match(fixture.element('readinessTitle').textContent,/complete/);
  assert.ok(fixture.requests.some(request=>request.url.endsWith('/line-commercial-details')));
});

test('VIEW access keeps commercial fields read only',async()=>{
  const fixture=setup();await settle();fixture.data.order.can_edit=false;
  fixture.data.lines=[{id:10,sku:'PART',description:'Part',quantity:'1',unit_price:'10.00',currency:'USD',line_total:'10.00',hsn_code:'',item_condition:''}];
  await fixture.context.showDetails(7);
  assert.equal(fixture.element('saveItemDetails').hidden,true);
  assert.equal(fixture.element('lineRows').children[0].children[4].children.length,0);
});

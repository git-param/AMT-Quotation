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
  querySelectorAll(selector) {
    const nodes = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === 'input:checked') return nodes.filter(node => node.tag === 'input' && node.checked);
    return nodes;
  }
}

function setup(search = '') {
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
    window:{createSkuDraftEditor:()=>({reset(){},currencyChanged(){},values(){return [];} }),confirm:()=>true},
    document:{getElementById:element,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)},
    location:{search},URLSearchParams,Intl,Date,
    Option: class extends Element { constructor(label,value){super('option');this.textContent=label;this.value=String(value);} },
    fetch:async (url,options={})=>{
      requests.push({url,options});
      if(denied)return {ok:false,status:403,json:async()=>({error:'Client access is read-only.'})};
      let response;
      if(url.startsWith('/api/orders?'))response=listing;
      else if(url==='/api/orders' && options.method==='POST')response=data;
      else if(url==='/api/orders/7')response=data;
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

test('create order copies selected items and submits a private delivery address',async()=>{
  const fixture=setup();await settle();
  await fixture.context.createOrder();
  fixture.element('enquiry').value='1';await fixture.context.selectedEnquiry();
  assert.equal(fixture.element('shipping_line1').value,'Saved shipping');
  fixture.element('savedAddress').value='custom';fixture.context.savedAddressChanged();
  fixture.element('shipping_line1').value='Order-only street';
  fixture.element('shipping_country').value='USA';
  await fixture.element('orderForm').onsubmit({preventDefault(){}});
  const request=fixture.requests.find(item=>item.url==='/api/orders'&&item.options.method==='POST');
  const body=JSON.parse(request.options.body);
  assert.equal(body.enquiry_id,1);
  assert.deepEqual(body.source_line_ids,[2]);
  assert.equal(body.delivery.shipping_address.line1,'Order-only street');
  assert.equal(body.delivery.billing_address.line1,'Billing');
  assert.equal(body.delivery.consignee.name,'Company');
  assert.equal(body.delivery.saved_address_id,undefined);
});

test('saved address selection posts its version instead of editable defaults',async()=>{
  const fixture=setup();await settle();await fixture.context.createOrder();
  fixture.element('enquiry').value='1';await fixture.context.selectedEnquiry();
  await fixture.element('orderForm').onsubmit({preventDefault(){}});
  const request=fixture.requests.find(item=>item.url==='/api/orders'&&item.options.method==='POST');
  const body=JSON.parse(request.options.body);
  assert.equal(body.delivery.saved_address_id,4);
  assert.equal(body.delivery.saved_address_kind,'shipping');
  assert.equal(body.delivery.shipping_address,undefined);
});

test('VIEW order detail hides editing and management controls',async()=>{
  const fixture=setup();await settle();fixture.data.order.can_edit=false;
  await fixture.context.showDetails(7);
  for(const id of ['editOrder','addLine','copyMore'])assert.equal(fixture.element(id).hidden,true);
  await assert.rejects(()=>fixture.context.editOrder(7),/read-only/);
  assert.equal(fixture.element('recordLinks').children.length,2);
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
  assert.equal(section.children[0].children[0].textContent,'Orders (1)');
  const controls=section.children[0].children[1];
  assert.equal(controls.children.length,1);
  assert.equal(controls.children[0].href,'/orders?client_id=9');
  assert.equal(section.children[1].href,'/orders?client_id=9&order_id=7');
  assert.ok(fixture.requests.some(item=>item.url==='/api/orders?client_id=9&page_size=5'));
});

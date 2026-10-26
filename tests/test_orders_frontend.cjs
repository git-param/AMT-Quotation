/* Order workflow checks using a small DOM fixture and mocked scoped APIs. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tag = tag;this.children = [];this.value = '';this.hidden = true;this.attributes={};
    this.classList = {add() {}};
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) {
    this.children = items;
    if (this.tag === 'select') this.value = items[0]?.value || '';
  }
  get options() { return this.children; }
  add(item) { this.children.push(item); }
  setAttribute(key,value) {this.attributes[key]=value;}
  reset() {}
  scrollIntoView() {}
  focus(){this.focused=true;}
  remove(){this.removed=true;}
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
  const piDefaults = {pi_prefix: ''};
  const listing = {orders:[],total:0,page:1,pages:0};
  let denied = false;
  const context = {
    window:{addEventListener(){},parent:{postMessage(){}},createPiPreview:()=>({reset(){},open(){}}),createSkuDraftEditor:()=>({reset(){},currencyChanged(){},values(){return [];} }),confirm:()=>true},
    document:{body:new Element(),getElementById:element,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)},
    location:{search},URLSearchParams,Intl,Date,
    Option: class extends Element { constructor(label,value){super('option');this.textContent=label;this.value=String(value);} },
    fetch:async (url,options={})=>{
      requests.push({url,options});
      if(denied)return {ok:false,status:403,json:async()=>({error:'Client access is read-only.'})};
      let response;
      if(url==='/static/common/countries.json')response=JSON.parse(fs.readFileSync(path.join(__dirname,'../frontend/common/countries.json'),'utf8'));
      else if(url.startsWith('/api/orders/deletions?'))response={deletions:[{reference:'ORD-000007',actor_name:'Owner',deleted_at:'2026-10-15T12:00:00Z'}]};
      else if(url==='/api/orders/pi-defaults')response=piDefaults;
      else if(url.startsWith('/api/orders?'))response=listing;
      else if(url==='/api/orders' && options.method==='POST')response=data;
      else if(url==='/api/orders/7')response=data;
      else if(url==='/api/orders/7/status'){data.order.status=JSON.parse(options.body).status;response={order:data.order};}
      else if(url==='/api/orders/7/invoices/12'&&options.method==='DELETE')response={message:'PI removed.'};
      else if(url==='/api/orders/7/discount'){data.order.discount=options.method==='DELETE'?null:JSON.parse(options.body);response=data;}
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
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/common/sku-feedback.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/common/order-locations.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/orders/orders.js'),'utf8'),context);
  return {context,element,requests,data,listing,piDefaults,deny(){denied=true;}};
}
const settle = () => new Promise(resolve=>setImmediate(resolve));

test('new orders prefill the department prefix and keep the full PI reference editable',async()=>{
  const f=setup();await settle();f.piDefaults.pi_prefix='PUC';
  await f.context.createOrder();
  assert.equal(f.element('pi_reference').value,'PUC/');
  assert.equal(f.element('pi_reference').readOnly,false);
  f.element('pi_reference').value='CUSTOM/123214';
  f.element('order_date').value='2026-10-17';
  await f.element('orderForm').onsubmit({preventDefault(){}});
  assert.equal(JSON.parse(f.requests.find(r=>r.url==='/api/orders'&&r.options.method==='POST').options.body).pi_reference,'CUSTOM/123214');
  f.data.order.pi_reference='SAVED/001';f.data.order.destination='INDIA';f.piDefaults.pi_prefix='NEW';
  await f.context.editOrder(7);
  assert.equal(f.element('pi_reference').value,'SAVED/001');
  f.data.order.pi_reference='';f.data.pi_defaults={pi_prefix:'AMT'};
  await f.context.editOrder(7);
  assert.equal(f.element('pi_reference').value,'AMT/');
});

test('party blocks are prefilled from editable client data without removed order header fields',async()=>{
  const fixture=setup();await settle();await fixture.context.createOrder();
  const block=fixture.element('consignee_text').value;
  assert.match(block,/Company/);assert.match(block,/Saved shipping/);assert.match(block,/Tel\/Phone: \+12345678901/);assert.match(block,/Email: pic@example.com/);
  assert.equal(fixture.element('buyer_text').value,fixture.context.window.orderLocations.addressOnly(block));assert.equal(fixture.element('notify_text').value,fixture.context.window.orderLocations.addressOnly(block));
  fixture.element('consignee_text').value=block+'\nOrder-only instruction';fixture.element('consignee_text').oninput();
  await fixture.element('orderForm').onsubmit({preventDefault(){}});
  const request=fixture.requests.find(item=>item.url==='/api/orders'&&item.options.method==='POST');
  const body=JSON.parse(request.options.body);
  assert.equal(body.client_id,9);assert.deepEqual(body.lines,[]);
  for(const key of ['status','payment_terms','pi_date','enquiry_id','notes'])assert.equal(body[key],undefined);
  assert.equal(body.pi_reference,'');assert.equal(body.delivery.instructions,undefined);
  assert.match(body.delivery.consignee_text,/Order-only instruction/);
  assert.equal(body.delivery.buyer_text,fixture.context.window.orderLocations.addressOnly(body.delivery.consignee_text));assert.equal(body.delivery.shipping_address,undefined);
});

test('new orders keep multiline address and contact sections together with delivery defaults',async()=>{
  const fixture=setup();await settle();await fixture.context.createOrder();
  assert.equal(fixture.element('delivery_terms').value,'DAP');
  assert.equal(fixture.element('delivery_time').value,'4 to 6 business days');
  assert.equal(fixture.element('dispatch_method').value,'DHL/Fedex/Aramex');
  assert.match(fixture.element('consignee_primary').value,/Company\nSaved shipping/);
  assert.match(fixture.element('consignee_details').value,/Country: India/);
  fixture.element('pi_reference').value='SALES/001';
  fixture.element('consignee_primary').value='Updated company\nNew street\nCity, state 12345';fixture.element('consignee_primary').oninput();
  fixture.element('consignee_details').value='INDIA\nTel: +12345678901';fixture.element('consignee_details').oninput();
  assert.match(fixture.element('buyer_primary').value,/Updated company\nNew street\nCity, state 12345/);
  await fixture.element('orderForm').onsubmit({preventDefault(){}});
  const saved=JSON.parse(fixture.requests.find(item=>item.url==='/api/orders'&&item.options.method==='POST').options.body);
  assert.equal(saved.pi_reference,'SALES/001');
  assert.match(saved.delivery.consignee_text,/^Updated company\nNew street\nCity, state 12345\n\nINDIA/);
  assert.equal(saved.delivery.buyer_text,fixture.context.window.orderLocations.addressOnly(saved.delivery.consignee_text));
});

test('buyer and notify stay editable and can independently follow or diverge from consignee',async()=>{
  const fixture=setup();await settle();await fixture.context.createOrder();
  const original=fixture.element('consignee_text').value;
  fixture.element('buyer_text').value=original+'\nBuyer-specific registration';fixture.element('buyer_text').oninput();
  assert.equal(fixture.element('buyer_same').checked,false);
  fixture.element('consignee_text').value=original+'\nConsignee revision';fixture.element('consignee_text').oninput();
  assert.match(fixture.element('buyer_text').value,/Buyer-specific registration/);
  assert.equal(fixture.element('notify_text').value,fixture.context.window.orderLocations.addressOnly(fixture.element('consignee_text').value));
  fixture.element('buyer_same').checked=true;fixture.element('buyer_same').onchange();
  assert.equal(fixture.element('buyer_text').value,fixture.context.window.orderLocations.addressOnly(fixture.element('consignee_text').value));
});

test('country suggestions sync the consignee and set INR and show consignee GST only for India',async()=>{
  const fixture=setup();await settle();await fixture.context.createOrder();
  const options=fixture.element('orderCountries').children.map(option=>option.value);
  assert.ok(options.includes('USA'));assert.ok(options.includes('INDIA'));
  assert.equal(new Set(options).size,options.length);
  assert.equal(fixture.element('consigneeGstField').hidden,false);
  fixture.element('consigneeGst').value='24AAGMO289C1ZP';fixture.element('consigneeGst').oninput();
  assert.match(fixture.element('consignee_text').value,/GST No\.: 24AAGMO289C1ZP/);
  assert.doesNotMatch(fixture.element('buyer_text').value,/GST No/);
  assert.equal(fixture.element('currency').value,'INR');
  assert.equal(fixture.element('buyer_same').checked,true);
  fixture.element('destination').value='usa';fixture.element('destination').onchange();
  assert.equal(fixture.element('consigneeGstField').hidden,true);
  assert.equal(fixture.element('destination').value,'USA');
  assert.match(fixture.element('consignee_text').value,/\nUSA\n/);
  assert.doesNotMatch(fixture.element('consignee_text').value,/Country: India/);
  fixture.element('destination').value='india';fixture.element('destination').onchange();
  assert.equal(fixture.element('consigneeGstField').hidden,false);
  assert.equal(fixture.element('consigneeGst').value,'24AAGMO289C1ZP');
  await fixture.element('orderForm').onsubmit({preventDefault(){}});
  const saved=JSON.parse(fixture.requests.find(item=>item.url==='/api/orders'&&item.options.method==='POST').options.body);
  assert.equal(saved.destination,'INDIA');
  assert.match(saved.delivery.consignee_text,/GST No\.: 24AAGMO289C1ZP/);
  assert.doesNotMatch(saved.delivery.buyer_text,/GST No/);
  assert.doesNotMatch(saved.delivery.buyer_text,/^(?:Country: ?)?INDIA$/im);
  assert.doesNotMatch(saved.delivery.notify_text,/^(?:Country: ?)?INDIA$/im);
  assert.equal(saved.currency,'INR');
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
  assert.equal(section.children[2].children[0].children[0].textContent,'Pending orders');
  assert.equal(section.children[2].children[0].children[1].textContent,'1');
  assert.equal(section.children[3].children[0].children[0].textContent,'Complete orders');
  assert.equal(section.children[3].children[2].hidden,true);
  assert.ok(fixture.requests.some(item=>item.url.includes('client_id=9')&&item.url.includes('completion=pending')));
  assert.ok(fixture.requests.some(item=>item.url.includes('completion=complete')));
});

 test('PI conversion uses the quotation rate without requesting an executive-entered rate',async()=>{
  const fixture=setup();await settle();await fixture.context.showDetails(7);
  fixture.element('piCurrency').value='INR';fixture.element('piCurrency').onchange();
  assert.match(fixture.element('conversionHint').textContent,/quotation tool exchange rate.*automatically/);
  fixture.element('piCurrency').value='USD';fixture.element('piCurrency').onchange();
  assert.match(fixture.element('conversionHint').textContent,/saved prices/);
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

test('order deletion requires confirmation and hides the deleted detail',async()=>{
  const fixture=setup();await settle();fixture.data.order.can_delete_order=true;
  await fixture.context.showDetails(7);
  assert.equal(fixture.element('deleteOrder').hidden,false);
  const prompts=[];
  fixture.context.window.confirm=text=>{prompts.push(text);return false;};
  await fixture.element('deleteOrder').onclick();
  assert.equal(fixture.requests.filter(request=>request.options.method==='DELETE').length,0);
  assert.match(prompts[0],/ORD-000007/);
  fixture.context.window.confirm=()=>true;
  await fixture.element('deleteOrder').onclick();
  assert.equal(fixture.requests.filter(request=>request.url==='/api/orders/7'&&request.options.method==='DELETE').length,1);
  assert.equal(fixture.element('detail').hidden,true);
});

test('order cards confirm deletion and expose actor and timestamp in the log',async()=>{
  const fixture=setup();await settle();fixture.data.order.can_delete_order=true;
  fixture.listing.orders=[fixture.data.order];fixture.listing.total=1;fixture.listing.pages=1;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/orders/related.js'),'utf8'),fixture.context);
  const host=new Element();await fixture.context.window.renderRelatedOrders(host,{client_id:9},true);
  const section=host.children[0];const entry=section.children[2].children[1].children[0];
  const remove=entry.children[1];assert.equal(remove.children[0].tag,'svg');
  fixture.context.window.confirm=()=>false;await remove.onclick();
  assert.equal(fixture.requests.filter(item=>item.options.method==='DELETE').length,0);
  fixture.context.window.confirm=()=>true;await remove.onclick();
  assert.equal(fixture.requests.filter(item=>item.url==='/api/orders/7'&&item.options.method==='DELETE').length,1);
  const log=section.children.at(-1);log.open=true;await log.ontoggle();
  assert.match(log.children[1].children[0].textContent,/ORD-000007 — deleted by Owner/);
  assert.ok(fixture.requests.some(item=>item.url==='/api/orders/deletions?client_id=9'));
});

test('composer presents one continuous form with references and location first',async()=>{
  const f=setup();await settle();await f.context.createOrder();
  assert.equal(f.element('save').textContent,'Save draft');
  assert.equal(f.element('cancel').hidden,false);
  const html=fs.readFileSync(path.join(__dirname,'../frontend/orders/orders.html'),'utf8');
  const form=html.slice(html.indexOf('<form id="orderForm"'),html.indexOf('<section id="detail"'));
  assert.doesNotMatch(form,/composer-steps|composer-stage|previousStage|nextStage/);
  const positions=['pi_reference','po_reference','destination','currency','order_date','delivery_terms','delivery_time','dispatch_method','shipping_charges','consignee_primary'].map(id=>form.indexOf('id="'+id+'"'));
  assert.ok(positions.every((position,index)=>position>=0&&(!index||position>positions[index-1])));
  assert.doesNotMatch(form,/<details/);
});

test('embedded order composer uses the outer close control only',async()=>{
  const f=setup('?client_id=9&embedded=1');await settle();await f.context.createOrder();
  assert.equal(f.element('cancel').hidden,true);
});

test('completion toggle switches both ways without clearing unsaved form edits',async()=>{
  const f=setup();await settle();Object.assign(f.data.order,{destination:'USA',shipping_charges:'0',po_reference:'',pi_reference:'',delivery_terms:'DAP',delivery_time:'4 days',dispatch_method:'Courier'});await f.context.editOrder(7);
  f.element('po_reference').value='Unsaved PO';
  assert.equal(f.element('composerStatus').textContent,'Complete');
  await f.element('composerStatus').onclick();
  assert.equal(f.data.order.status,'completed');
  assert.equal(f.element('composerStatus').textContent,'Move to pending');
  assert.equal(f.element('po_reference').value,'Unsaved PO');
  await f.element('composerStatus').onclick();
  assert.equal(f.data.order.status,'draft');
  assert.equal(f.element('composerStatus').textContent,'Complete');
});

test('completion actions stay hidden for read-only and cancelled orders',async()=>{
  const f=setup();await settle();f.data.order.can_edit=false;await f.context.showDetails(7);
  assert.equal(f.element('toggleOrderStatus').hidden,true);
  f.data.order.can_edit=true;f.data.order.status='cancelled';await f.context.showDetails(7);
  assert.equal(f.element('toggleOrderStatus').hidden,true);
});

test('invoice minus button confirms removal and calls only the selected record endpoint',async()=>{
  const f=setup();await settle();f.data.order.can_delete_order=true;await f.context.showDetails(7);
  f.context.appendInvoice({id:12,reference:'PI-9215',currency:'USD',workbook_format:'xlsx',has_pdf:true},7);
  const row=f.element('invoiceList').children[0],button=row.children.at(-1);
  assert.equal(button.textContent,'\u2212');assert.equal(button.attributes['aria-label'],'Remove PI PI-9215');
  f.context.window.confirm=()=>false;await button.onclick();
  assert.equal(f.requests.filter(item=>item.options.method==='DELETE').length,0);
  f.context.window.confirm=()=>true;await button.onclick();
  assert.ok(f.requests.some(item=>item.url==='/api/orders/7/invoices/12'&&item.options.method==='DELETE'));
  assert.equal(row.removed,true);
});

test('saved invoice downloads use the server PI filename for Excel and PDF',async()=>{
  const f=setup();await settle();
  const downloads=[];f.context.window.downloadPiFile=async (...args)=>downloads.push(args);
  f.context.appendInvoice({id:12,reference:'AMT/9233',currency:'USD',workbook_format:'xlsx',has_pdf:true},7);
  const row=f.element('invoiceList').children[0];
  await row.children[1].onclick({preventDefault(){}});
  await row.children[2].onclick({preventDefault(){}});
  assert.equal(downloads.length,2);
  assert.equal(downloads[0][0],'/api/orders/7/invoices/12/download?format=xlsx');
  assert.equal(downloads[1][0],'/api/orders/7/invoices/12/download?format=pdf');
  assert.ok(downloads.every(args=>args.length===1));
});

test('workspace header toggles status through its own iframe and refreshes lists',async()=>{
  const f=setup();await settle();f.context.location.origin='http://localhost';
  let handler;
  f.context.window.addEventListener=(_,callback)=>{handler=callback;};
  f.listing.orders=[f.data.order];f.listing.total=1;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/orders/related.js'),'utf8'),f.context);
  const host=new Element();await f.context.window.renderRelatedOrders(host,{client_id:9},false);
  const section=host.children[0],dialog=section.children[1],frame=dialog.children[1];
  dialog.showModal=()=>{};
  let sent;
  frame.contentWindow={postMessage:data=>{sent=data;}};
  section.children[2].children[1].children[0].onclick();
  const button=dialog.children[0].children[1].children[0];
  handler({origin:'http://other',source:frame.contentWindow,data:{type:'amt-order-state',order:f.data.order}});
  assert.equal(button.hidden,true);
  handler({origin:'http://localhost',source:frame.contentWindow,data:{type:'amt-order-state',order:f.data.order}});
  assert.equal(button.hidden,false);assert.equal(button.textContent,'Complete');
  button.onclick();assert.equal(sent.type,'amt-order-toggle-status');assert.equal(button.disabled,true);
  handler({origin:'http://localhost',source:frame.contentWindow,data:{type:'amt-order-state',order:{...f.data.order,status:'completed'},busy:false}});
  assert.equal(button.textContent,'Move to pending');assert.equal(button.disabled,false);
  await settle();assert.ok(f.requests.filter(request=>request.url.includes('completion=complete')).length>=2);
});

test('linked parties stay compact; custom party edits reopen with saved data',async()=>{
  const f=setup();await settle();await f.context.createOrder();
  assert.equal(f.element('buyerEditor').hidden,true);assert.equal(f.element('notifyEditor').hidden,true);
  f.element('buyer_same').checked=false;f.element('buyer_same').onchange();
  assert.equal(f.element('buyerEditor').hidden,false);assert.equal(f.element('buyer_primary').focused,true);
  f.element('buyer_primary').value='Separate buyer\nBuyer street';f.element('buyer_primary').oninput();
  f.element('consignee_primary').value='Consignee\nNew shipping';f.element('consignee_primary').oninput();
  assert.equal(f.element('buyerSummary').textContent,'Separate buyer\nBuyer street');
  assert.match(f.element('notifySummary').textContent,/New shipping/);
  Object.assign(f.data.order,{destination:'INDIA',po_reference:'',pi_reference:'',delivery_terms:'DAP',delivery_time:'4 to business 6 days',dispatch_method:'Courier',shipping_charges:'0'});
  f.data.delivery.buyer_text='Separate buyer\nBuyer street';
  await f.context.editOrder(7);
  assert.equal(f.element('buyerEditor').hidden,false);assert.equal(f.element('notifyEditor').hidden,true);
  assert.equal(f.element('buyer_primary').value,'Separate buyer\nBuyer street');
  assert.equal(f.element('save').textContent,'Save changes');
  assert.equal(f.element('editingItemsHint').hidden,false);
});

test('save failure retains the draft and displays a dismissible popup instead of a top message',async()=>{
  const f=setup();await settle();await f.context.createOrder();
  f.element('consignee_primary').value='Unsaved recipient';f.element('consignee_primary').oninput();
  const realFetch=f.context.fetch;
  f.context.fetch=async(url,options)=>url==='/api/orders'?{ok:false,status:500,json:async()=>({error:'Please retry saving.'})}:realFetch(url,options);
  await f.element('orderForm').onsubmit({preventDefault(){}});
  assert.equal(f.element('formError').hidden,true);assert.equal(f.element('message').textContent,'');
  const notice=f.context.document.body.children.find(child=>child.className==='sku-feedback').children[1];
  assert.equal(notice.hidden,false);assert.equal(notice.attributes.role,'alert');
  assert.equal(notice.children[0].children[1].textContent,'Please retry saving.');
  notice.children[1].onclick();assert.equal(notice.hidden,true);
  assert.equal(f.element('consignee_primary').value,'Unsaved recipient');assert.equal(f.element('save').disabled,false);
  f.context.fetch=realFetch;await f.element('orderForm').onsubmit({preventDefault(){}});
  assert.equal(f.element('editor').hidden,true);
});

test('stock save shows the reason for loading and always stops the spinner on failure',async()=>{
  const f=setup();await settle();
  let complete;
  f.context.fetch=()=>new Promise(resolve=>{complete=resolve;});
  const pending=f.context.api('/api/orders/7/lines/3',{method:'PUT',body:'{"quantity":"10"}'});
  const progress=f.context.document.body.children.find(child=>child.className==='sku-feedback').children[0];
  assert.equal(progress.hidden,false);assert.equal(progress.attributes['aria-busy'],'true');
  assert.equal(progress.children[0].children[0].textContent,'Checking stock before saving');
  assert.match(progress.children[0].children[1].textContent,/current stock.*requested quantity/);
  complete({ok:false,status:400,json:async()=>({error:'SKU 3456: only 0 available.'})});
  await assert.rejects(pending,/only 0 available/);
  assert.equal(progress.hidden,true);assert.equal(progress.attributes['aria-busy'],'false');
});

test('pending drafts resume in the composer and enforce client scope',async()=>{
  const f=setup('?client_id=9&order_id=7&edit=1');
  Object.assign(f.data.order,{destination:'INDIA',po_reference:'',pi_reference:'',delivery_terms:'DAP',delivery_time:'4 to 6 business days',dispatch_method:'Courier',shipping_charges:'0'});
  await settle();await settle();
  assert.equal(f.element('editor').hidden,false);assert.equal(f.element('save').textContent,'Save changes');
  f.data.order.client_id=10;
  await assert.rejects(()=>f.context.editOrder(7),/selected record/);
});

test('bulk description is required only above four order products',async()=>{
  const f=setup();await settle();
  const line={id:1,sku:'PART',description:'Part',quantity:'1',unit_price:'10.00',currency:'USD',line_total:'10.00',hsn_code:'85371090',item_condition:'New',uom:'PCs'};
  f.data.lines=Array.from({length:4},(_,index)=>({...line,id:index+1}));await f.context.showDetails(7);
  assert.equal(f.element('bulkDescriptionField').hidden,true);assert.equal(f.element('bulkDescription').required,false);
  f.data.lines.push({...line,id:5});await f.context.showDetails(7);
  assert.equal(f.element('bulkDescriptionField').hidden,false);assert.equal(f.element('bulkDescription').required,true);
});

test('discount form defaults to percentage and saves selected SKUs and PI visibility',async()=>{
  const f=setup();await settle();
  const line={id:1,sku:'PART',description:'Part',quantity:'1',unit_price:'10.00',currency:'USD',line_total:'10.00',hsn_code:'85371090',item_condition:'New',uom:'PCs'};
  f.data.lines=[line,{...line,id:2,sku:'SECOND'}];await f.context.showDetails(7);
  f.element('giveDiscount').onclick();
  assert.equal(f.element('discountForm').hidden,false);assert.equal(f.element('discountType').value,'percent');
  assert.equal(f.element('discountShow').checked,true);
  f.element('discountScope').value='multiple';f.element('discountScope').onchange();
  assert.equal(f.element('discountSkus').hidden,false);
  f.element('discountSkuChoices').children.forEach(label=>{label.children[0].checked=true;});
  f.element('discountValue').value='15';f.element('discountShow').checked=false;
  await f.context.persistDiscount();
  assert.deepEqual(JSON.parse(f.requests.find(request=>request.url.endsWith('/discount')).options.body),{type:'percent',value:'15',scope:'multiple',line_ids:[1,2],show_on_pi:false});
  assert.match(f.element('discountSummary').textContent,/Hidden in PI/);
  f.element('giveDiscount').onclick();assert.equal(f.element('discountValue').value,'15');
  await f.context.persistDiscount(true);assert.equal(f.data.order.discount,null);
});

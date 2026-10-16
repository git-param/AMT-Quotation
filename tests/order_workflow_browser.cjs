/* Real-browser integration test. Run against an isolated fixture server with a
   browser-fixture account: node tests/order_workflow_browser.cjs <base> <CDP port>. */
(async()=>{
const assert=require('node:assert/strict'),fs=require('node:fs');
const [base,debug]=process.argv.slice(2);
const targets=process.env.CDP_TARGETS?JSON.parse(process.env.CDP_TARGETS):await new Promise((resolve,reject)=>require('node:http').get(`http://127.0.0.1:${debug}/json/list`,response=>{let body='';response.on('data',chunk=>body+=chunk);response.on('end',()=>resolve(JSON.parse(body)));}).on('error',reject));
const ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',()=>reject(Error('CDP WebSocket connection failed')),{once:true});});
let sequence=0;const pending=new Map(),errors=[];
ws.addEventListener('message',event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);});
const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
const evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
async function until(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out: '+expression+'; '+await evaluate("document.querySelector('#message')?.textContent")+'; '+errors.join('; '));}
const click=id=>evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
const set=(id,value,event='input')=>evaluate(`(()=>{const n=document.getElementById(${JSON.stringify(id)});n.value=${JSON.stringify(value)};n.dispatchEvent(new Event(${JSON.stringify(event)},{bubbles:true}));})()`);
const shot=async name=>{await new Promise(r=>setTimeout(r,150));const r=await send('Page.captureScreenshot',{format:'png'});fs.writeFileSync('.verification/'+name+'.png',Buffer.from(r.data,'base64'));};
try{
await send('Runtime.enable');await send('Page.enable');await send('Emulation.setDeviceMetricsOverride',{width:1366,height:960,deviceScaleFactor:1,mobile:false});
await send('Page.navigate',{url:base+'/login'});await until("document.querySelector('#username')");
assert.equal(await evaluate("fetch('/login',{method:'POST',body:new URLSearchParams({username:'browser-fixture',password:'local-fixture-only'})}).then(r=>r.ok)"),true);
const client=await evaluate(`fetch('/api/leads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Order Workflow Fixture',company:'Northstar Industrial',email:'orders@example.com',phone:'+919876543210',shipping_address:{line1:'12 Industrial Estate',city:'Mumbai',country:'India'}})}).then(r=>r.json())`);
assert.ok(client.lead?.id,JSON.stringify(client));const clientId=client.lead.id;
await send('Page.navigate',{url:base+'/orders?client_id='+clientId+'&new=1'});
await until("!document.querySelector('#editor')?.hidden && document.querySelector('#referenceHint').textContent.includes('Northstar Industrial')");
assert.equal(await evaluate("document.querySelector('#currency').value"),'INR');
assert.equal(await evaluate("document.querySelector('#save').textContent"),'Save draft');
assert.equal(await evaluate("document.querySelectorAll('.composer-stage,.composer-steps,#nextStage,#previousStage').length"),0);
assert.deepEqual(await evaluate("[...document.querySelectorAll('#orderForm .composer-fields input,#orderForm .composer-fields select')].slice(0,4).map(n=>n.id)"),['pi_reference','po_reference','destination','currency']);
assert.equal(await evaluate("['pi_reference','po_reference','destination','currency','shipping_charges','consignee_primary'].every(id=>document.getElementById(id).getClientRects().length>0)"),true);
await shot('order-composer-basics-desktop');
// Required fields are focused on Save without navigating sections.
await set('order_date','');await click('save');
assert.equal(await evaluate("document.activeElement.id"),'order_date');

await set('order_date','2026-10-16');

assert.equal(await evaluate("document.querySelector('#buyerEditor').hidden"),true);
assert.equal(await evaluate("document.querySelector('#notifyEditor').hidden"),true);
assert.equal(await evaluate("document.querySelector('#consigneeGstField').hidden"),false);
await set('consigneeGst','24AAGMO289C1ZP');
await set('consignee_primary','Northstar Industrial\n12 Industrial Estate\nMumbai 400001');
assert.match(await evaluate("document.querySelector('#buyerSummary').textContent"),/Mumbai 400001/);
assert.doesNotMatch(await evaluate("document.querySelector('#buyerSummary').textContent"),/GST|Tel|PIC|Email/);
await click('buyer_same');assert.equal(await evaluate("document.activeElement.id"),'buyer_primary');
await set('buyer_primary','Independent Buyer\n1 Billing Street');
await set('consignee_primary','Northstar Industrial\nUpdated shipping address');
assert.match(await evaluate("document.querySelector('#buyer_text').value"),/Independent Buyer/);
assert.match(await evaluate("document.querySelector('#notify_text').value"),/Updated shipping address/);
await set('destination','usa','change');assert.equal(await evaluate("document.querySelector('#consigneeGstField').hidden"),true);
await set('destination','india','change');assert.equal(await evaluate("document.querySelector('#consigneeGst').value"),'24AAGMO289C1ZP');
await shot('order-composer-delivery-desktop');
// Invalid shipping charges remain visible and receive focus.
await evaluate("document.querySelector('#shipping_charges').value='-1'");
await click('save');
assert.equal(await evaluate("document.activeElement.id"),'shipping_charges');
await set('shipping_charges','15.25');

// A failed request retains values and offers an inline accessible error.
await evaluate("window.realFetch=window.fetch;window.fetch=(url,options)=>url==='/api/orders'&&options?.method==='POST'?Promise.resolve(new Response(JSON.stringify({error:'Fixture save failure; please retry.'}),{status:500,headers:{'Content-Type':'application/json'}})):window.realFetch(url,options)");
await click('save');await until("!document.querySelector('#formError').hidden");
assert.match(await evaluate("document.querySelector('#buyer_primary').value"),/Independent Buyer/);
assert.equal(await evaluate("document.querySelector('#save').disabled"),false);
await evaluate("window.fetch=window.realFetch");await click('save');await until("!document.querySelector('#detail').hidden");
const orderId=await evaluate("current.order.id");
let record=await evaluate(`fetch('/api/orders/${orderId}').then(r=>r.json())`);
assert.equal(record.order.status,'draft');assert.equal(record.lines.length,0);assert.match(record.delivery.buyer_text,/Independent Buyer/);assert.match(record.delivery.notify_text,/Updated shipping/);assert.match(record.delivery.consignee_text,/24AAGMO289C1ZP/);
// Reopen the saved draft, complete references, and retain separate party snapshots.
await click('editOrder');await until("!document.querySelector('#editor').hidden");
assert.equal(await evaluate("document.querySelector('#buyerEditor').hidden"),false);assert.equal(await evaluate("document.querySelector('#notifyEditor').hidden"),true);
await set('pi_reference','WORKFLOW/2026/001');await set('po_reference','PO-WORKFLOW-001');
await click('save');await until("!document.querySelector('#detail').hidden");
await click('addLine');await evaluate("[...document.querySelectorAll('#lineDrafts button')].find(b=>b.textContent==='Add manual SKU').click()");
await until("document.querySelector('#lineDrafts [aria-label=\"HSN code\"]')?.value==='85371090'");
await evaluate("(()=>{for(const [label,value] of Object.entries({'SKU / item code':'WORKFLOW-PART','Description':'Browser tested part','Quantity':'2','Agreed unit price (INR)':'100','HSN code':'85371090','Item condition':'New','Unit of measure':'PCs'})){const n=document.querySelector('#lineDrafts [aria-label=\"'+label+'\"]');if(!n)throw Error(label);n.value=value;n.dispatchEvent(new Event('input',{bubbles:true}));}[...document.querySelectorAll('#lineDrafts button')].find(b=>b.textContent==='Save all SKU lines').click();})()");
await until("document.querySelector('#lineRows').textContent.includes('WORKFLOW-PART')");
await set('piCurrency','INR','change');await evaluate("document.querySelector('#piForm').requestSubmit()");await until("document.querySelector('#piPreview .pi-paper')");
assert.ok(await evaluate("document.querySelector('#piPreview').textContent.includes('BANK') || document.querySelector('#piPreview').textContent.toLowerCase().includes('bank')"));
await evaluate("[...document.querySelectorAll('#piPreview button')].find(b=>b.textContent==='Generate XLSX').click()");
await until("document.querySelector('#invoiceList a')");
const downloads=await evaluate("Promise.all([...document.querySelectorAll('#invoiceList a')].map(async a=>{const r=await fetch(a.href);const b=await r.arrayBuffer();return {ok:r.ok,size:b.byteLength,format:new URL(a.href).searchParams.get('format')};}))");
assert.equal(downloads.length,2);assert.ok(downloads.every(d=>d.ok&&d.size>100));
// Initial SKU lines also save through the new-order composer.
await click('newOrder');await until("!document.querySelector('#editor').hidden");await click('manualToggle');
await evaluate("[...document.querySelectorAll('#initialDrafts button')].find(b=>b.textContent==='Add manual SKU').click()");
await until("document.querySelector('#initialDrafts [aria-label=\"HSN code\"]')?.value==='85371090'");
await click('save');await until("document.activeElement.matches(':invalid') || !document.querySelector('#formError').hidden");
await evaluate("(()=>{for(const [label,value] of Object.entries({'SKU / item code':'INITIAL-PART','Description':'Initial draft part','Quantity':'3','Agreed unit price (INR)':'25.50','Item condition':'New'})){const n=document.querySelector('#initialDrafts [aria-label=\"'+label+'\"]');n.value=value;n.dispatchEvent(new Event('input',{bubbles:true}));}})()");
await click('buyer_same');await set('buyer_primary','Mobile Buyer\nBilling Street');
await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
await shot('order-composer-delivery-mobile');
assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
await shot('order-composer-review-mobile');assert.equal(await evaluate("document.documentElement.scrollWidth<=innerWidth"),true);
await click('save');await until("!document.querySelector('#detail').hidden");
record=await evaluate("fetch('/api/orders/'+current.order.id).then(r=>r.json())");
assert.equal(record.lines.length,1);assert.equal(record.lines[0].quantity,'3');assert.equal(record.lines[0].unit_price,'25.50');assert.match(record.delivery.buyer_text,/Mobile Buyer/);
// Exercise the actual Clients & Orders iframe too.
await send('Page.navigate',{url:base+'/clients-orders'});await until("document.querySelector('#leads')?.textContent.includes('Order Workflow Fixture')");
await evaluate("[...document.querySelectorAll('#leads button')].find(b=>b.getAttribute('aria-label')?.includes('Order Workflow Fixture') && b.getAttribute('aria-label')?.startsWith('View details')).click()");
await until("document.querySelector('.related-orders .btn-add')");await evaluate("document.querySelector('.related-orders .btn-add').click()");
await until("document.querySelector('iframe')?.contentWindow.document.querySelector('#editor') && !document.querySelector('iframe').contentWindow.document.querySelector('#editor').hidden");
assert.equal(await evaluate("document.querySelector('iframe').contentWindow.document.documentElement.scrollWidth<=document.querySelector('iframe').contentWindow.innerWidth"),true);
assert.equal(await evaluate("document.querySelector('iframe').contentWindow.getComputedStyle(document.querySelector('iframe').contentWindow.document.querySelector('#cancel')).display"),'none');
assert.equal(await evaluate("document.querySelectorAll('.order-dialog-header button').length"),1);
await shot('order-composer-embedded-mobile');
// The desktop composer should expose the header fields and all party cards at once.
for(const [width,height] of [[1920,947],[1366,900]]){
  await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
  await evaluate("(()=>{const w=document.querySelector('iframe').contentWindow;w.scrollTo(0,0);})()");
  assert.equal(await evaluate("(()=>{const w=document.querySelector('iframe').contentWindow,d=w.document,footer=d.querySelector('.composer-footer').getBoundingClientRect();return ['pi_reference','po_reference','destination','currency','order_date','delivery_terms','delivery_time','dispatch_method','shipping_charges','consignee_primary','consignee_details','buyerSummary','notifySummary','manualToggle'].every(id=>{const r=d.getElementById(id).getBoundingClientRect();return r.width>0&&r.top>=0&&r.bottom<=footer.top;})&&footer.bottom<=w.innerHeight;})()"),true,`All initial order details fit at ${width} x ${height}`);
  await shot('order-composer-all-details-'+width);
}

await evaluate("document.querySelector('.order-dialog').close()");
await send('Emulation.setDeviceMetricsOverride',{width:1366,height:960,deviceScaleFactor:1,mobile:false});
await until("document.querySelector('.order-card-group .related-order-card')");
await evaluate("document.querySelector('.order-card-group .related-order-card').click()");
await until("document.querySelector('iframe')?.contentWindow.document.querySelector('#editor') && !document.querySelector('iframe').contentWindow.document.querySelector('#editor').hidden");
assert.equal(await evaluate("document.querySelector('iframe').contentWindow.document.querySelector('#save').textContent"),'Save changes');
await shot('order-composer-resume-desktop');

// Real mixed lookup: valid SKU saves independently, missing SKU offers manual entry.
const inFrame=code=>evaluate(`(async()=>{const w=document.querySelector('iframe').contentWindow,d=w.document;${code}})()`);
await evaluate("document.querySelector('.order-dialog').close()");
await until("!document.querySelector('.order-dialog').open && document.querySelector('iframe').getAttribute('src')==='about:blank'");
await evaluate("document.querySelector('.related-orders .btn-add').click()");
await until("document.querySelector('iframe')?.contentWindow.document.querySelector('#editor') && !document.querySelector('iframe').contentWindow.document.querySelector('#editor').hidden");
await inFrame("d.getElementById('manualToggle').click();const input=d.querySelector('#initialDrafts [aria-label=\"SKU codes\"]');input.value='LOOKUP-AVAILABLE, LOOKUP-MISSING';[...d.querySelectorAll('#initialDrafts button')].find(b=>b.textContent==='Look Up SKUs').click()");
await until("document.querySelector('iframe').contentWindow.document.querySelector('#initialDrafts .draft-lookup-notice')?.textContent.includes('LOOKUP-MISSING')");
assert.match(await inFrame("return d.querySelector('#initialDrafts .draft-lookup-notice').textContent"),/not found.*manually/);
assert.equal(await inFrame("return d.querySelectorAll('#initialDrafts .draft-product-row').length"),1);
await shot('order-mixed-sku-lookup');
await inFrame("d.getElementById('save').click()");
await until("!document.querySelector('iframe').contentWindow.document.getElementById('detail').hidden");
let mixed=await inFrame("return w.fetch('/api/orders/'+w.eval('current.order.id')).then(r=>r.json())");
assert.equal(mixed.lines.length,1);assert.equal(mixed.lines[0].sku,'LOOKUP-AVAILABLE');assert.equal(mixed.lines[0].hsn_code,'85371090');
await inFrame("d.getElementById('addLine').click();d.querySelector('#lineDrafts [aria-label=\"SKU codes\"]').value='LOOKUP-MISSING';[...d.querySelectorAll('#lineDrafts button')].find(b=>b.textContent==='Look Up SKUs').click()");
await until("document.querySelector('iframe').contentWindow.document.querySelector('#lineDrafts .draft-lookup-notice button')");
await inFrame("d.querySelector('#lineDrafts .draft-lookup-notice button').click()");
await until("document.querySelector('iframe').contentWindow.document.querySelector('#lineDrafts [aria-label=\"SKU / item code\"]')?.value==='LOOKUP-MISSING'");
assert.equal(await inFrame("return d.querySelector('#lineDrafts [aria-label=\"HSN code\"]').value"),'85371090');
await inFrame("for(const [label,value] of Object.entries({'Description':'Missing SKU entered manually','Quantity':'2','Agreed unit price (INR)':'150','Item condition':'New'})){const n=d.querySelector('#lineDrafts [aria-label=\"'+label+'\"]');n.value=value;n.dispatchEvent(new w.Event('input',{bubbles:true}));}[...d.querySelectorAll('#lineDrafts button')].find(b=>b.textContent==='Save all SKU lines').click()");
await until("document.querySelector('iframe').contentWindow.document.querySelector('#lineRows').textContent.includes('LOOKUP-MISSING')");
mixed=await inFrame("return w.fetch('/api/orders/'+w.eval('current.order.id')).then(r=>r.json())");
assert.equal(mixed.lines.length,2);assert.ok(mixed.lines.every(line=>line.hsn_code==='85371090'));
assert.deepEqual(errors,[]);
console.log('Browser workflow passed: draft creation, single-form field order, required validation, save failure/retry, party synchronization, country/GST, reopen/edit, SKU persistence, automatic manual HSN, mixed lookup/manual recovery, INR PI XLSX/PDF, desktop/mobile and embedded layout.');
}finally{ws.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');

class Element{
  constructor(){this.children=[];this.attributes={};}
  append(...items){this.children.push(...items);}
  setAttribute(key,value){this.attributes[key]=value;}
}
function setup(){
  const body=new Element();const context={window:{},document:{body,createElement:()=>new Element()}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/common/sku-feedback.js'),'utf8'),context);
  return {feedback:context.window.skuFeedback,progress:body.children[0].children[0],notice:body.children[0].children[1]};
}
test('lookup progress explains the wait and stays visible until all requests finish',()=>{
  const {feedback,progress}=setup();
  const stopLookup=feedback.startRequest('/api/enquiries/sku-lookup',{method:'POST'});
  assert.equal(progress.hidden,false);assert.equal(progress.children[0].children[0].textContent,'Looking up SKU details');
  assert.match(progress.children[0].children[1].textContent,/prices and available quantities/);
  const stopSave=feedback.startRequest('/api/orders/7/lines/bulk',{method:'POST'});
  stopLookup();assert.equal(progress.hidden,false);
  assert.equal(progress.children[0].children[0].textContent,'Checking stock before saving');
  stopSave();assert.equal(progress.hidden,true);stopSave();assert.equal(progress.hidden,true);
});
test('errors stay until dismissed and display message content as text',()=>{
  const {feedback,notice}=setup();
  feedback.show('SKU <script>: requested 10, but only 0 available.',true);
  assert.equal(notice.hidden,false);assert.equal(notice.attributes.role,'alert');
  assert.equal(notice.children[0].children[1].textContent,'SKU <script>: requested 10, but only 0 available.');
  notice.children[1].onclick();assert.equal(notice.hidden,true);
});
test('new draft saves explain stock validation while ordinary reads show no spinner',()=>{
  const {feedback,progress}=setup();
  feedback.startRequest('/api/orders/7');assert.equal(progress.hidden,true);
  const done=feedback.startRequest('/api/orders',{method:'POST',body:JSON.stringify({lines:[{sku:'PART'}]})});
  assert.equal(progress.hidden,false);assert.match(progress.children[0].children[1].textContent,/saved after the check passes/);
  done();assert.equal(progress.hidden,true);
});

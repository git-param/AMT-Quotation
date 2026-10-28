const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');

function setup(){
  const nodes=new Map(),requests=[];
  const el=id=>{
    if(!nodes.has(id))nodes.set(id,{value:'',hidden:true,attributes:{},
      setAttribute(key,value){this.attributes[key]=value;},
      removeAttribute(key){delete this.attributes[key];},
      replaceChildren(){},focus(){this.focused=true;},
      scrollIntoView(){this.scrolled=true;}});
    return nodes.get(id);
  };
  const context={el,current:{order:{id:7,currency:'USD'},lines:[]},
    api:async(url,options)=>{
      requests.push({url,options});
      if(url==='/api/pi-discount-limit')return {maximum_percent:'10'};
      throw new Error('Discount exceeds the administrator limit of 10%.');
    },json:(method,data)=>({method,body:JSON.stringify(data)}),message(){},showDetails(){}};
  vm.createContext(context);
  const source=fs.readFileSync('frontend/orders/orders.js','utf8');
  vm.runInContext(source.slice(source.indexOf('let discountChoices='),source.indexOf('function action(')),context);
  return {context,el,requests};
}

test('discount form prominently states the loaded maximum and highlights excessive percentages',async()=>{
  const {el,requests}=setup();
  el('giveDiscount').onclick();
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(el('discountLimitHint').textContent,/Discount must not exceed 10%/);
  el('discountValue').value='11';el('discountValue').oninput();
  assert.equal(el('discountValue').attributes['aria-invalid'],'true');
  assert.equal(el('discountError').hidden,false);
  assert.match(el('discountError').textContent,/Enter a lower discount/);
  assert.equal(requests.length,1);
  el('discountValue').value='9';el('discountValue').oninput();
  assert.equal(el('discountValue').attributes['aria-invalid'],undefined);
  assert.equal(el('discountError').hidden,true);
});

test('rejected discount focuses and scrolls the invalid value field after reaching the backend',async()=>{
  const {context,el,requests}=setup();
  el('giveDiscount').onclick();
  await new Promise(resolve=>setImmediate(resolve));
  el('discountValue').value='11';
  await vm.runInContext('persistDiscount()',context);
  assert.equal(requests.at(-1).url,'/api/orders/7/discount');
  assert.equal(el('discountValue').focused,true);
  assert.equal(el('discountValue').scrolled,true);
  assert.equal(el('discountValue').attributes['aria-invalid'],'true');
  assert.match(el('discountError').textContent,/10%.*lower discount/);
  assert.equal(el('applyDiscount').disabled,false);
});

test('fixed amount mode explains that the same percentage cap applies',async()=>{
  const {el}=setup();
  el('giveDiscount').onclick();
  await new Promise(resolve=>setImmediate(resolve));
  el('discountType').value='amount';el('discountType').onchange();
  assert.match(el('discountLimitHint').textContent,/10%.*amount entered must stay within this percentage/);
  assert.match(el('discountLimitHint').textContent,/before shipping and tax/);
});

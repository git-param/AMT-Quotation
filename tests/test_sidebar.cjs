/* Verify shared navigation without changing backend authorization. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const vm=require('node:vm');

class Element {
  constructor(tag){
    this.tag=tag;this.children=[];this.attributes={};this.classes=new Set();
    this.classList={add:value=>this.classes.add(value),contains:value=>this.classes.has(value),toggle:(value,on)=>on?this.classes.add(value):this.classes.delete(value)};
    this.style={removeProperty(key){delete this[key];}};
  }
  set className(value){this.classes=new Set(value.split(/\s+/));}
  get className(){return [...this.classes].join(' ');}
  append(...items){for(const item of items){if(item.parent)item.parent.children=item.parent.children.filter(child=>child!==item);item.parent=this;this.children.push(item);}}
  prepend(item){this.append(item);this.children.unshift(this.children.pop());}
  replaceChildren(...items){this.children=[];this.append(...items);}
  setAttribute(key,value){this.attributes[key]=value;}
  getAttribute(key){return this.attributes[key]??null;}
  removeAttribute(key){delete this.attributes[key];}
  querySelectorAll(selector){const nodes=this.children.flatMap(child=>[child,...child.querySelectorAll('*')]);return selector==='a[href]'?nodes.filter(item=>item.tag==='a'&&item.getAttribute('href')):nodes;}
  querySelector(){return this.querySelectorAll('a[href]')[0];}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(child=>child!==this);this.parent=null;}
  focus(){this.focused=true;}
}

async function setup(user,mobile=false){
  const body=new Element('body');const header=new Element('header');body.append(header);
  const original={};
  for(const [url,id] of [['/enquiries',''],['/leads',''],['/client-access','accessLink'],['/sources','sourcesLink'],['/manager','mgrLink'],['/logout','']]){
    const link=new Element('a');link.setAttribute('href',url);link.id=id;header.append(link);original[url]=link;
    if(url==='/manager')link.setAttribute('target','_blank');
  }
  const media={matches:mobile,addEventListener(){}};
  const events={};
  const context={document:{body,querySelector:()=>header,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),addEventListener:(key,callback)=>events[key]=callback},window:{matchMedia:()=>media},URLSearchParams,location:{search:'',pathname:'/leads'},fetch:async()=>({ok:true,json:async()=>user})};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/common/sidebar.js'),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  return {body,header,original,sidebar:body.children[0],events};
}

test('header links move to sidebar with original IDs and active-page state',async()=>{
  const view=await setup({role:'admin',permissions:['management.view','sources.manage','leads.share_manage','settings.manage']});
  assert.equal(view.header.querySelectorAll('a[href]').length,0);
  assert.equal(view.original['/client-access'].id,'accessLink');
  assert.equal(view.original['/manager'].getAttribute('target'),null);
  assert.equal(view.sidebar.children[1].children.find(row=>row.children[0].href==='/clients-orders').children[0].attributes['aria-current'],'page');
  const rows=view.sidebar.children[1].children;
  assert.equal(rows.length,8);
  assert.ok(rows.every(row=>!row.hidden));
  assert.ok(rows.some(row=>row.children[0].href==='/clients-orders'));
  assert.ok(rows.some(row=>row.children[0].href==='/search-pi'));
});

test('executives do not see management, source, or sharing links',async()=>{
  const view=await setup({role:'sales_executive',permissions:['quotation.use']});
  for(const url of ['/manager','/sources','/client-access'])assert.equal(view.original[url].parent.hidden,true);
  assert.equal(view.original['/leads'].parent,null);
  assert.equal(view.sidebar.children[1].children.find(row=>row.children[0].href==='/configuration').hidden,true);
  assert.ok(!view.sidebar.children[1].children.some(row=>['/leads','/enquiries','/orders'].includes(row.children[0].href)));
});

test('mobile menu opens accessibly and Escape closes it',async()=>{
  const view=await setup({role:'sales_tl',permissions:['sources.manage','leads.share_manage']},true);
  const toggle=view.header.children[0];
  assert.equal(view.sidebar.inert,true);
  toggle.onclick();
  assert.equal(view.sidebar.inert,false);
  assert.equal(toggle.attributes['aria-expanded'],'true');
  view.events.keydown({key:'Escape'});
  assert.equal(view.sidebar.inert,true);
  assert.equal(toggle.attributes['aria-expanded'],'false');
});

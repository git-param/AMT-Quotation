const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),test=require('node:test');
function setup(response){
  const links=[],revoked=[];
  const context={window:{},fetch:async()=>response,URL:{createObjectURL:()=> 'blob:invoice',revokeObjectURL:url=>revoked.push(url)},setTimeout:callback=>callback(),
    document:{body:{append:link=>links.push(link)},createElement:()=>({click(){this.clicked=true;},remove(){this.removed=true;}})}};
  vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/common/downloads.js','utf8'),context);
  return {download:context.window.downloadPiFile,links,revoked};
}
test('blocked PDF downloads expose the specific warning without starting a file download',async()=>{
  const f=setup({ok:false,json:async()=>({error:'Missing: Consignee GST No., Consignee Tel/Phone'})});
  await assert.rejects(()=>f.download('/invoice.pdf'),/Consignee GST No\./);
  assert.equal(f.links.length,0);
});
test('validated downloads preserve the invoice filename and clean up the temporary URL',async()=>{
  const f=setup({ok:true,headers:{get:()=> 'attachment; filename="AMT-123214.pdf"'},blob:async()=>({})});
  await f.download('/invoice.pdf');
  assert.equal(f.links[0].download,'AMT-123214.pdf');assert.equal(f.links[0].clicked,true);assert.equal(f.links[0].removed,true);
  assert.deepEqual(f.revoked,['blob:invoice']);
});

const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),test=require('node:test');
async function setup(){
 const context={window:{},document:{getElementById:()=>null},fetch:async url=>({ok:true,json:async()=>JSON.parse(fs.readFileSync('frontend/common/'+url.split('/').at(-1),'utf8'))})};
 vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/common/order-locations.js','utf8'),context);
 await context.window.orderLocations.ready;return context.window.orderLocations;
}
test('local consignee numbers get calling codes from the selected country without duplicating explicit codes',async()=>{
 const loc=await setup();
 assert.match(loc.countryBlock('Company\nStreet\nTel: 2025550123','USA'),/Tel\/Phone: \+1 2025550123/);
 assert.match(loc.countryBlock('Company\nStreet\nTel: 0501234567','UAE'),/Tel\/Phone: \+971 501234567/);
 assert.match(loc.countryBlock('Company\nStreet\nTel: 02012345678','UK'),/Tel\/Phone: \+44 2012345678/);
 assert.match(loc.countryBlock('Company\nStreet\nTel: +919876543210','USA'),/Tel\/Phone: \+919876543210/);
 assert.match(loc.countryBlock('Company\nStreet\nTel:','CANADA'),/Tel\/Phone: \+1$/);
});

const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');const path=require('node:path');const read=name=>fs.readFileSync(path.join(__dirname,name),'utf8');
function ui(){const ctx={};vm.createContext(ctx);vm.runInContext(read('ui.js'),ctx);return ctx.UsageUI;}
test('countdowns handle reset boundaries, days and missing times',()=>{const u=ui(),now=Date.now();assert.equal(u.remaining(null,now),'Reset time unavailable');assert.equal(u.remaining(new Date(now-1).toISOString(),now),'Awaiting reset');assert.equal(u.remaining(new Date(now+60000).toISOString(),now),'Resets in 1m');assert.equal(u.remaining(new Date(now+90000000).toISOString(),now),'Resets in 1d 1h');});
test('missing usage is distinct from zero and unsafe errors are escaped',()=>{const u=ui(),root={querySelector:()=>({addEventListener(){}}),innerHTML:''};u.render(root,{data:{five_hour:{utilization:0},seven_day:null},error:'<script>bad</script>'});assert.match(root.innerHTML,/100% available/);assert.match(root.innerHTML,/Not reported/);assert.doesNotMatch(root.innerHTML,/<script>/);assert.match(root.innerHTML,/&lt;script&gt;/);});
test('display clamps out of range readings and shows high usage color',()=>{const root={querySelector:()=>({addEventListener(){}}),innerHTML:''};ui().render(root,{data:{five_hour:{utilization:130},seven_day:{utilization:-3}}});assert.match(root.innerHTML,/width:100%/);assert.match(root.innerHTML,/width:0%/);assert.match(root.innerHTML,/#d77850/);});
async function contentHarness(responses,cookie='lastActiveOrg=org-1',roundedComposer=false){
 let listener,observer;const requests=[];let mounted=false;let sideMounted=false;const sideAnchor={nextElementSibling:null,getClientRects:()=>[{}],closest:s=>s==='li'?null:{getBoundingClientRect:()=>({width:240})},after(el){this.nextElementSibling=el;sideMounted=true;}};const anchor={nextElementSibling:null,after(el){this.nextElementSibling=el;},lastElementChild:null,append(el){this.lastElementChild=el;el.parentElement=this;mounted=true;}};if(roundedComposer){anchor.matches=()=>false;anchor.querySelector=()=>({});}const editor={parentElement:roundedComposer?anchor:null,getClientRects:()=>[{}],closest:selector=>selector.includes('fieldset')?anchor:null};const child=()=>({style:{},remove(){mounted=false;},append(){},querySelector(){return {addEventListener(){}};}});const host=child();host.attachShadow=()=>child();const context={UsageUI:{render(){},renderCredit(){}},MutationObserver:class{constructor(callback){observer=callback;}observe(){}disconnect(){}},requestAnimationFrame:callback=>callback(),document:{body:{},querySelectorAll:selector=>selector.startsWith('nav ')?[sideAnchor]:[editor],cookie,hidden:false,getElementById(){return null;},createElement(){const element=child();element.attachShadow=()=>child();return element;},documentElement:{append(){}},addEventListener(){},removeEventListener(){}},chrome:{runtime:{id:'test-extension',getURL:s=>s,onMessage:{addListener:f=>listener=f}},storage:{local:{get:async()=>({}),set:async()=>{}}}},setInterval(){},clearInterval(){},getComputedStyle:()=>({borderTopLeftRadius:'16px',borderTopWidth:'1px',backgroundColor:'rgb(48, 48, 46)'}),AbortSignal,fetch:async path=>{requests.push(path);const r=responses.shift();return {ok:r.status===undefined||r.status===200,status:r.status||200,json:async()=>r.data};}};vm.createContext(context);vm.runInContext(read('content.js'),context);await new Promise(r=>setImmediate(r));return {invalidate:()=>{delete context.chrome.runtime.id;observer();},requests,anchor,isSidebarMounted:()=>sideMounted,isMounted:()=>mounted,remount:()=>{anchor.lastElementChild=null;mounted=false;observer();},read:()=>new Promise(resolve=>listener({type:'quiet-usage'},{},resolve))};
}
test('requests selected organization and returns real usage',async()=>{const org={data:[{uuid:'org-1'},{uuid:'org-2'}]},usage={data:{five_hour:{utilization:75},seven_day:{utilization:67}}};const h=await contentHarness([org,usage,org,usage]);const result=await h.read();assert.equal(result.data.five_hour.utilization,75);assert.deepEqual(h.requests,['/api/organizations','/api/organizations/org-1/usage','/api/organizations','/api/organizations/org-1/usage']);});
test('ambiguous organizations and expired sessions show actionable errors',async()=>{const org={data:[{uuid:'one'},{uuid:'two'}]};const h=await contentHarness([org,org],'');assert.match((await h.read()).error,/Choose an organization/);assert.equal(h.requests.some(p=>p.endsWith('/usage')),false);const unauthorized=await contentHarness([{status:401},{status:401}]);assert.match((await unauthorized.read()).error,/Sign in/);});

test('usage attaches inside composer and reattaches after navigation',async()=>{const org={data:[{uuid:'org-1'}]},usage={data:{five_hour:{utilization:12}}};const h=await contentHarness([org,usage]);assert.equal(h.isMounted(),true);assert.equal(h.anchor.lastElementChild.id,"quiet-claude-usage");h.remount();assert.equal(h.isMounted(),true);});
test('manifest has no popup or storage permissions',()=>{const m=JSON.parse(read('manifest.json'));assert.equal(m.action,undefined);assert.equal(m.permissions,undefined);assert.deepEqual(m.host_permissions,['https://claude.ai/*']);});

test('sidebar attaches below Projects using the same account request',async()=>{const h=await contentHarness([{data:[{uuid:'org-1'}]},{data:{five_hour:{utilization:25}}}]);assert.equal(h.isSidebarMounted(),true);assert.equal(h.requests.length,2);});
test('sidebar displays both usage windows and orange bars',()=>{const root={querySelector:()=>({}),innerHTML:''};ui().render(root,{sidebar:true,data:{five_hour:{utilization:75},seven_day:{utilization:67}}});assert.match(root.innerHTML,/usage sidebar/);assert.match(root.innerHTML,/Session/);assert.match(root.innerHTML,/Weekly/);assert.match(root.innerHTML,/#df9464/);assert.match(root.innerHTML,/#dba477/);});

test('text-only credit appears in both layouts',()=>{
  for(const sidebar of [false,true]){
    const root={querySelector:()=>({}),innerHTML:''};ui().render(root,{sidebar});
    assert.match(root.innerHTML,/© By Alna/);assert.doesNotMatch(root.innerHTML,/<img/);
  }
});
test('changing the credit prevents UI rendering',()=>{
  const context={};vm.createContext(context);
  vm.runInContext(read('ui.js').replace("const credit = 'By Alna'", "const credit = 'By Someone Else'"),context);
  assert.throws(()=>context.UsageUI.render({}),/Attribution integrity check failed/);
});

test('credit is the final footer after usage metrics',()=>{
 const root={querySelector:()=>({}),innerHTML:''};ui().render(root,{data:{five_hour:{utilization:25}}});
 assert.match(root.innerHTML,/<footer class="credit-footer"><span class="attribution"/);
 assert.ok(root.innerHTML.indexOf('credit-footer')>root.innerHTML.indexOf('class="details"'));
 assert.match(root.innerHTML,/© By Alna<\/span><\/footer><\/div>$/);
});

test('uses the rounded message box even when it has no fieldset or form',async()=>{
 const h=await contentHarness([{data:[{uuid:'org-1'}]},{data:{five_hour:{utilization:25}}}], 'lastActiveOrg=org-1',true);
 assert.equal(h.isMounted(),true);
 assert.equal(h.anchor.lastElementChild.id,'quiet-claude-usage');
});

test('composer credit sits outside the message box while usage remains inside',async()=>{
 const h=await contentHarness([{data:[{uuid:'org-1'}]},{data:{five_hour:{utilization:25}}}]);
 assert.equal(h.anchor.lastElementChild.id,'quiet-claude-usage');
 assert.equal(h.anchor.nextElementSibling.id,'quiet-claude-usage-credit');
 const u=ui(),root={querySelector:()=>({}),innerHTML:''};
 u.render(root,{composer:true,data:{five_hour:{utilization:25}}});
 assert.match(root.innerHTML,/Session/);assert.doesNotMatch(root.innerHTML,/credit-footer/);
 u.renderCredit(root);assert.match(root.innerHTML,/© By Alna/);assert.doesNotMatch(root.innerHTML,/class="details"/);
});

test('extension reload stops the old content script and further requests',async()=>{
 const h=await contentHarness([{data:[{uuid:'org-1'}]},{data:{five_hour:{utilization:25}}}]);
 assert.equal(h.isMounted(),true);h.invalidate();assert.equal(h.isMounted(),false);
 await h.read();assert.equal(h.requests.length,2);
});

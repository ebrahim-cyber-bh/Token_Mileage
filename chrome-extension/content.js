(() => {
  if(document.getElementById('quiet-claude-usage')) return;
  const host=document.createElement('div');host.id='quiet-claude-usage';
  host.style.cssText='display:block;width:100%;min-width:0;grid-column:1 / -1;flex:0 0 100%;';
  const shadow=host.attachShadow({mode:'open'}), css=document.createElement('link');
  css.rel='stylesheet';css.href=chrome.runtime.getURL('ui.css');shadow.append(css);
  const root=document.createElement('div');shadow.append(root);
  const sideHost=document.createElement('div');sideHost.id='quiet-claude-usage-sidebar';
  sideHost.style.cssText='display:block;width:100%;min-width:0;flex:0 0 auto;grid-column:1 / -1;';
  const sideShadow=sideHost.attachShadow({mode:'open'}),sideCss=document.createElement('link');
  sideCss.rel='stylesheet';sideCss.href=chrome.runtime.getURL('ui.css');sideShadow.append(sideCss);
  const sideRoot=document.createElement('div');sideShadow.append(sideRoot);
  const creditHost=document.createElement('div');creditHost.id='quiet-claude-usage-credit';
  creditHost.style.cssText='display:block;width:100%;min-width:0;grid-column:1 / -1;flex:0 0 100%;padding:2px 14px 4px;';
  const creditShadow=creditHost.attachShadow({mode:'open'}),creditCss=document.createElement('link');
  creditCss.rel='stylesheet';creditCss.href=chrome.runtime.getURL('ui.css');creditShadow.append(creditCss);
  const creditRoot=document.createElement('div');creditShadow.append(creditRoot);
  UsageUI.renderCredit(creditRoot);
  let state={},pending,stopped=false,timer;
  function stop(){
    if(stopped)return;
    stopped=true;
    observer.disconnect();clearInterval(timer);
    document.removeEventListener('visibilitychange',onVisible);
    host.remove();sideHost.remove();creditHost.remove();
  }
  function alive(){
    if(stopped)return false;
    try{if(chrome.runtime.id)return true;}catch{}
    stop();return false;
  }
  function onVisible(){if(!document.hidden)refresh();}
  function draw(){if(!alive())return;UsageUI.render(root,{...state,composer:true},{refresh});UsageUI.render(sideRoot,{...state,sidebar:true},{refresh});}
  function mountSidebar(){
    const links=document.querySelectorAll('nav a[href="/projects"], nav a[href="/projects/"], aside a[href="/projects"], aside a[href="/projects/"], [data-testid="sidebar"] a[href="/projects"], [data-testid="sidebar"] a[href="/projects/"]');
    const link=Array.from(links).find(e=>{
      const sidebar=e.closest('nav, aside, [data-testid="sidebar"]');
      return e.getClientRects().length && sidebar?.getBoundingClientRect().width>=180;
    });
    if(!link){sideHost.remove();return;}
    // Insert a sibling without moving Claude's existing navigation elements.
    const anchor=link.closest('li') || link;
    if(anchor.nextElementSibling!==sideHost)anchor.after(sideHost);
  }
  function mount(){
    if(!alive())return;
    mountSidebar();
    const editors=document.querySelectorAll('[data-testid="chat-input"] [contenteditable="true"], [data-testid="chat-input"][contenteditable="true"], .ProseMirror[contenteditable="true"], fieldset [contenteditable="true"], [data-testid="chat-input"] textarea, [contenteditable="true"][role="textbox"], [data-placeholder][contenteditable="true"]');
    const editor=Array.from(editors).find(e=>e.getClientRects().length && !e.closest('[role="dialog"]'));
    if(!editor){host.remove();creditHost.remove();return;}
    // Prefer the visible rounded composer, rather than the outer form (which
    // can also contain the model selector below the message box).
    let anchor=null;
    let fallback=null;
    for(let candidate=editor.parentElement,i=0;candidate && i<12;i++,candidate=candidate.parentElement){
      if(candidate.matches('main, body, [role="dialog"]'))break;
      const controls=candidate.querySelector('button');
      if(!controls)continue;
      if(!fallback)fallback=candidate;
      const style=getComputedStyle(candidate);
      const rounded=parseFloat(style.borderTopLeftRadius)>8;
      const surface=style.backgroundColor && !['transparent','rgba(0, 0, 0, 0)'].includes(style.backgroundColor);
      const bordered=parseFloat(style.borderTopWidth)>0;
      if(rounded && (surface || bordered)){anchor=candidate;break;}
    }
    anchor=anchor || fallback || editor.closest('[data-testid="chat-input"]:not([contenteditable="true"]), fieldset, form');
    if(!anchor || anchor===editor){host.remove();creditHost.remove();return;}
    if(host.parentElement!==anchor || anchor.lastElementChild!==host)anchor.append(host);
    if(anchor.nextElementSibling!==creditHost)anchor.after(creditHost);
  }
  let scheduled=false;
  const observer=new MutationObserver(()=>{
    if(scheduled)return;scheduled=true;
    requestAnimationFrame(()=>{scheduled=false;mount();});
  });
  observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['class','hidden','aria-expanded']});
  mount();
  async function request(path){const response=await fetch(path,{credentials:'include',cache:'no-store',signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error(response.status===401||response.status===403?'Sign in to Claude, then refresh.':response.status===429?'Claude is busy. Try again in a minute.':'Usage is temporarily unavailable.');return response.json();}
  async function load(){
    state.loading=true;draw();
    try {
      const orgs=await request('/api/organizations');
      if(!Array.isArray(orgs)||!orgs.length)throw new Error('Sign in to Claude, then refresh.');
      let cookieOrg='';try{cookieOrg=decodeURIComponent(document.cookie.split('; ').find(c=>c.startsWith('lastActiveOrg='))?.split('=').slice(1).join('=')||'');}catch{}
      const org=orgs.find(o=>o.uuid===cookieOrg)||(orgs.length===1?orgs[0]:null);
      if(!org)throw new Error('Choose an organization in Claude, then refresh.');
      if(!/^[a-zA-Z0-9-]+$/.test(org.uuid))throw new Error('Could not identify your Claude account.');
      const data=await request(`/api/organizations/${org.uuid}/usage`);
      if(!data||!['five_hour','seven_day'].some(k=>typeof data[k]?.utilization==='number'))throw new Error('Claude returned an unfamiliar usage format.');
      state={...state,data,updated:Date.now(),error:null};
    } catch(e){state.error=e.message||'Could not connect to Claude.';}
    finally{state.loading=false;draw();}
    return {...state};
  }
  function refresh(){if(!alive())return Promise.resolve({...state});if(!pending)pending=load().finally(()=>pending=null);return pending;}
  chrome.runtime.onMessage.addListener((msg,sender,reply)=>{if(msg.type!=='quiet-usage')return;refresh().then(reply);return true;});
  refresh();
  timer=setInterval(onVisible,60000);
  document.addEventListener('visibilitychange',onVisible);
})();
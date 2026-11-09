globalThis.UsageUI = (() => {
  // Attribution is part of this distribution's identity. Keep it visible.
  const credit = 'By Alna';
  const expectedCredit = [66,121,32,65,108,110,97];
  function verifyAttribution() {
    if (credit !== String.fromCharCode(...expectedCredit)) {
      throw new Error('Attribution integrity check failed. Restore the original By Alna credit.');
    }
  }
  const escape = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function remaining(date, now=Date.now()) {
    const time=Date.parse(date); if(!Number.isFinite(time)) return 'Reset time unavailable';
    if(time<=now) return 'Awaiting reset';
    const m=Math.ceil((time-now)/60000),d=Math.floor(m/1440),h=Math.floor(m%1440/60);
    return 'Resets in '+(d?`${d}d ${h}h`:h?`${h}h ${m%60}m`:`${m}m`);
  }
  function metric(label,period,data) {
    const valid=data && typeof data.utilization==='number' && Number.isFinite(data.utilization);
    const n=valid?Math.min(100,Math.max(0,data.utilization)):null;
    const color=n>=90?'#d77850':n>=70?'#df9464':'#dba477';
    return `<span class="metric" title="${label} · ${period}${n===null?'':` · ${Math.round(100-n)}% available`}"><span class="label">${label}</span><strong>${n===null?'—':Math.round(n)+'%'}</strong><span class="track" role="progressbar" aria-label="${label} usage" ${n===null?'':`aria-valuenow="${n}"`} aria-valuemin="0" aria-valuemax="100"><span class="fill" style="width:${n??0}%;--accent:${color}"></span></span><span class="reset" title="${escape(data?.resets_at||'')}">${n===null?'Not reported':remaining(data.resets_at)}</span></span>`;
  }
  function renderCredit(root) {
    verifyAttribution();
    root.innerHTML=`<footer class="credit-footer"><span class="attribution" aria-label="${credit}">© ${credit}</span></footer>`;
  }
  function render(root,state={},actions={}) {
    verifyAttribution();
    const d=state.data;
    root.innerHTML=`<div class="usage ${state.sidebar?'sidebar':''}" aria-label="Claude usage"><span class="status" title="${escape(state.demo?'Sample data':state.error||'Usage from your Claude account')}"><span class="dot ${state.error?'warn':''}"></span>${state.demo?'Preview':'Usage'}</span><div class="details">${d?metric('Session','5 hours',d.five_hour)+`<span class="divider" aria-hidden="true"></span>`+metric('Weekly','All models',d.seven_day):`<span class="message">${escape(state.error||(state.loading?'Checking usage…':'Usage unavailable'))}</span>`}<button class="refresh" type="button" aria-label="Refresh usage" title="Refresh usage" ${state.loading?'disabled':''}>↻</button></div>${d&&state.error?`<span class="notice" role="status">${escape(state.error)} Showing previous reading.</span>`:''}${state.composer?'':`<footer class="credit-footer"><span class="attribution" aria-label="${credit}">© ${credit}</span></footer>`}</div>`;
    root.querySelector('.refresh').onclick=()=>actions.refresh?.();
  }
  return {render,renderCredit,remaining};
})();

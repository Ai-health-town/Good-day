"""Gesture-enabled, local audio reminders with a small authenticated refresh."""
import json

import streamlit as st
from streamlit.components.v2 import component

from task_schedule import reminder_items
from workspace import Forbidden
from workspace_clock import CLOCK, render_clock

REMINDERS = """
<style>
.gday-reminders{font-family:'IBM Plex Sans Arabic',sans-serif;flex:none;margin-inline-start:auto;color:#38534f;}
.gday-reminders button{font-family:inherit;cursor:pointer;}
.gday-reminders button:focus-visible{outline:2px solid #13897b;outline-offset:2px;}
.gday-sound-button{display:inline-flex;align-items:center;justify-content:center;gap:9px;min-height:42px;padding:10px 15px;border:1px solid #dce5e3;border-radius:14px;background:#fff;color:#6a7d7b;font-size:12px;font-weight:500;line-height:1.5;white-space:nowrap;box-shadow:0 2px 8px #203c3504;transition:background .18s,border-color .18s,color .18s;}
.gday-sound-button:hover{border-color:#acd1c5;background:#f8fcfa;color:#1a7467;}
.gday-sound-button svg{width:19px;height:19px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;}
.gday-sound-button[aria-pressed=true]{background:#eaf7f2;border-color:#b2d9cb;color:#147c69;}
.gday-sound-dot{width:6px;height:6px;border-radius:50%;background:#c1ccca;flex:none;}
.gday-sound-button[aria-pressed=true] .gday-sound-dot{background:#20a586;box-shadow:0 0 0 3px #20a58612;}
.gday-sound-button[aria-pressed=true] .gday-sound-slash{display:none;}
.gday-reminders[data-sound-state=locked] .gday-sound-button{border-color:#e3d8bf;color:#927037;}
.gday-sound-feedback{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0;}
.gday-task-toast{position:fixed;right:22px;bottom:22px;max-width:min(420px,calc(100vw - 44px));background:white;border:1px solid #b5d7ca;border-right:4px solid #13897b;border-radius:14px;box-shadow:0 8px 35px #173e3520;padding:18px;z-index:99990;direction:rtl;}
.gday-task-toast strong{display:block;font-size:14px;color:#174e44;margin-bottom:5px;}
.gday-task-toast p{font-size:12px;line-height:1.8;color:#435e57;margin:0 0 10px;}
.gday-task-toast button{border:1px solid #cbded7;background:#fff;color:#147a6a;border-radius:9px;padding:7px 10px;font-size:11px;}
.gday-task-toast[hidden]{display:none;}
@media(prefers-reduced-motion:reduce){.gday-sound-button{transition:none;}}
</style>
<aside class="gday-reminders" id="gday-task-reminders" aria-label="التنبيهات الصوتية للمهام" data-sound-state="muted">
 <button type="button" class="gday-sound-button" data-sound aria-pressed="false" aria-label="تفعيل التنبيهات الصوتية" title="تفعيل تنبيهات مهامك وتشغيل نغمة للتأكد">
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/><path class="gday-sound-slash" d="m3 3 18 18"/></svg>
  <span data-sound-label>تنبيهات المهام</span><span class="gday-sound-dot" aria-hidden="true"></span>
 </button>
 <span class="gday-sound-feedback" data-feedback role="status" aria-live="polite"></span>
 <div class="gday-task-toast" data-toast hidden role="status" aria-live="polite"><strong data-toast-heading></strong><p data-toast-text></p><button type="button" data-dismiss>إغلاق التنبيه</button></div>
</aside>
<script>
(() => {
 const payload = __REMINDER_DATA__;
 const root = document.getElementById('gday-task-reminders');
 if (!root) return;
 let engine = window.gdayTaskReminders;
 if (engine && (engine.account !== payload.account || engine.version !== 2)) {engine.stop(); engine = null;}
 if (!engine) {
   engine = {version:2,account:payload.account,enabled:false,ctx:null,seen:new Set(),shown:new Set(),timer:null,root:null,items:[],busy:false,detachedAt:null};
   engine.stop = () => {
     clearInterval(engine.timer); engine.items=[]; engine.enabled=false;
     document.removeEventListener('visibilitychange',engine.onWake);
     window.removeEventListener('pageshow',engine.onWake);
     if(engine.ctx){engine.ctx.onstatechange=null; engine.ctx.close().catch(()=>{});}
     if(window.gdayTaskReminders===engine) window.gdayTaskReminders=null;
   };
   engine.play = () => {
     if (!engine.ctx || engine.ctx.state !== 'running') return false;
     try{
       const ctx=engine.ctx, start=ctx.currentTime;
       for (const [offset,hz] of [[0,659],[0.24,880]]) {
         const tone=ctx.createOscillator(), gain=ctx.createGain();
         tone.type='sine'; tone.frequency.value=hz;
         gain.gain.setValueAtTime(0,start+offset);
         gain.gain.linearRampToValueAtTime(0.11,start+offset+0.025);
         gain.gain.exponentialRampToValueAtTime(0.0001,start+offset+0.19);
         tone.connect(gain); gain.connect(ctx.destination);
         tone.onended=()=>{tone.disconnect();gain.disconnect();};
         tone.start(start+offset); tone.stop(start+offset+0.21);
       }
       return true;
     }catch(_){engine.enabled=false;engine.report();return false;}
   };
   engine.loadSeen = () => {
     try {const saved=JSON.parse(localStorage.getItem('gday.reminders.'+engine.account)||'[]'); if(Array.isArray(saved)) saved.slice(-200).forEach(k=>{if(typeof k==='string')engine.seen.add(k);});} catch(_) {}
   };
   engine.report = () => {
     const r=engine.root, running=engine.enabled && engine.ctx?.state==='running';
     if(!r?.isConnected)return;
     const signature=`${running}|${engine.enabled}|${engine.items.length}`;
     if(r.gdaySoundSignature===signature)return;
     r.gdaySoundSignature=signature;
     r.dataset.soundState=running?'enabled':engine.enabled?'locked':'muted';
     const button=r.querySelector('[data-sound]');
     const action=running?'كتم التنبيهات الصوتية':engine.enabled?'استئناف التنبيهات الصوتية':'تفعيل التنبيهات الصوتية';
     r.querySelector('[data-sound-label]').textContent=running?'التنبيهات مفعّلة':engine.enabled?'استئناف التنبيهات':'تنبيهات المهام';
     button.setAttribute('aria-pressed',String(running));
     button.setAttribute('aria-label',action);
     button.title=action+(engine.items.length?` · ${engine.items.length} تنبيه قادم`:'');
   };
   engine.tick = () => {
     // A short DOM replacement during navigation must not discard consent.
     // No reminders run while detached; a real unmount still releases audio.
     if(!engine.root?.isConnected){
       if(engine.detachedAt===null)engine.detachedAt=Date.now();
       if(Date.now()-engine.detachedAt>=2000)engine.stop();
       return false;
     }
     engine.detachedAt=null;
     engine.report(); engine.loadSeen();
     const now=Date.now();
     const due=engine.items.filter(t=>now>=t.notifyAt && now<=t.due+60000 && !engine.seen.has(t.key));
     const visual=due.filter(t=>!engine.shown.has(t.key));
     if(visual.length){
       const r=engine.root;
       r.querySelector('[data-toast-heading]').textContent=visual.length===1?(now>=visual[0].due?'حان موعد مهمتك':'اقترب موعد مهمتك'):'اقترب موعد عدة مهام';
       r.querySelector('[data-toast-text]').textContent=visual.slice(0,3).map(t=>t.title).join(' • ')+(visual.length>3?` • و${visual.length-3} مهام أخرى`:'');
       r.querySelector('[data-toast]').hidden=false;
       visual.forEach(t=>engine.shown.add(t.key));
     }
     if(due.length && engine.enabled && engine.play()){
       due.forEach(t=>engine.seen.add(t.key));
       engine.seen=new Set([...engine.seen].slice(-200));
       try{localStorage.setItem('gday.reminders.'+engine.account,JSON.stringify([...engine.seen]));}catch(_){}
       return true;
     }
     return false;
   };
   engine.onWake=()=>{
     if(document.visibilityState==='hidden' || !engine.root?.isConnected)return;
     if(engine.enabled && engine.ctx && engine.ctx.state!=='running'){
       return engine.ctx.resume().then(()=>{engine.report();engine.tick();}).catch(()=>engine.report());
     }else engine.tick();
   };
   document.addEventListener('visibilitychange',engine.onWake);
   window.addEventListener('pageshow',engine.onWake);
   window.gdayTaskReminders=engine;
   engine.timer=setInterval(()=>engine.tick(),1000);
 }
 engine.root=root; engine.items=payload.items;
 const unlock=async()=>{
   const Audio=window.AudioContext||window.webkitAudioContext;
   if(!Audio) throw new Error('unsupported');
   if(!engine.ctx || engine.ctx.state==='closed'){
     engine.ctx=new Audio();
     engine.ctx.onstatechange=()=>engine.report();
   }
   await engine.ctx.resume();
   if(engine.ctx.state!=='running')throw new Error('blocked');
 };
 root.querySelector('[data-sound]').onclick=async()=>{
   if(engine.busy)return;
   engine.busy=true;
   try{
     if(engine.enabled && engine.ctx?.state==='running')engine.enabled=false;
     else{
       await unlock();
       if(window.gdayTaskReminders!==engine || !engine.root?.isConnected)return;
       engine.enabled=true;
       // A due reminder is also the confirmation tone: never ring twice.
       if(!engine.tick() && !engine.play())throw new Error('audio');
     }
     engine.root.querySelector('[data-feedback]').textContent=engine.enabled?'التنبيهات الصوتية مفعّلة':'التنبيهات الصوتية مكتومة';
   }catch(_){
     engine.enabled=false;
     engine.root.querySelector('[data-toast-heading]').textContent='تعذر تفعيل الصوت';
     engine.root.querySelector('[data-toast-text]').textContent='تحقق من صوت المتصفح والجهاز، ثم اضغط زر التنبيهات مجددًا.';
     engine.root.querySelector('[data-toast]').hidden=false;
   }finally{engine.busy=false;engine.report();}
 };
 root.querySelector('[data-dismiss]').onclick=()=>{root.querySelector('[data-toast]').hidden=true;};
 engine.tick();
})();
</script>
"""


def reminders_html(state, actor):
    payload = json.dumps({"account": actor["id"], "items": reminder_items(state, actor)}, ensure_ascii=False)
    # A title can contain HTML or </script>; it must remain JSON data, never code.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return REMINDERS.replace("__REMINDER_DATA__", payload)


# Register static trusted assets once. Task titles travel only as component data
# and are displayed with textContent, never interpolated into executable assets.
_clock_markup, _, _clock_script = CLOCK.partition("<script>")
_reminder_markup, _, _reminder_script = REMINDERS.partition("<script>")
_task_header = component(
    "gday_task_schedule_header",
    html=_clock_markup.replace("<!--TASK_REMINDERS-->", _reminder_markup),
    js="export default function(component) {\nconst payload = component.data;\n"
    + _clock_script.rsplit("</script>", 1)[0].replace(
        "document.getElementById('gday-workspace-clock')",
        "component.parentElement.querySelector('#gday-workspace-clock')",
    )
    + _reminder_script.rsplit("</script>", 1)[0].replace(
        " const payload = __REMINDER_DATA__;", ""
    ).replace(
        "document.getElementById('gday-task-reminders')",
        "component.parentElement.querySelector('#gday-task-reminders')",
    )
    + "\n}",
    isolate_styles=False,
)


def render_task_header(store, token, initial_state, actor):
    initial = [(initial_state, actor)]

    @st.fragment(run_every="30s")
    def header():
        if initial:
            state, current = initial.pop()
        else:
            try:
                state, _, current = store.context(token)
            except Forbidden:
                render_clock()
                st.warning("انتهت جلسة التنبيهات؛ حدّث الصفحة لتسجيل الدخول.")
                return
        _task_header(
            data={"account": current["id"], "items": reminder_items(state, current)},
            key="gday_task_schedule_header",
            width="stretch",
        )

    header()

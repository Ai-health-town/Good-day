"""Gesture-enabled, local audio reminders with a small authenticated refresh."""
import json

import streamlit as st
from streamlit.components.v2 import component

from task_schedule import reminder_items
from workspace import Forbidden
from workspace_clock import CLOCK, render_clock

REMINDERS = """
<style>
.gday-reminders{font-family:'IBM Plex Sans Arabic',sans-serif;max-width:355px;min-width:230px;color:#38534f;font-size:11px;}
.gday-reminder-top{display:flex;align-items:center;justify-content:space-between;gap:16px;}
.gday-reminder-top strong{font-size:12px;white-space:nowrap;}
.gday-reminders button{font-family:inherit;border:1px solid #cbded7;background:#fff;color:#147a6a;border-radius:9px;padding:7px 10px;cursor:pointer;font-size:11px;white-space:nowrap;}
.gday-reminders button:focus-visible{outline:2px solid #13897b;outline-offset:2px;}
.gday-reminders button[aria-pressed=true]{background:#e7f4ed;border-color:#a7cfc0;}
.gday-reminder-test{margin-inline-start:5px;}
.gday-reminder-note{font-size:10px;color:#85938f;margin-top:5px;line-height:1.7;max-width:350px;}
.gday-task-toast{position:fixed;right:22px;bottom:22px;max-width:min(420px,calc(100vw - 44px));background:white;border:1px solid #b5d7ca;border-right:4px solid #13897b;border-radius:14px;box-shadow:0 8px 35px #173e3520;padding:18px;z-index:99990;direction:rtl;}
.gday-task-toast strong{display:block;font-size:14px;color:#174e44;margin-bottom:5px;}
.gday-task-toast p{font-size:12px;line-height:1.8;color:#435e57;margin:0 0 10px;}
.gday-task-toast[hidden]{display:none;}
@media(max-width:520px){.gday-reminders{max-width:none;width:100%;}.gday-reminder-note{max-width:none;}}
</style>
<aside class="gday-reminders" id="gday-task-reminders" aria-label="التنبيهات الصوتية للمهام" data-sound-state="locked">
 <div class="gday-reminder-top"><strong>♬ تنبيهات مهامك</strong><div><button type="button" data-sound aria-pressed="false">تفعيل الصوت</button><button type="button" class="gday-reminder-test" data-test>تجربة الصوت</button></div></div>
 <div class="gday-reminder-note" data-reminder-status></div>
 <div class="gday-reminder-note">اترك المنصة مفتوحة. قد يتأخر الصوت إذا أوقف المتصفح الصفحة أو كان الجهاز صامتًا.</div>
 <div class="gday-task-toast" data-toast hidden role="status" aria-live="polite"><strong data-toast-heading></strong><p data-toast-text></p><button type="button" data-dismiss>إغلاق التنبيه</button></div>
</aside>
<script>
(() => {
 const payload = __REMINDER_DATA__;
 const root = document.getElementById('gday-task-reminders');
 if (!root) return;
 let engine = window.gdayTaskReminders;
 if (engine && engine.account !== payload.account) {engine.stop(); engine = null;}
 if (!engine) {
   engine = {account:payload.account,enabled:false,ctx:null,seen:new Set(),shown:new Set(),timer:null,root:null,items:[]};
   engine.stop = () => {clearInterval(engine.timer); if(engine.ctx) engine.ctx.close().catch(()=>{}); if(window.gdayTaskReminders===engine) window.gdayTaskReminders=null;};
   engine.play = () => {
     if (!engine.ctx || engine.ctx.state !== 'running') return false;
     const ctx=engine.ctx, start=ctx.currentTime;
     for (const [offset,hz] of [[0,659],[0.24,880]]) {
       const tone=ctx.createOscillator(), gain=ctx.createGain();
       tone.type='sine'; tone.frequency.value=hz;
       gain.gain.setValueAtTime(0,start+offset);
       gain.gain.linearRampToValueAtTime(0.11,start+offset+0.025);
       gain.gain.exponentialRampToValueAtTime(0.0001,start+offset+0.19);
       tone.connect(gain); gain.connect(ctx.destination); tone.start(start+offset); tone.stop(start+offset+0.21);
     }
     return true;
   };
   engine.loadSeen = () => {
     try {const saved=JSON.parse(localStorage.getItem('gday.reminders.'+engine.account)||'[]'); if(Array.isArray(saved)) saved.slice(-200).forEach(k=>{if(typeof k==='string')engine.seen.add(k);});} catch(_) {}
   };
   engine.report = () => {
     const r=engine.root, running=engine.enabled && engine.ctx?.state==='running';
     r.dataset.soundState=running?'enabled':engine.enabled?'locked':'muted';
     const button=r.querySelector('[data-sound]');
     button.textContent=running?'كتم الصوت':engine.enabled?'استئناف الصوت':'تفعيل الصوت';
     button.setAttribute('aria-pressed',String(running));
     const count=engine.items.length;
     if(!engine.noteUntil || engine.noteUntil<Date.now()) r.querySelector('[data-reminder-status]').textContent=count?`${count} تنبيه لمهامك خلال الأيام السبعة القادمة · بتوقيت الرياض`:'لا توجد تنبيهات مفعّلة لمهامك خلال الأيام السبعة القادمة.';
   };
   engine.tick = () => {
     if(!engine.root?.isConnected){engine.stop(); return;}
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
     }
   };
   window.gdayTaskReminders=engine;
   engine.timer=setInterval(()=>engine.tick(),1000);
 }
 engine.root=root; engine.items=payload.items;
 const unlock=async()=>{
   const Audio=window.AudioContext||window.webkitAudioContext;
   if(!Audio) throw new Error('unsupported');
   if(!engine.ctx || engine.ctx.state==='closed')engine.ctx=new Audio();
   await engine.ctx.resume();
   if(engine.ctx.state!=='running')throw new Error('blocked');
 };
 root.querySelector('[data-sound]').onclick=async()=>{
   try{
     if(engine.enabled && engine.ctx?.state==='running')engine.enabled=false;
     else{await unlock(); engine.enabled=true; engine.play();}
     engine.report(); engine.tick();
   }catch(_){root.querySelector('[data-reminder-status]').textContent='تعذر تفعيل الصوت. تحقق من إعداد الصوت للمتصفح ثم اضغط مجددًا.';}
 };
 root.querySelector('[data-test]').onclick=async()=>{
   try{await unlock();engine.play();engine.noteUntil=Date.now()+5000;root.querySelector('[data-reminder-status]').textContent='شُغّلت نغمة التجربة. زر تفعيل الصوت يتيح تنبيهات المهام تلقائيًا.';}
   catch(_){root.querySelector('[data-reminder-status]').textContent='تعذر تشغيل النغمة؛ تحقق من صوت المتصفح والجهاز.';}
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

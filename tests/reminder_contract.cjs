const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {script} = JSON.parse(fs.readFileSync(0, 'utf8'));

function environment() {
  const state = {now:95000, contexts:0, tones:[], gains:[], blocked:false, broken:false, storageBlocked:false};
  const makeRoot = () => {
    const nodes = new Map();
    const element = key => {
      if (!nodes.has(key)) nodes.set(key, {textContent:'', hidden:true, attrs:{},
        setAttribute(k,v){this.attrs[k]=v;}});
      return nodes.get(key);
    };
    return {isConnected:true, dataset:{}, querySelector:element};
  };
  let root = makeRoot();
  const storage = new Map(), timers = new Map(), documentEvents = new Map(), windowEvents = new Map();
  class AudioContext {
    constructor(){state.contexts++; this.state='suspended'; this.currentTime=5; this.destination={};}
    async resume(){if(state.blocked) throw Error('blocked'); this.state='running'; this.onstatechange?.();}
    async close(){this.state='closed';}
    createOscillator(){
      if(state.broken) throw Error('audio hardware unavailable');
      const tone={frequency:{value:0},connect(node){this.target=node;},start(at){this.at=at;state.tones.push(this);},stop(at){this.until=at;},disconnect(){this.disconnected=true;}};
      return tone;
    }
    createGain(){
      const gain={values:[],gain:{setValueAtTime(value){gain.values.push(value);},linearRampToValueAtTime(value){gain.values.push(value);},exponentialRampToValueAtTime(value){gain.values.push(value);}},
        connect(node){this.target=node;},disconnect(){this.disconnected=true;}};
      state.gains.push(gain);
      return gain;
    }
  }
  const sandbox={window:{AudioContext,addEventListener:(k,v)=>windowEvents.set(k,v),removeEventListener:k=>windowEvents.delete(k)},
    document:{getElementById:()=>root,visibilityState:'visible',addEventListener:(k,v)=>documentEvents.set(k,v),removeEventListener:k=>documentEvents.delete(k)},
    Date:{now:()=>state.now},
    localStorage:{getItem:k=>{if(state.storageBlocked)throw Error('storage');return storage.get(k)||null;},setItem:(k,v)=>{if(state.storageBlocked)throw Error('storage');storage.set(k,v);}},
    setInterval:fn=>{const id=timers.size+1;timers.set(id,fn);return id;},clearInterval:id=>timers.delete(id),console};
  vm.createContext(sandbox);
  return {state,sandbox,storage,timers,documentEvents,windowEvents,
    get root(){return root;}, get engine(){return sandbox.window.gdayTaskReminders;},
    element:key=>root.querySelector(key),
    run(code=script){vm.runInContext(code,sandbox);},
    replaceRoot(){root.isConnected=false;root=makeRoot();},
    click(){return root.querySelector('[data-sound]').onclick();}};
}

(async()=>{
  let checks=0;
  const e=environment(); e.run();
  assert.equal(e.state.contexts,0);
  assert.equal(e.state.tones.length,0);
  assert.equal(e.element('[data-toast]').hidden,false);
  await e.click();
  assert.equal(e.root.dataset.soundState,'enabled');
  assert.equal(e.element('[data-sound]').attrs['aria-pressed'],'true');
  assert.equal(e.state.contexts,1);
  assert.equal(e.state.tones.length,2); // One due chime, no second confirmation chime.
  for(const [index,hz] of [659,880].entries()){
    const tone=e.state.tones[index],gain=tone.target;
    assert.equal(tone.frequency.value,hz);
    assert.equal(gain.target,e.engine.ctx.destination);
    assert.ok(gain.values.some(value=>value>0.1));
    assert.ok(tone.until>tone.at);
    tone.onended(); assert.ok(tone.disconnected && gain.disconnected);
  }
  e.engine.tick(); assert.equal(e.state.tones.length,2); checks++;

  e.run(); assert.equal(e.state.contexts,1); assert.equal(e.state.tones.length,2);
  const oldRoot=e.root; oldRoot.isConnected=false; e.engine.tick();
  e.state.now+=1000; e.replaceRoot(); e.run();
  assert.equal(e.state.contexts,1); assert.equal(e.root.dataset.soundState,'enabled');
  assert.equal(e.timers.size,1); checks++;

  await e.click();
  assert.equal(e.root.dataset.soundState,'muted');
  const next={title:'المهمة القادمة',key:'next',due:150000,notifyAt:120000};
  e.engine.items=[next]; e.state.now=125000; e.engine.tick();
  assert.equal(e.state.tones.length,2); assert.ok(!e.engine.seen.has('next'));
  await e.click(); assert.equal(e.state.tones.length,4);
  e.engine.tick(); assert.equal(e.state.tones.length,4); checks++;

  e.engine.items=[{title:'بعد قليل',key:'future',due:200000,notifyAt:180000}];
  e.state.now=175000; e.engine.tick(); assert.equal(e.state.tones.length,4);
  e.state.now=180000; e.engine.tick(); assert.equal(e.state.tones.length,6);
  assert.equal(e.element('[data-toast-text]').textContent,'بعد قليل');
  e.engine.tick(); assert.equal(e.state.tones.length,6); checks++;

  e.engine.items=[]; e.state.now=185000; e.engine.tick();
  assert.equal(e.state.tones.length,6); // Completed, removed, reassigned or disabled by authenticated refresh.
  e.engine.items=[{title:'قديم',key:'old',due:1000,notifyAt:0}]; e.state.now=200000; e.engine.tick();
  assert.equal(e.state.tones.length,6); checks++;

  e.engine.ctx.state='suspended'; e.engine.report();
  assert.equal(e.root.dataset.soundState,'locked');
  await e.documentEvents.get('visibilitychange')();
  assert.equal(e.root.dataset.soundState,'enabled');
  assert.equal(e.state.tones.length,6);
  e.element('[data-dismiss]').onclick(); assert.equal(e.element('[data-toast]').hidden,true); checks++;

  const old=e.engine; e.run(script.replace('"account": "me"','"account": "other"'));
  assert.equal(old.ctx.state,'closed'); assert.equal(old.items.length,0);
  assert.equal(e.engine.account,'other'); assert.equal(e.engine.enabled,false);
  assert.equal(e.state.tones.length,6); checks++;

  e.root.isConnected=false; e.engine.tick(); e.state.now+=2100; e.engine.tick();
  assert.equal(e.engine,null); assert.equal(e.timers.size,0);
  assert.equal(e.documentEvents.size,0); assert.equal(e.windowEvents.size,0); checks++;

  const blocked=environment(); blocked.state.blocked=true; blocked.run(); await blocked.click();
  assert.equal(blocked.engine.enabled,false); assert.equal(blocked.root.dataset.soundState,'muted');
  assert.equal(blocked.state.tones.length,0); assert.equal(blocked.engine.seen.size,0);
  assert.equal(blocked.element('[data-toast-heading]').textContent,'تعذر تفعيل الصوت');
  blocked.state.blocked=false; await blocked.click(); assert.equal(blocked.state.tones.length,2); checks++;

  const noStorage=environment(); noStorage.state.storageBlocked=true; noStorage.run(); await noStorage.click();
  noStorage.engine.tick(); assert.equal(noStorage.state.tones.length,2); checks++;

  const broken=environment(); broken.state.broken=true; broken.run(); await broken.click();
  assert.equal(broken.engine.seen.size,0); assert.equal(broken.engine.enabled,false);
  assert.equal(broken.element('[data-toast-heading]').textContent,'تعذر تفعيل الصوت'); checks++;

  const unsupported=environment(); unsupported.sandbox.window.AudioContext=undefined; unsupported.run(); await unsupported.click();
  assert.equal(unsupported.root.dataset.soundState,'muted'); assert.equal(unsupported.state.contexts,0); checks++;

  const fast=environment(); fast.run(); await Promise.all([fast.click(),fast.click()]);
  assert.equal(fast.state.contexts,1); assert.equal(fast.state.tones.length,2); checks++;

  console.log(JSON.stringify({checks:'passed',scenarios:checks}));
})().catch(error=>{console.error(error);process.exitCode=1;});

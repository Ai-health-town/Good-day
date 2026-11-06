const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {script} = JSON.parse(fs.readFileSync(0, 'utf8'));
let current = 95000, contexts = 0, tones = 0;
const nodes = new Map();
const element = key => {
  if (!nodes.has(key)) nodes.set(key, {textContent:'', hidden:true, setAttribute(){}});
  return nodes.get(key);
};
const root = {isConnected:true, dataset:{}, querySelector:element};
const storage = new Map();
class AudioContext {
  constructor(){contexts++; this.state='suspended'; this.currentTime=0; this.destination={};}
  async resume(){this.state='running';}
  async close(){this.state='closed';}
  createOscillator(){return {frequency:{value:0},connect(){},start(){tones++;},stop(){}};}
  createGain(){return {gain:{setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}};}
}
const sandbox = {window:{AudioContext}, document:{getElementById:()=>root},
 Date:{now:()=>current}, localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},
 setInterval:()=>1,clearInterval(){},console};
vm.createContext(sandbox);
(async()=>{
 vm.runInContext(script,sandbox);
 assert.equal(contexts,0); // A pending task must never start sound automatically.
 assert.equal(element('[data-toast]').hidden,false);
 await element('[data-sound]').onclick();
 assert.equal(root.dataset.soundState,'enabled');
 assert.equal(contexts,1);
 const first = tones;
 assert.ok(first>0);
 sandbox.window.gdayTaskReminders.tick();
 assert.equal(tones,first); // No repeat on the next second.
 vm.runInContext(script,sandbox); // Fragment refresh must keep the user's audio context.
 assert.equal(contexts,1);
 assert.equal(tones,first);
 const engine=sandbox.window.gdayTaskReminders;
 engine.items=[]; current=100000; engine.tick();
 assert.equal(tones,first); // Completed, removed or reassigned task was withdrawn by refresh.
 engine.items=[{title:'قديم',key:'old',due:1000,notifyAt:0}]; current=200000; engine.tick();
 assert.equal(tones,first); // Opening a page must not ring for old overdue tasks.
 root.isConnected=false; engine.tick();
 assert.equal(sandbox.window.gdayTaskReminders,null);
 console.log(JSON.stringify({checks:'passed'}));
})().catch(error=>{console.error(error);process.exitCode=1;});

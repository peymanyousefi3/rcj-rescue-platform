const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

test('the popup bridge preserves exported ready and playback callbacks, including seeking and looping',()=>{
 const received=[],attributes={},keys={},messages=[];
 const slider={setAttribute:(name,value)=>attributes[name]=value,addEventListener:(name,callback)=>keys[name]=callback};
 const animation={data:{basicTimeStep:1000,frames:Array.from({length:9},(_,i)=>({time:i*1000}))},step:0,gui:'pause',
   pause(){this.gui='pause';},
   updateAnimationState(step){this.step=step;this.stepCallback(this.data.frames[step].time);}};
 let ready=false;
 const player={_view:{animation},
   onready(){assert.equal(this,player);ready=true;animation.stepCallback=function(time){assert.equal(this,animation);received.push(time);};},
   querySelectorAll:()=>[],addEventListener(){},
   querySelector:selector=>selector==='#timeSlider'?{shadowRoot:{querySelector:()=>slider}}:null,
   setAnimationStepCallback(callback){animation.stepCallback=callback;}};
 const context={location:{hash:'#test-nonce'},parent:{postMessage:message=>messages.push(message)},
   window:{addEventListener(){}},document:{querySelector:()=>player,createElement:()=>({}),head:{append(){}}},queueMicrotask};
 vm.runInNewContext(fs.readFileSync('static/arena/replay-bridge.js','utf8'),context);
 player.onready();
 assert.equal(ready,true);
 assert.equal(messages[0].type,'asr-replay-ready');
 // Normal progress, tied timestamps, rewind, restart and loop all reach the original export unchanged.
 for(const time of [0,1000,2000,2000,8000,1000,0])animation.stepCallback(time);
 assert.deepEqual(received,[0,1000,2000,2000,8000,1000,0]);
 keys.keydown({key:'End',preventDefault(){}});
 assert.equal(received.at(-1),8000);
 keys.keydown({key:'Home',preventDefault(){}});
 assert.equal(received.at(-1),0);
 assert.equal(attributes['aria-valuenow'],'0');
 keys.keydown({key:'ArrowRight',preventDefault(){}});
 assert.equal(received.at(-1),5000);
 keys.keydown({key:'ArrowLeft',preventDefault(){}});
 assert.equal(received.at(-1),0);
});

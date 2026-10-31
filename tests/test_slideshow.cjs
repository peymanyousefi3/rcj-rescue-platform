const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('static/arena/slideshow.js','utf8');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.handlers={};this.textContent='';this.classList={add:()=>{}};}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(name,value){this[name]=value;}
  addEventListener(name,handler){this.handlers[name]=handler;}
  closest(){return null;}
  click(){this.handlers.click();}
  get text(){return [this.textContent,...this.children.map(x=>x.text)].join(' ');}
}
function fixture(){
  const texts={};for(const key of ['brand_word','event_short','event_name','title_small','title_large','title_bottom','qr_caption','venue','venue_location','schedule_subtitle','schedule_date','timezone','quarantine_label','no_schedule','results_title','results_method','results_date','results_updated','results_link','results_released','results_unreleased','rank','team','round','map_max','raw','normalized','total_time','final_percentage','final_total','pending','empty_results'])texts[key]=key;
  Object.assign(texts,{welcome:'Welcome to',schedule_title:'Schedule',results_title:'Results {challenge}',results_method:'{round_count} rounds · {method}',round:'R'});
  return {design:{texts,colors:{},images:{logo:'/logo',cover:'/banner',qr:'/qr'}},enabled:true,generated_at:new Date(0).toISOString(),settings:{intro:true,schedule:true,results:true,intro_seconds:120,schedule_seconds:18,results_seconds:18,refresh_seconds:30,rows:8},
    competition:{short_name:'Cup',name:'Competition',header_title:'Robotics',league_name:'Simulation',banner_title:'Simulation',location:'Venue',dates:'Dates',branding:{logo:'/logo',banner:'/banner'}},
    schedule:[{id:1,title:'<script>unsafe</script>',date:'Today',start:'10:00',end:'10:10',team:'A',field:'1'}],
    results:[{id:1,name:'Main',rankings_released:false,percentage:true,rounds:[{label:'R1',maximum:null}],rows:[{name:'A',code:'1',rank:null,total:'85.00',time:32,scores:[{raw:'80.00',normalized:'0.8000',discarded:true}]}]}]};
}
async function setup(small=false){
  const ids=new Map(['presentation','slide-content','slide-position','update-status','pause','previous','next','fullscreen'].map(id=>[id,new Element('div')]));
  ids.get('presentation').dataset={layout:'/layout.json'};
  const timers=new Map(), handlers={}, calls=[];let clock=0,serial=0,body=fixture(),offline=false;
  const doc={getElementById:id=>ids.get(id),createElement:tag=>new Element(tag),createElementNS:(ns,tag)=>new Element(tag),fonts:{ready:Promise.resolve(),load:()=>Promise.resolve()},hidden:false,addEventListener:(name,fn)=>handlers[name]=fn,documentElement:{requestFullscreen:async()=>{calls.push('fullscreen');}}};
  class DateMock extends Date {static now(){return clock;}}
  const context={document:doc,window:{innerHeight:720,matchMedia:()=>({matches:small,addEventListener:()=>{}})},Date:DateMock,AbortSignal,
    fetch:async(url,options)=>{calls.push({url,options});if(url==='/layout.json')return {ok:true,json:async()=>JSON.parse(fs.readFileSync('static/arena/slide-assets/layout.json','utf8'))};if(offline)throw Error();return {ok:true,json:async()=>JSON.parse(JSON.stringify(body))};},
    setTimeout:(fn,delay)=>{const id=++serial;timers.set(id,{fn,at:clock+delay});return id;},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(source,context);
  async function flush(){for(let i=0;i<40;i++)await Promise.resolve();}
  async function tick(ms){const end=clock+ms;while(true){const due=[...timers.entries()].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!due)break;clock=due[1].at;timers.delete(due[0]);due[1].fn();await flush();}clock=end;await flush();}
  await flush();return {ids,doc,handlers,calls,tick,update:value=>body=value,offline:()=>offline=true,body};
}
test('loops even when refresh is shorter than slide timing; pause and keyboard work',async()=>{
  const x=await setup();assert.match(x.ids.get('slide-content').text,/Welcome to/);
  await x.tick(119000);assert.match(x.ids.get('slide-content').text,/Welcome to/);
  await x.tick(1000);assert.match(x.ids.get('slide-content').text,/Schedule/);
  assert.match(x.ids.get('slide-content').text,/<script>unsafe<\/script>/);
  assert.equal(x.ids.get('slide-content').children[0].tag,'svg');
  x.ids.get('pause').click();await x.tick(40000);assert.match(x.ids.get('slide-content').text,/Schedule/);
  x.ids.get('next').click();assert.match(x.ids.get('slide-content').text,/85.00/);assert.ok(x.ids.get('slide-content').children[0].children.some(n=>n.tag==='line'));
  x.ids.get('next').click();assert.match(x.ids.get('slide-content').text,/Welcome to/);
  x.handlers.keydown({key:'ArrowLeft',target:new Element('body'),preventDefault:()=>{}});assert.match(x.ids.get('slide-content').text,/Results/);
  assert.equal(x.calls[0].options.credentials,'omit');assert.equal(x.calls[0].options.cache,'no-store');
});
test('refresh applies public changes and disabling clears previously shown records',async()=>{
  const x=await setup();x.body.design.texts.event_name='Updated event';x.update(x.body);await x.tick(30000);assert.match(x.ids.get('slide-content').text,/Updated event/);
  x.offline();await x.tick(30000);assert.match(x.ids.get('update-status').text,/Connection lost/);assert.match(x.ids.get('slide-content').text,/Updated event/);
  const y=await setup();y.update({enabled:false,settings:y.body.settings});await y.tick(30000);assert.match(y.ids.get('slide-content').text,/Slideshow unavailable/);assert.doesNotMatch(y.ids.get('slide-content').text,/Venue/);
});
test('three fixed slides keep every round together and full-screen uses the native API',async()=>{
  const x=await setup(true);x.body.results[0].rounds=Array.from({length:7},(_,i)=>({label:`R${i+1}`,maximum:null}));
  x.body.results[0].rows[0].scores=Array.from({length:7},()=>({raw:'1',normalized:'1'}));x.update(x.body);await x.tick(30000);
  assert.equal(x.ids.get('slide-position').textContent,'1 / 3');x.ids.get('previous').click();assert.match(x.ids.get('slide-content').text,/R 7/);assert.match(x.ids.get('slide-content').text,/R 6/);
  x.ids.get('fullscreen').click();assert.ok(x.calls.includes('fullscreen'));
});

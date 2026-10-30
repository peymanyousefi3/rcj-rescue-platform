const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('field camera buttons zoom, rotate, reset and disable after load failure',()=>{
 const handlers={},buttons=['left','right','in','out','reset'].map(action=>({dataset:{fieldCamera:action},disabled:true,addEventListener(type,callback){this.click=callback;}}));
 const model={addEventListener(name,callback){handlers[name]=callback;},getCameraOrbit(){return {theta:0,phi:1,radius:10};},getCameraTarget(){return {x:1,y:2,z:3};}};
 vm.runInNewContext(fs.readFileSync('static/arena/field-viewer.js','utf8'),{document:{querySelector:selector=>selector==='model-viewer'?model:{textContent:''},querySelectorAll:()=>buttons}});
 handlers.load();assert.ok(buttons.every(b=>!b.disabled));
 buttons[0].click();assert.ok(model.cameraOrbit.startsWith('-0.261'));
 buttons[2].click();assert.ok(model.cameraOrbit.endsWith('8m'));
 buttons[4].click();assert.equal(model.cameraOrbit,'0rad 1rad 10m');assert.equal(model.cameraTarget,'1m 2m 3m');
 handlers.error();assert.ok(buttons.every(b=>b.disabled));
});

'use strict';
(()=>{
 const nonce=location.hash.slice(1);const send=(type,detail={})=>parent.postMessage({type,nonce,...detail},'*');
 window.addEventListener('error',event=>{if(event.target!==window||event.error)send('asr-replay-error');},true);
 window.addEventListener('unhandledrejection',()=>send('asr-replay-error'));
 const style=document.createElement('style');style.textContent='html,body{margin:0!important;padding:0!important;width:100%!important;min-height:100%;height:auto!important;overflow:auto!important}.webots-view-container{width:100%!important;height:auto!important;min-height:70vh;margin:0!important;padding:0!important;overflow:visible!important}webots-view{display:block!important;width:100%!important;height:clamp(320px,70vh,720px)!important;position:relative!important}';document.head.append(style);
 const player=document.querySelector('webots-view');if(!player){send('asr-replay-error');return;}
 const exportedReady=player.onready;
 player.onready=(...args)=>{
   if(typeof exportedReady==='function')exportedReady.apply(player,args);
   const labelControls=()=>player.querySelectorAll('button[title]').forEach(button=>button.setAttribute('aria-label',button.id==='play-button'?(player._view?.animation?.gui==='real-time'?'Pause replay':'Play replay'):button.title));
   labelControls();player.addEventListener('click',()=>queueMicrotask(labelControls));window.addEventListener('keydown',()=>queueMicrotask(labelControls));
   const animation=player._view?.animation,slider=player.querySelector('#timeSlider')?.shadowRoot?.querySelector('#range');
   if(animation?.data&&slider){
     const maximum=animation.data.frames.at(-1).time;slider.tabIndex=0;slider.setAttribute('role','slider');slider.setAttribute('aria-label','Replay timeline');slider.setAttribute('aria-valuemin','0');slider.setAttribute('aria-valuemax',String(maximum/1000));
     const update=time=>{slider.setAttribute('aria-valuenow',String(time/1000));slider.setAttribute('aria-valuetext',(time/1000).toFixed(1)+' of '+(maximum/1000).toFixed(1)+' seconds');};
     const exportedStep=animation.stepCallback;
     player.setAnimationStepCallback(function(time){if(typeof exportedStep==='function')exportedStep.call(this,time);update(time);send('asr-replay-position',{time_ms:time});});update(0);
     slider.addEventListener('keydown',event=>{
       if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();
       const step=event.key==='Home'?0:event.key==='End'?animation.data.frames.length-1:Math.max(0,Math.min(animation.data.frames.length-1,animation.step+Math.round((event.key==='ArrowRight'?5000:-5000)/animation.data.basicTimeStep)));
       if(animation.gui==='real-time')player.querySelector('#play-button')?.click();
       animation.updateAnimationState(step);animation.pause();labelControls();
     });
   }
   window.addEventListener('message',event=>{
     if(event.source!==parent||event.data?.nonce!==nonce||event.data.type!=='asr-replay-seek')return;
     const time=event.data.time_ms,animation=player._view?.animation,frames=animation?.data?.frames;
     if(!Number.isFinite(time)||time<0||!frames?.length)return;
     const target=Math.min(time,frames.at(-1).time);let low=0,high=frames.length;
     while(low<high){const middle=Math.floor((low+high)/2);if(frames[middle].time<=target)low=middle+1;else high=middle;}
     if(animation.gui==='real-time')player.querySelector('#play-button')?.click();
     const step=Math.max(0,low-1);animation.updateAnimationState(step);animation.pause();labelControls();
     send('asr-replay-position',{time_ms:frames[step].time});
   });
   send('asr-replay-ready');
 };
 window.addEventListener('pagehide',()=>{try{player.close();}catch(_){}});
})();

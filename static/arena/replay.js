'use strict';
(()=>{
 const dialog=document.querySelector('[data-replay-dialog]');if(!dialog)return;
 const stage=dialog.querySelector('[data-replay-viewport]'),status=dialog.querySelector('[data-replay-status]');let frame,nonce,opener,timer,controller,events=[],eventButtons=[],latest,complaintLink,pendingStart=0,loadId=0,activeEvent=-2,playerReady=false;
 const resultPanel=dialog.querySelector('[data-match-result]');
 function seek(milliseconds){
   if(!Number.isFinite(milliseconds)||milliseconds<0)return;
   const video=stage.querySelector('video');
   if(video){if(video.readyState)video.currentTime=Math.min(milliseconds/1000,video.duration||Infinity);return;}
   if(!playerReady){pendingStart=milliseconds;return;}
   frame?.contentWindow.postMessage({type:'asr-replay-seek',nonce,time_ms:milliseconds},'*');
 }
 function updatePosition(milliseconds){
   if(!Number.isFinite(milliseconds)||milliseconds<0)return;
   let low=0,high=events.length;while(low<high){const middle=Math.floor((low+high)/2);if(events[middle].playback_time_ms<=milliseconds)low=middle+1;else high=middle;}const active=low-1;
   if(active!==activeEvent){activeEvent=active;
   if(latest&&latest.dataset.unavailable!=='true')latest.textContent=active<0?'No events yet':`Latest event: ${events[active].timestamp} — ${events[active].text}`;
   eventButtons.forEach((button,i)=>{if(i===active)button.setAttribute('aria-current','true');else button.removeAttribute('aria-current');});
   }
   if(complaintLink){const seconds=Math.floor(milliseconds/1000),at=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');
     const url=new URL(complaintLink.dataset.base,location.origin);url.searchParams.set('at',at);url.searchParams.set('at_ms',String(Math.round(milliseconds)));complaintLink.href=url.pathname+url.search;complaintLink.textContent='Report a concern at '+at;}
 }
 function showEvents(data){
   events=data.result?.events||[];eventButtons=[];
   const section=document.createElement('section');section.className='replay-events';
   const heading=document.createElement('h3');heading.textContent='Replay events';section.append(heading);
   latest=document.createElement('p');latest.className='replay-latest';latest.textContent=data.result?.event_history_available?'No events yet':'Event history unavailable';section.append(latest);
   if(data.result?.event_history_available){const list=document.createElement('ol');list.setAttribute('aria-label','Jump to a replay event');
     for(const item of events){const row=document.createElement('li'),button=document.createElement('button');button.type='button';button.textContent=item.timestamp+' — '+item.text;button.addEventListener('click',()=>seek(item.playback_time_ms));row.append(button);list.append(row);eventButtons.push(button);}section.append(list);}
   if(data.complaint_url){complaintLink=document.createElement('a');complaintLink.className='button secondary';complaintLink.dataset.base=data.complaint_url+'?recording='+encodeURIComponent(data.recording_id);section.append(complaintLink);}
   resultPanel.append(section);updatePosition(0);
   if(!data.result?.event_history_available){latest.dataset.unavailable='true';latest.textContent='Event history unavailable';}
 }
 function showResult(result){
   resultPanel.replaceChildren();resultPanel.hidden=false;
   const title=document.createElement('h3');title.textContent='Final match results';resultPanel.append(title);
   if(!result?.available){const message=document.createElement('p');message.className='match-result-unavailable';message.textContent='Final result unavailable';resultPanel.append(message);}
   if(Object.keys(result?.scores||{}).length||Object.keys(result?.times||{}).length){
     const list=document.createElement('dl');
     const rows=[['Final score',result.scores?.final_score],['Field score',result.scores?.field_score],['Exit bonus',result.scores?.exit_bonus],['Map bonus',result.scores?.map_bonus],['Final elapsed time',result.times?.elapsed_seconds],['Match time limit',result.times?.max_seconds],['Final remaining time',result.times?.remaining_seconds]];
     for(const [label,value] of rows){const name=document.createElement('dt'),display=document.createElement('dd');name.textContent=label;display.textContent=value??'Unavailable';if(label==='Final score')display.className='match-result-total';list.append(name,display);}
     resultPanel.append(list);
   }
 }
 function release(){playerReady=false;activeEvent=-2;loadId++;events=[];eventButtons=[];latest=null;complaintLink=null;pendingStart=0;clearTimeout(timer);controller?.abort();const video=stage.querySelector('video');if(video){video.pause();video.removeAttribute('src');video.load();}frame?.remove();frame=null;stage.replaceChildren();nonce=null;resultPanel.hidden=true;resultPanel.replaceChildren();}
 dialog.querySelector('[data-replay-close]').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',()=>{if(document.fullscreenElement||document.webkitFullscreenElement){const exit=document.exitFullscreen||document.webkitExitFullscreen;exit?.call(document);}release();opener?.focus({preventScroll:true});});
 const fullscreen=dialog.querySelector('[data-replay-fullscreen]'),shell=dialog.querySelector('[data-replay-shell]');
 fullscreen.addEventListener('click',async()=>{
   try{
     if(document.fullscreenElement||document.webkitFullscreenElement){const exit=document.exitFullscreen||document.webkitExitFullscreen;await exit.call(document);}
     else{const enter=shell.requestFullscreen||shell.webkitRequestFullscreen;if(!enter)throw new Error('Fullscreen is unavailable in this browser. The responsive viewer remains available in this window.');await enter.call(shell);}
   }catch(error){status.hidden=false;status.textContent=error.message;}
 });
 const updateFullscreen=()=>{const active=!!(document.fullscreenElement||document.webkitFullscreenElement);fullscreen.textContent=active?'Exit fullscreen':'Fullscreen';fullscreen.setAttribute('aria-label',active?'Exit recording fullscreen':'Open recording fullscreen');};
 document.addEventListener('fullscreenchange',updateFullscreen);document.addEventListener('webkitfullscreenchange',updateFullscreen);
 document.addEventListener('click',async event=>{
   const button=event.target.closest('[data-replay]');if(!button)return;event.preventDefault();release();opener=button;
   status.hidden=false;status.textContent='Loading recording…';if(!dialog.open)dialog.showModal();controller=new AbortController();const thisLoad=loadId;pendingStart=Number(button.dataset.startMs)||0;
   try{
     const response=await fetch(button.dataset.replay,{credentials:'same-origin',signal:controller.signal});if(!response.ok)throw new Error('This recording is unavailable or has been withdrawn. Close the viewer and refresh the page.');
     const data=await response.json();if(!dialog.open||thisLoad!==loadId)return;
     showResult(data.result);showEvents(data);
     dialog.querySelector('[data-replay-kind]').textContent=data.kind==='video'?'VIDEO RECORDING':'WEBOTS · INTERACTIVE 3D';
     if(data.kind==='video'){
       dialog.querySelector('h2').textContent=data.title;
       const video=document.createElement('video');video.controls=true;video.playsInline=true;video.preload='metadata';video.setAttribute('aria-label',data.title+' video recording');
       video.addEventListener('loadeddata',()=>{clearTimeout(timer);status.hidden=true;});
       video.addEventListener('loadedmetadata',()=>seek(pendingStart));
       for(const name of ['timeupdate','seeked','loadedmetadata'])video.addEventListener(name,()=>updatePosition(video.currentTime*1000));
       video.addEventListener('error',()=>{clearTimeout(timer);status.hidden=false;status.textContent='The video could not be loaded or its codec is unsupported. Try an MP4 with H.264 video and AAC audio, or contact the organizer.';});
       timer=setTimeout(()=>{status.hidden=false;status.textContent='The video is taking too long to load. Check your connection, then close and reopen the viewer.';},90000);
       video.src=data.url;stage.append(video);video.play().catch(()=>{if(dialog.open){status.hidden=false;status.textContent='Press Play in the video controls to start the recording.';}});return;
     }
     dialog.querySelector('h2').textContent=data.title;nonce=new URL(data.url,location.origin).hash.slice(1);
     frame=document.createElement('iframe');frame.title=data.title+' interactive Webots replay';frame.sandbox='allow-scripts allow-pointer-lock';frame.allow='fullscreen';frame.allowFullscreen=true;frame.referrerPolicy='no-referrer';frame.src=data.url;stage.append(frame);
     timer=setTimeout(()=>{status.hidden=false;status.textContent='The recording is taking too long to load. Check your connection and WebGL support, then close and reopen the viewer.';},90000);
   }catch(error){if(error.name!=='AbortError')status.textContent=error.message;}
 });
 window.addEventListener('message',event=>{
   if(!frame||event.source!==frame.contentWindow||event.data?.nonce!==nonce)return;
   if(event.data.type==='asr-replay-ready'){playerReady=true;clearTimeout(timer);status.hidden=true;if(pendingStart){seek(pendingStart);pendingStart=0;}}
   if(event.data.type==='asr-replay-position')updatePosition(event.data.time_ms);
   if(event.data.type==='asr-replay-error'){clearTimeout(timer);status.hidden=false;status.textContent='A required scene, texture or player file could not be loaded. Close the viewer and try again, or contact the organizer.';}
 });
})();

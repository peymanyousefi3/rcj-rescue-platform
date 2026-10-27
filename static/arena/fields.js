'use strict';
(()=>{
 const dialog=document.querySelector('[data-field-dialog]');if(!dialog)return;
 const viewport=dialog.querySelector('[data-field-viewport]'),status=dialog.querySelector('[data-field-status]');let opener,controller;
 dialog.querySelector('[data-field-close]').addEventListener('click',()=>dialog.close());
 dialog.addEventListener('close',()=>{controller?.abort();viewport.replaceChildren();opener?.focus({preventScroll:true});});
 document.addEventListener('click',async event=>{
   const button=event.target.closest('[data-field]');if(!button)return;event.preventDefault();opener=button;
   controller?.abort();controller=new AbortController();viewport.replaceChildren();status.hidden=false;status.textContent='Loading field…';if(!dialog.open)dialog.showModal();
   try{const response=await fetch(button.dataset.field,{credentials:'same-origin',signal:controller.signal});if(!response.ok)throw new Error('This map is unavailable or has not been released for your team.');
     if(!dialog.open)return;const frame=document.createElement('iframe');frame.title='Round field information and interactive 3D map';frame.src=button.dataset.field;frame.allow='fullscreen';frame.allowFullscreen=true;frame.addEventListener('load',()=>{status.hidden=true;});viewport.append(frame);
   }catch(error){if(error.name!=='AbortError')status.textContent=error.message;}
 });
})();

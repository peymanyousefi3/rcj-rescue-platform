 'use strict';
const calendarElement=document.querySelector('#schedule-calendar');
const adminDialog=document.querySelector('[data-admin-dialog]');
let editorUrl,returnFocus,editorController;
function finishEditor(url){
 const next=new URL(url,location.origin);
 if(next.pathname===location.pathname&&next.search===location.search){location.hash=next.hash;location.reload();}else location.assign(next.href);
}
function initEditor(content){ASRAdmin.init(content);ASRAdmin.lineups(content);initResultUploads(content);initFieldFolders(content);initScoringSettings(content);}

function initScoringSettings(root){
 root.querySelectorAll('[data-form-kind="challenge"]').forEach(form=>{
  const method=form.elements.calculation;
  function update(){const field=method.value==='trimmed_mean';for(const name of ['discard_count','tie_break','top_count','score_source']){const block=form.querySelector('[data-form-field="'+name+'"]');if(block)block.hidden=['discard_count','tie_break'].includes(name)?!field:name==='top_count'?method.value!=='best':field;}}
  method.addEventListener('change',update);update();
 });
}

async function openCalendarEditor(url){
  editorController?.abort();editorController=new AbortController();
  editorUrl=new URL(url,location.origin);editorUrl.hash='';const requestedUrl=new URL(editorUrl);
  const content=adminDialog.querySelector('[data-dialog-content]');
  if(!adminDialog.open){returnFocus=document.activeElement;adminDialog.showModal();}
  content.textContent='Loading editor…';
  try{
    const response=await fetch(requestedUrl,{credentials:'same-origin',signal:editorController.signal});
    if(!response.ok||response.redirected)throw new Error('The editor could not be opened. Refresh and sign in again.');
    const html=await response.text();if(!adminDialog.open||requestedUrl.href!==editorUrl.href)return;content.innerHTML=html;
    const titles={round:'Round settings',event:'Schedule activity',superteam:'SuperTeam profile',team:'Team & account',quarantine:'File quarantine',window:'Round upload window',share:'Shared file delivery',file:'File details',notice:'Announcement',challenge:'Challenge & scoring',competition:'Competition settings','email-settings':'Email settings','managed-upload':'Upload files'};
    adminDialog.querySelector('h2').textContent=editorUrl.pathname.includes('/results/')?(editorUrl.searchParams.get('recording')==='1'?'Team recording':'Team results & recording'):titles[editorUrl.searchParams.get('editor')]||'Edit entry';
    initEditor(content);
    content.querySelector('.admin-form input:not([type=hidden]),.admin-form select')?.focus({preventScroll:true});
  }catch(error){if(error.name!=='AbortError')content.textContent=error.message;}
}
if(adminDialog){
 adminDialog.querySelector('[data-dialog-close]').addEventListener('click',()=>adminDialog.close());
 adminDialog.addEventListener('close',()=>{editorController?.abort();adminDialog.querySelector('[data-dialog-content]').replaceChildren();returnFocus?.focus({preventScroll:true});});
 adminDialog.addEventListener('click',event=>{
   const type=event.target.closest('[data-calendar-type]');
   if(type){event.preventDefault();const url=new URL(editorUrl);url.searchParams.set('editor',type.dataset.calendarType);url.searchParams.delete('round');openCalendarEditor(url);}
 });
 adminDialog.addEventListener('change',event=>{
   if(event.target.matches('[data-calendar-existing-round]')&&event.target.value){const url=new URL(editorUrl);url.searchParams.set('editor','round');url.searchParams.set('round',event.target.value);openCalendarEditor(url);}
 });
 adminDialog.addEventListener('submit',async event=>{
   const form=event.target;if(!form.matches('.admin-form,[data-recording-action]'))return;event.preventDefault();
   const button=form.querySelector('button[type=submit]');if(form.dataset.saving)return;form.dataset.saving='1';button.disabled=true;
   try{
     const recordingAction=form.matches('[data-recording-action]');
     const body=new FormData(form),sourceCell=returnFocus?.closest('[data-score-cell]');
     if(form.matches('[data-result-form]')&&sourceCell){
       if(sourceCell.querySelector('[data-raw-score]').value!=='')body.set('skip_score_import','on');
       if(sourceCell.querySelector('[data-remaining-time]').value.trim()!=='')body.set('skip_time_import','on');
     }
     const response=await fetch(recordingAction?form.action:editorUrl,{method:'POST',headers:recordingAction?{'X-ASR-Recording':'1'}:{'X-ASR-Editor':'1'},body,credentials:'same-origin'});
     if(response.redirected){
       if(recordingAction||editorUrl.searchParams.get('inline')==='1')throw new Error('Your scores are still here. Sign in again in another tab, then retry the recording.');
       finishEditor(response.url);return;
     }
     if(response.headers.get('Content-Type')?.includes('application/json')){
       const result=await response.json();
       if(response.ok&&result.recording_update){document.dispatchEvent(new CustomEvent('asr-recording-updated',{detail:result.recording_update}));adminDialog.close();return;}
       if(!response.ok||!result.redirect)throw new Error(result.error||'Could not save this entry.');
       finishEditor(result.redirect);
       return;
     }
     if(!response.ok)throw new Error('Could not save this entry. Close and reopen it to try again.');
     const content=adminDialog.querySelector('[data-dialog-content]');content.innerHTML=await response.text();initEditor(content);
     content.querySelector('.errorlist')?.scrollIntoView({block:'nearest'});
   }catch(error){delete form.dataset.saving;button.disabled=false;let message=form.querySelector('[data-save-error]');if(!message){message=document.createElement('p');message.dataset.saveError='';message.setAttribute('role','alert');form.prepend(message);}message.textContent=error.message;}
 });
}
if(calendarElement&&window.FullCalendar){
 const entries=JSON.parse(document.querySelector('#calendar-data').textContent);
 const status=document.querySelector('[data-calendar-status]'),day=document.querySelector('[data-calendar-date]');
 let saved={};try{saved=JSON.parse(sessionStorage.getItem('asr-calendar')||'{}');}catch(_){}
 const initial=saved.date||calendarElement.dataset.firstDay;let saving=false;
 function editor(kind,id,start,end){
   const url=new URL('/control/',location.origin);url.searchParams.set('editor',kind);url.searchParams.set('return','programme');if(id)url.searchParams.set(kind,id);
   if(start)url.searchParams.set('starts_at',start);if(end)url.searchParams.set('ends_at',end);openCalendarEditor(url);
 }
 async function persist(info){
   if(saving){info.revert();return;}saving=true;status.textContent='Saving schedule…';calendar.setOption('editable',false);
   const item=info.event,props=item.extendedProps,data=new FormData();data.set('kind',props.kind);data.set('id',props.pk);data.set('revision',props.revision);
   data.set('starts_at',item.start.toISOString().slice(0,19));data.set('ends_at',item.end.toISOString().slice(0,19));
   try{
     const response=await fetch(calendarElement.dataset.moveUrl,{method:'POST',headers:{'X-CSRFToken':document.querySelector('input[name=csrfmiddlewaretoken]').value},body:data,credentials:'same-origin'});
     const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not save. The previous time has been restored.');
     item.setExtendedProp('revision',result.revision);if(result.end)item.setEnd(result.end);status.textContent=result.message+' Workbook updates are paused.';
   }catch(error){info.revert();status.textContent=error.message;}
   finally{saving=false;calendar.setOption('editable',true);}
 }
 const calendar=new FullCalendar.Calendar(calendarElement,{
   initialView:saved.view==='competition'?'competition':'timeGridDay',initialDate:initial,timeZone:'UTC',
   views:{competition:{type:'timeGrid',visibleRange:{start:calendarElement.dataset.firstDay,end:calendarElement.dataset.endDay},buttonText:'Competition'}},
   headerToolbar:{left:'prev,next today',center:'title',right:'timeGridDay,competition'},
   buttonIcons:false,buttonText:{today:'Today',prev:'Previous',next:'Next',day:'Day'},allDaySlot:false,
   height:680,slotMinTime:'00:00:00',slotMaxTime:'24:00:00',scrollTime:'09:00:00',slotDuration:'00:30:00',snapDuration:'00:05:00',
   eventTimeFormat:{hour:'2-digit',minute:'2-digit',hour12:false},slotLabelFormat:{hour:'2-digit',minute:'2-digit',hour12:false},
   firstDay:1,nowIndicator:true,editable:true,eventResizableFromStart:true,longPressDelay:500,events:entries,
   selectable:true,selectMirror:true,unselectAuto:true,
   eventDrop:persist,eventResize:persist,
   eventDidMount:info=>{info.el.tabIndex=0;info.el.setAttribute('role','button');info.el.setAttribute('aria-label','Edit '+info.event.title);info.el.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();editor(info.event.extendedProps.kind,info.event.extendedProps.pk);}});},
   datesSet:info=>{day.value=calendar.getDate().toISOString().slice(0,10);sessionStorage.setItem('asr-calendar',JSON.stringify({date:day.value,view:info.view.type}));},
   eventClick:info=>{if(!saving)editor(info.event.extendedProps.kind,info.event.extendedProps.pk);},
   select:info=>{editor('event',null,info.startStr.slice(0,19),info.endStr.slice(0,19));calendar.unselect();}
 });
 document.querySelector('[data-calendar-add]').addEventListener('click',()=>editor('event',null,day.value+'T09:00:00',day.value+'T09:30:00'));
 calendar.render();day.addEventListener('change',()=>{if(day.value)calendar.changeView('timeGridDay',day.value);});
 document.querySelector('#programme').addEventListener('toggle',()=>{if(document.querySelector('#programme').open)calendar.updateSize();});
}
window.ASRAdmin.lineups=function(root=document){
root.querySelectorAll('[data-lineup-form]').forEach(form=>{
  const allTeams=JSON.parse(document.querySelector('#lineup-team-data').textContent),list=form.querySelector('[data-lineup-list]');
  const hidden=form.elements['lineup-lineup'],status=form.querySelector('[data-lineup-status]');
  const stored=JSON.parse(hidden.value||'[]');
  const rows=new Map(stored.map(row=>[row.team,row]));
  function iconButton(label,text,action){const button=document.createElement('button');button.type='button';button.className='admin-icon';button.setAttribute('aria-label',label);button.title=label;button.textContent=text;button.addEventListener('click',action);return button;}
  function input(row,key,label,type='number'){
    const wrapper=document.createElement('label');wrapper.className='lineup-cell';const caption=document.createElement('span');caption.className='lineup-mobile-label';caption.textContent={duration:'Run minutes',gap:'Gap before',field:'Location'}[key];
    const field=document.createElement('input');field.type=type;field.value=row[key]??'';field.setAttribute('aria-label',label);field.dataset.runField=key;
    if(type==='number'){field.step='any';field.min=key==='duration'?'.01':'0';field.max='10080';field.required=true;}else field.maxLength=30;
    field.addEventListener('input',sync);wrapper.append(caption,field);return wrapper;
  }
  function create(row){
    const team=allTeams.find(t=>t.id===row.team);if(!team)return;
    const item=document.createElement('li');item.className='lineup-row';item.dataset.team=row.team;item.runData=row;
    const identity=document.createElement('div');identity.className='lineup-identity';
    const handle=document.createElement('span');handle.className='lineup-handle';handle.textContent='⠿';handle.setAttribute('aria-hidden','true');handle.title='Drag to reorder';
    const label=document.createElement('div'),number=document.createElement('span');number.className='lineup-number';const name=document.createElement('strong');name.textContent=team.name;
    const code=document.createElement('small');code.textContent=team.code;label.append(name,code);identity.append(handle,number,label);
    const time=document.createElement('output');time.className='lineup-time';time.setAttribute('aria-label','Run time for '+team.name);
    const actions=document.createElement('div');actions.className='lineup-actions';
    actions.append(iconButton('Move '+team.name+' up','↑',()=>{if(item.previousElementSibling)list.insertBefore(item,item.previousElementSibling);sync();}),iconButton('Move '+team.name+' down','↓',()=>{if(item.nextElementSibling)list.insertBefore(item.nextElementSibling,item);sync();}));
    item.append(identity,time,input(row,'duration','Run minutes for '+team.name),input(row,'gap','Gap before '+team.name),input(row,'field','Location for '+team.name,'text'),actions);list.append(item);
  }
  function sync(){
    const roundStart=new Date(form.elements.starts_at.value+'Z').getTime();let cursor=roundStart;let invalid=false;
    const arranged=[...list.children].map((item,index)=>{
      const row={...item.runData};item.querySelectorAll('[data-run-field]').forEach(field=>{row[field.dataset.runField]=field.type==='number'?Number(field.value):field.value;});
      cursor+=row.gap*60000;const start=cursor;cursor+=row.duration*60000;invalid ||= start<roundStart||row.duration<=0;
      item.querySelector('.lineup-number').textContent=index+1;
      const format=value=>Number.isFinite(value)?new Date(value).toISOString().slice(11,16):'—';item.querySelector('output').textContent=format(start)+'–'+format(cursor);
      const buttons=item.querySelectorAll('.lineup-actions button');buttons[0].disabled=index===0;buttons[1].disabled=index===list.children.length-1;
      rows.set(row.team,row);return row;
    });
    hidden.value=JSON.stringify(arranged);
    status.textContent=invalid?'Enter a valid run duration and gap for every team.':arranged.length+' teams · finishes '+(Number.isFinite(cursor)?new Date(cursor).toISOString().slice(0,16).replace('T',' at '):'after setting a start')+' · Toronto time';
    status.classList.toggle('is-error',invalid);
  }
  const challenge=form.elements.challenge,superChallenges=JSON.parse(document.querySelector('#superteam-challenge-data')?.textContent||'[]').map(String);
  function scopeTeams(changed=false){
    const scope=superChallenges.includes(challenge.value)?challenge.value:'';
    const boxes=[...form.querySelectorAll('[data-lineup-editor] [data-picker-option] input')];
    boxes.forEach(box=>{const allowed=box.dataset.teamChallenge===scope;box.disabled=!allowed;box.closest('[data-picker-option]').hidden=!allowed;if(changed)box.checked=allowed;});
    if(changed){list.replaceChildren();boxes.filter(box=>box.checked&&!box.disabled).forEach(box=>{const team=allTeams.find(t=>t.id.replaceAll('-','')===box.value.replaceAll('-',''));if(team)create(rows.get(team.id)||{team:team.id,duration:15,gap:0,field:'',confirmed:true});});sync();}
  }
  scopeTeams();challenge.addEventListener('change',()=>scopeTeams(true));
  stored.forEach(create);
  if(window.Sortable)Sortable.create(list,{handle:'.lineup-handle',animation:matchMedia('(prefers-reduced-motion: reduce)').matches?0:150,ghostClass:'lineup-ghost',onEnd:sync});
  form.querySelector('[data-lineup-editor] [data-team-picker]').addEventListener('change',()=>{
    const selected=[...form.querySelectorAll('[data-lineup-editor] [data-picker-option] input:checked')].map(box=>box.value.replaceAll('-',''));
    [...list.children].forEach(item=>{if(!selected.includes(item.dataset.team.replaceAll('-','')))item.remove();});
    allTeams.forEach(team=>{if(selected.includes(team.id.replaceAll('-',''))&&![...list.children].some(item=>item.dataset.team===team.id))create(rows.get(team.id)||{team:team.id,duration:15,gap:0,field:'',confirmed:true});});sync();
  });
  form.elements.starts_at.addEventListener('input',sync);
  form.addEventListener('submit',sync);form.addEventListener('reset',()=>requestAnimationFrame(()=>{list.replaceChildren();stored.forEach(row=>create({...row}));sync();}));sync();
});

};
window.ASRAdmin.lineups();

document.addEventListener('click',event=>{const link=event.target.closest('[data-result-editor]');if(link){event.preventDefault();openCalendarEditor(link.href);}});
async function recordingFolderFiles(entry,parent=''){
    const path=parent+entry.name;
    if(entry.isFile)return [{path,file:await new Promise((resolve,reject)=>entry.file(resolve,reject))}];
    const reader=entry.createReader(),files=[];let batch;
    while((batch=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject))).length)
      for(const child of batch)files.push(...await recordingFolderFiles(child,path+'/'));
    return files;
  }

function initResultUploads(root){
 root.querySelectorAll('[data-result-form]').forEach(form=>{
  const video=form.querySelector('[data-recording-video]'),videoStatus=form.querySelector('[data-video-selection]');
  video?.addEventListener('change',()=>{videoStatus.textContent=video.files[0]?video.files[0].name+' · Video will play first; the Webots export remains the fallback.':'';});
  const raw=form.elements.raw,normalized=form.elements.normalized,override=form.elements.normalized_override;
  const others=JSON.parse(root.querySelector('#other-raw-scores')?.textContent||'[]').map(Number);
  function normalize(){normalized.readOnly=!override.checked;if(override.checked)return;const value=raw.value===''?null:Number(raw.value),highest=Math.max(...others,...(value===null?[]:[value]));normalized.value=value===null||(highest===0&&form.hasAttribute('data-field-scoring')&&form.dataset.zeroPolicy!=='zero')?'':(highest===0?0:value/highest).toFixed(4);}
  if(raw.type!=='hidden'){raw.addEventListener('input',normalize);override.addEventListener('change',normalize);normalize();}
  const folder=form.querySelector('[data-export-folder]'),zip=form.querySelector('[data-export-zip]'),options=form.querySelector('[data-export-options]'),status=form.querySelector('[data-export-status]');
  const selects={};let selection=0,filesByPath=new Map(),replays=new Map(),fileCount=0;
  const thumbnail=form.querySelector('[data-export-thumbnail]'),thumbnailImage=thumbnail.querySelector('img'),thumbnailName=thumbnail.querySelector('[data-export-thumbnail-name]');let thumbnailReader;
  function clearThumbnail(){thumbnailReader?.abort();thumbnailReader=null;thumbnail.hidden=true;thumbnailImage.removeAttribute('src');thumbnailImage.alt='';thumbnailName.textContent='';}
  function showThumbnail(){
    clearThumbnail();const path=selects.preview.value,file=filesByPath.get(path);if(!file)return;
    const reader=new FileReader();thumbnailReader=reader;
    reader.onload=()=>{if(thumbnailReader!==reader||!form.isConnected)return;thumbnailName.textContent=path;thumbnailImage.alt='Selected thumbnail: '+file.name;thumbnailImage.src=reader.result;};
    reader.onerror=()=>{if(thumbnailReader!==reader||!form.isConnected)return;clearThumbnail();status.textContent='The selected thumbnail could not be read. Select the folder or preview image again.';};
    reader.readAsDataURL(file);
  }
  thumbnailImage.addEventListener('load',()=>{if(thumbnailReader&&form.isConnected)thumbnail.hidden=false;});
  thumbnailImage.addEventListener('error',()=>{if(!thumbnailImage.hasAttribute('src')||!form.isConnected)return;clearThumbnail();status.textContent='The selected thumbnail could not be displayed. Choose another preview image.';});

  [['entry','Choose replay HTML…'],['preview','Choose preview…']].forEach(([name,label])=>{
    const field=form.elements[name],select=document.createElement('select');select.name=name;select.id=field.id;
    select.add(new Option(label,''));field.replaceWith(select);selects[name]=select;
  });
  function detectThumbnail(){
    clearThumbnail();const entry=selects.entry.value,replay=replays.get(entry);selects.preview.value='';
    if(!replay){status.textContent=fileCount+' files selected. Choose the Webots replay HTML below.';return;}
    try{
      const reference=replay.thumbnail;
      if(!reference||/^(?:[a-z][a-z0-9+.-]*:|\/)/i.test(reference))throw new Error();
      const base=new URL(entry.split('/').map(encodeURIComponent).join('/'),'https://webots-export.invalid/');
      const image=new URL(reference,base),path=decodeURIComponent(image.pathname.slice(1));
      if(image.origin!==base.origin||!filesByPath.has(path)||![...selects.preview.options].some(option=>option.value===path))throw new Error();
      selects.preview.value=path;showThumbnail();
      status.textContent=fileCount+' files selected. Thumbnail detected from '+entry+': '+path+'.';
    }catch(_){status.textContent=fileCount+' files selected. The thumbnail referenced by this HTML is missing or unsupported. Include the complete export, or choose its preview below.';}
  }
  selects.entry.addEventListener('change',detectThumbnail);selects.preview.addEventListener('change',showThumbnail);
  async function choose(source,names){
    clearThumbnail();const current=++selection,other=source===folder?zip:folder;other.value='';replays=new Map();
    const files=[...source.files];fileCount=files.length;filesByPath=new Map(files.map((file,index)=>[names?.[index]||file.webkitRelativePath||file.name,file]));
    const pathsByFile=new Map([...filesByPath].map(([path,file])=>[file,path]));
    form.elements.paths.value=JSON.stringify([...filesByPath.keys()]);
    options.hidden=source===zip||!files.length;
    [['entry',/\.html?$/i,'Choose replay HTML…'],['preview',/\.(jpe?g|png|webp)$/i,'Choose preview…']].forEach(([name,pattern,label])=>{
      const select=selects[name];select.replaceChildren(new Option(label,''));
      for(const [path,file] of filesByPath)if(pattern.test(file.name))select.add(new Option(path,path));
    });
    if(!files.length){status.textContent='';return;}
    if(source===zip){status.textContent='ZIP selected. The server will detect the replay HTML and its thumbnail when you save.';return;}
    status.textContent=fileCount+' files selected. Detecting the replay and its thumbnail…';
    try{
      const candidates=await Promise.all(files.filter(file=>/\.html?$/i.test(file.name)).map(async file=>{
        // Template contents are inert: uploaded HTML is never mounted or executed.
        const template=document.createElement('template');template.innerHTML=await file.text();
        const viewers=template.content.querySelectorAll('webots-view');
        return viewers.length===1?[pathsByFile.get(file),{thumbnail:viewers[0].getAttribute('data-thumbnail')}]:null;
      }));
      if(current!==selection||!form.isConnected)return;
      replays=new Map(candidates.filter(Boolean));
      selects.entry.replaceChildren(new Option('Choose replay HTML…',''));
      for(const path of replays.keys())selects.entry.add(new Option(path,path));
      const named=[...replays.keys()].filter(path=>path.split('/').at(-1).toLowerCase()==='replay.html');
      if(replays.size===1||named.length===1){selects.entry.value=named[0]||replays.keys().next().value;detectThumbnail();}
      else status.textContent=replays.size?fileCount+' files selected. More than one recording was found. Choose its HTML below to detect the matching thumbnail.':'No Webots replay HTML was found. Choose a complete exported recording folder.';
    }catch(_){if(current===selection&&form.isConnected)status.textContent='The replay HTML could not be read. Select the folder again or upload its ZIP.';}
  }
  folder.addEventListener('change',()=>choose(folder));zip.addEventListener('change',()=>choose(zip));
  for(const zone of form.querySelectorAll('.recording-upload-grid .export-drop')){
    const input=zone.querySelector('input[type=file]');
    zone.addEventListener('dragover',event=>{event.preventDefault();zone.classList.add('is-dragging');});
    zone.addEventListener('dragleave',event=>{if(!zone.contains(event.relatedTarget))zone.classList.remove('is-dragging');});
    zone.addEventListener('drop',async event=>{
      event.preventDefault();zone.classList.remove('is-dragging');
      try{
        let selected=[...event.dataTransfer.files].map(file=>({file,path:file.name}));
        if(input===folder){
          const version=++selection,entries=[...event.dataTransfer.items].filter(item=>item.kind==='file').map(item=>item.webkitGetAsEntry?.());
          if(!entries.length||entries.some(entry=>!entry))throw new Error('Use Choose Webots export folder to preserve its subfolders in this browser.');
          selected=(await Promise.all(entries.map(entry=>recordingFolderFiles(entry)))).flat();
          if(version!==selection||!form.isConnected)return;
        }else if(selected.length!==1)throw new Error('Choose one ZIP or one video for this upload area.');
        const transfer=new DataTransfer();selected.forEach(item=>transfer.items.add(item.file));input.files=transfer.files;
        if(input===folder||input===zip)choose(input,selected.map(item=>item.path));else input.dispatchEvent(new Event('change',{bubbles:true}));
      }catch(error){status.textContent=error.message||'The files could not be read. Use the Choose button instead.';}
    });
  }
 });
}

document.addEventListener('click',event=>{
 const add=event.target.closest('.add-editor > summary');
 const open=event.target.closest('[data-open-editor]');
 const link=event.target.closest('a[href]');
 let url;
 if(add){
   const form=add.parentElement.querySelector('form[data-form-kind]');if(!form)return;
   url=new URL('/control/',location.origin);url.searchParams.set('editor',form.dataset.formKind);
 }else if(open){url=new URL('/control/',location.origin);url.searchParams.set('editor',open.dataset.openEditor);}
 else if(link&&!link.matches('[data-calendar-type],[data-result-editor]')){
   const candidate=new URL(link.href,location.origin);if(candidate.pathname!=='/control/'||!candidate.search)return;
   const kind=['round','superteam','team','event','share','file','challenge','window','notice','quarantine'].find(key=>candidate.searchParams.has(key));
   if(kind)candidate.searchParams.set('editor',kind);
   else if(candidate.searchParams.has('replace'))candidate.searchParams.set('editor','managed-upload');
   if(candidate.searchParams.has('editor'))url=candidate;
 }
 if(url){event.preventDefault();openCalendarEditor(url);}
});
// Individual deadlines are edited in a dialog rather than cramped table cells.
document.querySelectorAll('form.deadline-override').forEach(form=>{
 const button=document.createElement('button');button.type='button';button.className='button secondary';button.textContent='Edit deadline';
 const copy=form.cloneNode(true);copy.className='admin-form';
 const input=copy.querySelector('[type=datetime-local]');input.previousElementSibling?.classList.remove('sr-only');
 const save=copy.querySelector('button');save.className='button primary';save.textContent='Save deadline';
 const actions=document.createElement('div');actions.className='form-actions';actions.append(save);
 const cancel=document.createElement('a');cancel.href='/control/#quarantines';cancel.className='button secondary';cancel.textContent='Cancel';actions.append(cancel);copy.append(actions);
 button.addEventListener('click',()=>{editorUrl=new URL('/control/',location.origin);returnFocus=button;const content=adminDialog.querySelector('[data-dialog-content]');content.replaceChildren(copy.cloneNode(true));adminDialog.querySelector('h2').textContent='Individual team deadline';adminDialog.showModal();ASRAdmin.init(content);content.querySelector('[type=datetime-local]').focus();});
 form.replaceWith(button);
});
const legacyParams=new URLSearchParams(location.search);
if(!legacyParams.has('editor')&&['round','superteam','team','event','share','file','challenge','window','notice','quarantine','replace'].some(key=>legacyParams.has(key))){
 const key=[...legacyParams.keys()].find(key=>['round','superteam','team','event','share','file','challenge','window','notice','quarantine','replace'].includes(key));
 const url=new URL(location.href);url.searchParams.set('editor',key==='replace'?'managed-upload':key);openCalendarEditor(url);
}

function initFieldFolders(root){
 root.querySelectorAll('[data-field-package]').forEach(module=>{
  const form=module.closest('form'),input=module.querySelector('[data-field-folder]'),list=module.querySelector('[data-field-detection]'),status=module.querySelector('[data-field-detection-status]');let generation=0;
  const clear=module.querySelector('[data-field-folder-clear]');
  clear.addEventListener('click',()=>{generation++;input.value='';form.elements.field_paths.value='';form.elements.field_choices.value='';list.replaceChildren();list.hidden=true;status.textContent='';clear.hidden=true;});
  const roles=[['wbt','Webots world · WBT',/\.wbt$/i],['map_json','Map JSON',/\.json$/i],['info_json','Field information JSON',/\.json$/i],['glb','3D field · GLB',/\.glb$/i],['jpeg','Thumbnail · Image',/\.(png|jpe?g|jfif|gif|webp|avif|heic|heif|bmp|dib|ico|icns|tiff?|svg|jp2|j2k|jpf|ppm|pgm|pbm|pnm|tga|pcx|psd|dds|qoi)$/i]];
  input.addEventListener('change',async()=>{
   const current=++generation,files=[...input.files],paths=files.map(file=>file.webkitRelativePath||file.name);form.elements.field_paths.value=JSON.stringify(paths);list.replaceChildren();list.hidden=!files.length;clear.hidden=!files.length;
   if(!files.length){status.textContent='';form.elements.field_choices.value='';return;}
   status.textContent='Detecting field files…';const metadata=[],geometry=[];
   for(let i=0;i<files.length;i++){
    if(!/\.json$/i.test(paths[i]))continue;
    try{const data=JSON.parse(await files[i].text()),keys=Object.keys(data||{}).map(key=>key.toLowerCase().replaceAll('_',''));
      if(keys.some(key=>['tiles','grid','rooms','cells','map','walls'].includes(key)))geometry.push(paths[i]);
      else if(keys.some(key=>['website','author','description','dimensions','fieldname','name'].includes(key)))metadata.push(paths[i]);
    }catch(_){};
   }
   if(current!==generation)return;
   const worlds=paths.filter(path=>/\.wbt$/i.test(path));
   const assigned=new Set();
   for(const [role,title,pattern] of roles){
    const candidates=paths.filter((path,index)=>(pattern.test(path)||(role==='jpeg'&&files[index].type.startsWith('image/')))&&!path.split('/').some(part=>part.startsWith('.')));let preferred=candidates.filter(path=>!assigned.has(path));
    if(preferred.length!==1&&(role==='info_json'||role==='map_json')){
      const named=candidates.filter(path=>/(?:field[ _.-]*)?info(?:rmation)?|metadata/i.test(path.split('/').pop().replace(/\.json$/i,'')));
      const maps=candidates.filter(path=>!named.includes(path));
      preferred=role==='info_json'?named:maps;
      if(preferred.length!==1)preferred=(role==='info_json'?metadata:geometry.length?geometry:candidates.filter(path=>!metadata.includes(path))).filter(path=>candidates.includes(path)&&!assigned.has(path));
    }else if(candidates.length>1&&!['wbt','map_json','info_json'].includes(role)){
      const matched=candidates.filter(path=>worlds.some(world=>world.replace(/\.[^.]+$/,'')===path.replace(/\.[^.]+$/,'')));if(matched.length===1)preferred=matched;else if(role==='jpeg'){const previews=candidates.filter(path=>/preview|thumbnail|thumb/i.test(path.split('/').pop()));if(previews.length===1)preferred=previews;}
    }
    const label=document.createElement('label'),caption=document.createElement('span'),select=document.createElement('select');caption.textContent=title;select.dataset.fieldRole=role;select.setAttribute('aria-label',title+' detected file');select.add(new Option('Choose a matching file…',''));
    candidates.forEach(path=>select.add(new Option(path,path)));if(preferred.length===1){select.value=preferred[0];assigned.add(preferred[0]);}
    select.addEventListener('change',sync);label.append(caption,select);list.append(label);
   }
   // A folder replaces the package in one operation; clear individual replacement inputs.
   for(const [role] of roles)form.elements[role].value='';sync();
  });
  function sync(){const choices={};list.querySelectorAll('[data-field-role]').forEach(select=>choices[select.dataset.fieldRole]=select.value);form.elements.field_choices.value=JSON.stringify(choices);const selected=Object.values(choices).filter(Boolean),complete=selected.length===5&&new Set(selected).size===5;status.textContent=complete?'All 5 field files detected. Ready to save.':'Select a match for each missing or ambiguous file type.';}
 });
}

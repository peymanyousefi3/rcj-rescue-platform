'use strict';
window.ASRAdmin={
elapsedSeconds(value){
 value=String(value??'').trim();if(value==='')return null;
 let remaining;
 if(/^[0-9]{1,3}$/.test(value))remaining=Number(value);
 else if(/^[0-9]{1,2}:[0-5][0-9]$/.test(value)){const [minutes,seconds]=value.split(':').map(Number);remaining=minutes*60+seconds;}
 else throw new Error('Enter remaining time from 0:00 to 8:00, or whole seconds from 0 to 480.');
 if(remaining>480)throw new Error('Enter remaining time from 0:00 to 8:00, or whole seconds from 0 to 480.');
 return 480-remaining;
},
formatClock(seconds){return seconds==null?'—':Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');},
refreshClock(input,output){
 try{const elapsed=this.elapsedSeconds(input.value);input.setCustomValidity('');output.textContent=this.formatClock(elapsed);}
 catch(error){input.setCustomValidity(error.message);output.textContent='—';}
},
scorePastePlan(text,{row,column,rowCount,columnCount}){
 const lines=text.replace(/^\uFEFF/,'').replace(/\r\n?/g,'\n').replace(/\n$/,'').split('\n').map(line=>line.split('\t'));
 const width=lines[0].length;
 if(lines.some(line=>line.length!==width))throw new Error('Copy a rectangular block of score cells, without team names or headers.');
 if(row<0||column<0||row+lines.length>rowCount||column+width>columnCount)throw new Error('The copied block does not fit from this cell. Copy fewer cells or start nearer the top left.');
 return lines.flatMap((line,r)=>line.map((entry,c)=>{
  let value=entry.trim();
  if(/^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$/.test(value))value=value.replaceAll(',','');
  if(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d+$/.test(value)){
   const [mantissa,power]=value.toLowerCase().split('e'),exponent=Number(power);
   if(!Number.isSafeInteger(exponent)||Math.abs(exponent)>100)throw new Error('The copied exponent is outside the score range.');
   const sign=mantissa.startsWith('-')?'-':'',[whole,fraction='']=mantissa.replace(/^[+-]/,'').split('.'),digits=whole+fraction,point=whole.length+exponent;
   value=sign+(point<=0?'0.'+'0'.repeat(-point)+digits:point>=digits.length?digits+'0'.repeat(point-digits.length):digits.slice(0,point)+'.'+digits.slice(point));
  }
  if(value&&!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value))throw new Error('Copied row '+(r+1)+', column '+(c+1)+': use numeric scores with a decimal point, without formulas, units or headers.');
  const [whole,fraction='']=value.replace(/^[+-]/,'').split('.');
  if(whole.replace(/^0+/,'').length>10||fraction.length>4)throw new Error('Copied row '+(r+1)+', column '+(c+1)+': use at most 10 digits before the decimal point and 4 after it.');
  value=value.replace(/^\+/,'').replace(/^(-?)\./,(_,sign)=>sign+'0.').replace(/\.$/,'');
  return {row:row+r,column:column+c,value};
 }));
},
scoreHistory(initial){
 return {value:initial,past:[],group:null,
  record(next,group=null){
   if(JSON.stringify(next)===JSON.stringify(this.value))return false;
   if(group===null||group!==this.group){this.past.push(this.value);if(this.past.length>100)this.past.shift();}
   if(group!==null&&group===this.group&&JSON.stringify(next)===JSON.stringify(this.past.at(-1))){this.past.pop();group=null;}
   this.value=next;this.group=group;return true;
  },
  undo(){if(!this.past.length)return null;this.group=null;this.value=this.past.pop();return this.value;},
  rebase(index,before,after){for(const state of [this.value,...this.past])state[index]=state[index].map((value,i)=>value===before[i]?after[i]:value);this.group=null;},
  commit(next){this.value=next;this.past.length=0;this.group=null;}
 };
},
init(root=document){
root.querySelectorAll('[data-form-kind="quarantine"]').forEach(form=>{
 const challenge=form.elements.challenge;if(!challenge)return;
 const update=()=>{form.querySelectorAll('[data-team-challenge]').forEach(box=>{const allowed=box.dataset.teamChallenge===challenge.value;box.disabled=!allowed;box.closest('[data-picker-option]').hidden=!allowed;if(!allowed)box.checked=false;});};
 challenge.addEventListener('change',update);update();
});
root.querySelectorAll('[data-run-clock]').forEach(clock=>{
 const input=clock.querySelector('[data-remaining-time]'),output=clock.querySelector('[data-elapsed-time]');
 const refresh=()=>ASRAdmin.refreshClock(input,output);input.addEventListener('input',refresh);
 clock.closest('form')?.addEventListener('reset',()=>requestAnimationFrame(refresh));refresh();
});
root.querySelectorAll('[data-email-settings]').forEach(form=>{
 const update=()=>{const gmail=form.elements.provider.value==='gmail';const smtp=form.querySelector('[data-smtp-fields]');smtp.hidden=gmail;smtp.disabled=gmail;form.querySelector('[data-gmail-help]').hidden=!gmail;};
 form.elements.provider.addEventListener('change',update);update();
});
root.querySelectorAll('[data-managed-upload]').forEach(form=>{
 const destination=form.elements.destination,select=form.querySelector('[data-recipient-destination]');
 function update(){
  if(select)destination.value=select.value;
  const scope=destination.value,names=new Set(['title','files','replacement','targets']);
  if(['team','public'].includes(scope))names.add('kind');
  if(scope==='map'||scope==='team'&&form.elements.kind.value==='round_file')names.add('round');
  if(scope==='quarantine')names.add('quarantine');
  form.querySelectorAll('[data-upload-field]').forEach(group=>{group.hidden=!names.has(group.dataset.uploadField);group.querySelectorAll('input,select,textarea').forEach(input=>input.disabled=group.hidden);});
  const publicOption=form.querySelector('[data-public-recipient]');if(publicOption){publicOption.hidden=scope!=='organizer';publicOption.querySelector('input').disabled=scope!=='organizer';}
  // Public resources have no team recipient. Keep the integrated destination control visible.
  const picker=form.querySelector('[data-team-picker]');if(picker){picker.hidden=scope==='resource';picker.querySelectorAll('input').forEach(input=>input.disabled=scope==='resource');}
 }
 select?.addEventListener('change',update);form.elements.kind.addEventListener('change',update);form.addEventListener('reset',()=>requestAnimationFrame(update));update();
});
// Native controls preserve keyboard behavior and ordinary form submissions.
root.querySelectorAll('[data-score-grid]').forEach(browser=>{
 const form=browser.querySelector('[data-score-form]');if(!form)return;
 const status=browser.querySelector('[data-score-status]'),search=browser.querySelector('[data-score-search]');
 const save=form.querySelector('[type=submit]'),reset=form.querySelector('[type=reset]'),undo=form.querySelector('[data-score-undo]'),missing=browser.querySelector('[data-score-missing-count]');let saving=false;
 const cells=[...browser.querySelectorAll('[data-score-cell]')].map(element=>({element,raw:element.querySelector('[data-raw-score]'),remaining:element.querySelector('[data-remaining-time]'),elapsed:element.querySelector('[data-elapsed-time]'),output:element.querySelector('[data-normalized]'),manual:element.querySelector('[data-score-manual]'),override:element.querySelector('[data-score-override]'),error:element.querySelector('[data-score-error]')}));
 cells.forEach(cell=>cell.savedNormalized=cell.output.textContent);
 const inputs=cells.flatMap(cell=>[cell.raw,cell.remaining,cell.manual,cell.override].filter(Boolean));
 const snapshot=()=>cells.map(cell=>[cell.raw.value,!!cell.override?.checked,cell.override?.checked?cell.manual.value:'',cell.remaining.value]);
 const edits=ASRAdmin.scoreHistory(snapshot());
 const columns=[...browser.querySelectorAll('[data-score-column]')].map(header=>({header,cells:cells.filter(cell=>cell.element.dataset.round===header.dataset.scoreColumn),issue:browser.querySelector('[data-round-issue="'+header.dataset.scoreColumn+'"]')}));
 form.noValidate=true;
 const cellDirty=cell=>cell.raw.value!==cell.raw.defaultValue||cell.remaining.value!==cell.remaining.defaultValue||cell.override&&(cell.override.checked!==cell.override.defaultChecked||cell.override.checked&&cell.manual.value!==cell.manual.defaultValue);
 const dirty=()=>cells.some(cellDirty);
 function refresh(){
  let missingCount=0;
  cells.forEach(cell=>{
   ASRAdmin.refreshClock(cell.remaining,cell.elapsed);
   const empty=cell.raw.value===''&&!cell.raw.validity.badInput;
   cell.element.classList.toggle('is-missing',empty);cell.raw.placeholder=empty?'—':'';
   if(empty){missingCount++;cell.raw.setAttribute('aria-description','Missing raw score. Enter zero for a scored run with zero points.');cell.raw.title='Missing raw score';}
   else{cell.raw.removeAttribute('aria-description');cell.raw.removeAttribute('title');}
  });
  const missingText=missingCount+' missing';if(missing.textContent!==missingText)missing.textContent=missingText;
  columns.forEach(column=>{
   const values=column.cells.filter(cell=>cell.raw.value!==''&&cell.raw.validity.valid).map(cell=>Number(cell.raw.value)),highest=values.length?Math.max(...values):0;
   const field=column.header.dataset.fieldScoring==='true',policy=column.header.dataset.zeroPolicy;
   const changed=column.cells.some(cellDirty);
   column.cells.forEach(cell=>{
    const pending=field&&highest===0&&policy!=='zero',automatic=cell.raw.value===''||!cell.raw.validity.valid||pending?'':(highest===0?0:Number(cell.raw.value)/highest).toFixed(4);
    if(cell.manual){cell.manual.readOnly=!cell.override.checked;if(!cell.override.checked)cell.manual.value=automatic;}
    cell.output.textContent=!changed?cell.savedNormalized:cell.override?.checked?(cell.manual.value!==''&&cell.manual.validity.valid?Number(cell.manual.value).toFixed(4):'—'):automatic||'—';
   });
   const zero=field&&values.length===column.cells.length&&values.length>0&&highest===0;
   column.issue.textContent=zero&&policy!=='zero'?column.header.querySelector('.score-round-heading span').textContent+': '+(policy==='exclude'?'This all-zero round is excluded for every team.':'All field scores are zero. Choose an organizer decision in this round’s settings.'):'';
   column.issue.hidden=!column.issue.textContent;
  });
  save.disabled=saving||!dirty();reset.disabled=saving||!dirty();undo.disabled=saving||!edits.past.length;
 }
 const previewStatus=browser.querySelector('[data-score-preview-status]');
 const savedPreview=JSON.parse(browser.querySelector('script[id^="score-preview-data"]').textContent);
 let previewTimer,previewController,previewVersion=0;
 function renderPreview(data){
  browser.querySelector('[data-total-heading]').textContent=data.percentage?'Final %':'Total';
  previewStatus.textContent=data.message;browser.removeAttribute('aria-busy');
  browser.querySelectorAll('[data-score-row]').forEach(row=>{
   const result=data.rows[row.dataset.team],total=row.querySelector('[data-score-total]'),rank=row.querySelector('[data-score-rank]');
   total.textContent=result?.total!=null?result.total+(data.percentage?'%':''):'—';
   rank.textContent=result?.rank!=null?result.rank+(result.tie?' =':''):'—';
   total.title=data.provisional?'Provisional · completed rounds only':'Final calculation';
   rank.title=data.rankings_released?'Rankings released':'Rankings not released';
   row.querySelectorAll('[data-score-cell]').forEach(cell=>{
    const discarded=result?.discarded.includes(cell.dataset.round),excluded=result?.excluded.includes(cell.dataset.round),badge=cell.querySelector('[data-score-discard]');
    cell.classList.toggle('is-discarded',!!discarded);cell.classList.toggle('is-excluded',!!excluded);
    badge.textContent=excluded?'Excluded':'Discarded';badge.hidden=!discarded&&!excluded;
   });
  });
 }
 function clearPreview(message){
  browser.querySelectorAll('[data-score-total],[data-score-rank]').forEach(output=>output.textContent='—');
  cells.forEach(cell=>{cell.element.classList.remove('is-discarded','is-excluded');cell.element.querySelector('[data-score-discard]').hidden=true;});
  previewStatus.textContent=message;
 }
 function queuePreview(){
  clearTimeout(previewTimer);previewController?.abort();const version=++previewVersion;
  if(inputs.some(input=>!input.validity.valid)){clearPreview('Check the highlighted scores to calculate the preview.');browser.removeAttribute('aria-busy');return;}
  clearPreview('Calculating scores and discarded rounds…');browser.setAttribute('aria-busy','true');
  previewTimer=setTimeout(async()=>{
   previewController=new AbortController();
   try{
    const response=await fetch(browser.dataset.previewUrl,{method:'POST',body:new FormData(form),credentials:'same-origin',signal:previewController.signal});
    if(response.redirected||!response.ok||!response.headers.get('Content-Type')?.includes('application/json'))throw new Error('Preview unavailable. Your entries are kept; sign in again or reload if scores changed in another window.');
    const data=await response.json();if(version===previewVersion)renderPreview(data);
   }catch(error){if(error.name!=='AbortError'&&version===previewVersion){clearPreview(error.message);browser.removeAttribute('aria-busy');}}
  },250);
 }
 browser.addEventListener('asr-recording-updated',event=>{
  const data=event.detail,cell=cells.find(cell=>cell.element.dataset.round===data.round&&cell.element.dataset.team===data.team);if(!cell)return;
  const button=cell.element.querySelector('[data-result-editor]');button.classList.toggle('has-recording',data.present);button.querySelector('[data-recording-label]').textContent=data.present?'Recording':'Upload';
  cell.element.querySelector('.score-play')?.remove();if(data.player){const play=document.createElement('button');play.type='button';play.className='score-play';play.dataset.replay=data.player;play.textContent='▶';play.setAttribute('aria-label','Play recording');cell.element.querySelector('.score-cell-meta').append(play);}
  if(data.scores){
   const column=columns.find(column=>column.header.dataset.scoreColumn===data.round),revision=form.elements.namedItem('r'+data.round+'-revision');
   column.cells.forEach(cell=>{
    const team=cell.element.dataset.team,index=cells.indexOf(cell),before=[cell.raw.defaultValue,!!cell.override?.defaultChecked,cell.override?.defaultChecked?cell.manual.defaultValue:'',cell.remaining.defaultValue];
    const normalized=data.scores.normalized[team],after=[data.scores.raw[team]??'',!!data.scores.overrides[team],data.scores.overrides[team]?normalized??'':'',data.scores.elapsed_seconds[team]==null?'':ASRAdmin.formatClock(480-data.scores.elapsed_seconds[team])];
    const current=snapshot()[index].map((value,i)=>value===before[i]?after[i]:value);edits.rebase(index,before,after);
    cell.raw.defaultValue=after[0];cell.raw.value=current[0];cell.remaining.defaultValue=after[3];cell.remaining.value=current[3];
    cell.savedNormalized=normalized==null?'—':Number(normalized).toFixed(4);
    if(cell.override){cell.override.defaultChecked=after[1];cell.override.checked=current[1];cell.manual.defaultValue=after[2];cell.manual.value=current[2];}
   });
   revision.defaultValue=data.scores.revision;revision.value=data.scores.revision;refresh();queuePreview();
  }
  status.setAttribute('role','status');status.textContent='Recording updated.'+(dirty()?' Your unsaved scores are still here.':'');
 });
 document.addEventListener('asr-recording-updated',event=>browser.dispatchEvent(new CustomEvent('asr-recording-updated',{detail:event.detail})));
 function filter(){const query=search.value.trim().toLocaleLowerCase();let shown=0;browser.querySelectorAll('[data-score-row]').forEach(row=>{row.hidden=!row.querySelector('th').textContent.toLocaleLowerCase().includes(query);if(!row.hidden)shown++;});browser.querySelector('[data-score-empty]').hidden=shown>0;}
 function clearErrors(){inputs.forEach(input=>{input.removeAttribute('aria-invalid');input.removeAttribute('aria-describedby');});cells.forEach(cell=>cell.error.hidden=true);}
 function fieldError(input,message){const error=input.closest('[data-score-cell]').querySelector('[data-score-error]');error.id=input.id+'_error';error.textContent=message;error.hidden=false;input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby',error.id);}
 function reveal(input){search.value='';filter();input.closest('details')?.setAttribute('open','');input.focus();}
 search.addEventListener('input',filter);
 browser.addEventListener('input',event=>{if(saving||!inputs.includes(event.target))return;edits.record(snapshot(),event.target);clearErrors();refresh();queuePreview();status.setAttribute('role','status');status.textContent=dirty()?'Unsaved scores and times':'';});
 browser.addEventListener('focusout',event=>{if(inputs.includes(event.target))edits.group=null;});
 function undoEdit(){
  if(saving)return;const previous=edits.undo();if(!previous)return;
  cells.forEach((cell,index)=>{const [raw,override,manual,remaining]=previous[index];cell.raw.value=raw;cell.remaining.value=remaining;if(cell.override){cell.override.checked=override;cell.manual.value=manual;}});
  clearErrors();refresh();queuePreview();status.setAttribute('role','status');status.textContent='Last edit undone.'+(dirty()?' Unsaved scores':'');
 }
 undo.addEventListener('click',undoEdit);
 browser.addEventListener('paste',event=>{
  const start=cells.find(cell=>cell.raw===event.target);if(!start)return;
  const text=event.clipboardData?.getData('text/plain');if(!text)return;event.preventDefault();if(saving)return;
  try{
   const rows=[...browser.querySelectorAll('[data-score-row]')].filter(row=>!row.hidden);
   const plan=ASRAdmin.scorePastePlan(text,{row:rows.indexOf(start.element.closest('[data-score-row]')),column:columns.findIndex(column=>column.cells.includes(start)),rowCount:rows.length,columnCount:columns.length});
   const changes=plan.map(item=>({input:rows[item.row].querySelectorAll('[data-raw-score]')[item.column],value:item.value}));
   for(const change of changes){const probe=change.input.cloneNode(false);probe.value=change.value;if(change.value!==''&&(!probe.value||!probe.validity.valid))throw new Error(change.input.getAttribute('aria-label')+': this score is outside the allowed range.');}
   changes.forEach(change=>change.input.value=change.value);
   const changed=edits.record(snapshot());clearErrors();refresh();if(changed)queuePreview();
   status.setAttribute('role','status');status.textContent=changed?'Pasted '+changes.length+' score cells. Unsaved scores':'The pasted scores already match this table.';
  }catch(error){status.setAttribute('role','alert');status.textContent='Nothing pasted. '+error.message;}
 });
 browser.addEventListener('focusout',event=>{if(inputs.includes(event.target)&&!event.target.validity.valid)fieldError(event.target,event.target.validationMessage);});
 browser.addEventListener('keydown',event=>{
  if((event.ctrlKey||event.metaKey)&&!event.shiftKey&&event.key.toLowerCase()==='z'&&(event.target.closest('[data-score-cell]')||event.target===undo)){if(event.target.validity?.badInput)return;event.preventDefault();undoEdit();return;}
  if(event.key!=='Enter'||!inputs.includes(event.target))return;event.preventDefault();
  if(event.ctrlKey||event.metaKey){if(dirty()&&!saving)form.requestSubmit();return;}
  const key=event.target.matches('[data-remaining-time]')?'remaining':'raw';
  const column=columns.find(column=>column.cells.some(cell=>cell[key]===event.target));if(!column)return;
  const visible=column.cells.filter(cell=>!cell.element.closest('tr').hidden),index=visible.findIndex(cell=>cell[key]===event.target),next=visible[index+(event.shiftKey?-1:1)];if(next){next[key].focus();next[key].select();}
 });
 form.addEventListener('reset',()=>requestAnimationFrame(()=>{edits.record(snapshot());clearErrors();refresh();queuePreview();status.setAttribute('role','status');status.textContent='Changes reset. Use Undo to restore them.';}));
 browser.addEventListener('click',event=>{if(!dirty()||!event.target.closest('[data-score-settings]'))return;event.preventDefault();event.stopPropagation();status.textContent='Save or reset these scores before editing scoring settings.';status.focus();});
 browser.addEventListener('submit',event=>{if(event.target===form||!dirty())return;event.preventDefault();status.textContent='Save or reset these scores before removing a recording.';status.focus();});
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(saving||!dirty())return;clearErrors();const body=new FormData(form);saving=true;
  inputs.forEach(input=>{if(input.type==='checkbox')input.disabled=true;else input.readOnly=true;});save.disabled=true;reset.disabled=true;undo.disabled=true;status.textContent='Saving all scores…';
  try{
   const session=await fetch(form.action,{credentials:'same-origin',cache:'no-store'});
   if(session.redirected||!session.ok||!session.headers.get('Content-Type')?.includes('application/json'))throw new Error('Your entries are still here. Sign in again in another tab, then retry Save all scores.');
   const token=await session.json();body.set('csrfmiddlewaretoken',token.csrf);form.elements.csrfmiddlewaretoken.value=token.csrf;
   const response=await fetch(form.action,{method:'POST',body,credentials:'same-origin',headers:{'X-ASR-Scores':'1'}});
   if(response.redirected||!response.headers.get('Content-Type')?.includes('application/json'))throw new Error('Could not save. Your entries are still here. Reload or sign in again in another tab, then retry.');
   const result=await response.json();if(!response.ok){
    status.replaceChildren();status.setAttribute('role','alert');status.append('No scores were saved. ');
    Object.entries(result.errors||{}).forEach(([name,errors])=>{
     const message=errors.map(error=>error.message).join(' '),input=form.elements.namedItem(name);
     if(input&&inputs.includes(input)){
      fieldError(input,message);const link=document.createElement('a');link.href='#'+input.id;link.textContent=input.getAttribute('aria-label')+': '+message;link.addEventListener('click',event=>{event.preventDefault();reveal(input);});status.append(link,' ');
     }else status.append(message+' ');
    });status.focus();return;
   }
   columns.forEach(column=>{const id=column.header.dataset.scoreColumn,data=result.rounds[id],revision=form.elements.namedItem('r'+id+'-revision');revision.value=data.revision;revision.defaultValue=data.revision;
    column.cells.forEach(cell=>{const elapsed=data.elapsed_seconds[cell.element.dataset.team];cell.remaining.value=elapsed==null?'':ASRAdmin.formatClock(480-elapsed);cell.remaining.defaultValue=cell.remaining.value;cell.raw.defaultValue=cell.raw.value;cell.savedNormalized=data.normalized[cell.element.dataset.team]==null?'—':Number(data.normalized[cell.element.dataset.team]).toFixed(4);if(cell.override){cell.override.checked=!!data.overrides[cell.element.dataset.team];cell.override.defaultChecked=cell.override.checked;cell.manual.value=data.normalized[cell.element.dataset.team]??'';cell.manual.defaultValue=cell.manual.value;}});
   });
   status.setAttribute('role','status');status.textContent='All round scores saved.';edits.commit(snapshot());queuePreview();
  }catch(error){status.setAttribute('role','alert');status.textContent=error.message;}
  finally{saving=false;inputs.forEach(input=>{input.disabled=false;input.readOnly=false;});refresh();}
 });
 refresh();filter();renderPreview(savedPreview);
});
root.querySelectorAll('[data-team-picker]').forEach(picker => {
  const choices=[...picker.querySelectorAll('[data-picker-option]')];
  const search=picker.querySelector('[data-picker-search]');
  const boxes=choices.map(item=>item.querySelector('input[type=checkbox]'));
  function refresh(){
    const query=search.value.trim().toLocaleLowerCase();let visible=0;
    choices.forEach(item=>{item.hidden=item.querySelector('input').disabled||!item.textContent.toLocaleLowerCase().includes(query);if(!item.hidden)visible++;});
    picker.querySelector('[data-picker-count]').textContent=boxes.filter(box=>box.checked&&!box.disabled).length+' of '+boxes.filter(box=>!box.disabled).length+' teams selected';
    picker.querySelector('.picker-empty').hidden=visible>0;
  }
  picker.querySelector('[data-picker-all]').addEventListener('click',()=>{boxes.forEach(box=>box.checked=!box.disabled);picker.dispatchEvent(new Event('change',{bubbles:true}));refresh();});
  picker.querySelector('[data-picker-clear]').addEventListener('click',()=>{boxes.forEach(box=>box.checked=false);picker.dispatchEvent(new Event('change',{bubbles:true}));refresh();});
  picker.addEventListener('change',refresh);search.addEventListener('input',refresh);refresh();
  picker.closest('form')?.addEventListener('reset',()=>requestAnimationFrame(refresh));
});
root.querySelectorAll('[data-table-browser]').forEach(browser=>{
  const search=browser.querySelector('[data-row-search]'),team=browser.querySelector('[data-row-team]'),status=browser.querySelector('[data-row-status]');
  const rows=[...browser.querySelectorAll('tr[data-search-row]')];if(!rows.length)return;
  const controls=document.createElement('div');controls.className='table-pagination';
  const sizeLabel=document.createElement('label');sizeLabel.textContent='Entries ';
  const size=document.createElement('select');size.setAttribute('aria-label','Entries per page');
  [10,25,50,0].forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value||'All';size.append(option);});sizeLabel.append(size);
  const count=document.createElement('span');count.setAttribute('aria-live','polite');
  const previous=document.createElement('button'),next=document.createElement('button');
  [previous,next].forEach(button=>{button.type='button';button.className='page-button';});previous.textContent='Previous';next.textContent='Next';
  controls.append(sizeLabel,count,previous,next);browser.append(controls);
  const edited=rows.findIndex(row=>row.nextElementSibling?.classList.contains('editor-row'));let page=edited>=0?Math.floor(edited/10):0;
  function filter(reset=false){
    if(reset)page=0;const query=search?.value.trim().toLocaleLowerCase()||'';
    const matches=rows.filter(row=>row.textContent.toLocaleLowerCase().includes(query)&&(!team?.value||(row.dataset.team||'').split(/\s+/).includes(team.value))&&(!status?.value||row.dataset.status===status.value));
    const per=Number(size.value)||Math.max(matches.length,1);const pages=Math.max(1,Math.ceil(matches.length/per));page=Math.min(page,pages-1);
    const shown=new Set(matches.slice(page*per,(page+1)*per));
    rows.forEach(row=>{row.hidden=!shown.has(row);if(row.nextElementSibling?.classList.contains('editor-row'))row.nextElementSibling.hidden=row.hidden;});
    count.textContent=matches.length?(page*per+1)+'–'+Math.min((page+1)*per,matches.length)+' of '+matches.length+' entries':'0 entries';previous.disabled=page===0;next.disabled=page>=pages-1;
    const empty=browser.querySelector('.filter-empty');if(empty)empty.hidden=matches.length>0;
  }
  [search,team,status].filter(Boolean).forEach(control=>control.addEventListener(control===search?'input':'change',()=>filter(true)));
  size.addEventListener('change',()=>filter(true));previous.addEventListener('click',()=>{page--;filter();});next.addEventListener('click',()=>{page++;filter();});filter();
});
root.querySelectorAll('[data-duration-form]').forEach(form=>{
  const mode=form.elements.end_mode,start=form.elements.starts_at,end=form.elements.ends_at,duration=form.elements.duration_minutes;
  if(!mode||!start||!end||!duration)return;
  const summary=document.createElement('p');summary.className='time-summary';summary.setAttribute('aria-live','polite');start.closest('.editor-group').append(summary);
  function update(){
    const byDuration=mode.value==='duration';
    const durationField=duration.closest('[data-form-field]'),endField=end.closest('[data-form-field]');
    durationField.hidden=!byDuration;endField.hidden=byDuration;duration.disabled=!byDuration;end.disabled=byDuration;
    duration.required=byDuration;end.required=!byDuration;
    if(start.value&&byDuration&&Number(duration.value)>0){
      const date=new Date(start.value+'Z');date.setUTCMinutes(date.getUTCMinutes()+Number(duration.value));
      if(!Number.isNaN(date.getTime())){end.value=date.toISOString().slice(0,16);summary.textContent='Finishes '+end.value.replace('T',' at ')+' · Toronto time';}
    } else if(start.value&&end.value&&!byDuration){const minutes=(new Date(end.value+'Z')-new Date(start.value+'Z'))/60000;summary.textContent=minutes>0?'Duration: '+minutes+' minutes':'Choose an end after the start.';}
    else summary.textContent='All dates and times use Toronto time.';
  }
  [mode,start,end,duration].forEach(control=>control.addEventListener('input',update));form.addEventListener('reset',()=>requestAnimationFrame(update));update();
});
root.querySelectorAll('.admin-table').forEach(table=>{
  const headings=[...table.querySelectorAll('thead th')].map(th=>th.textContent.trim());
  table.setAttribute('role','table');
  table.querySelectorAll('tbody tr').forEach(row=>{
    row.setAttribute('role','row');
    if(row.classList.contains('editor-row'))return;
    [...row.children].forEach((cell,index)=>{cell.dataset.label=headings[index]||'';cell.setAttribute('role','cell');});
  });
});
if(root===document){
function highlightAdminSection(section){
  root.querySelectorAll('#navigation nav[aria-label=Administration] a').forEach(link=>{
    if(link.getAttribute('href')==='#'+section.id)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');
  });
}
root.querySelectorAll('.admin-section').forEach(section=>section.addEventListener('toggle',()=>{if(section.open)highlightAdminSection(section);}));
function highlightAdminAnchor(){const target=document.getElementById(location.hash.slice(1));const section=target?.closest('.admin-section');if(section)highlightAdminSection(section);}
window.addEventListener('hashchange',highlightAdminAnchor);highlightAdminAnchor();

}
// Cancel has an explicit action even when the destination hash has not changed.
root.querySelectorAll('.admin-form a.button').forEach(link=>{
  if(link.textContent.trim()!=='Cancel')return;
  link.addEventListener('click',event=>{
    event.preventDefault();const form=link.closest('form');if(form.closest('dialog')){form.closest('dialog').close();return;}form.reset();
    if(location.search){location.assign(link.href);return;}
    const container=form.closest('.add-editor,.sub-editor')||form.closest('.admin-section');if(container){container.open=false;container.querySelector(':scope > summary')?.focus();}
    history.replaceState(null,'',link.href);
    const target=document.getElementById(new URL(link.href).hash.slice(1));if(target){target.open=true;target.querySelector(':scope > summary')?.focus();}
  });
});
root.querySelectorAll('.admin-form').forEach(form=>{
  const actions=form.querySelector('.form-actions');if(!actions||actions.querySelector('[data-cancel-editor],a.button.secondary'))return;
  const cancel=document.createElement('button');cancel.type='button';cancel.className='button secondary';cancel.textContent='Cancel';
  cancel.addEventListener('click',()=>{if(form.closest('dialog')){form.closest('dialog').close();return;}form.reset();const editor=form.closest('.sub-editor,.add-editor');if(editor){editor.open=false;editor.querySelector(':scope > summary')?.focus();}});actions.append(cancel);
});

}};
window.ASRAdmin.init();

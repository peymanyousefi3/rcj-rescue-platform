(() => {
  'use strict';
  const root=document.getElementById('slide-content');
  if (!root) return;
  const position=document.getElementById('slide-position'), status=document.getElementById('update-status');
  const pauseButton=document.getElementById('pause');
  let payload=null, slides=[], index=0, paused=false, advanceTimer, refreshTimer, deadline=0, busy=false;
  function el(tag,text,className) {
    const node=document.createElement(tag);
    if(text!==undefined && text!==null) node.textContent=String(text);
    if(className) node.className=className;
    return node;
  }
  const NS='http://www.w3.org/2000/svg';
  let layout=[];
  function svg(tag,attrs,text,parent){
    const node=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs || {}))node.setAttribute(key,String(value));
    if(text!==undefined)node.textContent=String(text);if(parent)parent.append(node);return node;
  }
  function color(key){return key==='white'?'#fff':(payload.design?.colors?.[key] || '#122039');}
  function text(parent,x,y,value,size=30,weight=400,fill='ink',font='Open Sans',maxWidth,anchor='start'){
    const node=svg('text',{x,y,'font-size':size,'font-weight':weight,fill:color(fill),'font-family':font,class:({'Open Sans':'font-open','Barlow Condensed':'font-score','Roboto':'font-brand','Arial':'font-table'}[font] || 'font-open'),'text-anchor':anchor},value,parent);
    if(maxWidth && String(value).length*size*.57>maxWidth){node.setAttribute('textLength',maxWidth);node.setAttribute('lengthAdjust','spacingAndGlyphs');}
    return node;
  }
  function line(parent,x,y,w,stroke='line'){svg('line',{x1:x,y1:y,x2:x+w,y2:y,stroke:color(stroke),'stroke-width':1.2},undefined,parent);}
  function picture(parent,key,x,y,w,h,cover=false){const url=payload.design.images[key];if(url)svg('image',{href:url,x,y,width:w,height:h,preserveAspectRatio:cover?'xMidYMid slice':'xMidYMid meet'},undefined,parent);}
  function canvas(label){
    const node=svg('svg',{viewBox:'0 0 1600 900',class:'slide',role:'img','aria-label':label,'aria-describedby':'slide-description'});
    let description=label;
    if(payload.enabled && label==='Competition results')description=payload.results.map(g=>g.name+': '+g.rows.map(r=>r.name+', '+r.scores.map((s,i)=>g.rounds[i].label+' raw '+(s.raw??'unavailable')+', normalized '+(s.normalized??'unavailable')+(s.discarded?' discarded':'')).join('; ')+', total '+(r.total??'pending')+(g.rankings_released?', rank '+(r.rank??'pending'):'')).join('. ')).join('. ');
    else if(payload.enabled && label==='Current competition day schedule')description=payload.design.texts.schedule_date+': '+payload.schedule.map(e=>e.start+' '+e.title+' '+e.note).join('. ');
    else if(payload.enabled)description=Object.entries(payload.design.texts).filter(([k])=>['event_name','title_small','title_large','title_bottom','venue','venue_location'].includes(k)).map(([,v])=>v).join('. ');
    svg('desc',{id:'slide-description'},description,node);svg('rect',{width:1600,height:900,fill:'#fff'},undefined,node);return node;
  }
  function logos(parent,small=false){picture(parent,'logo',small?33.33:72.5,small?13.33:33.75,small?60.3:90,small?64:95.5);picture(parent,'partner',small?136.67:222.5,small?20:47.5,small?97.2:145,small?55.8:83.3);if(!small)svg('line',{x1:190,y1:53.75,x2:190,y2:113.75,stroke:color('line')},undefined,parent);}
  function footer(parent){const t=payload.design.texts;line(parent,72.5,816.25,1455);text(parent,82.5,868,t.venue,27.5,700,'ink','Open Sans',430);text(parent,1518,868,t.venue_location,27.5,400,'muted','Open Sans',1000,'end');}
  function intro(){
    const node=canvas('Competition introduction'),t=payload.design.texts;
    for(const item of layout){
      if(item.type==='image')picture(node,item.key,item.x,item.y,item.w,item.h,item.key==='cover');
      else if(item.type==='rect'){
        if(item.shear)svg('polygon',{points:`${item.x},${item.y} ${item.x+item.w},${item.y} ${item.x+item.w+item.shear},${item.y+item.h} ${item.x+item.shear},${item.y+item.h}`,fill:color(item.color)},undefined,node);
        else svg('rect',{x:item.x,y:item.y,width:item.w,height:item.h,fill:color(item.color)},undefined,node);
      } else if(item.type==='line')line(node,item.x,item.y,item.w);
      else {const n=text(node,item.anchor==='end'?item.x+item.w-6:item.x+6,item.baseline,t[item.key],item.size,item.weight,item.color,item.font,item.w-12,item.anchor || 'start');if(item.italic)n.setAttribute('font-style','italic');}
    }
    return node;
  }
  function schedule(){
    const t=payload.design.texts,node=canvas('Current competition day schedule');logos(node);
    text(node,1527.5,73,t.schedule_date,28.75,700,'ink','Open Sans',470,'end');text(node,1527.5,120,t.timezone,25,400,'muted','Open Sans',480,'end');
    svg('rect',{x:72.5,y:166.25,width:60,height:5,fill:color('accent')},undefined,node);
    text(node,68,265,t.schedule_title,67.5,700,'ink','Open Sans',1050);text(node,72.5,330,t.schedule_subtitle,32.5,400,'muted','Open Sans',1060);
    line(node,1184,367,0);svg('line',{x1:1184,y1:367,x2:1184,y2:780,stroke:color('line')},undefined,node);
    picture(node,'qr',1230,426.25,295,295);text(node,1378,767,t.qr_caption,28.75,700,'ink','Open Sans',310,'middle');
    const rows=payload.schedule, height=412/Math.max(5,rows.length),scale=Math.min(1,height/82.4);
    if(!rows.length)text(node,72.5,420,t.no_schedule,30,400,'muted','Open Sans',1050);
    rows.forEach((row,i)=>{const y=368+i*height;line(node,72.5,y,1062.5);
      text(node,72.5,y+58*scale,row.start+(row.note?'–'+row.end:''),35*scale,700,row.accent?'accent':'ink','Open Sans',290);
      text(node,388,y+(row.note?39:58)*scale,row.title,(row.note?30:37.5)*scale,700,'ink','Open Sans',744);
      if(row.note)text(node,388,y+72*scale,row.note,25*scale,700,'deadline','Open Sans',744);
    });footer(node);return node;
  }
  function table(parent,group,x,y,width,height){
    const t=payload.design.texts,rounds=group.rounds,n=rounds.length,rows=group.rows;
    const sourceHeight=114+Math.max(rows.length,1)*103.4,sy=height/sourceHeight;
    const header=70*sy,second=44*sy,rh=(height-header-second)/Math.max(rows.length,1);
    const rank=group.rankings_released?54:0,team=177,time=77,final=100,cell=(width-rank-team-time-final)/(2*Math.max(1,n));
    const sx=Math.min(1,cell/78),fontScale=Math.min(1,Math.max(Math.min(.78,rh/70),sy),Math.max(.33,sx));
    function rect(a,b,w,h,fill){svg('rect',{x:a,y:b,width:w,height:h,fill:fill==='white'?'#fff':color(fill),stroke:color('table_border'),'stroke-width':.8333},undefined,parent);}
    function label(a,b,w,h,value,size=22.5,bold=false,font='Barlow Condensed',fill='ink',left=false){
      let fs=size*fontScale;let lines=String(value).split('\n');
      if(left){const max=Math.max(8,Math.floor((w-22)/(fs*.54)));lines=lines.flatMap(part=>{const output=[];let line='';for(const word of part.split(' ')){if(line && (line+' '+word).length>max){output.push(line);line=word;}else line+=(line?' ':'')+word;}output.push(line);return output;});if(lines.length>2)lines=[lines[0],lines.slice(1).join(' ')];fs=Math.min(fs,h/(lines.length*1.1));}
      lines.forEach((value,i)=>text(parent,left?a+11:a+w/2,b+h/2+(i-(lines.length-1)/2)*fs*1.2+fs*.34,value,fs,bold?700:400,fill,font,w-6,left?'start':'middle'));
    }
    let cx=x;
    if(rank){rect(cx,y,rank,header+second,'table_alternate');label(cx,y,rank,header+second,t.rank,11.67,true,'Arial');cx+=rank;}
    rect(cx,y,team,header+second,'table_alternate');label(cx,y,team,header+second,t.team,16.67,true,'Arial','ink',true);cx+=team;
    rounds.forEach((r,i)=>{const xx=cx+i*cell*2;rect(xx,y,cell*2,header,'table_header');text(parent,xx+cell,y+header*.45,t.round+' '+r.label.replace(/^R/,''),19.17*fontScale,700,'ink','Arial',cell*2-6,'middle');const maximum=svg('text',{x:xx+cell,y:y+header*.78,'text-anchor':'middle','font-weight':700,fill:color('deadline')},undefined,parent);svg('tspan',{class:'font-table','font-size':15.83*fontScale},t.map_max+' ',maximum);svg('tspan',{class:'font-score','font-size':19.17*fontScale},r.maximum??'—',maximum);for(let j=0;j<2;j++){rect(xx+j*cell,y+header,cell,second,'table_alternate');label(xx+j*cell,y+header,cell,second,j?t.normalized:t.raw,14.67,false,'Arial');}});
    const tx=x+width-time-final;rect(tx,y,time,header+second,'table_alternate');label(tx,y,time,header+second,t.total_time,16.67,true,'Arial');rect(tx+time,y,final,header+second,'table_alternate');label(tx+time,y,final,header+second,group.percentage?t.final_percentage:t.final_total,16.67,true,'Arial');
    rows.forEach((row,i)=>{const yy=y+header+second+i*rh,fill=i%2?'table_alternate':'white';let xx=x;
      if(rank){rect(xx,yy,rank,rh,fill);label(xx,yy,rank,rh,row.rank??'—',22.5);xx+=rank;}
      rect(xx,yy,team,rh,fill);label(xx,yy,team,rh*.64,row.name,21.67,true,'Arial','ink',true);label(xx,yy+rh*.60,team,rh*.35,row.code+' · '+row.country,16.67,false,'Arial','score_muted',true);xx+=team;
      row.scores.forEach(score=>{for(const kind of ['raw','normalized']){rect(xx,yy,cell,rh,fill);const v=score[kind]??'—';label(xx,yy,cell,rh,v,22.5,kind==='normalized','Barlow Condensed',kind==='normalized'?'ink':'score_muted');if(score.discarded||score.excluded)line(parent,xx+cell*.12,yy+rh*.51,cell*.76,'ink');xx+=cell;}});
      rect(tx,yy,time,rh,fill);label(tx,yy,time,rh,row.time??'—',22.5);rect(tx+time,yy,final,rh,fill);label(tx+time,yy,final,rh,row.total===null?t.pending:row.total+(group.percentage?'%':''),22.5,true);
    });
  }
  function results(){
    const t=payload.design.texts,node=canvas('Competition results');logos(node,true);text(node,1545,51,t.results_date,28.75,700,'ink','Open Sans',470,'end');text(node,1545,90,t.results_updated,25,400,'muted','Open Sans',480,'end');
    const groups=payload.results, units=groups.reduce((sum,g)=>sum+114+Math.max(g.rows.length,1)*103.4,0),extra=Math.max(0,groups.length-1)*55,available=632-extra;
    let top=186;
    groups.forEach((g,i)=>{const title=t.results_title.replace('{challenge}',g.name),method=t.results_method.replace('{round_count}',g.round_count).replace('{method}',g.method);
      text(node,29,i?top+28:156,title,i?30:48.33,700,'ink','Open Sans',790);text(node,1545,i?top+28:146,method,i?20:21.67,400,'muted','Open Sans',790,'end');if(i)top+=45;
      const height=available*(114+Math.max(g.rows.length,1)*103.4)/Math.max(1,units);table(node,g,33.33,top,1500,height);top+=height+10;
    });
    if(!groups.length)text(node,72,350,t.empty_results,32);
    const link=text(node,45,879,t.results_link,21.67,700,'link','Open Sans',600);link.setAttribute('text-decoration','underline');
    text(node,1525,879,groups.length && groups.every(g=>g.rankings_released)?t.results_released:t.results_unreleased,20,400,'muted','Open Sans',950,'end');return node;
  }
  function makeSlides(){
    slides=[];const s=payload.settings;
    const add=(key,type,render)=>slides.push({key,seconds:Math.max(3,Math.min(120,s[`${type}_seconds`] || 18)),render});
    if(!payload.enabled){add('disabled','intro',()=>{const n=canvas('Slideshow unavailable');text(n,800,450,'Slideshow unavailable',55,700,'ink','Open Sans',1200,'middle');return n;});return;}
    if(s.intro)add('intro','intro',intro);if(s.schedule)add('schedule','schedule',schedule);if(s.results)add('results','results',results);
  }
  function queueAdvance(delay) {
    clearTimeout(advanceTimer);
    if(!paused && slides.length>1 && !document.hidden){const wait=delay ?? slides[index].seconds*1000;deadline=Date.now()+wait;advanceTimer=setTimeout(()=>show(index+1),wait);}
  }
  function show(value) {
    if(!slides.length)return;
    index=(value+slides.length)%slides.length;root.replaceChildren(slides[index].render());
    position.textContent=`${index+1} / ${slides.length}`;queueAdvance();
  }
  async function refresh() {
    if(busy)return;busy=true;
    try {
      const response=await fetch('/slide/data/',{cache:'no-store',credentials:'omit',signal:AbortSignal.timeout(12000)});
      if(!response.ok)throw new Error('Refresh failed');
      if(!layout.length){const template=await fetch(document.getElementById('presentation').dataset.layout,{cache:'force-cache',credentials:'omit'});if(!template.ok)throw new Error('Template unavailable');layout=await template.json();await document.fonts.ready;await Promise.all(['400 16px "Open Sans"','600 16px "Open Sans"','700 16px "Open Sans"','800 16px "Open Sans"','italic 900 16px Roboto','400 16px "Barlow Condensed"','700 16px "Barlow Condensed"'].map(font=>document.fonts.load(font)));}
      const updated=await response.json(), key=slides[index]?.key, remaining=Math.max(0,deadline-Date.now());
      payload=updated;makeSlides();const found=slides.findIndex(s=>s.key===key);show(found<0?0:found);if(found>=0 && remaining>0)queueAdvance(remaining);
      status.textContent=`Updated ${new Date(updated.generated_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    } catch(error) {
      status.textContent=payload?'Connection lost · Showing last update':'Unable to load · Retrying automatically';
      if(!payload){const v=el('section',null,'slide empty');v.append(el('h1','Waiting for competition data'),el('p','Please check your connection. This display will retry automatically.'));root.replaceChildren(v);}
    } finally {
      busy=false;clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,Math.max(15,payload?.settings.refresh_seconds || 30)*1000);
    }
  }
  document.getElementById('previous').addEventListener('click',()=>show(index-1));
  document.getElementById('next').addEventListener('click',()=>show(index+1));
  pauseButton.addEventListener('click',()=>{paused=!paused;pauseButton.textContent=paused?'Resume':'Pause';pauseButton.setAttribute('aria-label',paused?'Resume slideshow':'Pause slideshow');queueAdvance();});
  document.getElementById('fullscreen').addEventListener('click',async()=>{
    try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}
    catch(error){status.textContent='Fullscreen unavailable in this browser';}
  });
  document.addEventListener('keydown',e=>{
    if(e.target.closest('button,a,input,select,textarea'))return;
    if(e.key==='ArrowRight'){e.preventDefault();show(index+1);}else if(e.key==='ArrowLeft'){e.preventDefault();show(index-1);}
    else if(e.code==='Space'){e.preventDefault();pauseButton.click();}
  });
  document.addEventListener('visibilitychange',queueAdvance);

  refresh();
})();

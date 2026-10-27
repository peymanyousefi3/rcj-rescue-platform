const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{addEventListener(){}},document:{querySelectorAll:()=>[],getElementById:()=>null},location:{hash:''}};
vm.runInNewContext(fs.readFileSync('static/arena/admin.js','utf8'),context);
const {scorePastePlan,scoreHistory}=context.window.ASRAdmin;
const {elapsedSeconds,formatClock}=context.window.ASRAdmin;

test('recording imports rebase Undo without erasing manual drafts or restoring stale blank cells',()=>{
 const history=scoreHistory([['',false,'',''],['5',false,'','']]);
 history.record([['',false,'',''],['7',false,'','']]);
 history.rebase(0,['',false,'',''],['215.375',false,'','0:26']);
 assert.deepEqual(history.value,[['215.375',false,'','0:26'],['7',false,'','']]);
 assert.deepEqual(history.undo(),[['215.375',false,'','0:26'],['5',false,'','']]);
 history.record([['0',false,'','8:00'],['5',false,'','']]);
 history.rebase(0,['215.375',false,'','0:26'],['300',false,'','1:00']);
 assert.deepEqual(history.value[0],['0',false,'','8:00']);
});

test('remaining clock converts to elapsed seconds, including both boundaries and unknown times',()=>{
 for(const [input,seconds] of [['2:30',330],['150',330],['8:00',0],['480',0],['0:00',480],['0',480],['7:59',1],['08:00',0]]){
  assert.equal(elapsedSeconds(input),seconds);
 }
 assert.equal(elapsedSeconds(''),null);assert.equal(elapsedSeconds('  '),null);
 assert.equal(formatClock(330),'5:30');assert.equal(formatClock(0),'0:00');assert.equal(formatClock(480),'8:00');assert.equal(formatClock(null),'—');
 for(const value of ['8:01','481','-1','2:60','1.5','NaN','Infinity','1:02:03','1e2'])assert.throws(()=>elapsedSeconds(value));
});

test('clock edits participate in the same Undo and save baseline as scores',()=>{
 const initial=[['75',false,'','2:30']],history=scoreHistory(initial),input={};
 history.record([['75',false,'','1:00']],input);
 assert.deepEqual(history.undo(),initial);
 history.record([['75',false,'','0:00']],input);history.commit([['75',false,'','0:00']]);
 assert.equal(history.undo(),null);
});
const plan=(text,options={})=>JSON.parse(JSON.stringify(scorePastePlan(text,{row:0,column:0,rowCount:5,columnCount:7,...options})));

test('Excel blocks preserve row order, exact decimals, blanks, zeros and thousands separators',()=>{
 assert.deepEqual(plan('\uFEFF75\t1,000.2500\t\r\n0\t+.5\t-12.25\r\n',{row:1,column:2}),[
  {row:1,column:2,value:'75'},{row:1,column:3,value:'1000.2500'},{row:1,column:4,value:''},
  {row:2,column:2,value:'0'},{row:2,column:3,value:'0.5'},{row:2,column:4,value:'-12.25'}]);
 assert.equal(plan('9999999999.9999')[0].value,'9999999999.9999');
 assert.deepEqual(plan('1\r2\r')[1],{row:1,column:0,value:'2'});
 assert.equal(plan('\t\n').length,2);
 assert.equal(plan('0\n\n').length,2); // Only the clipboard terminator is removed; an explicit blank row remains.
 assert.equal(plan('-.25')[0].value,'-0.25');
 assert.equal(plan('1e3')[0].value,'1000');
 assert.equal(plan('1e-4')[0].value,'0.0001');
 assert.equal(plan('9.9999999999999E9')[0].value,'9999999999.9999');
 assert.throws(()=>plan('1e-5'));
 assert.throws(()=>plan('1e9999999999999'));
});

test('malformed, ambiguous, oversized and over-precision blocks fail before any plan is returned',()=>{
 for(const text of ['Team A\t75','=1+2','10%','NaN','Infinity','12,50','1.23456','10000000000','1\t2\n3'])assert.throws(()=>plan(text));
 assert.throws(()=>plan('1\t2',{column:6}),/does not fit/);
 assert.throws(()=>plan('1\n2',{row:4}),/does not fit/);
 assert.throws(()=>plan('1',{row:-1}),/does not fit/);
 assert.throws(()=>plan('1\n2',{rowCount:1}),/does not fit/); // Filtering never spills into hidden teams.
 assert.equal(plan('0000000000001.0000')[0].value,'0000000000001.0000');
});

test('Undo groups typing per cell and restores a whole paste and Reset atomically',()=>{
 const initial=[['',false,''],['',false,'']],a={},b={};
 const history=scoreHistory(initial);
 history.record([['1',false,''],['',false,'']],a);
 history.record([['10',false,''],['',false,'']],a);
 history.group=null;
 history.record([['10',false,''],['5',true,'0.5']],b);
 assert.equal(history.past.length,2);
 assert.deepEqual(history.undo(),[['10',false,''],['',false,'']]);
 assert.deepEqual(history.undo(),initial);
 assert.equal(history.undo(),null);
 const pasted=[['75',false,''],['100',false,'']];history.record(pasted);
 history.record(initial); // Reset is itself reversible.
 assert.deepEqual(history.undo(),pasted);
 assert.deepEqual(history.undo(),initial);
 assert.equal(history.record(initial),false);
});

test('successful saves start a new undo baseline and history has a bounded page-local lifetime',()=>{
 const history=scoreHistory([['0',false,'']]);
 for(let n=1;n<=110;n++)history.record([[String(n),false,'']]);
 assert.equal(history.past.length,100);
 history.commit([['110',false,'']]);
 assert.equal(history.undo(),null);
 history.record([['111',false,'']]);
 assert.deepEqual(history.undo(),[['110',false,'']]);
});

test('typing back to the starting value does not leave a no-op Undo entry',()=>{
 const group={},history=scoreHistory([['',false,'']]);
 history.record([['1',false,'']],group);history.record([['',false,'']],group);
 assert.equal(history.past.length,0);assert.equal(history.undo(),null);
});

const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={URLSearchParams,location:{search:''},document:{querySelector:()=>null,querySelectorAll:()=>[],addEventListener(){}},window:{ASRAdmin:{},addEventListener(){}}};
vm.runInNewContext(fs.readFileSync('static/arena/calendar.js','utf8'),context);

test('folder drops preserve nesting, duplicate basenames, and every directory-reader batch',async()=>{
 const file=name=>({name,isFile:true,file:resolve=>resolve({name})});
 const dir=(name,batches)=>({name,isDirectory:true,createReader(){let i=0;return {readEntries:resolve=>resolve(batches[i++]||[])};}});
 const root=dir('Recording',[[file('replay.html'),dir('textures',[[file('same.png')]])],
                           [dir('meshes',[[file('same.png')]])],[file('match-result.json')]]);
 const result=await context.recordingFolderFiles(root);
 assert.deepEqual(Array.from(result,row=>row.path),['Recording/replay.html','Recording/textures/same.png','Recording/meshes/same.png','Recording/match-result.json']);
 await assert.rejects(context.recordingFolderFiles({name:'bad',isFile:true,file:(_,reject)=>reject(new Error('Unreadable file'))}),/Unreadable file/);
});

'use strict';
const model=document.querySelector('model-viewer'),status=document.querySelector('[data-field-status]');
model.addEventListener('load',()=>{status.textContent='';});
model.addEventListener('error',()=>{status.textContent='The 3D field could not load. Download the field files or try again later.';});

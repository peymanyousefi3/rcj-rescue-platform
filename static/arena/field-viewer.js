'use strict';
const model=document.querySelector('model-viewer'),status=document.querySelector('[data-field-status]');
const controls=[...document.querySelectorAll('[data-field-camera]')];let initial;
const orbit=value=>`${value.theta}rad ${value.phi}rad ${value.radius}m`;
model.addEventListener('load',()=>{
 status.textContent='';initial={orbit:orbit(model.getCameraOrbit()),target:{...model.getCameraTarget()}};
 controls.forEach(button=>{button.disabled=false;});
});
model.addEventListener('error',()=>{status.textContent='The 3D field could not load. Download the field files or try again later.';controls.forEach(button=>{button.disabled=true;});});
controls.forEach(button=>button.addEventListener('click',()=>{
 if(!initial)return;
 const value=model.getCameraOrbit(),action=button.dataset.fieldCamera;
 if(action==='reset'){model.cameraOrbit=initial.orbit;model.cameraTarget=`${initial.target.x}m ${initial.target.y}m ${initial.target.z}m`;return;}
 if(action==='left')value.theta-=Math.PI/12;
 if(action==='right')value.theta+=Math.PI/12;
 if(action==='in')value.radius*=0.8;
 if(action==='out')value.radius*=1.25;
 model.cameraOrbit=orbit(value);
}));

'use strict';
// The sandbox stays opaque. Credentials are sent only to this replay's assets.
(()=>{
 const root=new URL('.',location.href),local=value=>{try{const url=new URL(value,location.href);return url.origin===root.origin&&url.pathname.startsWith(root.pathname.split('/').slice(0,3).join('/')+'/');}catch(_){return false;}};
 const originalFetch=window.fetch;
 window.fetch=(input,options={})=>originalFetch(input,local(input instanceof Request?input.url:input)?{...options,credentials:'include'}:options);
 const open=XMLHttpRequest.prototype.open;
 XMLHttpRequest.prototype.open=function(method,url,...args){open.call(this,method,url,...args);if(local(url))this.withCredentials=true;};
 const src=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');
 Object.defineProperty(HTMLImageElement.prototype,'src',{...src,set(value){if(local(value))this.crossOrigin='use-credentials';src.set.call(this,value);}});
})();

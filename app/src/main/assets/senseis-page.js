(function(){
"use strict";
var LOCAL="https://senseis.local/";
var active=null;
var besogoPromise=null;
function localUrl(raw,base){
 try{
  if(raw.charAt(0)==="?")return LOCAL+raw;
  var u=new URL(raw,base||document.baseURI);
  if(!/^(senseis\.xmp\.net|www\.senseis\.xmp\.net|senseis\.local)$/i.test(u.hostname))return null;
  u.protocol="https:";u.hostname="senseis.local";u.port="";
  if(u.pathname==="/"&&u.search.length>1)return LOCAL+u.search+u.hash;
  return u.href;
 }catch(e){return null;}
}
function mapInternalUrls(){
 document.querySelectorAll("a[href],script[src],link[href],source[src]").forEach(function(el){
  var attr=el.tagName==="A"||el.tagName==="LINK"?"href":"src";
  var raw=el.getAttribute(attr);
  if(!raw||/^(#|mailto:|tel:|javascript:|data:|blob:)/i.test(raw))return;
  var mapped=localUrl(raw);
  if(mapped)el.setAttribute(attr,mapped);
 });
 document.querySelectorAll("img[src]").forEach(function(img){
  img.loading="lazy";
  img.decoding="async";
  img.setAttribute("fetchpriority","low");
  var mapped=localUrl(img.getAttribute("src"));
  if(mapped)img.setAttribute("src",mapped);
 });
 document.querySelectorAll("base").forEach(function(b){b.remove();});
}
function loadBesogo(){
 if(besogoPromise)return besogoPromise;
 besogoPromise=new Promise(function(resolve,reject){
  var css=document.createElement("link");
  css.rel="stylesheet";css.href=LOCAL+"__app/besogo.css";document.head.appendChild(css);
  var theme=document.createElement("link");
  theme.rel="stylesheet";theme.href=LOCAL+"__app/board-sensei.css";document.head.appendChild(theme);
  var script=document.createElement("script");
  script.src=LOCAL+"__app/besogo.all.js";
  script.onload=resolve;
  script.onerror=function(){reject(new Error("BesoGo could not be loaded"));};
  document.head.appendChild(script);
 });
 return besogoPromise;
}
function restoreActive(){
 if(!active)return;
 var old=active;
 active=null;
 if(old.panel.parentNode){
  old.panel.replaceWith(old.image);
  bindDiagram(old.image,old.sgfUrl);
 }
 old.panel=null;
 old.image=null;
}
function bindDiagram(img,sgfUrl){
 if(img.__senseisBound)return;
 img.__senseisBound=true;
 img.style.cursor="pointer";
 img.title="Tap to open interactive Go diagram";
 img.addEventListener("click",function(event){
  event.preventDefault();event.stopPropagation();
  restoreActive();
  img.__senseisPinned=true;
  var original=img.cloneNode(true);
  original.__senseisBound=false;
  var panel=document.createElement("div");
  panel.style.cssText="position:relative;margin:12px auto;max-width:100%;";
  var close=document.createElement("button");
  close.type="button";close.textContent="Close diagram";
  close.setAttribute("aria-label","Close interactive diagram");
  close.style.cssText="display:block;margin:0 0 8px auto;padding:6px 12px;font-size:14px;";
  close.addEventListener("click",function(e){e.preventDefault();e.stopPropagation();restoreActive();});
  var board=document.createElement("div");
  board.className="besogo-viewer";
  board.setAttribute("aria-label",img.alt||"Go diagram");
  panel.appendChild(close);panel.appendChild(board);
  img.replaceWith(panel);
  active={panel:panel,image:original,sgfUrl:sgfUrl};
  board.textContent="Loading diagram…";
  loadBesogo().then(function(){
   if(!active||active.panel!==panel)return;
   return fetch(sgfUrl,{credentials:"same-origin"}).then(function(r){
    if(!r.ok)throw new Error("SGF not found");
    return r.text();
   }).then(function(sgf){
    if(!active||active.panel!==panel)return;
    if(!/\(\s*;/.test(sgf))throw new Error("Invalid SGF");
    board.textContent=sgf;
    window.besogo.create(board,{
     panels:["control","comment"],tool:"navOnly",orient:"portrait",
     maxwidth:640,nowheel:true,nokeys:true,resize:"auto"
    });
   });
  }).catch(function(){
   if(!active||active.panel!==panel)return;
   board.className="senseis-sgf-error";
   board.textContent="SGF diagram unavailable";
  });
 },false);
}
function enhance(){
 var style=document.createElement("style");
 style.textContent="body{max-width:100%;margin:0 auto;padding:12px;line-height:1.45;overflow-wrap:anywhere}img,video,svg{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse;display:block;overflow-x:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere}.besogo-container{max-width:100%;margin:14px auto!important}.besogo-panels{max-width:100%}.besogo-comment{max-height:180px;overflow:auto}.senseis-sgf-error{padding:12px;color:#8b1b1b;background:#fff0f0}";
 document.head.appendChild(style);
 mapInternalUrls();
 Array.prototype.slice.call(document.querySelectorAll("img[src]")).forEach(function(img){
  var imageSrc=img.getAttribute("src");
  var u;try{u=new URL(imageSrc,document.baseURI);}catch(e){return;}
  if(!/(^|\/)[0-9a-f]{32}\.png$/i.test(u.pathname))return;
  var anchor=img.closest?img.closest("a"):null;
  if(anchor){anchor.removeAttribute("href");anchor.removeAttribute("target");anchor.removeAttribute("download");anchor.removeAttribute("onclick");anchor.title="Go diagram";anchor.style.cursor="default";}
  bindDiagram(img,LOCAL+u.pathname.replace(/\.png$/i,".sgf"));
 });
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",enhance);
else enhance();
})();
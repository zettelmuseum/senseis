(function(){
"use strict";
var LOCAL="https://senseis.local/";
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
 document.querySelectorAll("a[href],img[src],script[src],link[href],source[src]").forEach(function(el){
  var attr=el.tagName==="A"||el.tagName==="LINK"?"href":"src";
  var raw=el.getAttribute(attr);
  if(!raw||/^(#|mailto:|tel:|javascript:|data:|blob:)/i.test(raw))return;
  var mapped=localUrl(raw);
  if(mapped)el.setAttribute(attr,mapped);
 });
 document.querySelectorAll("base").forEach(function(b){b.remove();});
}
function enhance(){
 var style=document.createElement("style");
 style.textContent="body{max-width:100%;margin:0 auto;padding:12px;line-height:1.45;overflow-wrap:anywhere}img,video,svg{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse;display:block;overflow-x:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere}.besogo-container{max-width:100%;margin:14px auto!important}.besogo-panels{max-width:100%}.besogo-comment{max-height:180px;overflow:auto}.senseis-sgf-error{padding:12px;color:#8b1b1b;background:#fff0f0}";
 document.head.appendChild(style);
 mapInternalUrls();
 Array.prototype.slice.call(document.querySelectorAll("img[src]")).forEach(function(img){
  var u;try{u=new URL(img.getAttribute("src"),document.baseURI);}catch(e){return;}
  if(!/(^|\/)[0-9a-f]{32}\.png$/i.test(u.pathname))return;
  var sgfUrl=LOCAL+u.pathname.replace(/\.png$/i,".sgf");
  var anchor=img.closest?img.closest("a"):null;
  if(anchor){anchor.removeAttribute("href");anchor.removeAttribute("target");anchor.removeAttribute("download");anchor.removeAttribute("onclick");anchor.title="Go diagram";anchor.style.cursor="default";}
  var viewer=document.createElement("div");
  viewer.className="besogo-viewer";
  viewer.setAttribute("panels","control+comment");
  viewer.setAttribute("maxwidth","640");
  viewer.setAttribute("orient","portrait");
  viewer.setAttribute("nowheel","true");
  viewer.setAttribute("nokeys","true");
  viewer.setAttribute("aria-label",img.alt||"Go diagram");
  img.replaceWith(viewer);
  fetch(sgfUrl,{credentials:"same-origin"}).then(function(r){
   if(!r.ok)throw new Error("SGF not found");
   return r.text();
  }).then(function(sgf){
   if(!/\(\s*;/.test(sgf))throw new Error("Invalid SGF");
   viewer.textContent=sgf;
   window.besogo.create(viewer,{
    panels:["control","comment"],tool:"navOnly",orient:"portrait",
    maxwidth:640,nowheel:true,nokeys:true,resize:"auto"
   });
  }).catch(function(){
   viewer.className="senseis-sgf-error";
   viewer.textContent="SGF diagram unavailable";
  });
 });
}
function loadBesogo(){
 var css=document.createElement("link");
 css.rel="stylesheet";css.href=LOCAL+"__app/besogo.css";document.head.appendChild(css);
 var theme=document.createElement("link");
 theme.rel="stylesheet";theme.href=LOCAL+"__app/board-sensei.css";document.head.appendChild(theme);
 var script=document.createElement("script");
 script.src=LOCAL+"__app/besogo.all.js";
 script.onload=enhance;
 script.onerror=function(){document.body.insertAdjacentText("afterbegin","BesoGo viewer could not be loaded.");};
 document.head.appendChild(script);
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",loadBesogo);
else loadBesogo();
})();
(function(){
"use strict";
var LOCAL="https://senseis.local/";
function localUrl(raw,base){
 try{
  var u=new URL(raw,base||document.baseURI);
  if(!/^(senseis\.xmp\.net|www\.senseis\.xmp\.net|senseis\.local)$/i.test(u.hostname))return null;
  u.protocol="https:";u.hostname="senseis.local";u.port="";
  if(u.pathname==="/"&&u.search.length>1)return LOCAL+u.search+u.hash;
  return u.href;
 }catch(e){return null;}
}
function prop(n,k){return n[k]||[];}
function parseSgf(s){
 var nodes=[],i=0,depth=0;
 while(i<s.length){
  var ch=s[i++];
  if(ch==="("){depth++;continue;} if(ch===")"){depth--;continue;}
  if(ch!==";"||depth<1)continue;
  var p={};
  while(i<s.length){
   while(i<s.length&&/\s/.test(s[i]))i++;
   if(!/[A-Z]/.test(s[i]||""))break;
   var k="";while(i<s.length&&/[A-Z]/.test(s[i]))k+=s[i++];
   var vals=[];
   while(s[i]==="["){
    i++;var v="";
    while(i<s.length&&s[i]!=="]"){
     if(s[i]==="\\"){i++;if(i<s.length){if(s[i]==="\r"){i++;if(s[i]==="\n")i++;}else if(s[i]!=="\n")v+=s[i++];else i++;}}
     else v+=s[i++];
    }
    if(s[i]==="]")i++;vals.push(v);
   }
   p[k]=vals;
  }
  nodes.push(p);
 }
 return nodes;
}
function coord(v,size){if(!v||v.length<2)return null;var x=v.charCodeAt(0)-97,y=v.charCodeAt(1)-97;return x>=0&&y>=0&&x<size&&y<size?[x,y]:null;}
function boardAt(nodes,upto,size){
 var b=new Array(size*size).fill(0);
 function group(x,y,color,seen){
  var stack=[[x,y]],stones=[],lib=false;
  while(stack.length){var q=stack.pop(),idx=q[1]*size+q[0];if(seen.has(idx))continue;seen.add(idx);stones.push(idx);
   [[1,0],[-1,0],[0,1],[0,-1]].forEach(function(d){var nx=q[0]+d[0],ny=q[1]+d[1];if(nx<0||ny<0||nx>=size||ny>=size)return;var ni=ny*size+nx;if(!b[ni])lib=true;else if(b[ni]===color&&!seen.has(ni))stack.push([nx,ny]);});
  }return {stones:stones,liberty:lib};
 }
 for(var z=0;z<=upto&&z<nodes.length;z++){
  var p=nodes[z];
  [["AB",1],["AW",2],["AE",0]].forEach(function(pair){prop(p,pair[0]).forEach(function(v){var c=coord(v,size);if(c)b[c[1]*size+c[0]]=pair[1];});});
  var mv=p.B?["B",1]:p.W?["W",2]:null;
  if(mv){var c=coord(mv[0]&&p[mv[0]][0],size);if(c){var x=c[0],y=c[1],idx=y*size+x;b[idx]=mv[1];var seen=new Set();
   [[1,0],[-1,0],[0,1],[0,-1]].forEach(function(d){var nx=x+d[0],ny=y+d[1];if(nx<0||ny<0||nx>=size||ny>=size)return;var ni=ny*size+nx;if(b[ni]===3-mv[1]&&!seen.has(ni)){var g=group(nx,ny,3-mv[1],seen);if(!g.liberty)g.stones.forEach(function(k){b[k]=0;});}});
  }}
 }
 return b;
}
function draw(canvas,nodes,index,size){
 var w=420,m=24,step=(w-2*m)/(size-1),ratio=window.devicePixelRatio||1;
 canvas.width=w*ratio;canvas.height=w*ratio;canvas.style.width="100%";canvas.style.height="auto";
 var c=canvas.getContext("2d");c.scale(ratio,ratio);c.fillStyle="#d9ad68";c.fillRect(0,0,w,w);c.strokeStyle="#342719";c.lineWidth=1;
 for(var j=0;j<size;j++){var p=m+j*step;c.beginPath();c.moveTo(m,p);c.lineTo(w-m,p);c.stroke();c.beginPath();c.moveTo(p,m);c.lineTo(p,w-m);c.stroke();}
 if(size===19)[3,9,15].forEach(function(y){[3,9,15].forEach(function(x){c.beginPath();c.arc(m+x*step,m+y*step,2.7,0,Math.PI*2);c.fillStyle="#342719";c.fill();});});
 var b=boardAt(nodes,index,size);
 for(var y=0;y<size;y++)for(var x=0;x<size;x++){var v=b[y*size+x];if(!v)continue;var px=m+x*step,py=m+y*step,r=step*.46;c.beginPath();c.arc(px,py,r,0,Math.PI*2);c.fillStyle=v===1?"#111":"#f8f8f5";c.fill();c.strokeStyle="#222";c.lineWidth=1;c.stroke();}
 var last=nodes[index],mv=last&&(last.B||last.W);if(mv&&mv[0]){var q=coord(mv[0],size);if(q){c.beginPath();c.arc(m+q[0]*step,m+q[1]*step,step*.17,0,Math.PI*2);c.strokeStyle=last.B?"#fff":"#111";c.lineWidth=2;c.stroke();}}
}
function initViewer(el,sgfUrl){
 el.className="senseis-sgf-viewer";
 el.innerHTML="<canvas></canvas><div class='sgfv-controls'><button type='button' class='sgfv-prev'>‹</button><span></span><button type='button' class='sgfv-next'>›</button></div>";
 var canvas=el.querySelector("canvas"),count=el.querySelector("span"),prev=el.querySelector(".sgfv-prev"),next=el.querySelector(".sgfv-next");
 fetch(sgfUrl).then(function(r){if(!r.ok)throw Error("SGF unavailable");return r.text();}).then(function(s){
  var nodes=parseSgf(s);if(!nodes.length)throw Error("Empty SGF");
  var size=parseInt((nodes[0].SZ||["19"])[0].split(":")[0],10)||19;if(size<2||size>25)size=19;
  var index=nodes.length-1;
  function render(){draw(canvas,nodes,index,size);count.textContent=(index+1)+" / "+nodes.length;prev.disabled=index===0;next.disabled=index===nodes.length-1;}
  prev.onclick=function(){if(index>0){index--;render();}};next.onclick=function(){if(index<nodes.length-1){index++;render();}};render();
 }).catch(function(){el.textContent="SGF diagram unavailable";});
}
function enhance(){
 var style=document.createElement("style");
 style.textContent="body{max-width:100%;margin:0 auto;padding:12px;line-height:1.45;overflow-wrap:anywhere}img,video,svg{max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse;display:block;overflow-x:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{overflow-wrap:anywhere}.senseis-sgf-viewer{max-width:420px;margin:12px auto;background:#d9ad68;padding:4px;border:1px solid #80613c}.sgfv-controls{display:flex;align-items:center;justify-content:center;gap:20px;padding:5px;background:#eee}.sgfv-controls button{min-width:42px;min-height:36px;font-size:22px}";
 document.head.appendChild(style);
 document.querySelectorAll("a[href],img[src],script[src],link[href],source[src]").forEach(function(el){
  var attr=el.tagName==="A"||el.tagName==="LINK"?"href":"src",raw=el.getAttribute(attr);
  if(!raw||/^(#|mailto:|tel:|javascript:|data:|blob:)/i.test(raw))return;
  var mapped=localUrl(raw);if(mapped)el.setAttribute(attr,mapped);
 });
 document.querySelectorAll("img[src]").forEach(function(img){
  var raw=img.getAttribute("src"),u;try{u=new URL(raw,document.baseURI);}catch(e){return;}
  if(!/\/[0-9a-f]{32}\.png$/i.test(u.pathname))return;
  var sgf=u.href.replace(/\.png(?=([?#]|$))/i,".sgf");
  var viewer=document.createElement("div");viewer.setAttribute("aria-label",img.alt||"Go diagram");
  if(img.parentElement&&img.parentElement.tagName==="A"&&/\/[0-9a-f]{32}\.png$/i.test(new URL(img.parentElement.href,document.baseURI).pathname)){img.parentElement.removeAttribute("href");img.parentElement.title="SGF diagram";}
  img.replaceWith(viewer);initViewer(viewer,sgf);
 });
 document.querySelectorAll("a[href]").forEach(function(a){
  var u;try{u=new URL(a.href,document.baseURI);}catch(e){return;}
  if(/\.sgf$/i.test(u.pathname)){a.setAttribute("data-senseis-sgf","1");a.setAttribute("download",u.pathname.split("/").pop()||"game.sgf");a.title="Save SGF file";}
 });
 if(!document.__senseisSgfHandler){document.addEventListener("click",function(e){var a=e.target;while(a&&a.tagName!=="A")a=a.parentNode;if(!a||!a.hasAttribute("data-senseis-sgf"))return;e.preventDefault();if(window.SenseiBridge&&window.SenseiBridge.saveSgf)window.SenseiBridge.saveSgf(a.href);},true);document.__senseisSgfHandler=true;}
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",enhance);else enhance();
})();
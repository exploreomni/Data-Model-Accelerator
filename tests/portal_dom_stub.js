/* A deliberately nonvisual DOM double: proves event/data handling, never layout or CSP. */
const assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const crypto=webcrypto;
class Node {
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.textContent='';this.dataset={};this.attributes={};this.style={};this.hidden=false;this.className='';this.classList={toggle:(key,on)=>{const names=new Set(this.className.split(' ').filter(Boolean));on?names.add(key):names.delete(key);this.className=[...names].join(' ');}};}
  append(...nodes){for(const n of nodes){if(n&&typeof n==='object')n.parentNode=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=String(v);if(k==='id')this.id=v;if(k==='class')this.className=v;if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;}
  getAttribute(k){return this.attributes[k]??null;}removeAttribute(k){delete this.attributes[k];}
  querySelectorAll(query){const all=[];const visit=n=>{for(const child of n.children||[]){if(child instanceof Node){all.push(child);visit(child);}}};visit(this);return all.filter(n=>query.split(',').some(q=>matches(n,q.trim())));}
  querySelector(q){return this.querySelectorAll(q)[0]||null;}focus(){this.focused=true;}scrollIntoView(){this.scrolled=true;}select(){this.selected=true;}remove(){}click(){this.onclick?.();}
}
function matches(n,q){if(q.startsWith('.'))return n.className.split(' ').includes(q.slice(1));if(q.startsWith('#')){const [id,tag]=q.slice(1).split(' ');return tag?n.tag===tag&&n.parentNode?.id===id:n.id===id;}if(q.startsWith('['))return n.getAttribute(q.slice(1,-1))!==null;return n.tag===q;}
const elements=new Map();
const document={documentElement:new Node('html'),body:new Node('body'),getElementById:id=>{assert(elements.has(id),'Missing template control: '+id);return elements.get(id);},createElement:tag=>new Node(tag),querySelectorAll:q=>[...elements.values()].filter(n=>matches(n,q)),querySelector:q=>document.querySelectorAll(q)[0]||null};
document.documentElement.outerHTML=PAGE;document.documentElement.append(document.body);
// Extract template controls only; injected source data is not parsed as HTML.
for(const match of PAGE.split('<script id="delivery-data"')[0].matchAll(/<([a-z][a-z0-9-]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
 const n=new Node(match[1]);for(const attr of match[2].matchAll(/([\w-]+)="([^"]*)"/g))n.setAttribute(attr[1],attr[2]);if(/\bdata-section\b/.test(match[2]))n.setAttribute('data-section','');n.hidden=/\bhidden\b/.test(match[2]);elements.set(match[3],n);
}
for(const match of PAGE.matchAll(/<a\b[^>]*data-nav="([^"]+)"[^>]*>/g)){const n=new Node('a');n.setAttribute('data-nav',match[1]);elements.set('nav:'+match[1],n);}
elements.get('delivery-data')||elements.set('delivery-data',new Node('script'));
elements.get('delivery-data').textContent=JSON.stringify(PAYLOAD);
const location={hash:'#overview'},listeners={};function addEventListener(name,callback){(listeners[name]??=[]).push(callback);}
function requestAnimationFrame(callback){callback();}

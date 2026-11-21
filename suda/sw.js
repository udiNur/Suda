// Suda's service worker. Two things:
//  1. Notifications while no page is open. A push arrives WITHOUT a payload (so nothing private travels through
//     the push service); the worker then reads the board's state itself and shows what is on him.
//  2. The page opens at once. The worker keeps the page's own file (suda.html, nothing else: no state, no
//     message, no picture) and answers an opening with the kept copy, while it reads the server's copy in the
//     background and keeps that for the next opening. When the server's copy is another build it tells the open
//     pages, and they offer "new version · refresh".
//  Nothing else passes through the worker: what the page sends and reads (a message of his, the state, a
//  picture) goes straight to the network, without waiting for a worker that has to be started first.
'use strict';
// <pure>
// The installation's language: `threads install` writes it here (with the few texts this worker shows), as it does
// into the pages. The repo's copy speaks English.
var LANG='en',DIR='ltr',L10N={};
function tr(text,vars){
  let out=L10N&&Object.prototype.hasOwnProperty.call(L10N,text)?L10N[text]:text;
  if(vars)out=String(out).replace(/\{(\w+)\}/g,(m,k)=>Object.prototype.hasOwnProperty.call(vars,k)?String(vars[k]):m);
  return out;
}
// What deserves a notification right now: an open thread that is on him, not asleep, not muted, whose last
// message he has not seen yet (the server records what he saw as thread.seen.msg; '' for a thread with no
// message). A thread can be on him right after his own message (an agent set it so, or his reply did not answer
// the open question), so who wrote last decides nothing. Each one says whether it is NEW in this push: the
// server stamps the threads it pushed for (thread.alert.pushed), and only the newest stamp sounds again.
function dueThreads(state){
  const threads=state&&state.threads&&typeof state.threads==='object'?Object.values(state.threads):[];
  const due=threads.filter(t=>{
    if(!t||t.status!=='open'||t.state!=='on-owner'||t.mute)return false;
    if(t.snooze&&Number.isFinite(t.snooze.until))return false;
    const messages=Array.isArray(t.messages)?t.messages:[],last=messages.length?messages[messages.length-1]:null;
    return !(t.seen&&t.seen.msg===(last?String(last.id):''));
  });
  const stamp=t=>t.alert&&Number.isFinite(t.alert.pushed)?t.alert.pushed:0,newest=Math.max(0,...due.map(stamp));
  return due.map(t=>({id:String(t.id),title:tr('Your turn: {title}',{title:String(t.title||t.id)}),body:String(t.note||'').slice(0,240),slot:Number(t.slot)||0,fresh:!newest||stamp(t)===newest}))
    .sort((a,b)=>a.slot-b.slot);
}
// Which of the worker's requests is the page itself: suda.html inside this worker's own folder, by its path alone
// (what stands after "?" is not the page's). Anything else is not the worker's business.
function shellPath(url,scope){
  let at=null,home=null;
  try{at=new URL(url);home=new URL(scope);}catch{return '';}
  return at.origin===home.origin&&at.pathname===home.pathname+'suda.html'?at.pathname:'';
}
// The rule the browser itself follows, before it wakes the worker: every request but the page's own file goes
// to the network. (A browser without such rules asks the worker, which lets the request go on as it is. So does
// a page that an older worker was in charge of when this one took over: until it is loaded again its requests
// still pass through the worker, as they always did.) The path is taken as written, never as a pattern: a
// folder whose name holds a sign of the pattern's own must not make the rule miss the page.
// The If-Modified-Since a reading of the page may carry, or '' (read it whole): the page's own date when the page
// asks (`since`), else the kept copy's Last-Modified. Only for a kept copy read 2 s or more after that date (its
// Date header): Last-Modified is in whole seconds, and a write later in the same second (an install that was still
// writing it) would be answered 304 for good.
function askSince(since,kept,keptDate){
  const lm=Date.parse(kept||''),read=Date.parse(keptDate||'');
  const trusted=Number.isFinite(lm)&&Number.isFinite(read)&&read-lm>=2000;
  if(since)return !kept||trusted||since!==kept?since:'';
  return trusted?kept:'';
}
const pastWorker=path=>[{condition:{not:{urlPattern:String(path).replace(/[{}()*+?:\\]/g,'\\$&')}},source:'network'}];
// </pure>
const SHELL='suda-shell-1';
const tellPages=async what=>{for(const page of await self.clients.matchAll({type:'window',includeUncontrolled:true}))page.postMessage(what);};
// The server's copy of the page, read past every cache and kept for the next opening. `was` is the copy kept
// until now: when the server's is another one, the open pages hear of it. The server is asked with the date of
// what is known (If-Modified-Since): `since`, the page's own date when the page asks (its check for a newer
// build), else the kept copy's. A 304 has no body: nothing is read or kept again (230 KB less on every opening).
async function readShell(path,was,since){
  const cache=await caches.open(SHELL),before=was||await cache.match(path);
  const date=askSince(since,before&&before.headers.get('Last-Modified'),before&&before.headers.get('Date'));
  const fresh=await fetch(path,{cache:'no-store',...(date?{headers:{'If-Modified-Since':date}}:{})});
  if(!fresh.ok)return fresh;
  const [old,now]=await Promise.all([before?before.clone().text():null,fresh.clone().text()]);
  await cache.put(path,fresh.clone());
  if(old!==null&&old!==now)await tellPages({kind:'shell-updated'});
  return fresh;
}
async function openShell(event,path){
  const kept=await (await caches.open(SHELL)).match(path);
  if(!kept)return readShell(path,null);                              // nothing kept yet: from the server, as before
  event.waitUntil(readShell(path,kept.clone()).catch(()=>{}));       // shown at once; the server's copy is read behind it (its own copy: the opening reads this one)
  return kept;
}
self.addEventListener('fetch',event=>{
  const request=event.request,path=request.method==='GET'?shellPath(request.url,self.registration.scope):'';
  if(!path)return;
  // An opening gets the kept copy. The page's own reading of its file (to see whether a newer build is there)
  // goes to the server, and what comes back is kept: the refresh that follows opens the new build.
  event.respondWith(request.mode==='navigate'?openShell(event,path):readShell(path,null,request.headers.get('If-Modified-Since')||''));
});
self.addEventListener('install',event=>{
  self.skipWaiting();
  const path=new URL('suda.html',self.registration.scope).pathname;
  // A message he sends must not wait for the worker to start (on his phone the page is taken away the moment
  // the screen goes dark, and what had not left by then was lost): only the page's own file is the worker's.
  try{if(typeof event.addRoutes==='function')event.waitUntil(Promise.resolve(event.addRoutes(pastWorker(path))).catch(()=>{}));}catch{}
  // the page is kept from the first moment, so that already the next opening is at once
  event.waitUntil(readShell(path,null).catch(()=>{}));
});
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const name of await caches.keys())if(name.startsWith('suda-shell-')&&name!==SHELL)await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener('push',event=>{
  event.waitUntil((async()=>{
    let due=[];
    // the summary is enough (every thread's last message is in it), and many times smaller; a server from before it has only the whole state
    for(const name of ['summary.json','state.json']){
      try{const r=await fetch(name+'?t='+Date.now(),{cache:'no-store'});if(r.ok){due=dueThreads(await r.json());break;}}catch{}
    }
    if(!due.length){
      // A push must show something. With nothing on him (he answered meanwhile) it is one quiet line.
      await self.registration.showNotification('Suda',{body:tr('There is an update in the threads'),tag:'suda',lang:LANG,dir:DIR,icon:'icons/suda2-192.png',silent:true,data:{url:'suda.html'}});
      return;
    }
    for(const t of due.slice(0,5)){
      // What this push is about sounds; what was already announced stays listed, quietly.
      await self.registration.showNotification(t.title,{body:t.body,tag:'suda:'+t.id,renotify:t.fresh,silent:!t.fresh,lang:LANG,dir:DIR,icon:'icons/suda2-192.png',badge:'icons/suda2-192.png',data:{url:'suda.html#'+t.id}});
    }
  })());
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  const url=new URL((event.notification.data&&event.notification.data.url)||'suda.html',self.registration.scope).href;
  event.waitUntil((async()=>{
    const pages=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    const open=pages.find(page=>page.url.startsWith(self.registration.scope));
    if(open){await open.focus();open.postMessage({kind:'open-thread',url});return;}
    await self.clients.openWindow(url);
  })());
});

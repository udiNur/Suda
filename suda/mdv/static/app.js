// MD Viewer: one Markdown file read in Suda's style. Draws with Suda's own markdown() (suda-pure.js) and its
// style sheet; the logic without a DOM is in mdv-pure.js.
'use strict';
const $=id=>document.getElementById(id);
const BASE=location.pathname.replace(/[^/]*$/,'');          // "/mdv/"
const API=BASE+'api/';
// (LANG, L10N and tr() are Suda's, from suda-pure.js: the installation's language, which static/l10n.js names)
const LANG_NAME={he:tr('Hebrew'),en:tr('English')};
const TRANSLATED_TO={he:tr('Translated into Hebrew ✓'),en:tr('Translated into English ✓')};
const TRANSLATE_TO={he:tr('Translate into Hebrew'),en:tr('Translate into English')};
const DIR={he:'rtl',en:'ltr'};

// ── small helpers, in Suda's shape ──
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined&&text!==null)n.textContent=text;return n;}
function dirOf(t){return blockDir(t)||'auto';}
function said(tag,cls,text){const n=el(tag,cls,text);n.dir=dirOf(String(text));return n;}
function button(label,cls,run){const b=el('button',cls,label);b.type='button';b.onclick=run;return b;}
function icon(name,size){const NS='http://www.w3.org/2000/svg',svg=document.createElementNS(NS,'svg'),use=document.createElementNS(NS,'use');svg.setAttribute('width',size);svg.setAttribute('height',size);svg.setAttribute('aria-hidden','true');use.setAttribute('href','#i-'+name);svg.append(use);return svg;}
function cardTop(title,...acts){const top=el('div','card-top');top.append(said('span','card-title',title),...acts.filter(Boolean));return top;}
function cardAct(name,label,run){const b=button(null,'',run);b.append(icon(name,14),el('span','act-label',label));b.title=label;return b;}
function toast(text,actLabel,act){
  const box=$('float-toasts'),t=el('div','toast');t.append(said('span','',text));
  if(actLabel){const b=button(actLabel,'text-btn',()=>{t.remove();act();});t.append(b);}
  box.append(t);setTimeout(()=>t.remove(),actLabel?6500:3200);
}
function copyText(text,done){
  const ok=()=>toast(done);
  if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(text).then(ok,()=>legacyCopy(text)&&ok());
  else if(legacyCopy(text))ok();
}
function legacyCopy(text){const a=el('textarea');a.value=text;a.style.cssText='position:fixed;opacity:0';document.body.append(a);a.select();let ok=false;try{ok=document.execCommand('copy');}catch{}a.remove();return ok;}
function store(key,value){try{if(value===undefined)return JSON.parse(localStorage.getItem('mdv.'+key)||'null');localStorage.setItem('mdv.'+key,JSON.stringify(value));}catch{return null;}}
function hhmm(ts){const d=new Date(ts*1000),now=new Date(),at=localeTag();const t=d.toLocaleTimeString(at,{hour:'2-digit',minute:'2-digit'});return d.toDateString()===now.toDateString()?t:d.toLocaleDateString(at,{day:'numeric',month:'numeric'})+' '+t;}
// A text with elements inside it, as Suda's trNodes: the translation's {name} places hold the nodes (or strings).
function trNodes(text,nodes){return String(tr(text)).split(/\{(\w+)\}/).map((part,i)=>i%2?(nodes[part]??''):part).filter(part=>part!=='');}
// The page's own markup in the installation's language: data-t (the element's text), data-t-attrs (those attributes).
function translateStatic(root){
  for(const n of root.querySelectorAll('[data-t]'))n.textContent=tr(n.textContent.trim());
  for(const n of root.querySelectorAll('[data-t-attrs]'))for(const a of n.dataset.tAttrs.split(' '))if(n.hasAttribute(a))n.setAttribute(a,tr(n.getAttribute(a)));
}
translateStatic(document);

// ── state ──
const params=new URLSearchParams(location.search);
const S={path:params.get('path')||'',doc:null,mode:['src','tr','both'].includes(params.get('mode'))?params.get('mode'):'src',
  sumOpen:false,sum:null,sumBusy:false,live:null,progress:null,wide:false,flash:null,events:null};
// Inside Suda (embed=1, in its panel over a thread, suda-fixes m190): the panel's buttons are in this head, and
// what the panel must do is said to Suda by message (ready, close, size), to this origin only.
const EMBED=params.get('embed')==='1'&&window.parent!==window;
let hostSays={full:false,canResize:false,back:false};
function tellHost(op,more){if(EMBED)try{parent.postMessage({kind:'mdv',op,...(more||{})},location.origin);}catch{}}
function pageHref(){const u=new URL(location.href);u.searchParams.delete('embed');return u.pathname+u.search;}
function paintEmbed(){
  if(!EMBED)return;
  document.documentElement.classList.add('embedded');
  $('head-embed').hidden=false;
  $('b-newpage').href=pageHref();
  const size=$('b-size');size.hidden=!hostSays.canResize;size.setAttribute('aria-pressed',String(hostSays.full));
  size.title=size.ariaLabel=hostSays.full?tr('Exit full screen'):tr('Full screen');
  $('b-back').hidden=!hostSays.back;
}
addEventListener('message',e=>{
  if(!EMBED||e.source!==parent||e.origin!==location.origin)return;
  const d=e.data;if(d&&d.kind==='mdv-host'){hostSays={full:!!d.full,canResize:!!d.canResize,back:!!d.back};paintEmbed();}
});
// Inside the panel another note is opened by Suda (task 73): Suda keeps the trail of notes, so Back (the phone's, or
// the panel's own) returns to the note before, and only the first one's Back closes the panel. On its own page
// the browser's history does it.
function goTo(href){
  if(!EMBED){location.href=href;return;}
  const u=new URL(href,location.href);let hash='';try{hash=decodeURIComponent(u.hash.slice(1));}catch{}
  tellHost('open',{path:u.searchParams.get('path')||'',mode:u.searchParams.get('mode')||'',hash});
}
const narrow=matchMedia('(max-width:639px)');
const coarse=matchMedia('(pointer:coarse)');
function paintTouch(){document.documentElement.classList.toggle('touch',narrow.matches||coarse.matches);}
paintTouch();narrow.addEventListener('change',()=>{paintTouch();render();});

// ── rendering a block: Suda's markdown, then Suda's cards ──
function dressTables(root){
  for(const holder of root.querySelectorAll('.table')){
    const table=holder.querySelector('table');if(!table||holder.closest('.sheet'))continue;
    const lines=Math.max(0,table.rows.length-(table.querySelector('th')?1:0));
    for(const row of table.rows)for(const cell of row.cells)if(cell.textContent.trim().length<=14)cell.classList.add('tight');
    const rows=()=>[...table.rows].map(r=>[...r.cells].map(c=>c.textContent));
    const card=el('div','card sheet');
    holder.replaceWith(card);
    card.append(cardTop(lines===1?tr('Table · one line'):tr('Table · {n} lines',{n:lines}),
      cardAct('copy',tr('Copy'),()=>copyText(tableText(rows(),true),tr('The table was copied, you can paste it in a spreadsheet'))),
      cardAct('download','CSV',()=>downloadText(tableText(rows(),false),(docTitle(S.doc.blocks,S.doc.name)||'table').slice(0,40)+'.csv','text/csv')),
      cardAct('expand',tr('Full screen'),()=>openModal(tr('Table'),holder.cloneNode(true)))),holder);
  }
}
function downloadText(text,name,type){const a=el('a');a.href=URL.createObjectURL(new Blob(['﻿'+text],{type:type+';charset=utf-8'}));a.download=name;document.body.append(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},500);}
function dressCode(root){
  for(const pre of root.querySelectorAll('pre:not(.mermaid)')){
    const holder=pre.querySelector('code');if(!holder||pre.closest('.code'))continue;
    const code=holder.textContent,lang=(/(?:^| )lang-([a-z0-9]+)/.exec(pre.className)||[])[1]||'',box=el('div','card code'),bar=el('div','card-top code-bar');
    const wrap=button(null,'wrap-toggle',()=>{const on=document.documentElement.classList.toggle('wrap-code');store('wrap',on);for(const w of document.querySelectorAll('.wrap-toggle'))w.setAttribute('aria-pressed',String(on));});
    wrap.append(tr('Wrap lines'));wrap.setAttribute('aria-pressed',String(document.documentElement.classList.contains('wrap-code')));
    const copy=button(null,'',()=>copyText(cleanCopy(code,true),tr('The code was copied')));copy.append(icon('copy',14),tr('Copy'));
    bar.append(el('span','card-title'+(lang?'':' plain'),lang||tr('Code')),wrap,copy);
    holder.replaceChildren(...codeNodes(code,lang));
    pre.replaceWith(box);box.append(bar,pre);
  }
}
// The coloured pieces of a block of code: every line stays left to right (its indentation, its scrolling, a file
// tree), a comment whose words start in Hebrew is an island that reads right to left (codeIsland, line by line: an
// island never crosses the end of a line), and a string holding Hebrew is isolated between its quotes (two Hebrew
// strings on one line keep their order). In sh and config files a # inside a word (a URL's #top) is not a comment.
// The pieces of a block of code come from Suda's codePieces() (suda-pure.js): the same islands as in Suda. Only the
// nodes are drawn here, as Suda's codeNodes() draws them.
function codeNodes(code,lang){
  return codePieces(code,lang).map(p=>{
    if(p.nl)return document.createTextNode('\n');
    if(p.k==='s'&&p.q!==undefined){const span=el('span','tk-s',p.q);span.append(el('bdi','',p.rtl),p.q);return span;}
    if(p.rtl!==undefined){const span=el('span','tk-c',p.lead),words=el('bdi','',p.rtl);words.dir='rtl';span.append(words);if(p.tail)span.append(p.tail);return span;}
    return p.k?el('span','tk-'+p.k,p.t):document.createTextNode(p.t);
  });
}
const SVG_CACHE=new Map();let mermaidN=0,mermaidChain=Promise.resolve();
function dressDiagrams(root){
  for(const pre of root.querySelectorAll('pre.mermaid')){
    const code=pre.textContent,figure=el('figure','card diagram'),body=el('div','diagram-body'),note=el('figcaption','diagram-note',tr('Drawing the diagram…'));
    const source=cardAct('text',tr('Source'),()=>{pre.hidden=!pre.hidden;source.setAttribute('aria-pressed',String(!pre.hidden));});
    source.setAttribute('aria-pressed','false');
    figure.style.margin='6px 0';
    pre.replaceWith(figure);body.append(note);
    figure.append(cardTop(tr('Diagram'),source,cardAct('expand',tr('Full screen'),()=>{const big=el('div','diagram-body');big.innerHTML=body.innerHTML;openModal(tr('Diagram'),big);})),body,pre);
    pre.hidden=true;pre.style.margin='0 12px 10px';
    drawDiagram(code).then(svg=>{note.remove();body.insertAdjacentHTML('afterbegin',svg);fitDiagram(body,code);},()=>{note.textContent=tr('The diagram cannot be drawn. This is its code.');pre.hidden=false;});
  }
}
// As Suda: as wide as the card, down to 60% of its own size (then the card scrolls) and up to 150%.
function fitDiagram(body,code){
  const svg=body.querySelector('svg');if(!svg)return;
  const vb=(svg.getAttribute('viewBox')||'').split(/\s+/).map(Number),w=vb[2]||600,h=vb[3]||300,room=Math.max(200,body.clientWidth-24);
  const width=Math.max(w*0.6,Math.min(room,w*1.5));
  svg.style.maxWidth='none';svg.style.width=width+'px';svg.style.height=(width*h/w)+'px';
  if(/flowchart\s+RL|graph\s+RL/i.test(code))body.scrollLeft=body.scrollWidth;
}
function themeNow(){const t=document.documentElement.dataset.theme;return t||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');}
// Mermaid draws one diagram at a time (it keeps state between renders).
function drawDiagram(code){
  const key=themeNow()+'\n'+code;
  if(SVG_CACHE.has(key))return Promise.resolve(SVG_CACHE.get(key));
  const run=mermaidChain.then(async()=>{
    for(let i=0;i<100&&!window.mermaid;i++)await new Promise(r=>setTimeout(r,60));
    if(!window.mermaid)throw new Error('no mermaid');
    mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:themeNow()==='dark'?'dark':'default',htmlLabels:false,flowchart:{htmlLabels:false},fontFamily:'-apple-system, "Segoe UI", Roboto, "Noto Sans Hebrew", sans-serif'});
    const out=await mermaid.render('mmd'+(++mermaidN),code);
    SVG_CACHE.set(key,out.svg);return out.svg;
  });
  mermaidChain=run.catch(()=>{});
  return run;
}
// A picture of the note (rewriteImages made it a link to the viewer's picture address): drawn, and a press opens it
// whole in a page of its own. One that does not load says so, by its name.
function dressImages(root){
  for(const a of root.querySelectorAll('a[href]')){
    const href=a.getAttribute('href');
    if(!href.startsWith(BASE+'api/asset?')||!/[?&]img=1(?:&|$)/.test(href))continue;
    const name=a.textContent,link=el('a','md-img'),img=el('img');
    link.href=href;link.target='_blank';link.rel='noopener';link.title=name;
    img.src=href;img.alt=name;img.loading='lazy';img.decoding='async';
    const w=/[?&]w=(\d{1,4})(?:&|$)/.exec(href);if(w)img.style.width=w[1]+'px';      // the width the README asked for (never past the text: max-width)
    img.onerror=()=>{link.replaceChildren(el('span','md-img-missing',tr('Picture not found: {name}',{name})));};
    link.append(img);a.replaceWith(link);
  }
}
// Links to other .md files open here; a `~/…/x.md` in code becomes a link too.
// Links to other notes (task 73). Every link to a note opens it here (in the panel: by Suda, see goTo); a link
// whose note does not open (missing, outside the roots, hidden: the server says, by the rule that opens notes) is
// marked before the tap and does not open. A note named in inline code by its full path, or by its name alone
// relative to this note's folder (`01-positioning.md`, suda m385), is a link too: by its name only once the note
// is there (a name in code that is not a note stays code). A #heading in the address scrolls to it.
function followLink(a,ev){
  if(ev.button||ev.metaKey||ev.ctrlKey||ev.shiftKey||ev.altKey)return;
  if(a.classList.contains('md-broken')){ev.preventDefault();toast(a.title||tr('File not found: {path}',{path:''}));return;}
  if(EMBED){ev.preventDefault();goTo(a.getAttribute('href'));}
}
function dressLinks(root){
  for(const a of root.querySelectorAll('a[href]')){
    const href=a.getAttribute('href');
    if(href.startsWith(BASE+'?')){a.removeAttribute('target');a.classList.add('md-link');a.addEventListener('click',ev=>followLink(a,ev));}
    else if(href.startsWith('#')){a.removeAttribute('target');a.addEventListener('click',ev=>{ev.preventDefault();scrollToHeading(href.slice(1));});}
  }
  for(const code of root.querySelectorAll('code')){
    if(code.closest('pre,a'))continue;
    const full=mdPathOf(code.textContent),name=full?null:mdNameOf(code.textContent);
    const path=full||(name&&S.doc?resolveRel(S.doc.dir,name):null);if(!path)continue;
    const a=el('a','md-link');a.href=viewerHref(BASE,path);a.title=path;if(name)a.dataset.maybe='1';code.replaceWith(a);a.append(code);
    a.addEventListener('click',ev=>followLink(a,ev));
  }
  queueLinkCheck();
}
const LINK_HERE=new Map();let linkTimer=0;
function queueLinkCheck(){clearTimeout(linkTimer);linkTimer=setTimeout(checkLinks,30);}
function linkPath(a){try{return new URL(a.href).searchParams.get('path');}catch{return null;}}
async function checkLinks(){
  const ask=[...new Set([...document.querySelectorAll('#doc a.md-link')].map(linkPath).filter(p=>p&&!LINK_HERE.has(p)))].slice(0,400);
  for(let i=0;i<ask.length;i+=40){
    const part=ask.slice(i,i+40);
    const r=await fetch(API+'exists?'+part.map(p=>'p='+encodeURIComponent(p)).join('&')).catch(()=>null);
    const j=r&&r.ok?await r.json().catch(()=>null):null;
    if(j&&j.ok&&Array.isArray(j.here))part.forEach((p,k)=>LINK_HERE.set(p,j.here[k]===true));
  }
  for(const a of document.querySelectorAll('#doc a.md-link')){
    const p=linkPath(a);if(!LINK_HERE.has(p))continue;
    const here=LINK_HERE.get(p);
    if(a.dataset.maybe){if(here)delete a.dataset.maybe;else a.replaceWith(...a.childNodes);}
    else if(!here){a.classList.add('md-broken');a.title=tr('File not found: {path}',{path:p});a.setAttribute('aria-disabled','true');}
  }
}
// A link's #heading on arrival: the first frame may come before the box that scrolls has its size (then the scroll
// stays at 0), so it is tried again a few times in the first second, and never after his own scroll, tap or key.
function goToHash(name){
  let his=false;const mine=()=>{his=true;};
  for(const ev of ['wheel','touchstart','pointerdown','keydown'])addEventListener(ev,mine,{once:true,capture:true});
  const go=()=>{if(!his)scrollToHeading(name);};
  requestAnimationFrame(go);for(const ms of [120,400,1000])setTimeout(go,ms);
}
// The heading a #name points at (its GitHub address, or its words), scrolled to; false when there is none. Suda's
// markdown draws a heading as <p class="h h2">, not <h2>.
function scrollToHeading(raw){
  let want=String(raw||'');try{want=decodeURIComponent(want);}catch{}
  want=headingSlug(want);if(!want)return false;
  const h=[...document.querySelectorAll('#doc p.h,#doc h1,#doc h2,#doc h3,#doc h4,#doc h5,#doc h6')].find(n=>headingSlug(n.textContent)===want);
  if(!h)return false;
  scrollToNode(h);return true;
}
function blockNode(text,lang,i,kind){
  const d=DIR[lang],b=el('div','blk md');b.dir=d;b.dataset.i=i;b.dataset.kind=kind;b.lang=lang;
  b.innerHTML=markdown(rewriteLinks(rewriteImages(joinSoftBreaks(text),S.doc.dir,BASE),S.doc.dir,BASE),d);
  dressImages(b);dressTables(b);dressCode(b);dressDiagrams(b);dressLinks(b);
  return b;
}

// ── the document ──
const trView=()=>S.doc&&S.doc.translation||{exists:false};      // (tr() is Suda's: the words in the installation's language)
// What stands beside block i: {t, stale, typing} or null.
function trAt(i){
  if(S.live&&S.live[i]!=null)return {t:S.live[i],stale:false,fresh:true};
  const v=trView();
  if(v.exists&&v.aligned&&v.blocks[i])return {...v.blocks[i],old:!!S.live};
  return null;
}
function trNode(i){
  const x=trAt(i),tl=S.doc.tr_lang;
  if(!x)return emptyTr(i);
  const n=blockNode(x.t,tl,i,'tr');
  if(x.stale||x.old){n.classList.add('stale');n.prepend(el('span','stale-tag',S.live?tr('Translating again…'):tr('The original changed · update the translation')));}
  if(S.failed&&S.failed.has(i))n.classList.add('failed');
  return n;
}
function emptyTr(i){
  const n=el('div','tr-empty');n.dataset.i=i;n.dataset.kind='tr';
  if(S.live){n.append('…');return n;}
  if(i===0||!trView().exists){
    if(i===0){n.append((trView().exists?tr('No translation for this block yet.'):tr('No translation for this file yet.'))+' ');if(S.doc.can_translate)n.append(button(tr('Translate now'),'text-btn',()=>startTranslate()));}
    else n.append('…');
  }else n.append(tr('No translation for this block yet'));
  return n;
}
function renderDoc(flash){
  const doc=$('doc');doc.replaceChildren();doc.className='doc'+(document.body.classList.contains('wide')?' wide':'');$('sum-slot').replaceChildren();
  const d=S.doc;if(!d)return;
  if(S.sumOpen)$('sum-slot').append(summaryNode());
  const v=trView(),tl=d.tr_lang,mode=S.mode;
  S.wide=$('scroll').clientWidth>=760;
  if(mode!=='src'&&v.exists&&!v.aligned&&!S.live){fullTranslation(doc,mode);return markFlash(flash);}
  if(mode==='both'&&S.wide){
    doc.classList.add('sbs');
    const cols=el('div','cols'),a=el('span','',tr('Original · {lang}',{lang:LANG_NAME[d.lang]})),b=el('span','',tr('Translation · {lang}',{lang:LANG_NAME[tl]}));b.dir=DIR[tl];
    cols.append(a,b);doc.append(cols);
  }
  d.blocks.forEach((text,i)=>{
    if(mode==='src'){doc.append(blockNode(text,d.lang,i,'src'));return;}
    if(mode==='tr'){
      if(!v.exists&&!S.live){if(i===0)doc.append(emptyTr(0));return;}
      doc.append(trNode(i));return;
    }
    const s=blockNode(text,d.lang,i,'src');
    if(S.wide){const p=el('div','pair');p.dataset.i=i;p.append(s,trNode(i));doc.append(p);}
    else{const u=el('div','under');u.dataset.i=i;u.dir=DIR[tl];u.append(el('span','under-tag',LANG[tl]),trNode(i));doc.append(s,u);}
  });
  markFlash(flash);
}
// A translation MDS could not line up block by block: shown whole, beside the whole source.
function fullTranslation(doc,mode){
  const d=S.doc,v=trView(),tl=d.tr_lang,side=(blocks,lang,kind)=>{const box=el('div');blocks.forEach((t,i)=>box.append(blockNode(t,lang,i,kind)));return box;};
  const right=side(blocksOf(v.full),tl,'tr');
  if(mode==='tr'){doc.append(right);return;}
  if(S.wide){doc.classList.add('sbs');const p=el('div','pair');p.append(side(d.blocks,d.lang,'src'),right);doc.append(p);}
  else{doc.append(side(d.blocks,d.lang,'src'));const u=el('div','under');u.dir=DIR[tl];u.append(el('span','under-tag',LANG[tl]),right);doc.append(u);}
}
function markFlash(flash){
  if(!flash||!flash.length)return;
  let first=null;
  for(const i of flash)for(const n of $('doc').querySelectorAll('.blk[data-i="'+i+'"][data-kind="src"]')){n.classList.add('flash');first=first||n;}
  if(first&&S.flashScroll)scrollToNode(first,true);
}
// (scrollIntoView would also scroll a page that holds this one in a frame)
function scrollToNode(n,smooth){const sc=$('scroll');const top=n.getBoundingClientRect().top-sc.getBoundingClientRect().top+sc.scrollTop-sc.clientHeight/3;sc.scrollTo({top:Math.max(0,top),behavior:smooth?'smooth':'auto'});}

// ── the summary: Suda's pinned strip, above the document (written in the installation's language) ──
function summaryNode(){
  const box=el('div','sum'),top=el('div','sum-top'),s=S.doc.summary;
  top.append(icon('sum',14),el('span','',tr('Summary')));
  const when=el('span','',S.sumBusy?tr('Summarizing…'):s?(s.stale?tr('Saved before the file changed'):s.ts?tr('Saved · {time}',{time:hhmm(s.ts)}):tr('Saved')):'');
  when.style.cssText='flex:none;font-weight:400;color:var(--mute)';top.append(when);
  if(!S.sumBusy&&S.doc.can_translate)top.append(button(s?tr('Summarize again'):tr('Summarize'),'text-btn',()=>makeSummary(!!s)));
  box.append(top);
  if(s){const body=el('div','md'),way=pageDir();body.dir=way;body.innerHTML=markdown(s.text,way);dressLinks(body);box.append(body);}
  else if(!S.sumBusy)box.append(el('div','tr-empty',S.doc.can_translate?tr('No summary for this file yet'):tr('No API key for the summary')));
  return box;
}
async function makeSummary(force){
  if(S.sumBusy)return;
  S.sumBusy=true;renderDoc();
  try{
    const r=await post('summary',{path:S.doc.path,force:!!force});
    if(!r.ok)throw new Error(r.message||r.error);
    S.doc.summary={text:r.text,stale:false,ts:r.ts};
  }catch(e){toast(tr('The summary failed: {error}',{error:String(e.message||e).slice(0,120)}));}
  S.sumBusy=false;renderDoc();
}
function toggleSummary(){
  S.sumOpen=!S.sumOpen;renderHead();renderDoc();
  if(S.sumOpen&&!S.doc.summary&&S.doc.can_translate)makeSummary(false);
  if(S.sumOpen)$('scroll').scrollTo({top:0});
}

// ── the head and the translation bar ──
function renderHead(){
  const d=S.doc,st=$('h-status');st.replaceChildren();
  if(!d){$('head-acts').hidden=true;return;}
  $('head-acts').hidden=false;
  $('h-slot').textContent=d.lang==='he'?tr('HE'):'EN';
  const title=docTitle(d.blocks,d.name);
  $('h-title').textContent=title;$('h-title').dir=dirOf(title);document.title=title+' · MD';
  $('h-path').textContent=d.path;$('h-path').title=d.path;
  st.append(el('span','chip lang',LANG_NAME[d.lang]));
  const v=trView();
  if(v.exists){
    if(v.stale)st.append(el('span','chip working',!v.aligned?tr('The translation is old'):v.stale===1?tr('The translation is old in one block'):tr('The translation is old in {n} blocks',{n:v.stale})));
    else st.append(el('span','chip done',TRANSLATED_TO[d.tr_lang]));
  }
  const live=el('span','live'+(S.events&&S.events.readyState===1?' on':''),tr('Live'));live.title=tr('Every change in the file shows here at once');st.append(live);
  st.append(el('span','note',tr('Saved {time} · {size}',{time:hhmm(d.mtime),size:sizeWords(d.size)})));
  $('b-sum').setAttribute('aria-pressed',String(S.sumOpen));
  $('b-tr').setAttribute('aria-pressed',String(S.mode!=='src'));
}
function renderXbar(){
  const d=S.doc,bar=$('xbar');bar.replaceChildren();
  if(!d){bar.hidden=true;return;}
  bar.hidden=false;
  const tl=d.tr_lang,seg=el('div','seg');
  [['src',tr('Original')],['tr',LANG_NAME[tl]],['both',S.wide?tr('Side by side'):tr('One under the other')]].forEach(([m,label])=>{
    const b=button(label,'',()=>setMode(m));b.setAttribute('aria-pressed',String(S.mode===m));b.dataset.mode=m;seg.append(b);
  });
  bar.append(seg);
  const state=el('span','xstate'),v=trView();
  if(S.live){
    const p=el('span','prog'),i=el('i');i.id='prog-i';p.append(i);state.append(p,el('span','note',tr('Translating… {progress}',{progress:S.progress||''})));
    paintProgress(i);
  }else if(!v.exists){
    state.append(el('span','note',d.can_translate?tr('Not translated yet'):tr('No API key for translating')));
    if(d.can_translate)state.append(button(TRANSLATE_TO[tl],'btn primary',()=>startTranslate()));
  }else if(v.stale){
    state.append(el('span','note',!v.aligned?tr('The original changed: the translation is old'):v.stale===1?tr('The original changed: one block to translate'):tr('The original changed: {n} blocks to translate',{n:v.stale})));
    if(d.can_translate)state.append(button(tr('Update the translation'),'btn',()=>startTranslate()));
  }else{
    const n=el('span','note saved');n.append(...trNodes('Saved beside the file: {file} · {time}',{file:el('bdi','fname',v.file||''),time:hhmm(v.mtime||d.mtime)}));state.append(n);
  }
  bar.append(state);
}
function paintProgress(i){
  const p=S.progressNum;if(!i||!p||!p.total)return;
  i.style.width=Math.round(100*p.done/p.total)+'%';
}
function setMode(m){
  if(!S.doc)return;
  S.mode=m;
  const u=new URL(location.href);if(m==='src')u.searchParams.delete('mode');else u.searchParams.set('mode',m);history.replaceState(null,'',u);
  paintEmbed();
  renderHead();renderDoc();renderXbar();
  if(m!=='src'&&!trView().exists&&!S.live&&S.doc.can_translate)startTranslate();
}

// ── translating: the server owns the job; this page reads its lines ──
async function post(what,body){
  const r=await fetch(API+what,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return r.json().catch(()=>({ok:false,error:'http-'+r.status}));
}
async function startTranslate(force){
  if(S.live||!S.doc)return;
  if(S.mode==='src')S.mode=narrow.matches?'tr':'both';
  follow(fetch(API+'translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:S.doc.path,force:!!force})}));
}
async function follow(request){
  const path=S.doc.path;
  S.live=[];S.failed=new Set();S.progress='';S.progressNum={done:0,total:0};render();
  let end=null;
  try{
    const r=await request;
    if(!r.ok||!r.body){const j=await r.json().catch(()=>({}));if(j.error==='busy'){end=j;throw null;}throw new Error(j.message||j.error||('http '+r.status));}
    const reader=r.body.getReader(),dec=new TextDecoder();let buf='';
    for(;;){
      const {value,done}=await reader.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      let at;
      while((at=buf.indexOf('\n'))>=0){
        const line=buf.slice(0,at);buf=buf.slice(at+1);if(!line.trim())continue;
        const ev=JSON.parse(line);
        if(S.doc.path!==path)return;
        if(ev.start){S.progressNum.total=ev.blocks;}
        else if(ev.i!=null){S.live[ev.i]=ev.t;S.progressNum.done++;S.progress=tr('{done} of {total} blocks',{done:S.progressNum.done,total:S.progressNum.total});swapTr(ev.i);}
        else if(ev.done||ev.error)end=ev;
      }
    }
  }catch(e){if(e)end={error:'failed',message:String(e.message||e)};}
  if(end&&end.failed&&end.failed.length)S.failed=new Set(end.failed);
  S.live=null;S.progress=null;
  await loadDoc();
  if(end&&end.error==='not-ours')toast(tr('The file {name} already exists and was not made here, so it is left alone',{name:end.message}));
  else if(end&&end.error==='busy')toast(tr('Other translations are running now. You can try again in a moment'));
  else if(!end||end.error)toast(end&&end.message?tr('The translation failed: {error}',{error:end.message.slice(0,140)}):tr('The translation failed'));
  else if(end.failed&&end.failed.length)toast(end.failed.length===1?tr('One block was not translated. You can try again'):tr('{n} blocks were not translated. You can try again',{n:end.failed.length}),tr('Try again'),()=>startTranslate());
  else toast(!end.sent?tr('The translation is already up to date'):end.reused?tr('The translation was saved beside the file: {file} · only the {n} blocks that changed were sent',{file:trView().file||'',n:end.sent}):tr('The translation was saved beside the file: {file}',{file:trView().file||''}));
}
function swapTr(i){
  const old=document.querySelector('#doc [data-kind="tr"][data-i="'+i+'"]');
  const note=document.querySelector('.xstate .note');if(note)note.textContent=tr('Translating… {progress}',{progress:S.progress||''});
  paintProgress($('prog-i'));
  if(!old)return;
  const n=trNode(i);n.classList.add('typing');old.replaceWith(n);setTimeout(()=>n.classList.remove('typing'),600);
}

// ── find in this file ──
let finds=[],findAt=0;
function openFind(){$('find').hidden=false;$('find-q').focus();}
function closeFind(){if($('find').hidden)return;$('find').hidden=true;$('find-q').value='';renderDoc();}
function runFind(){
  renderDoc();const q=$('find-q').value;finds=[];findAt=0;
  if(q.length>=2){
    const walker=document.createTreeWalker($('doc'),NodeFilter.SHOW_TEXT),units=[],codes=new Map();
    while(walker.nextNode()){
      const node=walker.currentNode,parent=node.parentElement;
      if(parent&&parent.closest('svg,.cols'))continue;
      // a block of code is searched as its whole text: a comment's marker and its Hebrew words (an island) or a
      // string's quotes and its words are in different nodes, and "-- note" in Hebrew is still one match
      const code=parent&&parent.closest('pre code');
      if(!code){units.push([node]);continue;}
      if(!codes.has(code)){codes.set(code,[]);units.push(codes.get(code));}
      codes.get(code).push(node);
    }
    const ql=q.toLowerCase(),cuts=new Map();
    for(const nodes of units){
      const starts=[];let text='';for(const n of nodes){starts.push(text.length);text+=n.nodeValue;}
      const lo=text.toLowerCase();
      for(let at=lo.indexOf(ql);at>=0;at=lo.indexOf(ql,at+q.length)){
        const group=[],end=at+q.length;finds.push(group);
        nodes.forEach((n,i)=>{const s=Math.max(at,starts[i]),e=Math.min(end,starts[i]+n.nodeValue.length);
          if(s<e){if(!cuts.has(n))cuts.set(n,[]);cuts.get(n).push([s-starts[i],e-starts[i],group]);}});
      }
    }
    for(const [node,list] of cuts){
      const t=node.nodeValue,frag=document.createDocumentFragment();let from=0;
      for(const [s,e,group] of list){frag.append(t.slice(from,s));const m=el('mark','hl',t.slice(s,e));m.dataset.find=String(finds.indexOf(group));group.push(m);frag.append(m);from=e;}
      frag.append(t.slice(from));node.replaceWith(frag);
    }
  }
  stepFind(0);
}
// one find may be in pieces (across the nodes of a line of code): its pieces light up and count together
function stepFind(d){
  if(!finds.length){$('find-count').textContent='0/0';return;}
  findAt=(findAt+d+finds.length)%finds.length;finds.forEach((g,i)=>g.forEach(m=>m.classList.toggle('cur',i===findAt)));
  scrollToNode(finds[findAt][0]);$('find-count').textContent=(findAt+1)+'/'+finds.length;
}

// ── menus, theme, keys ──
function openMenu(anchor){
  const m=$('menu');m.hidden=false;const r=anchor.getBoundingClientRect();
  const w=m.offsetWidth;const left=Math.max(8,Math.min(r.left,innerWidth-w-8));
  m.style.left=left+'px';m.style.top=Math.min(r.bottom+6,innerHeight-m.offsetHeight-8)+'px';
}
function closeMenu(){$('menu').hidden=true;}
function moreMenu(anchor){
  const m=$('menu');m.replaceChildren();
  const item=(ic,label,run,key)=>{const b=button(null,'',()=>{closeMenu();run();});b.append(icon(ic,18),said('span','',label));if(key)b.append(el('kbd','',key));m.append(b);};
  if(S.doc){
    if(innerWidth<900)item('search',tr('Search in the file'),openFind,'/');
    if(trView().exists&&S.doc.can_translate)item('translate',tr('Translate the whole file again'),()=>startTranslate(true));
    item('copy',tr('Copy the path'),()=>copyText(S.doc.path,tr('The path was copied')));
    item('width',document.body.classList.contains('wide')?tr('Reading width: normal'):tr('Reading width: full'),()=>{const on=document.body.classList.toggle('wide');store('wide',on);renderDoc();});
    m.append(el('hr'));
  }
  item('moon',themeNow()==='dark'?tr('Theme: light'):tr('Theme: dark'),toggleTheme);
  item('keys',tr('Keyboard shortcuts'),showKeys,'?');
  openMenu(anchor);
}
function setTheme(t){document.documentElement.dataset.theme=t;store('theme',t);SVG_CACHE.clear();renderDoc();}
function toggleTheme(){setTheme(themeNow()==='dark'?'light':'dark');}
function showKeys(){
  const box=el('div');
  [[tr('Search in the file'),'/'],[tr('Original, translation, side by side'),'T'],[tr('Summary'),'S'],[tr('Keyboard shortcuts'),'?'],[tr('Close'),'Esc']].forEach(([t,k])=>{
    const r=el('div','help-row');r.append(el('span','',t));const ks=el('span','help-keys');k.split(' ').forEach(x=>ks.append(el('kbd','',x)));r.append(ks);box.append(r);});
  openModal(tr('Keyboard shortcuts'),box);
}
function openModal(title,node){$('m-title').textContent=title;$('m-body').replaceChildren(node);$('modal').hidden=false;}

function render(flash){renderHead();renderDoc(flash);renderXbar();}

// ── loading, live reload ──
async function loadDoc(){
  const r=await fetch(API+'doc?path='+encodeURIComponent(S.path)).catch(()=>null);
  const j=r?await r.json().catch(()=>null):null;
  if(!j||!j.ok){oops(j&&j.error,j&&j.message);return false;}
  if(j.original){const u=new URL(location.href);u.searchParams.set('path',j.original);if(!u.searchParams.get('mode'))u.searchParams.set('mode','tr');location.replace(u);return false;}
  const before=S.doc&&S.doc.path===j.path?S.doc.blocks:null;
  S.doc=j;LINK_HERE.clear();
  store('recent',rememberPath(store('recent'),j.path,12));
  const flash=before?changedBlocks(before,j.blocks):null;
  const keep=$('scroll').scrollTop;
  render(flash);
  if(before)$('scroll').scrollTop=keep;
  else if(location.hash)goToHash(location.hash.slice(1));
  return {changed:flash};
}
function listen(){
  if(S.events)S.events.close();
  const es=new EventSource(API+'events?path='+encodeURIComponent(S.path));S.events=es;
  es.onopen=()=>renderHead();
  es.onerror=()=>renderHead();
  es.addEventListener('change',async()=>{
    if(S.live)return;                                  // the end of a translation reloads by itself
    const got=await loadDoc();
    if(got&&got.changed&&got.changed.length)toast(got.changed.length===1?tr('The file changed and was loaded again · one block'):tr('The file changed and was loaded again · {n} blocks',{n:got.changed.length}),tr('Show'),()=>{S.flashScroll=true;renderDoc(got.changed);S.flashScroll=false;});
  });
}
const ERRORS={missing:tr('The file was not found'),outside:tr('The file is outside the folders the viewer opens (MDS roots)'),hidden:tr('Hidden files and folders do not open here'),'not-markdown':tr('Only .md files open here'),'bad-path':tr('A full path is needed, or one that starts with ~/'),'too-big':tr('The file is too big'),host:tr('This address is not allowed')};
function oops(code,message){
  S.doc=null;render();
  const box=el('div','oops');box.append(el('p','',ERRORS[code]||tr('Could not open the file')),said('code','',S.path));
  $('doc').replaceChildren(box);$('h-title').textContent='MD Viewer';
}
function landing(){
  $('head-acts').hidden=true;$('xbar').hidden=true;$('h-title').textContent='MD Viewer';
  const box=el('div','land');box.append(el('h1','',tr('Open a Markdown file')),el('p','',tr('The full path to a .md file (or one that starts with ~/), from the MDS folders.')));
  const form=el('form'),input=el('input');input.name='path';input.placeholder='~/Documents/mds/…/file.md';input.autocomplete='off';input.spellcheck=false;
  form.append(input,button(tr('Open it'),'btn primary',()=>form.requestSubmit()));
  form.onsubmit=e=>{e.preventDefault();const v=input.value.trim();if(v)goTo(viewerHref(BASE,v));};
  box.append(form);
  const recent=store('recent')||[];
  if(recent.length){const list=el('div','recent');list.append(el('p','',tr('Opened lately')));for(const p of recent){const a=el('a','',p);a.href=viewerHref(BASE,p);list.append(a);}box.append(list);}
  $('doc').replaceChildren(box);input.focus();
}

// ── wiring ──
$('b-find').onclick=openFind;
$('b-sum').onclick=toggleSummary;
$('b-tr').onclick=()=>setMode(S.mode==='src'?(narrow.matches?'tr':'both'):'src');
$('b-more').onclick=e=>moreMenu(e.currentTarget);
$('b-close').onclick=()=>tellHost('close');
$('b-back').onclick=()=>tellHost('back');
$('b-size').onclick=()=>tellHost('size');
$('find-q').oninput=runFind;$('find-next').onclick=()=>stepFind(1);$('find-prev').onclick=()=>stepFind(-1);$('find-x').onclick=closeFind;
$('find-q').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();stepFind(e.shiftKey?-1:1);}if(e.key==='Escape'){e.stopPropagation();closeFind();}};
$('modal').onclick=e=>{if(e.target.id==='modal')$('modal').hidden=true;};$('m-x').onclick=()=>{$('modal').hidden=true;};
document.addEventListener('click',e=>{if(!$('menu').hidden&&!e.target.closest('#menu,#b-more'))closeMenu();});
document.addEventListener('keydown',e=>{
  const typing=e.target.closest&&e.target.closest('input,textarea');
  if(e.key==='Escape'){
    // the topmost thing closes; with nothing open, inside Suda's panel, the panel itself
    if(!$('menu').hidden)closeMenu();else if(!$('modal').hidden)$('modal').hidden=true;
    else if(!$('find').hidden)closeFind();else tellHost('close');
    return;
  }
  if(typing||e.metaKey||e.ctrlKey||e.altKey||!S.doc)return;
  if(e.key==='/'){e.preventDefault();openFind();}
  else if(e.key==='t'||e.key==='T'||e.key==='\u05d0'){const order=['src','both','tr'];setMode(order[(order.indexOf(S.mode)+1)%3]);}
  else if(e.key==='s'||e.key==='S'||e.key==='\u05d3'){toggleSummary();}
  else if(e.key==='?'){showKeys();}
});
let lastWide=null;
new ResizeObserver(()=>{const w=$('scroll').clientWidth>=760;if(w!==lastWide){lastWide=w;if(S.doc){renderDoc();renderXbar();}}}).observe($('scroll'));

// ── start ──
(async()=>{
  paintEmbed();tellHost('ready');                  // the panel can close by this page's own button from now on
  const theme=store('theme');if(theme==='dark'||theme==='light')document.documentElement.dataset.theme=theme;
  if(store('wide'))document.body.classList.add('wide');
  if(store('wrap'))document.documentElement.classList.add('wrap-code');
  if(!S.path){landing();return;}
  if(!await loadDoc())return;
  listen();
  // (a link with mode=tr shows the translate button; only a press spends a model call)
  if(S.doc.translating)follow(fetch(API+'translate?path='+encodeURIComponent(S.doc.path)));
})();

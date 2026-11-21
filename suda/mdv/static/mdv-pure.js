// MD Viewer: the page's logic that needs no DOM (tested by tests/test_js.py under node).
// Runs after suda-pure.js, whose markdown() draws every block.
'use strict';

// The address that opens a file in this viewer. Brackets and quotes are escaped too, so the address can stand
// inside a Markdown link (a ")" in a path would end it).
function viewerHref(base,path){
  return base+'?path='+encodeURIComponent(String(path)).replace(/[()'!*]/g,c=>'%'+c.charCodeAt(0).toString(16).toUpperCase());
}

// A link target, relative to the folder of the open file, as a path of its own; null for a web address or
// anything that climbs above /.
function resolveRel(dir,target){
  let t=String(target||'');
  if(!t||/^[a-z][a-z0-9+.-]*:/i.test(t)||t.startsWith('#'))return null;
  try{t=decodeURIComponent(t);}catch{return null;}
  let base;
  if(t.startsWith('~/')||t==='~')return normPath(t);
  if(t.startsWith('/'))return normPath(t);
  base=String(dir||'');
  if(!base)return null;
  return normPath(base.replace(/\/+$/,'')+'/'+t);
}
function normPath(p){
  const home=p.startsWith('~/')||p==='~',parts=[],rest=home?p.slice(1):p;
  for(const seg of rest.split('/')){
    if(!seg||seg==='.')continue;
    if(seg==='..'){if(!parts.length)return null;parts.pop();continue;}
    parts.push(seg);
  }
  return (home?'~/':'/')+parts.join('/');
}


// The parts of a block that are not code: fenced lines (a fence may stand under a line of text in the same block)
// and `inline code` are left as they are, everything else goes through `fn`.
function outsideCode(block,fn){
  const out=[];let fence='',prose=[];
  const flush=()=>{if(prose.length){out.push(prose.join('\n').split(/(`[^`\n]+`)/).map((part,k)=>k%2?part:fn(part)).join(''));prose=[];}};
  for(const line of String(block==null?'':block).split('\n')){
    const s=line.replace(/^\s+/,'');
    if(fence){out.push(line);if(s.startsWith(fence))fence='';continue;}
    if(s.startsWith('```')||s.startsWith('~~~')){flush();fence=s.slice(0,3);out.push(line);continue;}
    prose.push(line);
  }
  flush();
  return out.join('\n');
}
const MD_FILE=/\.(?:md|markdown)$/i;
// A block's Markdown with every link to a .md file pointing at this viewer instead (relative links are taken
// from the open file's folder). Code is left as it is: a fenced block whole, and `inline code` within a line.
function rewriteLinks(text,dir,base){
  return outsideCode(text,part=>part.replace(/\[([^\]\n]{1,300})\]\(([^)\s]+?)(#[^)\s]*)?\)/g,(all,label,target,hash)=>{
    if(/^https?:/i.test(target)||!MD_FILE.test(target.split('?')[0]))return all;
    const path=resolveRel(dir,target);
    return path?'['+label+']('+viewerHref(base,path)+anchorOf(hash)+')':all;
  }));
}

// The path in an inline code span that names a .md file by a full path (~/... or /...), else null.
// A link's #heading, kept for the note it opens (task 73): '#' and the heading, encoded; '' for none.
function anchorOf(hash){
  let h=String(hash||'').replace(/^#/,'');
  try{h=decodeURIComponent(h);}catch{return '';}
  h=h.trim().slice(0,200);
  return h?'#'+encodeURIComponent(h):'';
}
// The address of a heading, as GitHub makes it (lower case, spaces as -, punctuation out; Hebrew kept), to match
// a link's #heading.
function headingSlug(text){
  return String(text||'').trim().toLowerCase().replace(/[^\p{L}\p{N}\p{M}\s_-]/gu,'').replace(/\s/g,'-');
}
// A note named in inline code by its name alone, relative to the open note's folder (task 73, suda m385: the
// file's name as it is, `01-positioning.md`): the name, or null. A full path is mdPathOf's.
function mdNameOf(code){
  const t=String(code||'').trim();
  return /^(?:\.{1,2}\/)*[^\s`<>"'|\\:~/][^\s`<>"'|\\:]*$/.test(t)&&MD_FILE.test(t)?t:null;
}
function mdPathOf(code){
  const t=String(code||'').trim();
  return /^(?:~\/|\/)[^\s`<>"]*$/.test(t)&&MD_FILE.test(t)&&!t.includes('/../')?t:null;
}

// The blocks of the new text that were not in the old one (by their text, each old block used once): what
// changed on disk, to flash. Indexes into `now`.
function changedBlocks(before,now){
  const left=new Map();
  for(const b of before||[])left.set(b,(left.get(b)||0)+1);
  const out=[];
  (now||[]).forEach((b,i)=>{const n=left.get(b)||0;if(n)left.set(b,n-1);else out.push(i);});
  return out;
}

// The document's title: its first heading's words, else the file's name.
function docTitle(blocks,name){
  for(const b of blocks||[]){const m=/^\s{0,3}#{1,6}\s+(.+)$/m.exec(b);if(m&&!/^\s*(```|~~~)/.test(b))return m[1].replace(/[*_`]/g,'').trim();}
  return String(name||'');
}

// "1.4 KB", "820 B", "2.1 MB".
function sizeWords(n){
  n=Number(n)||0;
  if(n<1024)return n+' B';
  if(n<1024*1024)return (n/1024).toFixed(1).replace(/\.0$/,'')+' KB';
  return (n/1024/1024).toFixed(1).replace(/\.0$/,'')+' MB';
}

// The blocks of a text, split as the server does (core.blocks_of): on blank lines, a fenced block whole.
function blocksOf(text){
  const out=[];let cur=[],fence='';
  for(const line of String(text==null?'':text).split('\n')){
    const s=line.replace(/^\s+/,'');
    if(fence){cur.push(line);if(s.startsWith(fence))fence='';continue;}
    if(s.startsWith('```')||s.startsWith('~~~')){fence=s.slice(0,3);cur.push(line);continue;}
    if(!line.trim()){if(cur.length){out.push(cur.join('\n'));cur=[];}}
    else cur.push(line);
  }
  if(cur.length)out.push(cur.join('\n'));
  return out;
}

// The paths he opened lately, newest first, each once, at most `max`.
function rememberPath(list,path,max){
  return [path,...(Array.isArray(list)?list:[]).filter(p=>typeof p==='string'&&p!==path)].slice(0,max||12);
}

// A document's soft line breaks, joined (Suda draws each line of a message as a line of its own; a note cut at
// 120 characters would read ragged): a line that goes on a paragraph or a list item joins the line before it. A
// line that starts something (a heading, an item, a quote, a table row, a fence, a rule, a tag) stands alone, and
// so does the line after a heading, a quote, a row, a rule, a fence or a hard break (two spaces or a backslash).
// Fenced code is left as it is.
const STARTS=/^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|\||```|~~~|(?:[-*_=]\s*){3,}$|<)/;
const STOPS=/(?:\s{2}|\\)$|^\s*(?:#{1,6}\s|>|\||```|~~~|(?:[-*_=]\s*){3,}$|<)/;
function joinSoftBreaks(block){
  const out=[];let fence='';
  for(const line of String(block==null?'':block).split('\n')){
    const s=line.replace(/^\s+/,'');
    if(fence){out.push(line);if(s.startsWith(fence))fence='';continue;}
    if(s.startsWith('```')||s.startsWith('~~~')){fence=s.slice(0,3);out.push(line);continue;}
    const prev=out.length?out[out.length-1]:null;
    if(prev!==null&&prev.trim()&&line.trim()&&!STARTS.test(line)&&!STOPS.test(prev))out[out.length-1]=prev.replace(/\s+$/,'')+' '+s.trim();
    else out.push(line);
  }
  return out.join('\n');
}

// Pictures in a note (suda-fixes task 45): `![alt](path)` and a README's `<img src="path" alt="...">`, by a path
// relative to the note's folder (or ~/..., or absolute), become a link to the viewer's own picture address, which the
// page then draws as the picture. A picture on the web is not fetched (the page loads nothing from elsewhere): it
// stays a link to it. Code is left as it is. The label never holds "]" (Suda's markdown keeps it text).
const PICTURE=/\.(?:png|jpe?g|gif|webp|avif|svg)$/i;
function rewriteImages(text,dir,base){
  const enc=p=>encodeURIComponent(p).replace(/[()'!*]/g,c=>'%'+c.charCodeAt(0).toString(16).toUpperCase());
  const one=(alt,target,width)=>{
    const clean=String(alt||'').replace(/[\[\]\n]/g,' ').trim();
    if(/^https?:/i.test(target))return '['+(clean||target)+']('+target+')';
    if(!PICTURE.test(target.split(/[?#]/)[0]))return null;
    const path=resolveRel(dir,target.split(/[?#]/)[0]);
    if(!path)return null;
    const w=/^\d{1,4}$/.test(String(width||''))&&+width>0&&+width<=2000?'&w='+(+width):'';
    return '['+(clean||path.split('/').pop())+']('+base+'api/asset?path='+enc(path)+'&img=1'+w+')';
  };
  // an attribute by its whole name (src is not data-src), quoted or not
  const attr=(attrs,name)=>{const m=new RegExp('(?:^|\\s)'+name+'\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\'|([^\\s"\'>]+))','i').exec(attrs);return m?(m[1]??m[2]??m[3]):null;};
  // a whole tag: its name and attributes, nothing running past its own ">"
  const TAG='<\\/?(?:p|div|center|picture|a|span)(?:\\s+[\\w:-]+(?:\\s*=\\s*(?:"[^"]*"|\'[^\']*\'|[^\\s"\'>]+))?)*\\s*\\/?>|<br\\s*\\/?>';
  const IMG='<img(?:\\s+[\\w:-]+(?:\\s*=\\s*(?:"[^"]*"|\'[^\']*\'|[^\\s"\'>]+))?)*\\s*\\/?>';
  const onlyTags=new RegExp('^\\s*(?:(?:'+TAG+'|'+IMG+')\\s*)+$','i'),wrapper=new RegExp(TAG,'gi'),img=new RegExp(IMG,'gi');
  return outsideCode(text,part=>{
    const pictured=/<img\b/i.test(part);
    return part.split('\n').flatMap(line=>{
    // the tags READMEs wrap a picture in (centred paragraph, a link, a break) go, in a part that has a picture, on a
    // line that holds only whole tags (a line of words keeps every character); a line left empty goes with them
    if(pictured&&onlyTags.test(line)){line=line.replace(wrapper,'').trim();if(!line)return [];}
    return [line.replace(img,tag=>{
      const attrs=tag.slice(4).replace(/\/?>$/,''),src=attr(attrs,'src');
      if(!src)return tag;
      const got=one(attr(attrs,'alt')||'',src.trim(),attr(attrs,'width')||'');
      return got===null?tag:got;
    }).replace(/!\[([^\]\n]{0,300})\]\(([^)\s]+)(?:\s+"[^"\n]*")?\)/g,(all,alt,target)=>{const got=one(alt,target);return got===null?all:got;})];
    }).join('\n');
  });
}

// codeIsland() and codePieces() live in Suda's pure section (suda-pure.js, made from suda.html by sync.py): one
// function for both pages, so the two cannot drift (suda-fixes 51).

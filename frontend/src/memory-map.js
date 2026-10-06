// Deterministic world coordinates; filtering, resizing and opening the pane do not rearrange nodes.
export function cloudLayout(items) {
  const placed=[];
  for (const item of items) {
    let hash=2166136261;
    for(const c of item.id) hash=Math.imul(hash^c.charCodeAt(0),16777619)>>>0;
    const width=190, height=132;
    let x=0,y=0;
    for(let attempt=0;attempt<2000;attempt++) {
      const angle=(hash%628)/100+attempt*2.399963;
      const radius=80+Math.sqrt(attempt)*65;
      x=Math.round(Math.cos(angle)*radius*1.3);y=Math.round(Math.sin(angle)*radius*.85);
      if(placed.every(p=>Math.abs(x-p.x)>width+28||Math.abs(y-p.y)>height+28))break;
    }
    placed.push({id:item.id,x,y,width,height});
  }
  if(!placed.length)return [];
  const minX=Math.min(...placed.map(p=>p.x-p.width/2)),minY=Math.min(...placed.map(p=>p.y-p.height/2));
  return placed.map(p=>({...p,x:p.x-minX+40,y:p.y-minY+40}));
}
export function createMemoryMap(viewport,world) {
  let scale=1,x=0,y=0,drag=null,ignoreClick=false;
  const saved=new Map();let key='',bounds={width:600,height:460};
  const paint=()=>{world.style.transform=`translate(${x}px,${y}px) scale(${scale})`;saved.set(key,{scale,x,y});};
  function fit(){scale=Math.min(1,(viewport.clientWidth-32)/bounds.width,(viewport.clientHeight-32)/bounds.height);x=(viewport.clientWidth-bounds.width*scale)/2;y=(viewport.clientHeight-bounds.height*scale)/2;paint();}
  function zoom(delta){const next=Math.max(.25,Math.min(2,scale*delta)),cx=viewport.clientWidth/2,cy=viewport.clientHeight/2;x=cx-(cx-x)*next/scale;y=cy-(cy-y)*next/scale;scale=next;paint();}
  viewport.onpointerdown=e=>{if(e.target.closest('button,input')||e.button!==0)return;drag={x:e.clientX,y:e.clientY,ox:x,oy:y};viewport.setPointerCapture(e.pointerId);};
  viewport.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4)ignoreClick=true;x=drag.ox+dx;y=drag.oy+dy;paint();};
  viewport.onpointerup=viewport.onpointercancel=()=>{drag=null;setTimeout(()=>ignoreClick=false,0);};
  viewport.addEventListener('click',e=>{if(ignoreClick){e.preventDefault();e.stopPropagation();}},true);
  viewport.onkeydown=e=>{if(e.target!==viewport)return;const moves={ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]};if(moves[e.key]){e.preventDefault();x+=moves[e.key][0];y+=moves[e.key][1];paint();}};
  // Tabbing to an off-screen cloud brings it into view without losing keyboard access.
  world.addEventListener('focusin',e=>{const b=e.target.closest('[data-cloud]');if(!b)return;const r=b.getBoundingClientRect(),v=viewport.getBoundingClientRect();if(r.left<v.left||r.right>v.right||r.top<v.top||r.bottom>v.bottom){x=viewport.clientWidth/2-parseFloat(b.style.left)*scale;y=viewport.clientHeight/2-parseFloat(b.style.top)*scale;paint();}});
  let lastWidth=viewport.clientWidth,lastHeight=viewport.clientHeight;
  const resize=new ResizeObserver(()=>{const w=viewport.clientWidth,h=viewport.clientHeight;if(!w||!h)return;if(!saved.has(key))fit();else if(lastWidth&&lastHeight){x+=(w-lastWidth)/2;y+=(h-lastHeight)/2;paint();}lastWidth=w;lastHeight=h;});resize.observe(viewport);
  return {set(items,nextKey){key=nextKey;bounds={width:Math.max(300,...items.map(p=>p.x+p.width/2+40)),height:Math.max(260,...items.map(p=>p.y+p.height/2+40))};const state=saved.get(key);if(state){({scale,x,y}=state);paint();}else {fit();if(scale<.8&&items.length){scale=.8;x=viewport.clientWidth/2-items[0].x*scale;y=viewport.clientHeight/2-items[0].y*scale;paint();}}},fit,zoom,dispose(){resize.disconnect();}};
}

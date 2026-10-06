import test from 'node:test';
import assert from 'node:assert/strict';
import {cloudLayout} from '../src/memory-map.js';
for(const count of [1,4,12,30,100])test(`Stable collision-free layout for ${count} nodes`,()=>{
 const items=Array.from({length:count},(_,i)=>({id:`project-${i}`}));
 const nodes=cloudLayout(items);assert.deepEqual(nodes,cloudLayout(items));
 for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
  const a=nodes[i],b=nodes[j];assert.ok(Math.abs(a.x-b.x)>190+20||Math.abs(a.y-b.y)>132+20,`Overlap ${i}, ${j}`);
 }
 assert.ok(new Set(nodes.map(p=>p.x)).size>=Math.ceil(count/2));
});

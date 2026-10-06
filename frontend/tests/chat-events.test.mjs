import test from 'node:test';
import assert from 'node:assert/strict';
import {readChatEvents} from '../src/chat-ui.js';
function response(text){const bytes=new TextEncoder().encode(text);return new Response(new ReadableStream({start(c){for(const b of bytes)c.enqueue(new Uint8Array([b]));c.close();}}));}
test('Split UTF-8 events expose status and final validated result',async()=>{const statuses=[];const r=await readChatEvents(response('event: status\ndata: {"message":"Preparing…"}\n\n: keepalive\n\nevent: result\ndata: {"turn":{"status":"completed"}}\n\n'),s=>statuses.push(s));assert.deepEqual(statuses,['Preparing…']);assert.equal(r.turn.status,'completed');});
test('A missing final event is an interrupted request, not success',async()=>{await assert.rejects(()=>readChatEvents(response('event: status\ndata: {"message":"Working"}\n\n'),()=>{}),/interrupted/);});
test('Conflict events retain HTTP semantics for draft recovery',async()=>{await assert.rejects(()=>readChatEvents(response('event: error\ndata: {"message":"Reload","status":409}\n\n'),()=>{}),e=>e.status===409);});

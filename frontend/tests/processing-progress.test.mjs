import { test } from 'node:test';
import assert from 'node:assert/strict';
import { processingSteps } from '../src/processing-progress.js';

test('audio shows real current stage and saved checkpoints', () => {
  const rows = processingSteps({input_type:'audio',status:'processing',completed_stages:['transcription','translation'],job:{stage:'summary'}});
  assert.deepEqual(rows.map(s=>s.state), ['completed','completed','running','pending']);
});
test('new queued audio does not pretend transcription has started', () => {
  assert.equal(processingSteps({input_type:'audio',status:'queued',job:{stage:'transcribe',attempts:0}})[0].state,'pending');
});
test('provider polling is waiting, and retry preserves completed stages', () => {
  assert.equal(processingSteps({input_type:'audio',status:'queued',job:{stage:'transcription',attempts:2}})[0].state,'waiting');
  const rows=processingSteps({status:'queued',completed_stages:['translation','summary'],job:{stage:'extraction',attempts:2}});
  assert.deepEqual(rows.map(s=>s.state),['completed','completed','waiting']);
});
test('text skips transcription; document includes parsing', () => {
  assert.deepEqual(processingSteps({input_type:'text'}).map(s=>s.id),['translation','summary','extraction']);
  assert.equal(processingSteps({input_type:'document',original_text:'Extracted text'})[0].state,'completed');
});
test('failure marks only reported stage and keeps completed work', () => {
  assert.deepEqual(processingSteps({status:'failed',completed_stages:['translation','summary'],job:{stage:'extraction'}}).map(s=>s.state),['completed','completed','failed']);
  assert.ok(processingSteps({status:'failed',job:{stage:'normalize'}}).every(s=>s.state==='pending'));
});
test('legacy ready entries show completion even without checkpoints', () => {
  assert.ok(processingSteps({input_type:'audio',status:'ready'}).every(s=>s.state==='completed'));
});

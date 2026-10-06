const labels = {
  transcription: ['Transcribing the recording', 'Recording transcribed'],
  parse: ['Reading the document', 'Document read'],
  translation: ['Translating to English', 'English translation ready'],
  summary: ['Generating summary', 'Summary ready'],
  extraction: ['Creating memories, decisions & actions', 'Memories, decisions & actions ready'],
};

export function processingSteps(entry) {
  const tasks = [
    ...(entry.input_type === 'audio' ? ['transcription'] : entry.input_type === 'document' ? ['parse'] : []),
    'translation', 'summary', 'extraction',
  ];
  const completed = new Set(entry.completed_stages || []);
  if (entry.input_type === 'document' && entry.original_text?.trim()) completed.add('parse');
  const current = entry.job?.stage === 'transcribe' ? 'transcription' : entry.job?.stage;
  return tasks.map(id => {
    let state = entry.status === 'ready' || completed.has(id) ? 'completed' : 'pending';
    if (entry.status === 'failed' && current === id) state = 'failed';
    else if (state !== 'completed' && current === id) {
      if (entry.status === 'processing') state = 'running';
      else if (entry.status === 'queued' && entry.job?.attempts > 0) state = 'waiting';
    }
    return { id, state, label: labels[id][state === 'completed' ? 1 : 0] };
  });
}

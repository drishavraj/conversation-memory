import math
import os
import re
import httpx
from sqlalchemy import select, update
from .models import SearchRecord, Entry, Knowledge
from .knowledge_api import serialize
from .provider import ProviderError

DIMENSIONS=768

def normalize(vector):
    if len(vector)!=DIMENSIONS or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in vector):
        raise ProviderError('embedding_vector_invalid')
    length=math.sqrt(sum(v*v for v in vector))
    if not length:raise ProviderError('embedding_vector_invalid')
    return [v/length for v in vector]

class GeminiEmbeddings:
    def __init__(self,key=None,model=None,transport=None):
        self.key=key or os.environ.get('GEMINI_API_KEY')
        self.model=model or os.environ.get('EMBEDDING_MODEL')
        if not self.key or not self.model:raise ProviderError('embedding_not_configured')
        if not re.fullmatch(r'[a-zA-Z0-9._-]+',self.model):raise ProviderError('embedding_model_invalid')
        self.transport=transport
    def embed(self,text):
        with httpx.Client(timeout=60,transport=self.transport) as client:
            response=client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent',headers={'x-goog-api-key':self.key},json={'content':{'parts':[{'text':text}]},'outputDimensionality':DIMENSIONS})
        if response.status_code!=200:raise ProviderError(f'embedding_http_{response.status_code}')
        return normalize(response.json().get('embedding',{}).get('values',[]))

def chunks(text,size=1800,overlap=200):
    for start in range(0,len(text),size-overlap):
        end=min(start+size,len(text))
        if text[start:end].strip():yield start,end,text[start:end]
        if end==len(text):break

def index_one(sessions,provider):
    # One resumable vector per invocation, avoiding retranscription or unbounded worker jobs.
    with sessions() as db:
        entry=db.scalar(select(Entry).where(Entry.status=='ready',Entry.index_status=='pending').order_by(Entry.uploaded_at,Entry.id).limit(1))
        if not entry:return False
        entry_id=entry.id
        existing={r.id:r for r in db.scalars(select(SearchRecord).where(SearchRecord.entry_id==entry_id))}
        targets=[]
        for k in db.scalars(select(Knowledge).where(Knowledge.entry_id==entry_id,Knowledge.status=='active').order_by(Knowledge.id)):
            targets.append((f'knowledge:{k.id}',k.id,k.version,k.text,None,None))
        for n,(start,end,text) in enumerate(chunks(entry.original_text)):
            targets.append((f'chunk:{entry_id}:{n}',None,None,text,start,end))
        target=next((t for t in targets if t[0] not in existing or existing[t[0]].model!=provider.model or existing[t[0]].knowledge_version!=t[2] or existing[t[0]].text!=t[3]),None)
        if target is None:
            entry.index_status='ready';entry.index_error=None;db.commit();return True
    try:
        vector=normalize(provider.embed(target[3]))
        with sessions() as db:
            current=db.get(Entry,entry_id)
            if current.status!='ready':return True
            if target[1]:
                k=db.get(Knowledge,target[1])
                if not k or k.status!='active' or k.version!=target[2]:return True
            row=db.get(SearchRecord,target[0])
            if row is None:
                row=SearchRecord(id=target[0],entry_id=entry_id);db.add(row)
            row.knowledge_id,row.knowledge_version,row.text,row.start,row.end,row.model,row.vector=target[1],target[2],target[3],target[4],target[5],provider.model,vector
            current.index_error=None
            db.commit()
    except Exception as error:
        code=error.code if isinstance(error,ProviderError) else 'embedding_failed'
        with sessions() as db:
            entry=db.get(Entry,entry_id);entry.index_status='failed';entry.index_error=code;db.commit()
        print('Indexing failed: '+code,flush=True)
    return True

def semantic_records(session,question,theme,provider,limit=12):
    query=normalize(provider.embed(question))
    matches=[]
    # Exact cosine ranking in Python for personal-scale collections. No pgvector extension needed.
    statement=select(SearchRecord,Entry).join(Entry,Entry.id==SearchRecord.entry_id).where(SearchRecord.model==provider.model,Entry.status=='ready')
    threshold=float(os.environ.get('SEMANTIC_MIN_SIMILARITY','0.6'))
    if not 0<=threshold<=1:raise ProviderError('semantic_threshold_invalid')
    for record,entry in session.execute(statement):
        if record.knowledge_id:
            k=session.get(Knowledge,record.knowledge_id)
            if not k or k.status!='active' or k.version!=record.knowledge_version:continue
            if theme and k.theme_id!=theme:continue
            result={**serialize(k),'source_title':entry.title,'event_at':entry.event_at.isoformat() if entry.event_at else None,'source_url':f'/api/entries/{entry.id}'}
        else:
            # A full passage can mix themes: keep it out of scoped search whenever
            # extracted items reveal mixed or unknown classification.
            if theme:
                if entry.theme_id!=theme:continue
                item_themes=list(session.scalars(select(Knowledge.theme_id).where(Knowledge.entry_id==entry.id)))
                if any(value!=theme for value in item_themes):continue
            result={'id':record.id,'kind':'transcript','text':record.text,'evidence':record.text,'evidence_start':record.start,'evidence_end':record.end,'theme_id':entry.theme_id,'origin':'original_source','source_entry_id':entry.id,'source_title':entry.title,'event_at':entry.event_at.isoformat() if entry.event_at else None,'source_url':f'/api/entries/{entry.id}'}
        if len(record.vector)!=DIMENSIONS:continue
        score=sum(a*b for a,b in zip(query,record.vector))
        if score>=threshold:matches.append((score,result))
    matches.sort(key=lambda x:x[0],reverse=True)
    return [{**record,'similarity':round(score,4)} for score,record in matches[:limit]]

def hybrid(keyword,semantic,limit=12):
    scores={};records={}
    for group in (keyword,semantic):
        for rank,record in enumerate(group,1):
            id=record['id'];records[id]={**records.get(id,{}),**record};scores[id]=scores.get(id,0)+1/(60+rank)
    return [records[id] for id in sorted(scores,key=scores.get,reverse=True)[:limit]]

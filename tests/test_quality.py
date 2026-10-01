from datetime import datetime, timezone
from test_api import client, headers
from app.extraction import Extraction, validate_evidence

def test_duplicate_same_event_different_offset(client,headers):
    payload={'text':'Exact conversation', 'title':'First', 'theme_id':'office', 'event_at':'2026-10-01T12:00:00+05:30'}
    first=client.post('/api/entries/text',json=payload,headers=headers)
    assert first.status_code==201
    payload.update(title='Renamed', event_at='2026-10-01T06:30:00Z')
    second=client.post('/api/entries/text',json=payload,headers=headers)
    assert second.status_code==200 and second.json()['duplicate']
    assert second.json()['id']==first.json()['id']
    assert len(client.get('/api/entries',headers=headers).json())==1
    payload['theme_id']='personal'
    assert client.post('/api/entries/text',json=payload,headers=headers).status_code==201

def test_distinct_events_preserved(client,headers):
    for date in ['2026-10-01T12:00:00Z','2026-10-02T12:00:00Z']:
        assert client.post('/api/entries/text',json={'text':'Same words', 'event_at':date},headers=headers).status_code==201

def test_proposal_and_date_guards():
    result=Extraction.model_validate({'english_text':'Maybe Wednesday UAT. I will send tomorrow.', 'summary':'Tentative UAT and document commitment.', 'items':[{'kind':'action','text':'Maybe UAT Wednesday','evidence':'Maybe Wednesday UAT.','certainty':'tentative','owner':None,'due_date':'2026-10-07','date_basis':'inferred'},{'kind':'action','text':'Send document','evidence':'I will send tomorrow.','certainty':'explicit','owner':'Rishav','due_date':'2026-10-02','date_basis':'relative'}]})
    validate_evidence(result,'Maybe Wednesday UAT. I will send tomorrow.',datetime(2026,10,1,tzinfo=timezone.utc))
    assert result.items[0].kind=='decision'
    assert result.items[0].due_date is None
    assert result.items[0].date_basis=='inferred'
    assert str(result.items[1].due_date)=='2026-10-02'

def test_upgrade_preserves_old_duplicates(tmp_path,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from app.database import make_engine
    from sqlalchemy import text
    url=f'sqlite:///{tmp_path}/legacy.db'
    monkeypatch.setenv('DATABASE_URL',url)
    config=Config('alembic.ini')
    command.upgrade(config,'0003')
    engine=make_engine(url)
    with engine.begin() as db:
        for id in ['old-1','old-2']:
            db.execute(text("INSERT INTO entries(id,title,original_text,theme_id,event_at,uploaded_at,status) VALUES(:id,'Legacy','same','office',NULL,'2026-10-01 00:00:00','ready')"),{'id':id})
    command.upgrade(config,'head')
    with engine.connect() as db:
        rows=db.execute(text('SELECT fingerprint FROM entries')).all()
        assert len(rows)==2
        assert sum(row[0] is not None for row in rows)==1
    engine.dispose()

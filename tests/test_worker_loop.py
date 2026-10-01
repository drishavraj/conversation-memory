from threading import Event
from test_api import client, headers
from test_processing import Fake
from app.database import session_factory
from app.worker import run_forever

class StopAfterTwo(Fake):
    def __init__(self,stop):
        super().__init__();self.stop=stop
    def extract(self,*args):
        result=super().extract(*args)
        if self.calls==2:self.stop.set()
        return result

def test_loop_drains_queue(client,headers):
    source='Rahul: Maybe Wednesday UAT. Rishav: I will send the API document.'
    ids=[]
    for day in [1,2]:
        data=client.post('/api/entries/text',headers=headers,json={'text':source,'event_at':f'2026-10-0{day}T12:00:00Z'}).json()
        ids.append(data['id'])
    stop=Event();provider=StopAfterTwo(stop)
    run_forever(session_factory(client.app.state.engine),provider,stop,1)
    assert provider.calls==2
    for id in ids:
        assert client.get('/api/entries/'+id,headers=headers).json()['status']=='ready'

def test_loop_idle_and_stop(monkeypatch):
    waits=[]
    class Stop:
        done=False
        def is_set(self):return self.done
        def wait(self,seconds):waits.append(seconds);self.done=True
    monkeypatch.setattr('app.worker.process_one',lambda *_:False)
    run_forever(None,None,Stop(),5)
    assert waits==[5]

def test_loop_recovers_from_database_failure_without_leaking(monkeypatch,capsys):
    class Stop:
        done=False
        def is_set(self):return self.done
        def wait(self,seconds):self.done=True
    def broken(*_):raise RuntimeError('SECRET_DATABASE_URL')
    monkeypatch.setattr('app.worker.process_one',broken)
    run_forever(None,None,Stop(),1)
    output=capsys.readouterr().out
    assert 'SECRET' not in output
    assert 'database_or_processing_error' in output

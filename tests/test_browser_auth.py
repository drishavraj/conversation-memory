import time
from types import SimpleNamespace
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from app.browser_auth import BrowserAuth
from test_api import client, TOKEN

@pytest.fixture
def auth(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL','https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_test')
    monkeypatch.setenv('AUTH_OWNER_USER_ID','11111111-1111-4111-8111-111111111111')
    verifier=BrowserAuth()
    key=ec.generate_private_key(ec.SECP256R1())
    verifier.client=SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=key.public_key()))
    return verifier,key

def make_token(key, **updates):
    claims={'iss':'https://example.supabase.co/auth/v1','aud':'authenticated','iat':int(time.time()),'exp':int(time.time())+300,'sub':'11111111-1111-4111-8111-111111111111','aal':'aal2','role':'authenticated'}
    claims.update(updates)
    return jwt.encode(claims,key,algorithm='ES256')

def test_mfa_owner_signature_and_expiry(auth):
    verifier,key=auth
    assert verifier.verify(make_token(key))['sub']=='11111111-1111-4111-8111-111111111111'
    for update,code in [({'aal':'aal1'},403),({'role':'service_role'},403),({'exp':int(time.time())-30},401),({'iss':'https://evil.example/auth/v1'},401),({'aud':'other'},401)]:
        with pytest.raises(HTTPException) as exc:verifier.verify(make_token(key,**update))
        assert exc.value.status_code==code
    with pytest.raises(HTTPException) as exc:verifier.verify(make_token(ec.generate_private_key(ec.SECP256R1())))
    assert exc.value.status_code==401
    with pytest.raises(HTTPException):verifier.verify('not-a-jwt')

def test_no_auth_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv('SUPABASE_URL',raising=False)
    assert not BrowserAuth().configured
    with pytest.raises(HTTPException):BrowserAuth().verify('anything')

def test_ui_does_not_publish_owner_token(client):
    config=client.get('/api/ui-config')
    assert config.status_code==200
    assert TOKEN not in config.text
    assert client.get('/').status_code==200
    assert client.get('/api/session').status_code==401
    assert client.get('/api/session',headers={'Authorization':'Bearer '+TOKEN}).status_code==200

def test_disabling_legacy_token(client,monkeypatch):
    monkeypatch.setenv('ALLOW_OWNER_API_TOKEN','false')
    from app.main import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app('sqlite://',TOKEN)) as locked:
        assert locked.get('/api/session',headers={'Authorization':'Bearer '+TOKEN}).status_code==401

def test_api_enforces_mfa_and_single_owner(client,auth,monkeypatch):
    verifier,key=auth
    monkeypatch.setattr('app.main.BrowserAuth',lambda:verifier)
    monkeypatch.setenv('ALLOW_OWNER_API_TOKEN','false')
    from app.main import create_app
    from fastapi.testclient import TestClient
    with TestClient(create_app(str(client.app.state.engine.url),TOKEN)) as browser:
        for token,expected in [(make_token(key),200),(make_token(key,aal='aal1'),403),(make_token(key,sub='another-owner'),403),(TOKEN,401)]:
            assert browser.get('/api/entries',headers={'Authorization':'Bearer '+token}).status_code==expected
        assert browser.get('/api/ui-config').headers['cache-control']=='no-store'
        assert TOKEN not in browser.get('/api/ui-config').text

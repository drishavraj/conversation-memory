"""Single-owner browser authentication. Provider signatures and MFA are checked server-side."""
import os
from urllib.parse import urlparse
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException

class BrowserAuth:
    def __init__(self):
        self.url = os.environ.get('SUPABASE_URL', '').rstrip('/')
        self.key = os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')
        if self.key.startswith('sb_secret_'):
            raise RuntimeError('Use the Supabase publishable key, never a secret key')
        if self.key.count('.') == 2:
            try:
                if jwt.decode(self.key, options={'verify_signature':False}).get('role') != 'anon':
                    raise RuntimeError('Use the Supabase publishable or legacy anon key')
            except jwt.PyJWTError:
                raise RuntimeError('Invalid Supabase public key')
        self.owner = os.environ.get('AUTH_OWNER_USER_ID', '')
        self.configured = bool(self.url and self.key and self.owner)
        self.client = None
        if self.configured:
            parsed = urlparse(self.url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
                raise RuntimeError('SUPABASE_URL must be an HTTPS origin')
            self.client = PyJWKClient(self.url + '/auth/v1/.well-known/jwks.json', timeout=5)

    def verify(self, token):
        if not self.configured:
            raise HTTPException(401, 'Authentication required')
        try:
            key = self.client.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=['ES256', 'RS256'],
                audience='authenticated', issuer=self.url + '/auth/v1',
                options={'require':['exp','iat','iss','aud','sub','aal']})
        except jwt.PyJWKClientConnectionError:
            raise HTTPException(503, 'Login verification temporarily unavailable')
        except (jwt.PyJWTError, ValueError):
            raise HTTPException(401, 'Session invalid or expired')
        if claims.get('sub') != self.owner or claims.get('role') != 'authenticated':
            raise HTTPException(403, 'This account does not have access')
        if claims.get('aal') != 'aal2':
            raise HTTPException(403, 'Authenticator verification required')
        return claims

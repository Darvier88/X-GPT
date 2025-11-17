# main.py - API con FastAPI (FLUJO OAUTH CORRECTO)
"""
API REST para análisis de tweets con autenticación OAuth 2.0
Flujo: Login → Obtener userName del usuario autenticado → Operar con sus tweets
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import urlencode
import uuid
import time
import requests
import base64
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Importar solo las funciones helper de X_login (NO initiate_login_with_scope_testing)
from X.X_login import (
    generate_code_verifier,
    generate_code_challenge,
    AUTH_URL,
    TOKEN_URL,
    USER_INFO_URL,
    REQUESTED_SCOPES
)

from config import get_oauth2_credentials
from X.search_tweets import fetch_user_tweets, save_tweets_to_file
from GPT.risk_classifier_only_text import classify_risk_text_only, load_tweets_from_json
from X.deleate_tweets_rts import delete_tweets_batch

# Credenciales OAuth
oauth_creds = get_oauth2_credentials()
CLIENT_ID = oauth_creds['client_id']
CLIENT_SECRET = oauth_creds['client_secret']
REDIRECT_URI = oauth_creds['redirect_uri']  # Debe ser tu URL de API: http://localhost:8000/api/auth/callback
print(f"REDIRECT_URI cargado: {REDIRECT_URI}")

# ============================================================================
# FastAPI Setup
# ============================================================================

app = FastAPI(
    title="Twitter Analysis API",
    description="API con OAuth 2.0 para analizar tweets del usuario autenticado",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Almacenamiento en memoria
# ============================================================================

# Sesiones OAuth temporales (en producción usar Redis/DB)
oauth_sessions: Dict[str, Dict[str, Any]] = {}

# Jobs en background
background_jobs: Dict[str, Dict[str, Any]] = {}

# ============================================================================
# Modelos Pydantic
# ============================================================================

class LoginResponse(BaseModel):
    success: bool
    authorization_url: str
    state: str
    message: str = "Visita la URL para autorizar la aplicación"

class TokenResponse(BaseModel):
    success: bool
    access_token: str
    refresh_token: Optional[str] = None
    expires_in: int
    user: Dict[str, Any]

class UserInfoResponse(BaseModel):
    id: str
    username: str
    name: str
    followers_count: int
    following_count: int
    tweet_count: int
    verified: bool

class SearchRequest(BaseModel):
    max_tweets: Optional[int] = Field(None, description="Límite de tweets (None = todos)")
    save_to_file: bool = Field(True, description="Guardar en JSON")

class ClassifyRequest(BaseModel):
    tweets: Optional[List[str]] = Field(None, description="Lista de tweets directa")
    json_path: Optional[str] = Field(None, description="Path a JSON de tweets")
    max_tweets: Optional[int] = Field(None, description="Límite de tweets a clasificar")

class DeleteRequest(BaseModel):
    json_path: str
    delete_retweets: bool = True
    delete_originals: bool = True
    delay_seconds: float = 1.0

# ============================================================================
# Funciones Helper OAuth
# ============================================================================

def create_oauth_session() -> tuple:
    """Crea una nueva sesión OAuth con PKCE"""
    session_id = str(uuid.uuid4())
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = str(uuid.uuid4())
    
    oauth_sessions[session_id] = {
        'code_verifier': code_verifier,
        'code_challenge': code_challenge,
        'state': state,
        'created_at': datetime.now(),
        'access_token': None,
        'refresh_token': None,
        'user': None
    }
    
    return session_id, code_challenge, state

def exchange_code_for_token(session_id: str, code: str) -> Dict[str, Any]:
    """Intercambia authorization code por access token"""
    session = oauth_sessions.get(session_id)
    if not session:
        return {'success': False, 'error': 'Sesión no encontrada'}
    
    # Preparar request de token
    auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_b64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
    
    data = {
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': REDIRECT_URI,
        'code_verifier': session['code_verifier'],
        'client_id': CLIENT_ID
    }
    
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': f'Basic {auth_b64}'
    }
    
    try:
        response = requests.post(TOKEN_URL, data=data, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return {
                'success': False,
                'error': f"Error {response.status_code}: {response.text}"
            }
        
        tokens = response.json()
        
        # Guardar tokens en sesión
        session['access_token'] = tokens['access_token']
        session['refresh_token'] = tokens.get('refresh_token')
        session['expires_in'] = tokens.get('expires_in', 7200)
        session['expires_at'] = datetime.now() + timedelta(seconds=tokens.get('expires_in', 7200))
        
        # Obtener info del usuario
        user_info = get_user_info(tokens['access_token'])
        if user_info['success']:
            session['user'] = user_info['user']
        
        return {
            'success': True,
            'access_token': tokens['access_token'],
            'refresh_token': tokens.get('refresh_token'),
            'expires_in': tokens.get('expires_in', 7200),
            'user': session.get('user')
        }
    
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_user_info(access_token: str) -> Dict[str, Any]:
    """Obtiene información del usuario autenticado"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'user.fields': 'id,username,name,public_metrics,verified'}
        
        response = requests.get(USER_INFO_URL, headers=headers, params=params, timeout=10)
        
        if response.status_code != 200:
            return {'success': False, 'error': f"Error {response.status_code}"}
        
        data = response.json().get('data', {})
        metrics = data.get('public_metrics', {})
        
        return {
            'success': True,
            'user': {
                'id': data.get('id'),
                'username': data.get('username'),
                'name': data.get('name'),
                'followers_count': metrics.get('followers_count', 0),
                'following_count': metrics.get('following_count', 0),
                'tweet_count': metrics.get('tweet_count', 0),
                'verified': data.get('verified', False)
            }
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Obtiene y valida una sesión"""
    session = oauth_sessions.get(session_id)
    if not session:
        return None
    
    # Verificar expiración
    if session.get('expires_at'):
        if datetime.now() >= session['expires_at']:
            return None
    
    return session

# ============================================================================
# API 1: AUTENTICACIÓN OAUTH
# ============================================================================

@app.get("/api/auth/login", response_model=LoginResponse)
async def login():
    """
    Paso 1: Inicia el proceso de login OAuth 2.0
    
    Retorna la URL de autorización que el usuario debe visitar en su navegador.
    El frontend debe redirigir al usuario a esta URL.
    """
    session_id, code_challenge, state = create_oauth_session()
    
    # Construir URL de autorización
    auth_params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': ' '.join(REQUESTED_SCOPES),
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256'
    }
    
    authorization_url = f"{AUTH_URL}?{urlencode(auth_params)}"
    
    return LoginResponse(
        success=True,
        authorization_url=authorization_url,
        state=state,
        message=f"Session ID: {session_id}. Guarda este ID para el callback."
    )

@app.get("/api/auth/callback")
async def auth_callback(code: str, state: str):
    """
    Paso 2: Callback de Twitter después de autorización
    
    Twitter redirige aquí con el authorization_code.
    Este endpoint intercambia el code por access_token.
    """
    # Buscar sesión por state
    session_id = None
    for sid, session in oauth_sessions.items():
        if session.get('state') == state:
            session_id = sid
            break
    
    if not session_id:
        raise HTTPException(status_code=400, detail="State inválido o sesión expirada")
    
    # Intercambiar code por token
    result = exchange_code_for_token(session_id, code)
    
    if not result['success']:
        raise HTTPException(status_code=400, detail=result['error'])
    
    # Retornar HTML con el session_id para que el frontend lo capture
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Autenticación Exitosa</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                margin: 0;
            }}
            .container {{
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                text-align: center;
                max-width: 500px;
            }}
            h1 {{ color: #1DA1F2; }}
            .session-id {{
                background: #f5f5f5;
                padding: 15px;
                border-radius: 5px;
                font-family: monospace;
                word-break: break-all;
                margin: 20px 0;
            }}
            .user-info {{
                margin: 20px 0;
                padding: 15px;
                background: #e8f5fe;
                border-radius: 5px;
            }}
            button {{
                background: #1DA1F2;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
            }}
            button:hover {{ background: #1a8cd8; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✅ ¡Autenticación Exitosa!</h1>
            <div class="user-info">
                <p><strong>Usuario:</strong> @{result['user']['username']}</p>
                <p><strong>Nombre:</strong> {result['user']['name']}</p>
            </div>
            <p>Tu Session ID:</p>
            <div class="session-id" id="sessionId">{session_id}</div>
            <button onclick="copySessionId()">📋 Copiar Session ID</button>
            <p style="margin-top: 20px; color: #666; font-size: 14px;">
                Guarda este Session ID para hacer requests a la API.
            </p>
        </div>
        <script>
            function copySessionId() {{
                const sessionId = document.getElementById('sessionId').textContent;
                navigator.clipboard.writeText(sessionId);
                alert('Session ID copiado al portapapeles!');
            }}
            // Auto-copiar al cargar
            copySessionId();
        </script>
    </body>
    </html>
    """
    
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_content)

@app.get("/api/auth/me")
async def get_current_user(session_id: str = Query(..., description="Session ID obtenido del login")):
    """
    Obtiene información del usuario autenticado
    """
    session = get_session(session_id)
    if not session or not session.get('user'):
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    
    return {
        "success": True,
        "user": session['user'],
        "expires_at": session.get('expires_at').isoformat() if session.get('expires_at') else None
    }

# ============================================================================
# API 2: BÚSQUEDA DE TWEETS (del usuario autenticado)
# ============================================================================

@app.post("/api/tweets/search")
async def search_my_tweets(
    request: SearchRequest,
    session_id: str = Query(..., description="Session ID")
):
    """
    Busca tweets del usuario autenticado
    """
    session = get_session(session_id)
    if not session or not session.get('user'):
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    username = session['user']['username']
    
    try:
        result = fetch_user_tweets(
            username=username,
            max_tweets=request.max_tweets
        )
        
        if not result['success']:
            raise HTTPException(status_code=400, detail=result.get('error'))
        
        file_path = None
        if request.save_to_file:
            file_path = save_tweets_to_file(result)
        
        return {
            "success": True,
            "username": username,
            "stats": result.get('stats'),
            "tweets_count": len(result.get('tweets', [])),
            "execution_time": result.get('execution_time'),
            "file_path": file_path
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# API 3: CLASIFICACIÓN DE RIESGOS
# ============================================================================

@app.post("/api/risk/classify")
async def classify_risk(
    request: ClassifyRequest,
    session_id: str = Query(..., description="Session ID")
):
    """
    Clasifica riesgos de tweets
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    # Obtener tweets
    if request.json_path:
        tweets_data = load_tweets_from_json(request.json_path)
        tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
    elif request.tweets:
        tweets = request.tweets
    else:
        raise HTTPException(status_code=400, detail="Proporciona 'tweets' o 'json_path'")
    
    if request.max_tweets:
        tweets = tweets[:request.max_tweets]
    
    # Clasificar
    results = []
    stats = {
        "risk_distribution": {"low": 0, "mid": 0, "high": 0},
        "label_counts": {},
        "errors": 0
    }
    
    for i, tweet_text in enumerate(tweets, 1):
        result = classify_risk_text_only(tweet_text)
        result["tweet_id"] = i
        result["text"] = tweet_text
        results.append(result)
        
        if "error_code" not in result:
            level = result.get("risk_level", "low")
            stats["risk_distribution"][level] += 1
            for label in result.get("labels", []):
                stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1
        else:
            stats["errors"] += 1
    
    return {
        "success": True,
        "total_tweets": len(tweets),
        "results": results,
        "summary": stats
    }

# ============================================================================
# API 4: ELIMINACIÓN DE TWEETS
# ============================================================================

@app.post("/api/tweets/delete")
async def delete_my_tweets(
    request: DeleteRequest,
    session_id: str = Query(..., description="Session ID")
):
    """
    Elimina tweets del usuario autenticado
    """
    session = get_session(session_id)
    if not session or not session.get('access_token'):
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    # Cargar tweets del JSON
    import json
    try:
        with open(request.json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Archivo JSON no encontrado")
    
    tweets = data.get('tweets', [])
    user_id = session['user']['id']
    
    # Crear adapter para la sesión
    class SessionAdapter:
        def __init__(self, access_token):
            self.access_token = access_token
        
        def get_headers(self):
            return {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
    
    session_adapter = SessionAdapter(session['access_token'])
    
    # Eliminar tweets
    result = delete_tweets_batch(
        tweets=tweets,
        user_id=user_id,
        session=session_adapter,
        delete_retweets=request.delete_retweets,
        delete_originals=request.delete_originals,
        delay_seconds=request.delay_seconds,
        verbose=True
    )
    
    return result

# ============================================================================
# UTILIDADES
# ============================================================================

@app.get("/")
async def root():
    return {
        "name": "Twitter Analysis API",
        "version": "2.0.0",
        "flow": "OAuth Login → Get User → Search/Classify/Delete Tweets",
        "endpoints": {
            "login": "/api/auth/login",
            "callback": "/api/auth/callback",
            "me": "/api/auth/me",
            "search": "/api/tweets/search",
            "classify": "/api/risk/classify",
            "delete": "/api/tweets/delete",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "active_sessions": len(oauth_sessions),
        "timestamp": datetime.now().isoformat()
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*70)
    print("🚀 TWITTER ANALYSIS API - OAuth 2.0")
    print("="*70)
    print(f"\nREDIRECT_URI configurado: {REDIRECT_URI}")
    print("\n⚠️  IMPORTANTE: Configura este REDIRECT_URI en tu Twitter App:")
    print("   https://developer.x.com/en/portal/dashboard")
    print("\nDocumentación: http://localhost:8080/docs")
    print("="*70 + "\n")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=True
    )
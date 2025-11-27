# main.py - API con FastAPI + Firebase (sin almacenamiento JSON local)
"""
API REST para análisis de tweets con autenticación OAuth 2.0 y Firebase
Flujo: Login → Obtener userName del usuario autenticado → Operar con sus tweets → Guardar en Firebase
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timedelta
from urllib.parse import urlencode
import uuid
import time
import requests
import base64
import json
import asyncio
from pathlib import Path
import sys

# Firebase imports
import firebase_admin
from firebase_admin import credentials, firestore

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
from X.search_tweets import fetch_user_tweets
from GPT.risk_classifier_only_text import classify_risk_text_only
from X.deleate_tweets_rts import delete_tweets_batch
from estimacion_de_tiempo import quick_estimate_all, format_time

# ============================================================================
# Firebase Setup
# ============================================================================

# Inicializar Firebase (evitar reinicialización en reload)
db = None

def initialize_firebase():
    """Inicializa Firebase de forma segura"""
    global db
    
    try:
        # Verificar si ya está inicializado
        try:
            # Intentar obtener la app existente
            firebase_admin.get_app()
            # Si llegamos aquí, ya existe
            db = firestore.client()
            return True
        except ValueError:
            # No existe, proceder a inicializar
            pass
        
        # Buscar archivo de credenciales
        firebase_cred_files = [
            'background-checker-a0de1-firebase-adminsdk-fbsvc-5fd2e55d11.json',
            'firebase-credentials.json',
            'serviceAccountKey.json'
        ]
        
        cred_path = None
        for file in firebase_cred_files:
            if Path(file).exists():
                cred_path = file
                break
        
        if not cred_path:
            print(f"⚠️ No se encontró archivo de credenciales de Firebase")
            print(f"   Buscado: {firebase_cred_files}")
            return False
        
        # Inicializar Firebase
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print(f"✅ Firebase inicializado correctamente usando: {cred_path}")
        return True
        
    except Exception as e:
        print(f"⚠️ Error inicializando Firebase: {e}")
        return False

# Inicializar Firebase al cargar el módulo
initialize_firebase()

# Credenciales OAuth
oauth_creds = get_oauth2_credentials()
CLIENT_ID = oauth_creds['client_id']
CLIENT_SECRET = oauth_creds['client_secret']
REDIRECT_URI = oauth_creds['redirect_uri']
FRONTEND_CALLBACK_URL = "http://localhost:5173/callback"
print(f"REDIRECT_URI cargado: {REDIRECT_URI}")
print(f"FRONTEND_CALLBACK_URL: {FRONTEND_CALLBACK_URL}")

# ============================================================================
# FastAPI Setup
# ============================================================================

app = FastAPI(
    title="Twitter Analysis API",
    description="API con OAuth 2.0 y Firebase para analizar tweets del usuario autenticado",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Almacenamiento en memoria (solo para sesiones OAuth)
# ============================================================================

oauth_sessions: Dict[str, Dict[str, Any]] = {}
background_jobs: Dict[str, Dict[str, Any]] = {}
request_cache: Dict[str, Any] = {}  # Cache para prevenir requests duplicadas

# ============================================================================
# Modelos Pydantic
# ============================================================================

class LoginResponse(BaseModel):
    success: bool
    authorization_url: str
    state: str
    session_id: str
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
    save_to_firebase: bool = Field(True, description="Guardar en Firebase")

class ClassifyRequest(BaseModel):
    tweets: List[Union[str, Dict[str, Any]]] = Field(..., description="Lista de tweets (objetos completos)")
    max_tweets: Optional[int] = Field(None, description="Límite de tweets a clasificar")

class DeleteRequest(BaseModel):
    collection_id: str = Field(..., description="ID de la colección en Firebase")
    delete_retweets: bool = True
    delete_originals: bool = True
    delay_seconds: float = 1.0

class TweetObject(BaseModel):
    id: str
    text: str
    is_retweet: Optional[bool] = False
    author_id: Optional[str] = None
    created_at: Optional[str] = None
    referenced_tweets: Optional[List[Dict[str, Any]]] = None

class EstimateRequest(BaseModel):
    max_tweets: Optional[int] = Field(None, description="Número de tweets a analizar")

# ============================================================================
# Firebase Helper Functions
# ============================================================================

def save_tweets_to_firebase(username: str, tweets_data: Dict[str, Any]) -> str:
    """
    Guarda los tweets en Firebase Firestore
    Returns: document_id
    """
    if not db:
        raise Exception("Firebase no está inicializado")
    
    timestamp = datetime.now()
    doc_id = f"{username}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    
    # Estructura del documento
    doc_data = {
        "username": username,
        "user_info": tweets_data.get("user", {}),
        "tweets": tweets_data.get("tweets", []),
        "stats": tweets_data.get("stats", {}),
        "fetched_at": timestamp,
        "pages_fetched": tweets_data.get("pages_fetched", 0),
        "execution_time": tweets_data.get("execution_time_seconds", 0)
    }
    
    # Guardar en colección 'user_tweets'
    db.collection('user_tweets').document(doc_id).set(doc_data)
    
    print(f"✅ Tweets guardados en Firebase: {doc_id}")
    return doc_id

def save_classification_to_firebase(username: str, classification_data: Dict[str, Any]) -> str:
    """
    Guarda los resultados de clasificación en Firebase
    Returns: document_id
    """
    if not db:
        raise Exception("Firebase no está inicializado")
    
    timestamp = datetime.now()
    doc_id = f"{username}_classification_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    
    doc_data = {
        "username": username,
        "timestamp": timestamp,
        "results": classification_data.get("results", []),
        "summary": classification_data.get("summary", {}),
        "total_tweets": classification_data.get("total_tweets", 0),
        "execution_time": classification_data.get("execution_time", "0s")
    }
    
    # Guardar en colección 'risk_classifications'
    db.collection('risk_classifications').document(doc_id).set(doc_data)
    
    print(f"✅ Clasificación guardada en Firebase: {doc_id}")
    return doc_id

def get_tweets_from_firebase(doc_id: str) -> Optional[Dict[str, Any]]:
    """
    Recupera tweets desde Firebase
    """
    if not db:
        raise Exception("Firebase no está inicializado")
    
    doc_ref = db.collection('user_tweets').document(doc_id)
    doc = doc_ref.get()
    
    if doc.exists:
        return doc.to_dict()
    return None

def get_classification_from_firebase(doc_id: str) -> Optional[Dict[str, Any]]:
    """
    Recupera clasificación desde Firebase
    """
    if not db:
        raise Exception("Firebase no está inicializado")
    
    doc_ref = db.collection('risk_classifications').document(doc_id)
    doc = doc_ref.get()
    
    if doc.exists:
        return doc.to_dict()
    return None

# ============================================================================
# Funciones Helper OAuth (sin cambios)
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
        
        session['access_token'] = tokens['access_token']
        session['refresh_token'] = tokens.get('refresh_token')
        session['expires_in'] = tokens.get('expires_in', 7200)
        session['expires_at'] = datetime.now() + timedelta(seconds=tokens.get('expires_in', 7200))
        
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
    
    if session.get('expires_at'):
        if datetime.now() >= session['expires_at']:
            return None
    
    return session

# ============================================================================
# API 1: AUTENTICACIÓN OAUTH (sin cambios)
# ============================================================================

@app.get("/api/auth/login", response_model=LoginResponse)
async def login():
    """Paso 1: Inicia el proceso de login OAuth 2.0"""
    session_id, code_challenge, state = create_oauth_session()
    
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
        session_id=session_id,
        message="Redirige al usuario a authorization_url para autorizar"
    )

@app.get("/api/auth/callback")
async def auth_callback(code: str, state: str):
    """Paso 2: Callback de Twitter después de autorización"""
    session_id = None
    for sid, session in oauth_sessions.items():
        if session.get('state') == state:
            session_id = sid
            break
    
    if not session_id:
        error_url = f"{FRONTEND_CALLBACK_URL}?error=invalid_state"
        return RedirectResponse(url=error_url)
    
    result = exchange_code_for_token(session_id, code)
    
    if not result['success']:
        error_url = f"{FRONTEND_CALLBACK_URL}?error={result['error']}"
        return RedirectResponse(url=error_url)
    
    username = result['user']['username']
    callback_url = f"{FRONTEND_CALLBACK_URL}?session_id={session_id}&username={username}"
    
    return RedirectResponse(url=callback_url)

@app.get("/api/auth/me")
async def get_current_user(session_id: str = Query(..., description="Session ID obtenido del login")):
    """Obtiene información del usuario autenticado"""
    session = get_session(session_id)
    if not session or not session.get('user'):
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    
    return {
        "success": True,
        "user": session['user'],
        "expires_at": session.get('expires_at').isoformat() if session.get('expires_at') else None
    }

# ============================================================================
# API 2: BÚSQUEDA DE TWEETS (con Firebase)
# ============================================================================

@app.post("/api/tweets/search")
async def search_my_tweets(
    request: SearchRequest,
    session_id: str = Query(..., description="Session ID")
):
    """
    Busca tweets del usuario autenticado y los guarda en Firebase
    """
    # Generar cache key para prevenir requests duplicadas
    cache_key = f"search_{session_id}_{request.max_tweets}"
    
    # Si ya hay una request en progreso, esperar o retornar error
    if cache_key in request_cache:
        cache_entry = request_cache[cache_key]
        if time.time() - cache_entry['timestamp'] < 5:  # 5 segundos
            print(f"⚠️ Request duplicada detectada, ignorando...")
            raise HTTPException(
                status_code=429, 
                detail="Request en progreso, espera unos segundos"
            )
    
    # Marcar request como en progreso
    request_cache[cache_key] = {'timestamp': time.time()}
    
    try:
        session = get_session(session_id)
        if not session or not session.get('user'):
            raise HTTPException(status_code=401, detail="Sesión inválida")
        
        username = session['user']['username']
        
        print(f"\n{'='*70}")
        print(f"🔍 BÚSQUEDA DE TWEETS")
        print(f"{'='*70}")
        print(f"   Usuario: @{username}")
        print(f"   Max tweets: {request.max_tweets or 'Todos'}")
        print(f"   Guardar en Firebase: {request.save_to_firebase}")
        print(f"   Session ID: {session_id[:30]}...")
        print(f"{'='*70}\n")
        
        result = fetch_user_tweets(
            username=username,
            max_tweets=request.max_tweets
        )
        
        if not result.get('success'):
            error_msg = result.get('error', 'Error desconocido')
            print(f"❌ Error en fetch_user_tweets: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        
        print(f"✅ Tweets obtenidos: {len(result.get('tweets', []))}")
        
        firebase_doc_id = None
        if request.save_to_firebase:
            if db:
                try:
                    print(f"💾 Guardando en Firebase...")
                    firebase_doc_id = save_tweets_to_firebase(username, result)
                    print(f"✅ Guardado en Firebase: {firebase_doc_id}")
                except Exception as fb_error:
                    print(f"⚠️ Error guardando en Firebase: {str(fb_error)}")
                    import traceback
                    traceback.print_exc()
                    # No fallar si Firebase falla, continuar sin guardar
            else:
                print(f"⚠️ Firebase no conectado, no se guardará")
        
        user_info = result.get('user', {})
        
        response_data = {
            "success": True,
            "username": username,
            "user": {
                "id": user_info.get('author_id'),
                "username": user_info.get('username'),
                "name": user_info.get('name'),
                "followers": user_info.get('followers'),
                "account_created": user_info.get('account_created'),
                "avatar_url": user_info.get('avatar_url'),
                "profile_image_url": user_info.get('profile_image_url')
            },
            "tweets": result.get('tweets', []),
            "stats": result.get('stats'),
            "pages_fetched": result.get('pages_fetched'),
            "fetched_at": result.get('fetched_at'),
            "execution_time": result.get('execution_time'),
            "execution_time_seconds": result.get('execution_time_seconds'),
            "firebase_doc_id": firebase_doc_id
        }
        
        print(f"\n✅ Request completada exitosamente\n")
        
        # Limpiar cache después de 30 segundos
        import asyncio
        asyncio.create_task(clear_cache_after_delay(cache_key, 30))
        
        return response_data
    
    except HTTPException:
        # Limpiar cache inmediatamente en caso de error HTTP
        request_cache.pop(cache_key, None)
        raise
    except Exception as e:
        # Limpiar cache inmediatamente en caso de error
        request_cache.pop(cache_key, None)
        
        print(f"\n{'='*70}")
        print(f"❌ ERROR CRÍTICO EN SEARCH_MY_TWEETS")
        print(f"{'='*70}")
        print(f"Error: {str(e)}")
        print(f"Tipo: {type(e).__name__}")
        print(f"{'='*70}\n")
        
        import traceback
        traceback.print_exc()
        
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

async def clear_cache_after_delay(cache_key: str, delay: int):
    """Limpia una entrada del cache después de un delay"""
    await asyncio.sleep(delay)
    request_cache.pop(cache_key, None)

# ============================================================================
# API 3: CLASIFICACIÓN DE RIESGOS (con Firebase)
# ============================================================================

@app.post("/api/risk/classify")
async def classify_risk(
    request: ClassifyRequest,
    session_id: str = Query(..., description="Session ID"),
    save_to_firebase: bool = Query(True, description="Guardar en Firebase")
):
    """Clasifica riesgos de tweets y guarda en Firebase"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    username = session.get('user', {}).get('username', 'unknown')
    
    print("\n" + "="*70)
    print("🔍 DEBUG: CLASIFICACIÓN DE TWEETS")
    print("="*70)
    print(f"👤 Username: {username}")
    print(f"📊 Total tweets recibidos: {len(request.tweets)}")
    
    original_tweets = []
    
    for idx, tweet_item in enumerate(request.tweets):
        if isinstance(tweet_item, dict):
            original_tweets.append(tweet_item)
        elif isinstance(tweet_item, str):
            original_tweets.append({
                "id": None,
                "text": tweet_item,
                "is_retweet": False
            })
    
    print(f"\n✅ Total tweets procesados: {len(original_tweets)}")
    print("="*70 + "\n")
    
    if not original_tweets:
        raise HTTPException(status_code=400, detail="No se encontraron tweets para clasificar")
    
    if request.max_tweets:
        original_tweets = original_tweets[:request.max_tweets]
    
    start_time = time.time()
    results = []
    stats = {
        "total_analyzed": len(original_tweets),
        "risk_distribution": {"no": 0, "low": 0, "mid": 0, "high": 0},
        "label_counts": {},
        "errors": 0
    }
    
    print(f"\n🛡️  Clasificando {len(original_tweets)} tweets para @{username}...\n")
    
    for i, tweet_obj in enumerate(original_tweets, 1):
        tweet_text = tweet_obj.get("text", "") if isinstance(tweet_obj, dict) else str(tweet_obj)
        tweet_id = tweet_obj.get("id") if isinstance(tweet_obj, dict) else None
        is_retweet = tweet_obj.get("is_retweet", False) if isinstance(tweet_obj, dict) else False
        
        if not tweet_text.strip():
            continue
        
        result = classify_risk_text_only(tweet_text, tweet_id=str(tweet_id) if tweet_id else None)
        result["is_retweet"] = is_retweet
        
        if isinstance(tweet_obj, dict):
            for key in ['author_id', 'created_at', 'referenced_tweets']:
                if key in tweet_obj:
                    result[key] = tweet_obj[key]
        
        results.append(result)
        
        if "error_code" not in result:
            level = result.get("risk_level", "low")
            stats["risk_distribution"][level] += 1
            for label in result.get("labels", []):
                stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1
        else:
            stats["errors"] += 1
        
        if i % 10 == 0 or i == len(original_tweets):
            print(f"   ✅ Procesados: {i}/{len(original_tweets)}")
    
    end_time = time.time()
    execution_time = end_time - start_time
    
    classification_data = {
        "results": results,
        "summary": stats,
        "total_tweets": len(original_tweets),
        "execution_time": f"{execution_time:.2f}s"
    }
    
    firebase_doc_id = None
    if save_to_firebase:
        firebase_doc_id = save_classification_to_firebase(username, classification_data)
    
    return {
        "success": True,
        "total_tweets": len(original_tweets),
        "results": results,
        "summary": stats,
        "execution_time": f"{execution_time:.2f}s",
        "firebase_doc_id": firebase_doc_id
    }

# ============================================================================
# API 5: ESTIMACIÓN DE TIEMPO (sin cambios)
# ============================================================================

@app.get("/api/estimate/time")
async def estimate_processing_time(
    session_id: str = Query(..., description="Session ID")
):
    """Estima el tiempo total de procesamiento"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    username = session.get('user', {}).get('username', 'unknown')
    max_tweets = session.get('user', {}).get('tweet_count', 0)
    
    if max_tweets == 0:
        raise HTTPException(status_code=400, detail="No se pudo obtener el número de tweets del usuario")
    
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump({"tweets": []}, tmp)
            tmp_path = tmp.name
        
        estimacion = quick_estimate_all(
            username=username,
            max_tweets=max_tweets,
            json_path=tmp_path,
            sample_size=0
        )
        
        Path(tmp_path).unlink(missing_ok=True)
        
        tiempo_formateado = f"≈{estimacion['tiempo_total_formateado']}"
        
        return {
            "success": True,
            "tiempo_estimado_total": tiempo_formateado
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculando estimación: {str(e)}")

# ============================================================================
# UTILIDADES
# ============================================================================

@app.get("/")
async def root():
    return {
        "name": "Twitter Analysis API",
        "version": "3.0.0",
        "storage": "Firebase Firestore",
        "flow": "OAuth Login → Get User → Search/Classify Tweets → Save to Firebase",
        "endpoints": {
            "login": "/api/auth/login",
            "callback": "/api/auth/callback",
            "me": "/api/auth/me",
            "search": "/api/tweets/search",
            "classify": "/api/risk/classify",
            "estimate": "/api/estimate/time",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "active_sessions": len(oauth_sessions),
        "firebase_connected": db is not None,
        "timestamp": datetime.now().isoformat()
    }
@app.get("/api/firebase/get-data")
async def get_firebase_data(
    session_id: str = Query(...),
    tweets_doc_id: str = Query(None),
    classification_doc_id: str = Query(None)
):
    """
    Recupera datos desde Firebase usando los doc IDs
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    result = {}
    
    if tweets_doc_id:
        tweets_data = get_tweets_from_firebase(tweets_doc_id)
        if tweets_data:
            result["tweets"] = tweets_data
    
    if classification_doc_id:
        classification_data = get_classification_from_firebase(classification_doc_id)
        if classification_data:
            result["classification"] = classification_data
    
    return {
        "success": True,
        "data": result
    }

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*70)
    print("🚀 TWITTER ANALYSIS API - OAuth 2.0 + Firebase")
    print("="*70)
    print(f"\nREDIRECT_URI configurado: {REDIRECT_URI}")
    print(f"FRONTEND_CALLBACK_URL: {FRONTEND_CALLBACK_URL}")
    print(f"Firebase Status: {'✅ Conectado' if db else '❌ No conectado'}")
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
# main.py - API con FastAPI (FLUJO OAUTH CORRECTO + JSONs ALINEADOS)
"""
API REST para análisis de tweets con autenticación OAuth 2.0
Flujo: Login → Obtener userName del usuario autenticado → Operar con sus tweets
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
from estimacion_de_tiempo import quick_estimate_all, format_time

# Credenciales OAuth
oauth_creds = get_oauth2_credentials()
CLIENT_ID = oauth_creds['client_id']
CLIENT_SECRET = oauth_creds['client_secret']
REDIRECT_URI = oauth_creds['redirect_uri']
FRONTEND_CALLBACK_URL = "http://localhost:5173/callback"  # URL del frontend para callback
print(f"REDIRECT_URI cargado: {REDIRECT_URI}")
print(f"FRONTEND_CALLBACK_URL: {FRONTEND_CALLBACK_URL}")

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

oauth_sessions: Dict[str, Dict[str, Any]] = {}
background_jobs: Dict[str, Dict[str, Any]] = {}

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

class TweetObject(BaseModel):
    id: str
    text: str
    is_retweet: Optional[bool] = False
    author_id: Optional[str] = None
    created_at: Optional[str] = None
    referenced_tweets: Optional[List[Dict[str, Any]]] = None

class ClassifyRequest(BaseModel):
    tweets: List[Union[str, TweetObject, Dict[str, Any]]] = Field(..., description="Lista de tweets (objetos completos)")
    max_tweets: Optional[int] = Field(None, description="Límite de tweets a clasificar")
    # Eliminar json_path completamente
class EstimateRequest(BaseModel):
    max_tweets: Optional[int] = Field(None, description="Número de tweets a analizar")

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
    """Paso 1: Inicia el proceso de login OAuth 2.0"""
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
        session_id=session_id,
        message="Redirige al usuario a authorization_url para autorizar"
    )

@app.get("/api/auth/callback")
async def auth_callback(code: str, state: str):
    """
    Paso 2: Callback de Twitter después de autorización
    
    Twitter redirige aquí con el authorization_code.
    Este endpoint intercambia el code por access_token y redirige al frontend.
    """
    # Buscar sesión por state
    session_id = None
    for sid, session in oauth_sessions.items():
        if session.get('state') == state:
            session_id = sid
            break
    
    if not session_id:
        # Redirigir al frontend con error
        error_url = f"{FRONTEND_CALLBACK_URL}?error=invalid_state"
        return RedirectResponse(url=error_url)
    
    # Intercambiar code por token
    result = exchange_code_for_token(session_id, code)
    
    if not result['success']:
        # Redirigir al frontend con error
        error_url = f"{FRONTEND_CALLBACK_URL}?error={result['error']}"
        return RedirectResponse(url=error_url)
    
    # Redirigir al frontend con session_id y username
    username = result['user']['username']
    callback_url = f"{FRONTEND_CALLBACK_URL}?session_id={session_id}&username={username}"
    
    return RedirectResponse(url=callback_url)

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
    Incluye avatar_url del usuario en la respuesta
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
        
        # Extraer info del usuario (incluye avatar_url desde search_tweets.py)
        user_info = result.get('user', {})
        
        # RETORNAR ESTRUCTURA COMPLETA incluyendo tweets + avatar_url
        return {
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
    session_id: str = Query(..., description="Session ID"),
    save_files: bool = Query(True, description="Guardar archivos JSON de resultados")
):
    """Clasifica riesgos de tweets - Trabaja con datos en memoria"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    username = session.get('user', {}).get('username', 'unknown')
    
    print("\n" + "="*70)
    print("🔍 DEBUG: CLASIFICACIÓN DE TWEETS")
    print("="*70)
    print(f"👤 Username: {username}")
    print(f"📊 Total tweets recibidos: {len(request.tweets)}")
    
    # ✅ PROCESAR TWEETS (pueden venir como strings o como objetos)
    original_tweets = []
    
    for idx, tweet_item in enumerate(request.tweets):
        if isinstance(tweet_item, dict):
            # Ya es un objeto, usarlo directamente
            original_tweets.append(tweet_item)
            
            if idx < 3:  # Debug primeros 3
                print(f"\n🔍 Tweet {idx} (dict):")
                print(f"   id: {tweet_item.get('id')}")
                print(f"   text: {tweet_item.get('text', '')[:50]}...")
                print(f"   is_retweet: {tweet_item.get('is_retweet')}")
                
        elif isinstance(tweet_item, str):
            # Es solo texto, crear objeto mínimo
            original_tweets.append({
                "id": None,
                "text": tweet_item,
                "is_retweet": False
            })
            
            if idx < 3:
                print(f"\n⚠️ Tweet {idx} (string): {tweet_item[:50]}...")
        else:
            print(f"❌ Tweet {idx}: Tipo desconocido {type(tweet_item)}")
    
    print(f"\n✅ Total tweets procesados: {len(original_tweets)}")
    print("="*70 + "\n")
    
    if not original_tweets:
        raise HTTPException(status_code=400, detail="No se encontraron tweets para clasificar")
    
    # Limitar si se especifica
    if request.max_tweets:
        original_tweets = original_tweets[:request.max_tweets]
        print(f"⚠️ Limitado a {request.max_tweets} tweets")
    
    # ✅ CLASIFICAR
    start_time = time.time()
    results = []
    stats = {
        "total_analyzed": len(original_tweets),
        "risk_distribution": {"no": 0, "low": 0, "mid": 0, "high": 0},
        "label_counts": {},
        "errors": 0,
        "throttle_waits": 0
    }
    
    print(f"\n🛡️  Clasificando {len(original_tweets)} tweets para @{username}...\n")
    
    for i, tweet_obj in enumerate(original_tweets, 1):
        # Extraer datos del tweet
        tweet_text = tweet_obj.get("text", "") if isinstance(tweet_obj, dict) else str(tweet_obj)
        tweet_id = tweet_obj.get("id") if isinstance(tweet_obj, dict) else None
        is_retweet = tweet_obj.get("is_retweet", False) if isinstance(tweet_obj, dict) else False
        
        if not tweet_text.strip():
            print(f"⚠️ Tweet #{i}: Texto vacío, saltando...")
            continue
        
        # Debug primeros 3
        if i <= 3:
            print(f"📤 Tweet #{i}:")
            print(f"   ID: {tweet_id}")
            print(f"   Text: {tweet_text[:50]}...")
            print(f"   is_retweet: {is_retweet}")
        
        # ✅ CLASIFICAR
        result = classify_risk_text_only(tweet_text, tweet_id=str(tweet_id) if tweet_id else None)
        
        # Agregar metadata
        result["is_retweet"] = is_retweet
        
        # Copiar otros campos útiles del tweet original
        if isinstance(tweet_obj, dict):
            for key in ['author_id', 'created_at', 'referenced_tweets']:
                if key in tweet_obj:
                    result[key] = tweet_obj[key]
        
        results.append(result)
        
        # Stats
        if "error_code" not in result:
            level = result.get("risk_level", "low")
            stats["risk_distribution"][level] += 1
            for label in result.get("labels", []):
                stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1
        else:
            stats["errors"] += 1
        
        # Logging cada 10 tweets
        if i % 10 == 0 or i == len(original_tweets):
            print(f"   ✅ Procesados: {i}/{len(original_tweets)}")
    
    end_time = time.time()
    execution_time = end_time - start_time
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # ✅ PREPARAR RESPUESTA
    summary = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "username": username,
        "tiempo_total": f"{int(execution_time//60)}m{int(execution_time%60)}s" if execution_time >= 60 else f"{int(execution_time)}s",
        "total_tweets": len(original_tweets),
        "exitosos": len(original_tweets) - stats["errors"],
        "errores": stats["errors"],
        "distribucion": stats["risk_distribution"],
        "labels": stats["label_counts"]
    }
    
    detailed = {
        "resultados": results
    }
    
    saved_files = {}
    if save_files:
        summary_filename = f"risk_summary_{username}_{timestamp}.json"
        detailed_filename = f"risk_detailed_{username}_{timestamp}.json"
        
        Path(summary_filename).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), 
            encoding="utf-8"
        )
        Path(detailed_filename).write_text(
            json.dumps(detailed, ensure_ascii=False, indent=2), 
            encoding="utf-8"
        )
        
        saved_files = {
            "summary_file": summary_filename,
            "detailed_file": detailed_filename
        }
        
        print(f"\n✅ Archivos guardados:")
        print(f"   📄 {summary_filename}")
        print(f"   📄 {detailed_filename}")
    
    return {
        "success": True,
        "total_tweets": len(original_tweets),
        "results": results,
        "summary": stats,
        "execution_time": f"{execution_time:.2f}s",
        "files": saved_files
    }
# ============================================================================
# API 5: ESTIMACIÓN DE TIEMPO
# ============================================================================

@app.get("/api/estimate/time")
async def estimate_processing_time(
    session_id: str = Query(..., description="Session ID")
):
    """
    Estima el tiempo total de procesamiento basado en el tweet_count del usuario autenticado
    Usa las funciones de estimacion_de_tiempo.py
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    username = session.get('user', {}).get('username', 'unknown')
    
    # Obtener automáticamente el tweet_count del usuario
    max_tweets = session.get('user', {}).get('tweet_count', 0)
    
    if max_tweets == 0:
        raise HTTPException(status_code=400, detail="No se pudo obtener el número de tweets del usuario")
    
    try:
        # Crear un archivo temporal vacío para pasar a quick_estimate_all
        # (solo se usa para verificar existencia, no se lee)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump({"tweets": []}, tmp)
            tmp_path = tmp.name
        
        # Llamar a quick_estimate_all con sample_size=0 para evitar procesamiento real
        estimacion = quick_estimate_all(
            username=username,
            max_tweets=max_tweets,
            json_path=tmp_path,
            sample_size=0
        )
        
        # Limpiar archivo temporal
        Path(tmp_path).unlink(missing_ok=True)
        
        # Formatear tiempo estimado con símbolo ≈
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
        "version": "2.0.0",
        "flow": "OAuth Login → Get User → Search/Classify/Delete Tweets",
        "endpoints": {
            "login": "/api/auth/login",
            "callback": "/api/auth/callback",
            "me": "/api/auth/me",
            "search": "/api/tweets/search",
            "classify": "/api/risk/classify",
            "delete": "/api/tweets/delete",
            "estimate": "/api/estimate/time",
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
    print(f"FRONTEND_CALLBACK_URL: {FRONTEND_CALLBACK_URL}")
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
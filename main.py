# main.py - API Principal con FastAPI (CORREGIDO)
"""
APIs para Sistema de Análisis de Tweets
- Login OAuth 2.0
- Búsqueda de tweets
- Clasificación de riesgos
- Estimación de tiempos
- Eliminación de tweets
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import asyncio
import uuid
import time
from pathlib import Path
import requests
import secrets
import hashlib
import base64

# Tus módulos existentes
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

# CORRECCIÓN: Importar las funciones correctas de X_login.py
from X.X_login import (
    initiate_login_with_scope_testing,
    generate_code_verifier,
    generate_code_challenge,
    REDIRECT_URI,
    TOKEN_URL,
    USER_INFO_URL,
    AUTH_URL,
    REQUESTED_SCOPES
)

# Importar config para credenciales
try:
    from config import get_oauth2_credentials
    oauth_creds = get_oauth2_credentials()
    CLIENT_ID = oauth_creds['client_id']
    CLIENT_SECRET = oauth_creds['client_secret']
except:
    import os
    CLIENT_ID = os.environ.get('X_CLIENT_ID')
    CLIENT_SECRET = os.environ.get('X_CLIENT_SECRET')

from X.search_tweets import fetch_user_tweets, save_tweets_to_file
from GPT.risk_classifier_only_text import classify_risk_text_only, load_tweets_from_json
from X.deleate_tweets_rts import delete_tweets_from_json, delete_tweets_batch
from estimacion_de_tiempo import quick_estimate_all, format_time

# ============================================================================
# CONFIGURACIÓN DE FASTAPI
# ============================================================================

app = FastAPI(
    title="Twitter Analysis API",
    description="APIs para análisis, clasificación y gestión de tweets",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# CLASE OAuth2Session SIMPLIFICADA (para gestión interna)
# ============================================================================

class OAuth2SessionManager:
    """Gestiona sesiones OAuth 2.0"""
    
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        self.code_verifier = None
        self.code_challenge = None
        self.user_data = None
    
    def generate_pkce_params(self):
        """Genera parámetros PKCE"""
        self.code_verifier = generate_code_verifier()
        self.code_challenge = generate_code_challenge(self.code_verifier)
    
    def get_authorization_url(self, scopes: List[str] = None) -> tuple:
        """Genera URL de autorización"""
        if scopes is None:
            scopes = REQUESTED_SCOPES
        
        self.generate_pkce_params()
        
        state = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        
        auth_params = {
            'response_type': 'code',
            'client_id': CLIENT_ID,
            'redirect_uri': REDIRECT_URI,
            'scope': ' '.join(scopes),
            'state': state,
            'code_challenge': self.code_challenge,
            'code_challenge_method': 'S256'
        }
        
        from urllib.parse import urlencode
        auth_url = f"{AUTH_URL}?{urlencode(auth_params)}"
        return auth_url, state
    
    def exchange_code_for_token(self, authorization_code: str) -> Dict[str, Any]:
        """Intercambia código por token"""
        auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
        auth_b64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
        
        token_data = {
            'code': authorization_code,
            'grant_type': 'authorization_code',
            'redirect_uri': REDIRECT_URI,
            'code_verifier': self.code_verifier
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_b64}'
        }
        
        try:
            response = requests.post(TOKEN_URL, data=token_data, headers=headers, timeout=15)
            
            if response.status_code == 200:
                tokens = response.json()
                
                self.access_token = tokens.get('access_token')
                self.refresh_token = tokens.get('refresh_token')
                expires_in = tokens.get('expires_in', 7200)
                
                from datetime import timedelta
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                # Obtener info del usuario
                self._fetch_user_info()
                
                return {
                    'success': True,
                    'access_token': self.access_token,
                    'refresh_token': self.refresh_token,
                    'expires_in': expires_in,
                    'expires_at': self.token_expires_at.isoformat(),
                    'user': self.user_data
                }
            else:
                return {
                    'success': False,
                    'error': f"HTTP {response.status_code}: {response.text}"
                }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _fetch_user_info(self):
        """Obtiene información del usuario"""
        if not self.access_token:
            return
        
        try:
            headers = {'Authorization': f'Bearer {self.access_token}'}
            params = {'user.fields': 'id,name,username,public_metrics'}
            response = requests.get(USER_INFO_URL, headers=headers, params=params)
            
            if response.status_code == 200:
                self.user_data = response.json().get('data', {})
        except:
            self.user_data = {}
    
    def get_headers(self) -> Dict[str, str]:
        """Retorna headers con el access token"""
        if not self.access_token:
            raise ValueError("No access token available")
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def is_token_valid(self) -> bool:
        """Verifica si el token es válido"""
        if not self.access_token or not self.token_expires_at:
            return False
        
        from datetime import timedelta
        return datetime.now() < (self.token_expires_at - timedelta(minutes=5))

# ============================================================================
# MODELOS PYDANTIC
# ============================================================================

class LoginRequest(BaseModel):
    scopes: Optional[List[str]] = Field(
        default=['tweet.read', 'tweet.write', 'users.read', 'offline.access'],
        description="Permisos OAuth a solicitar"
    )

class LoginResponse(BaseModel):
    success: bool
    authorization_url: Optional[str] = None
    state: Optional[str] = None
    session_id: Optional[str] = None
    message: Optional[str] = None

class CallbackRequest(BaseModel):
    session_id: str
    authorization_code: str
    state: Optional[str] = None

class TokenResponse(BaseModel):
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    user: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class SearchTweetsRequest(BaseModel):
    username: str = Field(..., description="Usuario de Twitter (con o sin @)")
    max_tweets: Optional[int] = Field(None, description="Máximo de tweets a obtener")
    save_to_file: bool = Field(True, description="Guardar resultado en JSON")

class SearchTweetsResponse(BaseModel):
    success: bool
    user: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None
    tweets_count: Optional[int] = None
    execution_time: Optional[str] = None
    file_path: Optional[str] = None
    error: Optional[str] = None

class RiskClassificationRequest(BaseModel):
    json_path: Optional[str] = Field(None, description="Ruta al archivo JSON de tweets")
    tweets: Optional[List[str]] = Field(None, description="Lista de tweets para clasificar")
    max_tweets: Optional[int] = Field(None, description="Límite de tweets a analizar")

class RiskClassificationResponse(BaseModel):
    success: bool
    total_tweets: Optional[int] = None
    results: Optional[List[Dict[str, Any]]] = None
    summary: Optional[Dict[str, Any]] = None
    execution_time: Optional[str] = None
    error: Optional[str] = None

class TimeEstimationRequest(BaseModel):
    username: str
    max_tweets: int = Field(1000, ge=1, le=10000)
    json_path: Optional[str] = None
    sample_size: int = Field(3, ge=1, le=10)

class TimeEstimationResponse(BaseModel):
    success: bool
    tiempo_total_estimado: Optional[str] = None
    tiempo_total_segundos: Optional[float] = None
    desglose: Optional[Dict[str, Any]] = None
    configuracion: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class DeleteTweetsRequest(BaseModel):
    session_id: str
    json_path: str
    delete_retweets: bool = True
    delete_originals: bool = True
    delay_seconds: float = 1.0

class DeleteTweetsResponse(BaseModel):
    success: bool
    total_processed: Optional[int] = None
    retweets_deleted: Optional[int] = None
    tweets_deleted: Optional[int] = None
    failed: Optional[List[Dict[str, Any]]] = None
    execution_time: Optional[str] = None
    error: Optional[str] = None

class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # "pending", "running", "completed", "failed"
    progress: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

# ============================================================================
# ALMACENAMIENTO EN MEMORIA
# ============================================================================

oauth_sessions: Dict[str, OAuth2SessionManager] = {}
background_jobs: Dict[str, Dict[str, Any]] = {}

# ============================================================================
# API 1: LOGIN OAUTH 2.0
# ============================================================================

@app.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Inicia el proceso de login OAuth 2.0
    
    Retorna la URL de autorización que el usuario debe visitar
    """
    try:
        session = OAuth2SessionManager()
        auth_url, state = session.get_authorization_url(scopes=request.scopes)
        
        # Generar ID de sesión único
        session_id = str(uuid.uuid4())
        
        # Guardar sesión temporal
        oauth_sessions[session_id] = session
        
        return LoginResponse(
            success=True,
            authorization_url=auth_url,
            state=state,
            session_id=session_id,
            message="Visita la URL de autorización y autoriza la aplicación"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/callback", response_model=TokenResponse)
async def callback(request: CallbackRequest):
    """
    Procesa el callback de OAuth y obtiene el access token
    """
    try:
        # Recuperar sesión
        session = oauth_sessions.get(request.session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Sesión no encontrada o expirada")
        
        # Intercambiar código por token
        result = session.exchange_code_for_token(request.authorization_code)
        
        if not result['success']:
            return TokenResponse(
                success=False,
                error=result.get('error', 'Error desconocido')
            )
        
        # Guardar sesión actualizada
        oauth_sessions[request.session_id] = session
        
        return TokenResponse(
            success=True,
            access_token=result['access_token'],
            refresh_token=result.get('refresh_token'),
            expires_in=result['expires_in'],
            user=result.get('user')
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/session/{session_id}")
async def get_session_info(session_id: str):
    """
    Obtiene información de una sesión OAuth
    """
    session = oauth_sessions.get(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    
    return {
        "session_id": session_id,
        "has_token": session.access_token is not None,
        "is_valid": session.is_token_valid(),
        "expires_at": session.token_expires_at.isoformat() if session.token_expires_at else None,
        "user": session.user_data
    }


# ============================================================================
# API 2: BÚSQUEDA DE TWEETS
# ============================================================================

@app.post("/api/tweets/search", response_model=SearchTweetsResponse)
async def search_tweets(request: SearchTweetsRequest):
    """
    Obtiene tweets de un usuario
    """
    try:
        start_time = time.time()
        
        # Obtener tweets
        result = fetch_user_tweets(
            username=request.username,
            max_tweets=request.max_tweets
        )
        
        if not result['success']:
            return SearchTweetsResponse(
                success=False,
                error=result.get('error', 'Error desconocido')
            )
        
        # Guardar en archivo si se solicita
        file_path = None
        if request.save_to_file:
            file_path = save_tweets_to_file(result)
        
        execution_time = time.time() - start_time
        
        return SearchTweetsResponse(
            success=True,
            user=result.get('user'),
            stats=result.get('stats'),
            tweets_count=len(result.get('tweets', [])),
            execution_time=format_time(execution_time),
            file_path=file_path
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# API 3: CLASIFICACIÓN DE RIESGOS
# ============================================================================

@app.post("/api/risk/classify", response_model=RiskClassificationResponse)
async def classify_risk(request: RiskClassificationRequest):
    """
    Clasifica riesgos de tweets
    """
    try:
        start_time = time.time()
        
        # Obtener tweets a analizar
        if request.json_path:
            tweets_data = load_tweets_from_json(request.json_path)
            tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
        elif request.tweets:
            tweets = request.tweets
        else:
            raise HTTPException(
                status_code=400,
                detail="Debes proporcionar 'json_path' o 'tweets'"
            )
        
        # Aplicar límite si existe
        if request.max_tweets:
            tweets = tweets[:request.max_tweets]
        
        # Clasificar tweets
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
            
            # Actualizar estadísticas
            if "error_code" not in result:
                level = result.get("risk_level", "low")
                stats["risk_distribution"][level] += 1
                
                for label in result.get("labels", []):
                    stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1
            else:
                stats["errors"] += 1
        
        execution_time = time.time() - start_time
        
        # Preparar resumen
        summary = {
            "total": len(tweets),
            "exitosos": len(tweets) - stats["errors"],
            "errores": stats["errors"],
            "distribucion": stats["risk_distribution"],
            "labels": stats["label_counts"]
        }
        
        return RiskClassificationResponse(
            success=True,
            total_tweets=len(tweets),
            results=results,
            summary=summary,
            execution_time=format_time(execution_time)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/risk/classify/background")
async def classify_risk_background(
    request: RiskClassificationRequest,
    background_tasks: BackgroundTasks
):
    """
    Clasifica riesgos en background
    """
    job_id = str(uuid.uuid4())
    
    background_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "progress": 0.0,
        "result": None,
        "error": None,
        "started_at": datetime.now().isoformat(),
        "completed_at": None
    }
    
    async def run_classification():
        try:
            background_jobs[job_id]["status"] = "running"
            
            if request.json_path:
                tweets_data = load_tweets_from_json(request.json_path)
                tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
            elif request.tweets:
                tweets = request.tweets
            else:
                raise ValueError("Debes proporcionar 'json_path' o 'tweets'")
            
            if request.max_tweets:
                tweets = tweets[:request.max_tweets]
            
            total = len(tweets)
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
                
                background_jobs[job_id]["progress"] = (i / total) * 100
            
            background_jobs[job_id]["status"] = "completed"
            background_jobs[job_id]["completed_at"] = datetime.now().isoformat()
            background_jobs[job_id]["result"] = {
                "total_tweets": total,
                "results": results,
                "summary": {
                    "total": total,
                    "exitosos": total - stats["errors"],
                    "errores": stats["errors"],
                    "distribucion": stats["risk_distribution"],
                    "labels": stats["label_counts"]
                }
            }
        
        except Exception as e:
            background_jobs[job_id]["status"] = "failed"
            background_jobs[job_id]["error"] = str(e)
            background_jobs[job_id]["completed_at"] = datetime.now().isoformat()
    
    background_tasks.add_task(run_classification)
    
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Clasificación iniciada en background"
    }


@app.get("/api/risk/classify/status/{job_id}", response_model=JobStatusResponse)
async def get_classification_status(job_id: str):
    """
    Obtiene el estado de clasificación
    """
    job = background_jobs.get(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    
    return JobStatusResponse(**job)


# ============================================================================
# API 4: ESTIMACIÓN DE TIEMPOS
# ============================================================================

@app.post("/api/estimate", response_model=TimeEstimationResponse)
async def estimate_time(request: TimeEstimationRequest):
    """
    Estima tiempo total del proceso
    """
    try:
        json_path = request.json_path
        if not json_path:
            default_json = Path(__file__).resolve().parent / f"tweets_{request.username.lstrip('@')}*.json"
            matching = list(Path(__file__).resolve().parent.glob(f"tweets_{request.username.lstrip('@')}*.json"))
            if matching:
                json_path = str(matching[0])
        
        estimacion = quick_estimate_all(
            username=request.username,
            max_tweets=request.max_tweets,
            json_path=json_path or "",
            sample_size=request.sample_size
        )
        
        return TimeEstimationResponse(
            success=True,
            tiempo_total_estimado=estimacion['tiempo_total_formateado'],
            tiempo_total_segundos=estimacion['tiempo_total_segundos'],
            desglose=estimacion['tiempos_individuales'],
            configuracion={
                "username": request.username,
                "max_tweets": request.max_tweets,
                "sample_size": request.sample_size
            }
        )
    
    except Exception as e:
        return TimeEstimationResponse(
            success=False,
            error=str(e)
        )


@app.post("/api/execute-full-analysis")
async def execute_full_analysis(
    request: TimeEstimationRequest,
    background_tasks: BackgroundTasks
):
    """
    Ejecuta análisis completo: estima + busca + clasifica
    """
    job_id = str(uuid.uuid4())
    
    background_jobs[job_id] = {
        "job_id": job_id,
        "status": "estimating",
        "progress": 0.0,
        "result": None,
        "error": None,
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "stages": {
            "estimation": {"status": "running", "result": None},
            "search": {"status": "pending", "result": None},
            "classification": {"status": "pending", "result": None}
        }
    }
    
    async def run_full_analysis():
        try:
            # Estimación
            background_jobs[job_id]["status"] = "estimating"
            background_jobs[job_id]["progress"] = 10
            
            json_path = request.json_path or ""
            estimacion = quick_estimate_all(
                username=request.username,
                max_tweets=request.max_tweets,
                json_path=json_path,
                sample_size=request.sample_size
            )
            
            background_jobs[job_id]["stages"]["estimation"]["status"] = "completed"
            background_jobs[job_id]["stages"]["estimation"]["result"] = estimacion
            background_jobs[job_id]["progress"] = 20
            
            # Búsqueda
            background_jobs[job_id]["status"] = "searching"
            background_jobs[job_id]["progress"] = 30
            
            search_result = fetch_user_tweets(
                username=request.username,
                max_tweets=request.max_tweets
            )
            
            if not search_result['success']:
                raise Exception(f"Error en búsqueda: {search_result.get('error')}")
            
            file_path = save_tweets_to_file(search_result)
            
            background_jobs[job_id]["stages"]["search"]["status"] = "completed"
            background_jobs[job_id]["stages"]["search"]["result"] = {
                "tweets_count": len(search_result.get('tweets', [])),
                "file_path": file_path,
                "stats": search_result.get('stats')
            }
            background_jobs[job_id]["progress"] = 50
            
            # Clasificación
            background_jobs[job_id]["status"] = "classifying"
            background_jobs[job_id]["progress"] = 60
            
            tweets_data = load_tweets_from_json(file_path)
            tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
            
            total = len(tweets)
            results = []
            stats = {
                "risk_distribution": {"low": 0, "mid": 0, "high": 0},
                "label_counts": {},
                "errors": 0
            }
            
            for i, tweet_text in enumerate(tweets, 1):
                result = classify_risk_text_only(tweet_text)
                result["tweet_id"] = i
                results.append(result)
                
                if "error_code" not in result:
                    level = result.get("risk_level", "low")
                    stats["risk_distribution"][level] += 1
                    for label in result.get("labels", []):
                        stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1
                else:
                    stats["errors"] += 1
                
                progress = 60 + ((i / total) * 35)
                background_jobs[job_id]["progress"] = progress
            
            background_jobs[job_id]["stages"]["classification"]["status"] = "completed"
            background_jobs[job_id]["stages"]["classification"]["result"] = {
                "total_tweets": total,
                "summary": {
                    "total": total,
                    "exitosos": total - stats["errors"],
                    "errores": stats["errors"],
                    "distribucion": stats["risk_distribution"],
                    "labels": stats["label_counts"]
                }
            }
            
            background_jobs[job_id]["status"] = "completed"
            background_jobs[job_id]["progress"] = 100
            background_jobs[job_id]["completed_at"] = datetime.now().isoformat()
            background_jobs[job_id]["result"] = {
                "estimation": estimacion,
                "search": background_jobs[job_id]["stages"]["search"]["result"],
                "classification": background_jobs[job_id]["stages"]["classification"]["result"]
            }
        
        except Exception as e:
            background_jobs[job_id]["status"] = "failed"
            background_jobs[job_id]["error"] = str(e)
            background_jobs[job_id]["completed_at"] = datetime.now().isoformat()
    
    background_tasks.add_task(run_full_analysis)
    
    return {
        "job_id": job_id,
        "status": "estimating",
        "message": "Análisis completo iniciado"
    }


# ============================================================================
# API 5: ELIMINACIÓN DE TWEETS
# ============================================================================

@app.post("/api/tweets/delete", response_model=DeleteTweetsResponse)
async def delete_tweets(request: DeleteTweetsRequest):
    """
    Elimina tweets desde un archivo JSON
    """
    try:
        session = oauth_sessions.get(request.session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Sesión no encontrada")
        
        if not session.is_token_valid():
            raise HTTPException(status_code=401, detail="Token expirado o inválido")
        
        # Cargar tweets del JSON
        with open(request.json_path, 'r', encoding='utf-8') as f:
            import json
            data = json.load(f)
        
        if not data.get('success'):
            raise HTTPException(status_code=400, detail='JSON inválido')
        
        tweets = data.get('tweets', [])
        user_id = data.get('user', {}).get('author_id')
        
        if not user_id:
            raise HTTPException(status_code=400, detail='No se encontró user_id')
        
        # Importar función de eliminación
        from X.deleate_tweets_rts import delete_tweets_batch as delete_batch_function
        
        # Crear objeto de sesión compatible
        class SessionAdapter:
            def __init__(self, oauth_session):
                self.oauth_session = oauth_session
            
            def get_headers(self):
                return self.oauth_session.get_headers()
        
        session_adapter = SessionAdapter(session)
        
        result = delete_batch_function(
            tweets=tweets,
            user_id=user_id,
            session=session_adapter,
            delete_retweets=request.delete_retweets,
            delete_originals=request.delete_originals,
            delay_seconds=request.delay_seconds,
            verbose=True
        )
        
        if not result['success']:
            return DeleteTweetsResponse(
                success=False,
                error=result.get('error', 'Error desconocido')
            )
        
        return DeleteTweetsResponse(
            success=True,
            total_processed=result['total_processed'],
            retweets_deleted=result['retweets_deleted'],
            tweets_deleted=result['tweets_deleted'],
            failed=result['failed'],
            execution_time=result['execution_time']
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE UTILIDAD
# ============================================================================

@app.get("/")
async def root():
    """Endpoint raíz"""
    return {
        "name": "Twitter Analysis API",
        "version": "1.0.0",
        "endpoints": {
            "auth": "/api/auth/login",
            "search": "/api/tweets/search",
            "classify": "/api/risk/classify",
            "estimate": "/api/estimate",
            "delete": "/api/tweets/delete",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health_check():
    """Health check"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_sessions": len(oauth_sessions),
        "active_jobs": len(background_jobs)
    }


@app.get("/api/jobs")
async def list_jobs():
    """Lista todos los jobs"""
    return {
        "total_jobs": len(background_jobs),
        "jobs": [
            {
                "job_id": job_id,
                "status": job["status"],
                "progress": job.get("progress", 0),
                "started_at": job["started_at"]
            }
            for job_id, job in background_jobs.items()
        ]
    }


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Elimina un job"""
    if job_id not in background_jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    
    job = background_jobs[job_id]
    
    if job["status"] in ["running", "pending"]:
        raise HTTPException(
            status_code=400,
            detail="No se puede eliminar un job en ejecución"
        )
    
    del background_jobs[job_id]
    
    return {"message": f"Job {job_id} eliminado"}


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*70)
    print("🚀 TWITTER ANALYSIS API")
    print("="*70)
    print("\nIniciando servidor FastAPI...")
    print("Documentación: http://localhost:8000/docs")
    print("="*70 + "\n")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
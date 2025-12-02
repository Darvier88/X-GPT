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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
# Firebase imports
import firebase_admin
from firebase_admin import credentials, firestore
import secrets
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse, Response
from dotenv import load_dotenv
import os
import threading
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Importar solo las funciones helper de X_login (NO initiate_login_with_scope_testing)
load_dotenv()
from X.X_login import (
    generate_code_verifier,
    generate_code_challenge,
    AUTH_URL,
    TOKEN_URL,
    USER_INFO_URL,
    REQUESTED_SCOPES
)

from config import get_oauth2_credentials
from X.search_tweets import fetch_user_tweets_with_progress
from GPT.risk_classifier_only_text import classify_risk_text_only
from X.deleate_tweets_rts import delete_tweets_batch
from estimacion_de_tiempo import quick_estimate_all, format_time

# Gmail SMTP (desde variables de entorno)
GMAIL_USER = os.getenv('GMAIL_USER')
GMAIL_APP_PASSWORD = os.getenv('GMAIL_APP_PASSWORD')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')
FIREBASE_CREDENTIALS = os.getenv('FIREBASE_CREDENTIALS')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:8080')

print(f"GMAIL_USER cargado: {GMAIL_USER}")
print(f"RECIPIENT_EMAIL cargado: {RECIPIENT_EMAIL}")
print(f"GMAIL_APP_PASSWORD cargado: {'Sí' if GMAIL_APP_PASSWORD else 'No'}")


TOKEN_EXPIRATION_HOURS = 48 
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
        
        firebase_project_id = os.getenv("FIREBASE_PROJECT_ID")
        firebase_private_key = os.getenv("FIREBASE_PRIVATE_KEY")
        firebase_client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
        firebase_token_uri = os.getenv("FIREBASE_TOKEN_URI")

        if firebase_project_id and firebase_private_key and firebase_client_email:
            print("✅ Usando credenciales de Firebase desde variables de entorno")
            try:
                creds_dict = {
                    "type": "service_account",
                    "project_id": firebase_project_id,
                    "private_key": firebase_private_key.replace('\\n', '\n'),
                    "client_email": firebase_client_email,
                    "token_uri": firebase_token_uri or "https://oauth2.googleapis.com/token",
                }
                cred = credentials.Certificate(creds_dict)
                firebase_admin.initialize_app(cred)
                db = firestore.client()
                print("✅ Firebase inicializado correctamente (variables de entorno)")
                return True
            except Exception as e:
                print(f"❌ Error inicializando Firebase: {e}")
                return False
        else:
            print("❌ Faltan credenciales de Firebase en variables de entorno")
            print(f"   - FIREBASE_PROJECT_ID: {'✓' if firebase_project_id else '✗'}")
            print(f"   - FIREBASE_PRIVATE_KEY: {'✓' if firebase_private_key else '✗'}")
            print(f"   - FIREBASE_CLIENT_EMAIL: {'✓' if firebase_client_email else '✗'}")
            return False
        
    except Exception as e:
        print(f"⚠️ Error inicializando Firebase: {e}")
        return False

# Inicializar Firebase al cargar el módulo
initialize_firebase()
def send_email_notification(
    username: str,
    stats: Dict[str, Any],
    recipient_email: str = RECIPIENT_EMAIL,
    dashboard_link: str = f"{FRONTEND_URL}/dashboard" # ← NUEVO parámetro
) -> Dict[str, Any]:
    """
    Envía notificación por email cuando el análisis está listo
    MODIFICADO: Ahora recibe dashboard_link con token incluido
    """
    try:
        # Crear mensaje
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'✅ Your X/Twitter Analysis is Ready! (@{username})'
        msg['From'] = GMAIL_USER
        msg['To'] = recipient_email
        
        # Extraer estadísticas
        total_tweets = stats.get('total_tweets', 0)
        high_risk = stats.get('high_risk', 0)
        mid_risk = stats.get('mid_risk', 0)
        low_risk = stats.get('low_risk', 0)
        clean_posts = total_tweets - (high_risk + mid_risk + low_risk)
        
        # Template HTML
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                /* ... (estilos iguales) ... */
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🎉 Your Analysis is Complete!</h1>
            </div>
            
            <div class="content">
                <p class="greeting">Hi <strong>@{username}</strong>! 👋</p>
                
                <p>Great news! Your X/Twitter background check analysis has been completed successfully.</p>
                
                <div class="stats-box">
                    <h2>📊 Analysis Summary</h2>
                    <!-- ... estadísticas ... -->
                </div>
                
                <div style="text-align: center;">
                    <a href="{dashboard_link}" class="cta-button">
                        🔗 View Your Full Dashboard
                    </a>
                </div>
                
                <p style="font-size: 13px; color: #6c757d; text-align: center; margin-top: 10px;">
                    ⏰ This link expires in 48 hours
                </p>
                
                <!-- ... resto del HTML ... -->
            </div>
        </body>
        </html>
        """
        
        # Versión texto también con el link correcto
        text_content = f"""
Hi @{username}! 👋

Your X/Twitter background check analysis is complete.

📊 Analysis Summary:
• Total posts analyzed: {stats['total_tweets']:,}
• 🔴 High risk: {stats['high_risk']}
• 🟡 Medium risk: {stats['mid_risk']}
• 🟠 Low risk: {stats['low_risk']}

🔗 View Your Dashboard:
{dashboard_link}

⏰ This link expires in 48 hours

---
Background Checker
    Protect your digital reputation
        """
        
        # Adjuntar ambas versiones
        part1 = MIMEText(text_content, 'plain')
        part2 = MIMEText(html_content, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Enviar email
        print(f"\n📧 Enviando email a: {recipient_email}")
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email enviado exitosamente a {recipient_email}")
        
        return {
            'success': True,
            'message': f'Email sent to {recipient_email}',
            'recipient': recipient_email
        }
        
    except Exception as e:
        print(f"❌ Error enviando email: {str(e)}")
        return {'success': False, 'error': str(e)}


# Credenciales OAuth
oauth_creds = get_oauth2_credentials()
CLIENT_ID = oauth_creds['client_id']
CLIENT_SECRET = oauth_creds['client_secret']
REDIRECT_URI = f"{BACKEND_URL}/api/auth/callback"
FRONTEND_CALLBACK_URL = f"{FRONTEND_URL}/callback"
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
    allow_origins=[
        "https://tff-bgchecker-frontend.vercel.app",
        "https://frontend-tff.vercel.app",
        "http://localhost:5173"  # Para desarrollo local
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# ============================================================================
# Almacenamiento en memoria (solo para sesiones OAuth)
# ============================================================================

oauth_sessions: Dict[str, Dict[str, Any]] = {}
background_jobs: Dict[str, Dict[str, Any]] = {}
request_cache: Dict[str, Any] = {}  # Cache para prevenir requests duplicadas
deletion_rate_limit: Dict[str, Dict[str, Any]] = {}
DELETION_COOLDOWN_SECONDS = 300  # 5 minutos entre eliminaciones por usuario

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
    MODIFICADO: Agrega flag email_sent = False
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
        "execution_time": classification_data.get("execution_time", "0s"),
        "email_sent": False,  # ← NUEVO: Flag para trackear email
        "email_sent_at": None  # ← NUEVO: Timestamp cuando se envió
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
    background_tasks: BackgroundTasks,
    session_id: str = Query(..., description="Session ID")
):
    """
    ✅ VERSIÓN ASÍNCRONA: Inicia búsqueda en background y retorna job_id inmediatamente
    Esto evita el timeout de 60s de Vercel
    """
    # Validar sesión
    session = get_session(session_id)
    if not session or not session.get('user'):
        raise HTTPException(status_code=401, detail="Sesión inválida")
    
    username = session['user']['username']
    
    # Crear job ID único
    job_id = str(uuid.uuid4())
    
    print(f"\n{'='*70}")
    print(f"🚀 CREANDO JOB ASÍNCRONO")
    print(f"{'='*70}")
    print(f"   Job ID: {job_id}")
    print(f"   Usuario: @{username}")
    print(f"   Max tweets: {request.max_tweets or 'Todos'}")
    print(f"   Session ID: {session_id[:30]}...")
    print(f"{'='*70}\n")
    
    # Inicializar job status
    background_jobs[job_id] = {
        'status': 'pending',
        'username': username,
        'progress': 0,
        'total_tweets': 0,
        'current_page': 0,
        'message': 'Iniciando búsqueda de tweets...',
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        'result': None,
        'error': None,
        'wait_until': None,
        'wait_seconds': None
    }
    
    # Agregar tarea en background (NO esperar resultado)
    background_tasks.add_task(
        process_tweets_search_background,
        job_id=job_id,
        username=username,
        max_tweets=request.max_tweets,
        save_to_firebase=request.save_to_firebase,
        session_id=session_id
    )
    
    print(f"✅ Job {job_id} agregado a background_tasks")
    
    # ✅ RETORNAR INMEDIATAMENTE (sin esperar resultado)
    return {
        "success": True,
        "job_id": job_id,
        "status": "pending",
        "message": "Búsqueda iniciada en background. Usa GET /api/jobs/{job_id} para verificar progreso"
    }


# ============================================================================
# NUEVA FUNCIÓN: Procesa búsqueda en background
# ============================================================================

def process_tweets_search_background(
    job_id: str,
    username: str,
    max_tweets: Optional[int],
    save_to_firebase: bool,
    session_id: str
):
    """
    ✅ Procesa la búsqueda de tweets EN BACKGROUND
    Actualiza background_jobs[job_id] con el progreso en tiempo real
    """
    try:
        print(f"\n{'='*70}")
        print(f"🔄 BACKGROUND JOB INICIADO: {job_id}")
        print(f"{'='*70}")
        print(f"   Usuario: @{username}")
        print(f"   Thread: {threading.current_thread().name}")
        print(f"{'='*70}\n")
        
        # Actualizar status a "searching"
        background_jobs[job_id]['status'] = 'searching'
        background_jobs[job_id]['message'] = 'Obteniendo tweets de Twitter...'
        background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
        
        # ✅ Llamar a fetch_user_tweets_with_progress (versión mejorada)
        result = fetch_user_tweets_with_progress(
            username=username,
            max_tweets=max_tweets,
            job_id=job_id
        )
        
        if not result.get('success'):
            background_jobs[job_id]['status'] = 'error'
            background_jobs[job_id]['error'] = result.get('error', 'Error desconocido')
            background_jobs[job_id]['message'] = f"Error: {result.get('error')}"
            background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
            print(f"❌ Job {job_id} falló: {result.get('error')}")
            return
        
        print(f"✅ Tweets obtenidos: {len(result.get('tweets', []))}")
        
        # Guardar en Firebase
        firebase_doc_id = None
        if save_to_firebase and db:
            try:
                background_jobs[job_id]['message'] = 'Guardando tweets en Firebase...'
                background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
                
                firebase_doc_id = save_tweets_to_firebase(username, result)
                print(f"✅ Guardado en Firebase: {firebase_doc_id}")
            except Exception as fb_error:
                print(f"⚠️ Error guardando en Firebase: {str(fb_error)}")
                import traceback
                traceback.print_exc()
        
        # ✅ Marcar como completado
        user_info = result.get('user', {})
        
        background_jobs[job_id]['status'] = 'completed'
        background_jobs[job_id]['progress'] = 100
        background_jobs[job_id]['message'] = 'Búsqueda completada exitosamente'
        background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
        background_jobs[job_id]['result'] = {
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
        
        print(f"\n{'='*70}")
        print(f"✅ JOB COMPLETADO: {job_id}")
        print(f"{'='*70}")
        print(f"   Tweets: {len(result.get('tweets', []))}")
        print(f"   Tiempo: {result.get('execution_time')}")
        print(f"   Firebase Doc: {firebase_doc_id}")
        print(f"{'='*70}\n")
    
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"❌ ERROR EN BACKGROUND JOB: {job_id}")
        print(f"{'='*70}")
        print(f"Error: {str(e)}")
        print(f"{'='*70}\n")
        
        import traceback
        traceback.print_exc()
        
        background_jobs[job_id]['status'] = 'error'
        background_jobs[job_id]['error'] = str(e)
        background_jobs[job_id]['message'] = f'Error interno: {str(e)}'
        background_jobs[job_id]['updated_at'] = datetime.now().isoformat()


# ============================================================================
# NUEVO ENDPOINT: Verificar estado del job
# ============================================================================

@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    """
    ✅ Obtiene el estado actual de un job en background
    El frontend hace polling cada 3 segundos a este endpoint
    
    Estados posibles:
    - pending: Job creado, esperando inicio
    - searching: Obteniendo tweets de Twitter
    - waiting_rate_limit: Esperando que se reinicie el rate limit
    - completed: Job completado exitosamente
    - error: Job falló
    """
    if job_id not in background_jobs:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    
    job_data = background_jobs[job_id]
    
    response = {
        "job_id": job_id,
        "status": job_data['status'],
        "progress": job_data['progress'],
        "message": job_data['message'],
        "username": job_data['username'],
        "created_at": job_data['created_at'],
        "updated_at": job_data['updated_at'],
        "total_tweets": job_data['total_tweets'],
        "current_page": job_data.get('current_page', 0)
    }
    
    # Si está esperando rate limit, incluir info
    if job_data['status'] == 'waiting_rate_limit':
        response['wait_until'] = job_data.get('wait_until')
        response['wait_seconds'] = job_data.get('wait_seconds')
    
    # Si está completado, incluir el resultado
    if job_data['status'] == 'completed':
        response['result'] = job_data['result']
    
    # Si hay error, incluir detalles
    if job_data['status'] == 'error':
        response['error'] = job_data['error']
    
    return response



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
# API 4: ELIMINACIÓN DE TWEETS (con Firebase)
# ============================================================================

class OAuth2SessionAdapter:
    """Adaptador para convertir session dict en objeto compatible con delete_tweets_batch"""
    def __init__(self, access_token: str):
        self.access_token = access_token
    
    def get_headers(self) -> Dict[str, str]:
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

@app.post("/api/tweets/delete")
async def delete_user_tweets(
    firebase_doc_id: str = Query(..., description="ID del documento de Firebase con los tweets"),
    session_id: str = Query(..., description="Session ID"),
    tweet_ids: str = Query(None, description="IDs de tweets a eliminar (separados por coma)"),
    delete_retweets: bool = Query(True, description="Eliminar retweets"),
    delete_originals: bool = Query(True, description="Eliminar tweets originales"),
    delay_seconds: float = Query(1.0, description="Delay entre eliminaciones (segundos)"),
    delete_from_firebase: bool = Query(True, description="Eliminar también de Firebase")
):
    """
    Elimina tweets específicos del usuario autenticado desde Twitter Y Firebase (Opción A)
    """
    session = get_session(session_id)
    if not session or not session.get('access_token'):
        raise HTTPException(status_code=401, detail="Sesión inválida o sin access token")
    
    username = session.get('user', {}).get('username')
    user_id = session.get('user', {}).get('id')
    
    if not user_id:
        raise HTTPException(status_code=400, detail="No se pudo obtener el user_id")
    
    # ============================================================================
    # RATE LIMITING: Verificar si el usuario puede hacer otra eliminación
    # ============================================================================
    now = time.time()
    user_rate_key = f"{user_id}"
    
    if user_rate_key in deletion_rate_limit:
        last_deletion = deletion_rate_limit[user_rate_key].get('timestamp', 0)
        time_since_last = now - last_deletion
        
        if time_since_last < DELETION_COOLDOWN_SECONDS:
            remaining = int(DELETION_COOLDOWN_SECONDS - time_since_last)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Too many deletion requests",
                    "message": f"Please wait {remaining} seconds before trying again",
                    "retry_after_seconds": remaining,
                    "retry_after_formatted": f"{remaining // 60}m {remaining % 60}s" if remaining >= 60 else f"{remaining}s"
                }
            )
    
    # Obtener tweets desde Firebase
    tweets_data = get_tweets_from_firebase(firebase_doc_id)
    if not tweets_data:
        raise HTTPException(status_code=404, detail=f"No se encontró el documento: {firebase_doc_id}")
    
    all_tweets = tweets_data.get('tweets', [])
    if not all_tweets:
        raise HTTPException(status_code=400, detail="No hay tweets para eliminar")
    
    # ============================================================================
    # FILTRAR TWEETS: Solo eliminar los especificados en tweet_ids
    # ============================================================================
    tweets_to_delete = all_tweets
    
    if tweet_ids:
        try:
            target_ids = set(tweet_ids.split(','))
            tweets_to_delete = [
                t for t in all_tweets 
                if str(t.get('id')) in target_ids
            ]
            print(f"🎯 Filtrado: {len(tweets_to_delete)} de {len(all_tweets)} tweets")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error parsing tweet_ids: {str(e)}")
    
    if not tweets_to_delete:
        raise HTTPException(status_code=400, detail="No tweets found matching the specified IDs")
    
    print(f"\n{'='*70}")
    print(f"🗑️  ELIMINACIÓN DE TWEETS - OPCIÓN A (Twitter + Firebase)")
    print(f"{'='*70}")
    print(f"   Usuario: @{username}")
    print(f"   User ID: {user_id}")
    print(f"   Firebase Doc: {firebase_doc_id}")
    print(f"   Total tweets en Firebase: {len(all_tweets)}")
    print(f"   Tweets a eliminar: {len(tweets_to_delete)}")
    print(f"   Eliminar retweets: {delete_retweets}")
    print(f"   Eliminar originales: {delete_originals}")
    print(f"   Eliminar de Firebase: {delete_from_firebase}")
    print(f"   Delay: {delay_seconds}s")
    print(f"{'='*70}\n")
    
    # Crear adaptador OAuth2Session compatible
    oauth_adapter = OAuth2SessionAdapter(session['access_token'])
    
    # PASO 1: Ejecutar eliminación en Twitter
    try:
        print("🐦 PASO 1: Eliminando tweets de Twitter...")
        result = delete_tweets_batch(
            tweets=tweets_to_delete,
            user_id=user_id,
            session=oauth_adapter,
            delete_retweets=delete_retweets,
            delete_originals=delete_originals,
            delay_seconds=delay_seconds,
            verbose=True
        )
        
        print(f"\n✅ Eliminación de Twitter completada:")
        print(f"   Retweets eliminados: {result['retweets_deleted']}")
        print(f"   Tweets eliminados: {result['tweets_deleted']}")
        print(f"   Fallidos: {len(result['failed'])}")
        
        # ============================================================================
        # ACTUALIZAR RATE LIMIT: Marcar timestamp de esta eliminación
        # ============================================================================
        deletion_rate_limit[user_rate_key] = {
            'timestamp': time.time(),
            'tweets_deleted': result['retweets_deleted'] + result['tweets_deleted']
        }
        
        # PASO 2: Actualizar Firebase (eliminar tweets borrados exitosamente)
        if delete_from_firebase and db:
            print(f"\n🔥 PASO 2: Actualizando Firebase...")
            
            try:
                # IDs de tweets que se eliminaron exitosamente
                deleted_ids = set()
                for tweet in tweets_to_delete:
                    tweet_id = str(tweet.get('id'))
                    # Si NO está en la lista de fallidos, se eliminó exitosamente
                    if not any(str(f.get('tweet_id')) == tweet_id for f in result['failed']):
                        deleted_ids.add(tweet_id)
                
                print(f"   Tweets eliminados exitosamente de Twitter: {len(deleted_ids)}")
                
                # ═══════════════════════════════════════════════════════════════════
                # 2A: Actualizar colección 'user_tweets'
                # ═══════════════════════════════════════════════════════════════════
                print(f"\n   📊 Actualizando 'user_tweets'...")
                doc_ref = db.collection('user_tweets').document(firebase_doc_id)
                doc = doc_ref.get()
                
                if doc.exists:
                    data = doc.to_dict()
                    
                    # Filtrar tweets: mantener solo los que NO se eliminaron
                    original_tweets = data.get('tweets', [])
                    remaining_tweets = [
                        t for t in original_tweets 
                        if str(t.get('id')) not in deleted_ids
                    ]
                    
                    print(f"      Tweets originales: {len(original_tweets)}")
                    print(f"      Tweets restantes: {len(remaining_tweets)}")
                    
                    # Actualizar estadísticas
                    original_stats = data.get('stats', {})
                    new_stats = original_stats.copy()
                    new_stats['total_tweets'] = len(remaining_tweets)
                    
                    # Actualizar documento
                    doc_ref.update({
                        'tweets': remaining_tweets,
                        'stats': new_stats,
                        'last_cleanup': datetime.now(),
                        'cleanup_summary': {
                            'deleted_count': len(deleted_ids),
                            'remaining_count': len(remaining_tweets),
                            'failed_count': len(result['failed']),
                            'timestamp': datetime.now().isoformat()
                        }
                    })
                    
                    print(f"      ✅ 'user_tweets' actualizado")
                    result['firebase_updated'] = True
                    result['firebase_remaining_tweets'] = len(remaining_tweets)
                else:
                    print(f"      ⚠️ Documento 'user_tweets' no encontrado")
                    result['firebase_updated'] = False
                
                # ═══════════════════════════════════════════════════════════════════
                # 2B: Actualizar colección 'risk_classifications' (NUEVO) ⭐
                # ═══════════════════════════════════════════════════════════════════
                print(f"\n   🛡️  Actualizando 'risk_classifications'...")

                # Buscar el documento más reciente de clasificación para este usuario
                classifications_ref = db.collection('risk_classifications')
                query = classifications_ref.where('username', '==', username).order_by('timestamp', direction=firestore.Query.DESCENDING).limit(1)

                try:
                    classification_docs = list(query.stream())
                    
                    if classification_docs:
                        classification_doc = classification_docs[0]
                        classification_data = classification_doc.to_dict()
                        original_results = classification_data.get('results', [])
                        
                        print(f"      Clasificaciones originales: {len(original_results)}")
                        print(f"      IDs a eliminar (deleted_ids): {deleted_ids}")
                        
                        # 🔍 DEBUG: Normalizar AMBOS lados de la comparación
                        deleted_ids_normalized = {str(id).strip() for id in deleted_ids}
                        print(f"      IDs normalizados: {deleted_ids_normalized}")
                        
                        # Mostrar samples de lo que tenemos en results
                        if original_results:
                            sample_result = original_results[0]
                            print(f"      DEBUG - Sample result tweet_id: {sample_result.get('tweet_id')}")
                            print(f"      DEBUG - Sample tweet_id type: {type(sample_result.get('tweet_id'))}")
                            print(f"      DEBUG - Sample tweet_id as string: '{str(sample_result.get('tweet_id')).strip()}'")
                        
                        # 🔍 DEBUG: Verificar qué IDs se están comparando ANTES de filtrar
                        eliminated_count = 0
                        print(f"      🔍 Verificando coincidencias de IDs...")
                        for r in original_results:
                            r_id_normalized = str(r.get('tweet_id')).strip()
                            if r_id_normalized in deleted_ids_normalized:
                                eliminated_count += 1
                                print(f"         ✅ Coincidencia encontrada: {r_id_normalized}")
                        
                        if eliminated_count == 0:
                            print(f"      ⚠️ WARNING: Ningún tweet coincidió para eliminación!")
                            print(f"         Los IDs no están coincidiendo entre deleted_ids y risk_classifications")
                        else:
                            print(f"      ✅ Total de coincidencias: {eliminated_count}")
                        
                        # Filtrar resultados: mantener solo los que NO se eliminaron
                        remaining_results = [
                            r for r in original_results 
                            if str(r.get('tweet_id')).strip() not in deleted_ids_normalized
                        ]
                        
                        print(f"      Clasificaciones restantes después del filtro: {len(remaining_results)}")
                        print(f"      Clasificaciones eliminadas: {len(original_results) - len(remaining_results)}")
                        
                        # Recalcular estadísticas del summary desde cero
                        new_summary = {
                            "total_analyzed": len(remaining_results),
                            "risk_distribution": {"no": 0, "low": 0, "mid": 0, "high": 0},
                            "label_counts": {},
                            "errors": 0
                        }
                        
                        for r in remaining_results:
                            if "error_code" not in r:
                                level = r.get("risk_level", "low")
                                if level in new_summary["risk_distribution"]:
                                    new_summary["risk_distribution"][level] += 1
                                for label in r.get("labels", []):
                                    new_summary["label_counts"][label] = new_summary["label_counts"].get(label, 0) + 1
                            else:
                                new_summary["errors"] += 1
                        
                        print(f"      Nuevo summary calculado:")
                        print(f"         Total: {new_summary['total_analyzed']}")
                        print(f"         High: {new_summary['risk_distribution']['high']}")
                        print(f"         Mid: {new_summary['risk_distribution']['mid']}")
                        print(f"         Low: {new_summary['risk_distribution']['low']}")
                        print(f"         No: {new_summary['risk_distribution']['no']}")
                        
                        # Actualizar documento de clasificación
                        classification_doc.reference.update({
                            'results': remaining_results,
                            'summary': new_summary,
                            'total_tweets': len(remaining_results),
                            'last_cleanup': datetime.now(),
                            'cleanup_info': {
                                'deleted_count': len(deleted_ids),
                                'remaining_count': len(remaining_results),
                                'timestamp': datetime.now().isoformat()
                            }
                        })
                        
                        print(f"      ✅ 'risk_classifications' actualizado correctamente")
                        result['firebase_classification_updated'] = True
                        result['firebase_remaining_classifications'] = len(remaining_results)
                    else:
                        print(f"      ℹ️  No se encontró documento de clasificación para actualizar")
                        result['firebase_classification_updated'] = False

                except Exception as query_error:
                    print(f"      ⚠️ Error en query de clasificación: {str(query_error)}")
                    import traceback
                    traceback.print_exc()
                    result['firebase_classification_updated'] = False
                    result['firebase_classification_error'] = str(query_error)
            except Exception as fb_error:
                print(f"\n⚠️ Error actualizando Firebase: {str(fb_error)}")
                import traceback
                traceback.print_exc()
                result['firebase_updated'] = False
                result['firebase_error'] = str(fb_error)
                # No fallar si Firebase falla, continuar
        
        # PASO 3: Guardar reporte de eliminación
        if db:
            timestamp = datetime.now()
            report_id = f"{username}_deletion_{timestamp.strftime('%Y%m%d_%H%M%S')}"
            
            report_data = {
                "username": username,
                "user_id": user_id,
                "timestamp": timestamp,
                "source_firebase_doc": firebase_doc_id,
                "deletion_type": "full",
                "tweets_requested": len(tweets_to_delete),
                "result": result,
                "config": {
                    "delete_retweets": delete_retweets,
                    "delete_originals": delete_originals,
                    "delete_from_firebase": delete_from_firebase,
                    "delay_seconds": delay_seconds
                }
            }
            
            db.collection('deletion_reports').document(report_id).set(report_data)
            print(f"\n✅ Reporte guardado en Firebase: {report_id}")
            result['firebase_report_id'] = report_id
        
        print(f"\n{'='*70}")
        print(f"✅ ELIMINACIÓN TOTAL COMPLETADA")
        print(f"{'='*70}")
        print(f"   Tweets eliminados de Twitter: {result['tweets_deleted'] + result['retweets_deleted']}")
        print(f"   Tweets eliminados de Firebase: {len(deleted_ids) if delete_from_firebase else 0}")
        print(f"   Fallidos: {len(result['failed'])}")
        print(f"{'='*70}\n")
        
        return {
            "success": True,
            "username": username,
            "result": result
        }
    
    except Exception as e:
        print(f"\n❌ Error durante eliminación: {str(e)}\n")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error eliminando tweets: {str(e)}")

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
# MODIFICAR: Endpoint de Notificación por Email
# ============================================================================
@app.post("/api/notifications/send-analysis-ready")
async def send_analysis_ready_notification(
    session_id: str = Query(..., description="Session ID"),
    tweets_firebase_id: str = Query(..., description="Firebase doc ID de tweets"),
    classification_firebase_id: str = Query(..., description="Firebase doc ID de clasificación")
):
    """
    Envía email de notificación cuando el análisis está completo
    SIMPLIFICADO: Link directo con Firebase IDs (sin tokens)
    """
    try:
        # Validar sesión
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=401, detail="Sesión inválida")
        
        username = session.get('user', {}).get('username', 'unknown')
        
        print(f"\n{'='*70}")
        print(f"📧 VERIFICANDO ENVÍO DE EMAIL")
        print(f"{'='*70}")
        print(f"   Usuario: @{username}")
        print(f"   Classification Doc: {classification_firebase_id}")
        print(f"{'='*70}\n")
        
        # ═══════════════════════════════════════════════════════════════════
        # VERIFICAR SI EL EMAIL YA FUE ENVIADO
        # ═══════════════════════════════════════════════════════════════════
        if not db:
            raise HTTPException(status_code=500, detail="Firebase no está inicializado")
        
        # Obtener documento de clasificación
        classification_ref = db.collection('risk_classifications').document(classification_firebase_id)
        classification_doc = classification_ref.get()
        
        if not classification_doc.exists:
            raise HTTPException(
                status_code=404,
                detail="No se encontraron datos de clasificación"
            )
        
        classification_data = classification_doc.to_dict()
        
        # Verificar flag email_sent
        email_already_sent = classification_data.get('email_sent', False)
        
        if email_already_sent:
            email_sent_at = classification_data.get('email_sent_at')
            print(f"ℹ️  Email ya fue enviado anteriormente")
            print(f"   Enviado en: {email_sent_at}")
            print(f"   Saltando envío duplicado...")
            
            return {
                'success': True,
                'message': 'Email was already sent for this analysis',
                'already_sent': True,
                'sent_at': email_sent_at.isoformat() if email_sent_at else None
            }
        
        print(f"✅ Email no ha sido enviado, procediendo...")
        
        # Extraer estadísticas
        summary = classification_data.get('summary', {})
        risk_dist = summary.get('risk_distribution', {})
        
        stats = {
            'total_tweets': summary.get('total_analyzed', 0),
            'high_risk': risk_dist.get('high', 0),
            'mid_risk': risk_dist.get('mid', 0),
            'low_risk': risk_dist.get('low', 0)
        }
        
        print(f"📊 Estadísticas a enviar:")
        print(f"   Total: {stats['total_tweets']}")
        print(f"   High: {stats['high_risk']}")
        print(f"   Mid: {stats['mid_risk']}")
        print(f"   Low: {stats['low_risk']}")
        
        # ═══════════════════════════════════════════════════════════════════
        # CREAR LINK CON FIREBASE IDs (SIN TOKENS)
        # ═══════════════════════════════════════════════════════════════════
        dashboard_link = (
            f"{FRONTEND_URL}/dashboard?"
            f"tweets_id={tweets_firebase_id}&"
            f"classification_id={classification_firebase_id}&"
            f"username={username}"
        )
        
        print(f"🔗 Dashboard link: {dashboard_link}")
        # ═══════════════════════════════════════════════════════════════════
        
        # Enviar email
        result = send_email_notification(
            username=username,
            stats=stats,
            recipient_email=RECIPIENT_EMAIL,
            dashboard_link=dashboard_link
        )
        
        if not result['success']:
            raise HTTPException(
                status_code=500,
                detail=f"Error enviando email: {result.get('error')}"
            )
        
        # ═══════════════════════════════════════════════════════════════════
        # MARCAR EMAIL COMO ENVIADO EN FIREBASE
        # ═══════════════════════════════════════════════════════════════════
        timestamp = datetime.now()
        
        classification_ref.update({
            'email_sent': True,
            'email_sent_at': timestamp,
            'dashboard_link': dashboard_link
        })
        
        print(f"✅ Documento actualizado: email_sent = True")
        # ═══════════════════════════════════════════════════════════════════
        
        # Guardar log en Firebase
        if db:
            log_id = f"{username}_email_{timestamp.strftime('%Y%m%d_%H%M%S')}"
            
            log_data = {
                'username': username,
                'recipient_email': RECIPIENT_EMAIL,
                'notification_type': 'analysis_ready',
                'sent_at': timestamp,
                'status': 'sent',
                'stats': stats,
                'tweets_doc_id': tweets_firebase_id,
                'classification_doc_id': classification_firebase_id,
                'dashboard_link': dashboard_link
            }
            
            db.collection('email_notifications').document(log_id).set(log_data)
            print(f"✅ Log guardado en Firebase: {log_id}")
        
        print(f"\n{'='*70}")
        print(f"✅ EMAIL ENVIADO EXITOSAMENTE")
        print(f"{'='*70}\n")
        
        return {
            'success': True,
            'message': 'Email notification sent successfully',
            'recipient': RECIPIENT_EMAIL,
            'stats': stats,
            'dashboard_link': dashboard_link,
            'already_sent': False
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en endpoint de notificación: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail=f"Error enviando notificación: {str(e)}"
        )


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
            "delete": "/api/tweets/delete",
            "estimate": "/api/estimate/time",
            "docs": "/docs"
        }
    }
@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str):
    """Handle CORS preflight requests"""
    return Response(
        content="",
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "https://tff-bgchecker-frontend.vercel.app",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Credentials": "true"
        }
    )

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
    session_id: str = Query(None),  # ← Ahora es opcional
    tweets_doc_id: str = Query(None),
    classification_doc_id: str = Query(None)
):
    """
    Recupera datos desde Firebase usando los doc IDs
    
    MODIFICADO: Ya no requiere validación de sesión OAuth
    Los datos en Firebase ya son del usuario, no hay riesgo de seguridad
    """
    
    # Validación básica de parámetros
    if not tweets_doc_id and not classification_doc_id:
        raise HTTPException(
            status_code=400,
            detail="Se requiere al menos tweets_doc_id o classification_doc_id"
        )
    
    # OPCIONAL: Validar session_id si se proporciona (para usuarios logueados)
    # Pero si viene desde token, no habrá session_id válido y está OK
    if session_id:
        session = get_session(session_id)
        if session:
            username = session.get('user', {}).get('username')
            print(f"✅ Request from authenticated user: @{username}")
        else:
            print(f"ℹ️  Session ID provided but invalid (token access)")
    else:
        print(f"ℹ️  No session ID provided (token access)")
    
    result = {}
    
    try:
        # Obtener tweets si se proporciona el ID
        if tweets_doc_id:
            print(f"📊 Fetching tweets from Firebase: {tweets_doc_id}")
            tweets_data = get_tweets_from_firebase(tweets_doc_id)
            if tweets_data:
                result["tweets"] = tweets_data
                print(f"✅ Tweets loaded: {len(tweets_data.get('tweets', []))} tweets")
            else:
                print(f"⚠️ No tweets found for doc: {tweets_doc_id}")
        
        # Obtener clasificación si se proporciona el ID
        if classification_doc_id:
            print(f"🛡️ Fetching classification from Firebase: {classification_doc_id}")
            classification_data = get_classification_from_firebase(classification_doc_id)
            if classification_data:
                result["classification"] = classification_data
                print(f"✅ Classification loaded: {len(classification_data.get('results', []))} results")
            else:
                print(f"⚠️ No classification found for doc: {classification_doc_id}")
        
        # Verificar que se encontró al menos un documento
        if not result:
            raise HTTPException(
                status_code=404,
                detail="No se encontraron datos en Firebase con los IDs proporcionados"
            )
        
        return {
            "success": True,
            "data": result
        }
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error obteniendo datos de Firebase: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo datos: {str(e)}"
        )

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
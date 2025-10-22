"""
Twitter OAuth 2.0 Login (PKCE flow para consola)
Compatible con plan Basic de X API
Permite que usuarios hagan login con su cuenta de Twitter desde consola
"""

import requests
import secrets
import hashlib
import base64
import webbrowser
from urllib.parse import urlencode, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import json


# ==============================================
# CONFIGURACIÓN
# ==============================================
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_oauth2_credentials

# Obtener credenciales desde config
try:
    oauth_creds = get_oauth2_credentials()
    CLIENT_ID = oauth_creds['client_id']
    CLIENT_SECRET = oauth_creds['client_secret']
except ValueError as e:
    CLIENT_ID = None
    CLIENT_SECRET = None
    print(f"⚠️  Advertencia: {e}")

REDIRECT_URI = "http://127.0.0.1:8080/callback"  # Debe estar configurado en X Developer Portal

# Endpoints OAuth 2.0
AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
USER_INFO_URL = "https://api.twitter.com/2/users/me"

# Scopes que solicitaremos
SCOPES = [
    "tweet.read",
    "users.read",
    "follows.read",
    "offline.access"  # Para refresh token
]


# ==============================================
# PKCE (Proof Key for Code Exchange)
# ==============================================

def generate_code_verifier():
    """Genera un code_verifier aleatorio para PKCE"""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')
    return code_verifier.rstrip('=')


def generate_code_challenge(verifier):
    """Genera code_challenge desde el verifier usando SHA256"""
    digest = hashlib.sha256(verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode('utf-8')
    return code_challenge.rstrip('=')


# ==============================================
# SERVIDOR LOCAL PARA CAPTURAR CALLBACK
# ==============================================

class CallbackHandler(BaseHTTPRequestHandler):
    """Maneja el callback de OAuth"""
    
    authorization_code = None
    state = None
    error = None
    
    def do_GET(self):
        """Captura el código de autorización del callback"""
        # Parsear query params
        query = self.path.split('?', 1)[-1]
        params = parse_qs(query)
        
        # Extraer código y state
        CallbackHandler.authorization_code = params.get('code', [None])[0]
        CallbackHandler.state = params.get('state', [None])[0]
        CallbackHandler.error = params.get('error', [None])[0]
        
        # Enviar respuesta al navegador
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        if CallbackHandler.authorization_code:
            html = """
            <html>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: #1DA1F2;"> ¡Autorización exitosa!</h1>
                <p>Ya puedes cerrar esta ventana y volver a la consola.</p>
            </body>
            </html>
            """
        else:
            html = f"""
            <html>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: #e0245e;"> Error en autorización</h1>
                <p>{CallbackHandler.error or 'Error desconocido'}</p>
            </body>
            </html>
            """
        
        self.wfile.write(html.encode())
    
    def log_message(self, format, *args):
        """Silenciar logs del servidor"""
        pass


def start_callback_server(timeout=120):
    """
    Inicia servidor local temporal para capturar el callback
    
    Args:
        timeout: Segundos a esperar por el callback
    
    Returns:
        Tupla (authorization_code, state, error)
    """
    server = HTTPServer(('127.0.0.1', 8080), CallbackHandler)
    
    # Ejecutar servidor en thread separado
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()
    
    print(f" Servidor local iniciado en {REDIRECT_URI}")
    print(f" Esperando autorización (timeout: {timeout}s)...")
    
    # Esperar a que el thread termine o timeout
    server_thread.join(timeout=timeout)
    
    # Cerrar servidor
    server.server_close()
    
    return (
        CallbackHandler.authorization_code,
        CallbackHandler.state,
        CallbackHandler.error
    )


# ==============================================
# FLUJO OAUTH 2.0
# ==============================================

def initiate_login():
    """
    Inicia el proceso completo de login OAuth 2.0
    
    Returns:
        dict con credenciales del usuario o None si falla
    """
    try:
        print("\n" + "=" * 60)
        print(" INICIANDO LOGIN OAUTH 2.0 CON TWITTER")
        print("=" * 60)
        
        # Validar configuración
        if not CLIENT_ID or not CLIENT_SECRET:
            print("\n ERROR: Credenciales OAuth 2.0 no configuradas")
            print("   Configura las variables de entorno:")
            print("   - X_CLIENT_ID")
            print("   - X_CLIENT_SECRET")
            print("\n   O agrégalas en config.py")
            print("\n   Obtén tus credenciales en:")
            print("   https://developer.x.com/en/portal/dashboard")
            return None
        
        # =====================================
        # PASO 1: Generar PKCE
        # =====================================
        print("\n Paso 1/4: Generando parámetros PKCE...")
        
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = secrets.token_urlsafe(32)
        
        print(f" Code verifier generado: {code_verifier[:20]}...")
        print(f" Code challenge: {code_challenge[:20]}...")
        print(f" State: {state[:20]}...")
        
        # =====================================
        # PASO 2: URL de autorización
        # =====================================
        print("\n Paso 2/4: Generando URL de autorización...")
        
        auth_params = {
            'response_type': 'code',
            'client_id': CLIENT_ID,
            'redirect_uri': REDIRECT_URI,
            'scope': ' '.join(SCOPES),
            'state': state,
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }
        
        authorization_url = f"{AUTH_URL}?{urlencode(auth_params)}"
        
        print("\n" + "-" * 60)
        print(" Abriendo navegador para autorizar...")
        print("-" * 60)
        
        # Abrir navegador
        try:
            webbrowser.open(authorization_url)
            print(" Navegador abierto automáticamente")
        except:
            print("  No se pudo abrir automáticamente")
            print(f"\n Abre esta URL manualmente:")
            print(f"\n   {authorization_url}\n")
        
        # =====================================
        # PASO 3: Capturar código de autorización
        # =====================================
        print("\n Paso 3/4: Esperando autorización del usuario...")
        
        # Iniciar servidor temporal
        auth_code, returned_state, error = start_callback_server(timeout=120)
        
        if error:
            print(f"\n Error en autorización: {error}")
            return None
        
        if not auth_code:
            print("\n Timeout: No se recibió código de autorización")
            print("   El usuario no autorizó o el proceso tardó más de 2 minutos")
            return None
        
        # Verificar state para prevenir CSRF
        if returned_state != state:
            print("\n Error de seguridad: State no coincide (posible ataque CSRF)")
            return None
        
        print(f" Código de autorización recibido: {auth_code[:20]}...")
        
        # =====================================
        # PASO 4: Intercambiar código por tokens
        # =====================================
        print("\n Paso 4/4: Intercambiando código por tokens de acceso...")
        
        # Crear autenticación básica con Client ID y Secret
        auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
        auth_bytes = auth_string.encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
        
        token_data = {
            'code': auth_code,
            'grant_type': 'authorization_code',
            'redirect_uri': REDIRECT_URI,
            'code_verifier': code_verifier
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Basic {auth_b64}'
        }
        
        response = requests.post(TOKEN_URL, data=token_data, headers=headers)
        
        if response.status_code != 200:
            print(f"\n Error obteniendo tokens: {response.status_code}")
            print(f"   {response.text}")
            return None
        
        tokens = response.json()
        
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        expires_in = tokens.get('expires_in')
        
        if not access_token:
            print("\n No se recibió access token")
            return None
        
        print(f" Access token obtenido: {access_token[:20]}...")
        if refresh_token:
            print(f" Refresh token obtenido: {refresh_token[:20]}...")
        print(f" Expira en: {expires_in} segundos ({expires_in//3600} horas)")
        
        # =====================================
        # PASO 5: Obtener información del usuario
        # =====================================
        print("\n Obteniendo información del usuario...")
        
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'user.fields': 'id,name,username,public_metrics,created_at,description'}
        
        user_response = requests.get(USER_INFO_URL, headers=headers, params=params)
        
        if user_response.status_code != 200:
            print(f"  No se pudo obtener info del usuario: {user_response.status_code}")
            user_data = None
        else:
            user_data = user_response.json().get('data', {})
        
        # =====================================
        # RESULTADO FINAL
        # =====================================
        print("\n" + "=" * 60)
        print(" ¡LOGIN EXITOSO!")
        print("=" * 60)
        
        if user_data:
            print(f"👤 Nombre: {user_data.get('name')}")
            print(f"🔖 Usuario: @{user_data.get('username')}")
            print(f"🆔 User ID: {user_data.get('id')}")
            
            metrics = user_data.get('public_metrics', {})
            if metrics:
                print(f"👥 Seguidores: {metrics.get('followers_count', 0):,}")
                print(f"📊 Siguiendo: {metrics.get('following_count', 0):,}")
                print(f"📝 Tweets: {metrics.get('tweet_count', 0):,}")
            
            if user_data.get('description'):
                bio = user_data.get('description', '')[:100]
                print(f"📝 Bio: {bio}...")
        
        print("=" * 60)
        
        # Retornar credenciales
        return {
            'success': True,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': expires_in,
            'token_type': tokens.get('token_type', 'bearer'),
            'user': user_data
        }
        
    except Exception as e:
        print(f"\n Error durante el login: {e}")
        import traceback
        traceback.print_exc()
        return None


# ==============================================
# FUNCIONES AUXILIARES
# ==============================================

def save_session(credentials, filename='oauth2_session.json'):
    """Guarda la sesión OAuth en un archivo"""
    if not credentials or not credentials.get('success'):
        print(" No hay credenciales para guardar")
        return False
    
    try:
        session_data = {
            'access_token': credentials['access_token'],
            'refresh_token': credentials.get('refresh_token'),
            'expires_in': credentials['expires_in'],
            'token_type': credentials['token_type'],
            'user': credentials.get('user')
        }
        
        with open(filename, 'w') as f:
            json.dump(session_data, f, indent=2)
        
        print(f"\n💾 Sesión guardada en: {filename}")
        print("⚠️  IMPORTANTE: Este archivo contiene tokens sensibles")
        print("   No lo compartas ni lo subas a repositorios públicos")
        
        return True
    except Exception as e:
        print(f" Error guardando sesión: {e}")
        return False


def load_session(filename='oauth2_session.json'):
    """Carga una sesión OAuth guardada"""
    import os
    
    if not os.path.exists(filename):
        print(f"  No se encontró archivo de sesión: {filename}")
        return None
    
    try:
        with open(filename, 'r') as f:
            session_data = json.load(f)
        
        user = session_data.get('user', {})
        username = user.get('username', 'Unknown')
        
        print(f"\n📂 Sesión cargada: @{username}")
        
        return session_data
    except Exception as e:
        print(f" Error cargando sesión: {e}")
        return None


def test_access_token(access_token):
    """Prueba que el access token funcione haciendo un request simple"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'user.fields': 'username,name'}
        
        response = requests.get(USER_INFO_URL, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            print(f"\n Token válido - Usuario: @{data.get('username')}")
            return True
        else:
            print(f"\n Token inválido o expirado: {response.status_code}")
            return False
    except Exception as e:
        print(f" Error probando token: {e}")
        return False


# ==============================================
# EJEMPLO DE USO
# ==============================================

if __name__ == "__main__":
    print("\n🐦 TWITTER OAUTH 2.0 LOGIN")
    print("Compatible con plan Basic de X API")
    print("=" * 60)
    
    # Iniciar login
    credentials = initiate_login()
    
    if credentials and credentials.get('success'):
        # Guardar sesión
        print("\n" + "-" * 60)
        save_choice = input("💾 ¿Guardar sesión para uso futuro? (s/n): ").lower().strip()
        
        if save_choice == 's':
            save_session(credentials)
        
        # Probar token
        print("\n" + "-" * 60)
        print(" Probando access token...")
        test_access_token(credentials['access_token'])
        
    else:
        print("\n Login fallido. Revisa la configuración y vuelve a intentar.")
    
    print("\n" + "=" * 60)
    print("Proceso completado")
    print("=" * 60)
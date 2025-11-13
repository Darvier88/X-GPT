"""
Twitter OAuth 2.0 Login con Prueba Completa de Scopes
Prueba cada permiso (scope) individualmente para verificar configuración
Compatible con plan Basic de X API
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
import os
from datetime import datetime


# ==============================================
# CONFIGURACIÓN
# ==============================================
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from config import get_oauth2_credentials
    oauth_creds = get_oauth2_credentials()
    CLIENT_ID = oauth_creds['client_id']
    CLIENT_SECRET = oauth_creds['client_secret']
except (ValueError, ImportError) as e:
    CLIENT_ID = os.environ.get('X_CLIENT_ID')
    CLIENT_SECRET = os.environ.get('X_CLIENT_SECRET')
    if not CLIENT_ID or not CLIENT_SECRET:
        print(f"⚠️  Advertencia: {e}")

REDIRECT_URI = "http://127.0.0.1:8080/callback"

# Endpoints OAuth 2.0
AUTH_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.twitter.com/2/oauth2/token"
USER_INFO_URL = "https://api.twitter.com/2/users/me"

# Todos los scopes disponibles en X API
AVAILABLE_SCOPES = {
    'tweet.read': 'Leer tweets',
    'tweet.write': 'Crear y eliminar tweets',
    'tweet.moderate.write': 'Ocultar/mostrar respuestas',
    'users.read': 'Leer información de usuarios',
    'follows.read': 'Ver quién sigues y te sigue',
    'follows.write': 'Seguir y dejar de seguir cuentas',
    'offline.access': 'Mantener acceso (refresh token)',
    'space.read': 'Leer información de Spaces',
    'mute.read': 'Ver cuentas silenciadas',
    'mute.write': 'Silenciar y desilenciar cuentas',
    'like.read': 'Ver likes',
    'like.write': 'Dar y quitar likes',
    'list.read': 'Leer listas',
    'list.write': 'Crear y gestionar listas',
    'block.read': 'Ver cuentas bloqueadas',
    'block.write': 'Bloquear y desbloquear cuentas',
    'bookmark.read': 'Ver bookmarks',
    'bookmark.write': 'Crear y eliminar bookmarks',
    'dm.read': 'Leer mensajes directos',
    'dm.write': 'Enviar mensajes directos'
}

# Scopes que vamos a solicitar (ajusta según tus necesidades)
REQUESTED_SCOPES = [
    "tweet.read",
    "tweet.write",
    "users.read",
    "offline.access"
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
        query = self.path.split('?', 1)[-1]
        params = parse_qs(query)
        
        CallbackHandler.authorization_code = params.get('code', [None])[0]
        CallbackHandler.state = params.get('state', [None])[0]
        CallbackHandler.error = params.get('error', [None])[0]
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        if CallbackHandler.authorization_code:
            html = """
            <html>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: #1DA1F2;">✅ ¡Autorización exitosa!</h1>
                <p>Ya puedes cerrar esta ventana y volver a la consola.</p>
                <p style="color: #666;">Verificando permisos...</p>
            </body>
            </html>
            """
        else:
            html = f"""
            <html>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: #e0245e;">❌ Error en autorización</h1>
                <p>{CallbackHandler.error or 'Error desconocido'}</p>
            </body>
            </html>
            """
        
        self.wfile.write(html.encode())
    
    def log_message(self, format, *args):
        """Silenciar logs del servidor"""
        pass


def start_callback_server(timeout=120):
    """Inicia servidor local temporal para capturar el callback"""
    server = HTTPServer(('127.0.0.1', 8080), CallbackHandler)
    
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()
    
    print(f"🌐 Servidor local iniciado en {REDIRECT_URI}")
    print(f"⏳ Esperando autorización (timeout: {timeout}s)...")
    
    server_thread.join(timeout=timeout)
    server.server_close()
    
    return (
        CallbackHandler.authorization_code,
        CallbackHandler.state,
        CallbackHandler.error
    )


# ==============================================
# FUNCIONES DE PRUEBA DE SCOPES
# ==============================================

def test_tweet_read(access_token, user_id):
    """Prueba el scope tweet.read"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        url = f"https://api.twitter.com/2/users/{user_id}/tweets"
        params = {
            'max_results': 5,
            'tweet.fields': 'created_at,public_metrics'
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            tweet_count = len(data.get('data', []))
            return True, f"✅ Puede leer tweets ({tweet_count} tweets recientes encontrados)"
        elif response.status_code == 403:
            return False, "❌ Permiso denegado - Verifica que tweet.read esté habilitado"
        else:
            return False, f"❌ Error {response.status_code}: {response.text[:100]}"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:100]}"


def test_tweet_write(access_token):
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        # Payload inválido a propósito: falta 'text'
        response = requests.post(
            "https://api.twitter.com/2/tweets",
            headers=headers,
            json={}  # provoca 400 si tienes permiso de acceso al endpoint
        )
        if response.status_code in (200, 201):
            return True, "✅ Puede crear tweets (se publicó un tweet de prueba)"
        if response.status_code == 400:
            # Autorizado al endpoint, pero validación falló: permiso existe
            return True, "✅ Tiene permiso tweet.write (verificado sin publicar)"
        if response.status_code == 403:
            return False, "❌ Permiso denegado - tweet.write NO está habilitado"
        if response.status_code == 401:
            return False, "❌ Token inválido o expirado"
        return False, f"⚠️ Estado {response.status_code}: {response.text[:160]}"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:160]}"



def test_users_read(access_token):
    """Prueba el scope users.read"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {
            'user.fields': 'id,name,username,description,public_metrics,created_at,verified'
        }
        
        response = requests.get(USER_INFO_URL, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            username = data.get('username', 'Unknown')
            return True, f"✅ Puede leer info de usuarios (Usuario: @{username})"
        elif response.status_code == 403:
            return False, "❌ Permiso denegado - users.read NO está habilitado"
        else:
            return False, f"❌ Error {response.status_code}: {response.text[:100]}"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:100]}"


def test_follows_read(access_token, user_id):
    """Prueba el scope follows.read"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        url = f"https://api.twitter.com/2/users/{user_id}/following"
        params = {'max_results': 5}
        
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            following_count = len(data.get('data', []))
            return True, f"✅ Puede leer follows ({following_count} usuarios siguiendo)"
        elif response.status_code == 403:
            return False, "❌ Permiso denegado - follows.read NO está habilitado"
        else:
            return False, f"❌ Error {response.status_code}: {response.text[:100]}"
    except Exception as e:
        return False, f"❌ Error: {str(e)[:100]}"


def test_offline_access(refresh_token):
    """Verifica si se obtuvo refresh token"""
    if refresh_token:
        return True, f"✅ Refresh token obtenido (offline.access habilitado)"
    else:
        return False, "❌ No se obtuvo refresh token - offline.access NO está habilitado"


# ==============================================
# FLUJO OAUTH 2.0
# ==============================================

def initiate_login_with_scope_testing():
    """
    Inicia el proceso completo de login OAuth 2.0 y prueba todos los scopes
    
    Returns:
        dict con credenciales del usuario o None si falla
    """
    try:
        print("\n" + "=" * 70)
        print("🐦 INICIANDO LOGIN OAUTH 2.0 CON TWITTER - PRUEBA DE SCOPES")
        print("=" * 70)
        
        # Validar configuración
        if not CLIENT_ID or not CLIENT_SECRET:
            print("\n❌ ERROR: Credenciales OAuth 2.0 no configuradas")
            print("   Configura las variables de entorno:")
            print("   - X_CLIENT_ID")
            print("   - X_CLIENT_SECRET")
            return None
        
        # Mostrar scopes solicitados
        print("\n📋 SCOPES SOLICITADOS:")
        print("-" * 70)
        for scope in REQUESTED_SCOPES:
            description = AVAILABLE_SCOPES.get(scope, 'Descripción no disponible')
            print(f"  • {scope:<25} - {description}")
        print("-" * 70)
        
        # Generar PKCE
        print("\n🔐 Paso 1/5: Generando parámetros PKCE...")
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = secrets.token_urlsafe(32)
        print(f"  ✓ Code verifier: {code_verifier[:20]}...")
        print(f"  ✓ Code challenge: {code_challenge[:20]}...")
        
        # URL de autorización
        print("\n🌐 Paso 2/5: Generando URL de autorización...")
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
        
        print("\n" + "-" * 70)
        print("🔓 Abriendo navegador para autorizar...")
        print("-" * 70)
        
        try:
            webbrowser.open(authorization_url)
            print("✅ Navegador abierto automáticamente")
        except:
            print("⚠️  No se pudo abrir automáticamente")
            print(f"\n📋 Abre esta URL manualmente:\n   {authorization_url}\n")
        
        # Capturar código
        print("\n⏳ Paso 3/5: Esperando autorización del usuario...")
        auth_code, returned_state, error = start_callback_server(timeout=120)
        
        if error:
            print(f"\n❌ Error en autorización: {error}")
            return None
        
        if not auth_code:
            print("\n❌ Timeout: No se recibió código de autorización")
            return None
        
        if returned_state != state:
            print("\n❌ Error de seguridad: State no coincide")
            return None
        
        print(f"✅ Código de autorización recibido")
        
        # Intercambiar código por tokens
        print("\n🔄 Paso 4/5: Intercambiando código por tokens...")
        
        auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
        auth_b64 = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
        
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
            print(f"\n❌ Error obteniendo tokens: {response.status_code}")
            print(f"   {response.text}")
            return None
        
        tokens = response.json()
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        expires_in = tokens.get('expires_in')
        scope_granted = tokens.get('scope', '').split()
        
        print(f"✅ Access token obtenido")
        if refresh_token:
            print(f"✅ Refresh token obtenido")
        print(f"⏰ Expira en: {expires_in//3600}h {(expires_in%3600)//60}m")
        
        # Obtener info del usuario
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'user.fields': 'id,name,username,public_metrics'}
        user_response = requests.get(USER_INFO_URL, headers=headers, params=params)
        user_data = user_response.json().get('data', {}) if user_response.status_code == 200 else {}
        user_id = user_data.get('id')
        
        print("\n" + "=" * 70)
        print("✅ ¡LOGIN EXITOSO!")
        print("=" * 70)
        
        if user_data:
            print(f"\n👤 USUARIO AUTENTICADO:")
            print(f"  • Nombre: {user_data.get('name')}")
            print(f"  • Usuario: @{user_data.get('username')}")
            print(f"  • ID: {user_data.get('id')}")
            
            metrics = user_data.get('public_metrics', {})
            if metrics:
                print(f"  • Seguidores: {metrics.get('followers_count', 0):,}")
                print(f"  • Siguiendo: {metrics.get('following_count', 0):,}")
        
        # PRUEBA DE SCOPES
        print("\n" + "=" * 70)
        print("🧪 PASO 5/5: PROBANDO SCOPES")
        print("=" * 70)
        
        print("\n📊 Scopes otorgados por Twitter:")
        for scope in scope_granted:
            print(f"  ✓ {scope}")
        
        print("\n🔍 Probando permisos reales:")
        print("-" * 70)
        
        results = []
        
        # Probar cada scope
        if 'tweet.read' in REQUESTED_SCOPES:
            success, msg = test_tweet_read(access_token, user_id)
            results.append(('tweet.read', success, msg))
            print(f"\n[tweet.read]")
            print(f"  {msg}")
        
        if 'tweet.write' in REQUESTED_SCOPES:
            success, msg = test_tweet_write(access_token)
            results.append(('tweet.write', success, msg))
            print(f"\n[tweet.write]")
            print(f"  {msg}")
        
        if 'users.read' in REQUESTED_SCOPES:
            success, msg = test_users_read(access_token)
            results.append(('users.read', success, msg))
            print(f"\n[users.read]")
            print(f"  {msg}")
        
        if 'follows.read' in REQUESTED_SCOPES:
            success, msg = test_follows_read(access_token, user_id)
            results.append(('follows.read', success, msg))
            print(f"\n[follows.read]")
            print(f"  {msg}")
        
        if 'offline.access' in REQUESTED_SCOPES:
            success, msg = test_offline_access(refresh_token)
            results.append(('offline.access', success, msg))
            print(f"\n[offline.access]")
            print(f"  {msg}")
        
        # Resumen
        print("\n" + "=" * 70)
        print("📋 RESUMEN DE PERMISOS")
        print("=" * 70)
        
        working = [r for r in results if r[1]]
        failing = [r for r in results if not r[1]]
        
        print(f"\n✅ Funcionando: {len(working)}/{len(results)}")
        for scope, _, _ in working:
            print(f"  ✓ {scope}")
        
        if failing:
            print(f"\n❌ Con problemas: {len(failing)}/{len(results)}")
            for scope, _, msg in failing:
                print(f"  ✗ {scope}")
                print(f"    └─ {msg}")
            
            print("\n💡 SOLUCIÓN:")
            print("  1. Ve a https://developer.x.com/en/portal/dashboard")
            print("  2. Selecciona tu App")
            print("  3. Ve a Settings > User authentication settings")
            print("  4. Cambia App permissions a 'Read and Write'")
            print("  5. Guarda los cambios")
            print("  6. Vuelve a ejecutar este script")
        
        print("\n" + "=" * 70)
        
        return {
            'success': True,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': expires_in,
            'token_type': tokens.get('token_type', 'bearer'),
            'scope': scope_granted,
            'user': user_data,
            'test_results': results
        }
        
    except Exception as e:
        print(f"\n❌ Error durante el login: {e}")
        import traceback
        traceback.print_exc()
        return None


# ==============================================
# GUARDAR RESULTADOS
# ==============================================

def save_test_results(credentials, filename='oauth2_test_results.json'):
    """Guarda los resultados de las pruebas"""
    if not credentials or not credentials.get('success'):
        return False
    
    try:
        test_data = {
            'timestamp': datetime.now().isoformat(),
            'user': credentials.get('user'),
            'scopes_requested': REQUESTED_SCOPES,
            'scopes_granted': credentials.get('scope', []),
            'test_results': [
                {
                    'scope': r[0],
                    'success': r[1],
                    'message': r[2]
                }
                for r in credentials.get('test_results', [])
            ],
            'tokens': {
                'access_token': credentials['access_token'],
                'refresh_token': credentials.get('refresh_token'),
                'expires_in': credentials['expires_in']
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(test_data, f, indent=2)
        
        print(f"\n💾 Resultados guardados en: {filename}")
        return True
    except Exception as e:
        print(f"❌ Error guardando resultados: {e}")
        return False


# ==============================================
# EJEMPLO DE USO
# ==============================================

if __name__ == "__main__":
    print("\n🐦 TWITTER OAUTH 2.0 - TESTER DE SCOPES")
    print("Prueba completa de permisos y configuración")
    print("=" * 70)
    
    credentials = initiate_login_with_scope_testing()
    
    if credentials and credentials.get('success'):
        print("\n" + "-" * 70)
        save_choice = input("💾 ¿Guardar resultados? (s/n): ").lower().strip()
        
        if save_choice == 's':
            save_test_results(credentials)
    else:
        print("\n❌ Proceso fallido.")
    
    print("\n" + "=" * 70)
    print("✅ Proceso completado")
    print("=" * 70)
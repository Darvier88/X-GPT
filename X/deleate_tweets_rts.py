"""
Módulo para eliminar tweets y retweets de Twitter/X
Usando OAuth 2.0 con PKCE - Permite que cualquier usuario autorice la app
"""
import requests
import time
import json
import hashlib
import base64
import secrets
import webbrowser
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path
import sys
from urllib.parse import urlencode, parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_oauth2_credentials


# ===== OAUTH 2.0 CON PKCE =====

class OAuth2Session:
    """Maneja la autenticación OAuth 2.0 con PKCE"""
    
    def __init__(self):
        creds = get_oauth2_credentials()
        self.client_id = creds['client_id']
        self.client_secret = creds.get('client_secret')  # Opcional para public clients
        self.redirect_uri = creds['redirect_uri']
        
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        
        # PKCE
        self.code_verifier = None
        self.code_challenge = None
    
    def _generate_pkce_params(self):
        """Genera code_verifier y code_challenge para PKCE"""
        # Code verifier: random string de 43-128 caracteres
        self.code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        
        # Code challenge: SHA256 del verifier
        challenge = hashlib.sha256(self.code_verifier.encode('utf-8')).digest()
        self.code_challenge = base64.urlsafe_b64encode(challenge).decode('utf-8').rstrip('=')
    
    def get_authorization_url(self, scopes: List[str] = None) -> str:
        """
        Genera la URL de autorización para que el usuario autorice la app
        
        Args:
            scopes: Lista de permisos solicitados
            
        Returns:
            URL para abrir en el navegador
        """
        if scopes is None:
            scopes = ['tweet.read', 'tweet.write', 'users.read', 'offline.access']
        
        self._generate_pkce_params()
        
        # State para prevenir CSRF
        state = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'scope': ' '.join(scopes),
            'state': state,
            'code_challenge': self.code_challenge,
            'code_challenge_method': 'S256'
        }
        
        auth_url = f"https://twitter.com/i/oauth2/authorize?{urlencode(params)}"
        return auth_url, state
    
    def exchange_code_for_token(self, authorization_code: str) -> Dict[str, Any]:
        """
        Intercambia el código de autorización por access token
        
        Args:
            authorization_code: Código obtenido del callback
            
        Returns:
            {
                'success': bool,
                'access_token': str,
                'refresh_token': str,
                'expires_in': int
            }
        """
        url = "https://api.twitter.com/2/oauth2/token"
        
        data = {
            'grant_type': 'authorization_code',
            'code': authorization_code,
            'redirect_uri': self.redirect_uri,
            'code_verifier': self.code_verifier,
            'client_id': self.client_id
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        try:
            response = requests.post(url, data=data, headers=headers, timeout=15)
            
            if response.status_code == 200:
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token')
                expires_in = token_data.get('expires_in', 7200)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                return {
                    'success': True,
                    'access_token': self.access_token,
                    'refresh_token': self.refresh_token,
                    'expires_in': expires_in,
                    'expires_at': self.token_expires_at.isoformat()
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
    
    def refresh_access_token(self) -> Dict[str, Any]:
        """Renueva el access token usando el refresh token"""
        if not self.refresh_token:
            return {
                'success': False,
                'error': 'No refresh token available'
            }
        
        url = "https://api.twitter.com/2/oauth2/token"
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        try:
            response = requests.post(url, data=data, headers=headers, timeout=15)
            
            if response.status_code == 200:
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token', self.refresh_token)
                expires_in = token_data.get('expires_in', 7200)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                return {
                    'success': True,
                    'access_token': self.access_token,
                    'expires_in': expires_in
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
    
    def is_token_valid(self) -> bool:
        """Verifica si el access token sigue siendo válido"""
        if not self.access_token or not self.token_expires_at:
            return False
        
        # Considerar inválido si expira en menos de 5 minutos
        return datetime.now() < (self.token_expires_at - timedelta(minutes=5))
    
    def get_headers(self) -> Dict[str, str]:
        """Retorna headers con el access token"""
        if not self.access_token:
            raise ValueError("No access token available. Authorize first.")
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def save_session(self, filename: str = 'oauth_session.json'):
        """Guarda la sesión para reutilizarla"""
        session_data = {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'token_expires_at': self.token_expires_at.isoformat() if self.token_expires_at else None,
            'client_id': self.client_id,
            'saved_at': datetime.now().isoformat()
        }
        
        with open(filename, 'w') as f:
            json.dump(session_data, f, indent=2)
        
        print(f"✓ Sesión guardada: {filename}")
    
    @classmethod
    def load_session(cls, filename: str = 'oauth_session.json') -> 'OAuth2Session':
        """Carga una sesión guardada"""
        try:
            with open(filename, 'r') as f:
                session_data = json.load(f)
            
            session = cls()
            session.access_token = session_data['access_token']
            session.refresh_token = session_data['refresh_token']
            
            if session_data['token_expires_at']:
                session.token_expires_at = datetime.fromisoformat(session_data['token_expires_at'])
            
            # Refrescar si está expirado
            if not session.is_token_valid() and session.refresh_token:
                print("Token expirado, refrescando...")
                result = session.refresh_access_token()
                if result['success']:
                    print("✓ Token refrescado")
                    session.save_session(filename)
                else:
                    print(f"✗ Error refrescando token: {result['error']}")
                    return None
            
            return session
        
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"Error cargando sesión: {e}")
            return None


def authorize_user(auto_open_browser: bool = True) -> OAuth2Session:
    """
    Flujo completo de autorización OAuth 2.0
    
    Args:
        auto_open_browser: Si abrir el navegador automáticamente
        
    Returns:
        OAuth2Session autenticada
    """
    print("\n" + "="*70)
    print("AUTORIZACIÓN DE USUARIO - OAuth 2.0")
    print("="*70)
    
    session = OAuth2Session()
    
    # 1. Generar URL de autorización
    auth_url, state = session.get_authorization_url()
    
    print(f"\nPaso 1: Autorizar la aplicación")
    print(f"{'─'*70}")
    print(f"\n🔗 Abre esta URL en tu navegador:\n")
    print(f"{auth_url}\n")
    
    if auto_open_browser:
        print("Abriendo navegador automáticamente...")
        webbrowser.open(auth_url)
    
    print(f"\n{'─'*70}")
    print("Después de autorizar, Twitter te redirigirá a una URL.")
    print("Copia la URL COMPLETA de redirección y pégala aquí.")
    print(f"{'─'*70}\n")
    
    # 2. Obtener código de autorización
    callback_url = input("URL de callback: ").strip()
    
    # Parsear código de la URL
    parsed = urlparse(callback_url)
    params = parse_qs(parsed.query)
    
    if 'code' not in params:
        print("\n✗ Error: No se encontró el código de autorización en la URL")
        return None
    
    authorization_code = params['code'][0]
    
    # Verificar state (opcional pero recomendado)
    if 'state' in params and params['state'][0] != state:
        print("\n✗ Error: State no coincide (posible ataque CSRF)")
        return None
    
    print("\n✓ Código de autorización obtenido")
    
    # 3. Intercambiar código por access token
    print("\nPaso 2: Obteniendo access token...")
    
    result = session.exchange_code_for_token(authorization_code)
    
    if not result['success']:
        print(f"\n✗ Error obteniendo token: {result['error']}")
        return None
    
    print(f"\n✓ Autorización exitosa")
    print(f"   Access token válido por: {result['expires_in']}s (~{result['expires_in']//60} min)")
    
    # 4. Guardar sesión
    session.save_session()
    
    return session


# ===== FUNCIONES DE ELIMINACIÓN =====

def delete_single_tweet(tweet_id: str, session: OAuth2Session) -> Dict[str, Any]:
    """
    Elimina un solo tweet usando OAuth 2.0
    
    Args:
        tweet_id: ID del tweet a eliminar
        session: Sesión OAuth2 autenticada
        
    Returns:
        {
            'success': bool,
            'tweet_id': str,
            'deleted': bool,
            'error': str (si aplica)
        }
    """
    url = f"https://api.twitter.com/2/tweets/{tweet_id}"
    
    try:
        response = requests.delete(url, headers=session.get_headers(), timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'tweet_id': tweet_id,
                'deleted': data.get('data', {}).get('deleted', False)
            }
        else:
            return {
                'success': False,
                'tweet_id': tweet_id,
                'deleted': False,
                'error': f"HTTP {response.status_code}: {response.text}"
            }
    
    except Exception as e:
        return {
            'success': False,
            'tweet_id': tweet_id,
            'deleted': False,
            'error': str(e)
        }


def delete_single_retweet(user_id: str, source_tweet_id: str, session: OAuth2Session) -> Dict[str, Any]:
    """
    Elimina un retweet (unretweet) usando OAuth 2.0
    
    Args:
        user_id: ID del usuario que hizo el retweet
        source_tweet_id: ID del tweet ORIGINAL (no el ID del retweet)
        session: Sesión OAuth2 autenticada
        
    Returns:
        {
            'success': bool,
            'source_tweet_id': str,
            'unretweeted': bool,
            'error': str (si aplica)
        }
    """
    url = f"https://api.twitter.com/2/users/{user_id}/retweets/{source_tweet_id}"
    
    try:
        response = requests.delete(url, headers=session.get_headers(), timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'source_tweet_id': source_tweet_id,
                'unretweeted': data.get('data', {}).get('retweeted', False) == False
            }
        else:
            return {
                'success': False,
                'source_tweet_id': source_tweet_id,
                'unretweeted': False,
                'error': f"HTTP {response.status_code}: {response.text}"
            }
    
    except Exception as e:
        return {
            'success': False,
            'source_tweet_id': source_tweet_id,
            'unretweeted': False,
            'error': str(e)
        }


def extract_retweet_source_id(tweet: Dict[str, Any]) -> Optional[str]:
    """Extrae el ID del tweet original de un retweet"""
    referenced = tweet.get('referenced_tweets', [])
    for ref in referenced:
        if ref.get('type') == 'retweeted':
            return ref.get('id')
    return None


def delete_tweets_batch(
    tweets: List[Dict[str, Any]], 
    user_id: str,
    session: OAuth2Session,
    delete_retweets: bool = True,
    delete_originals: bool = True,
    delay_seconds: float = 1.0,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Elimina múltiples tweets en batch usando OAuth 2.0
    
    Args:
        tweets: Lista de tweets (del formato de search_tweets.py)
        user_id: ID del usuario (necesario para unretweets)
        session: Sesión OAuth2 autenticada
        delete_retweets: Si eliminar retweets
        delete_originals: Si eliminar tweets originales
        delay_seconds: Pausa entre cada eliminación (evitar rate limit)
        verbose: Mostrar progreso
        
    Returns:
        {
            'success': bool,
            'total_processed': int,
            'retweets_deleted': int,
            'tweets_deleted': int,
            'failed': list,
            'execution_time': str
        }
    """
    start_time = time.time()
    
    retweets = []
    originals = []
    
    # Clasificar tweets
    for tweet in tweets:
        if tweet.get('is_retweet', False):
            retweets.append(tweet)
        else:
            originals.append(tweet)
    
    if verbose:
        print(f"\n{'='*70}")
        print(f"ELIMINACIÓN EN BATCH")
        print(f"{'='*70}")
        print(f"Total tweets: {len(tweets)}")
        print(f"  Retweets: {len(retweets)}")
        print(f"  Originales: {len(originals)}")
        print(f"Configuración:")
        print(f"  Eliminar retweets: {'Sí' if delete_retweets else 'No'}")
        print(f"  Eliminar originales: {'Sí' if delete_originals else 'No'}")
        print(f"  Delay: {delay_seconds}s entre eliminaciones")
        print(f"{'='*70}\n")
    
    retweets_deleted = 0
    tweets_deleted = 0
    failed = []
    
    # Eliminar retweets
    if delete_retweets and retweets:
        if verbose:
            print(f"🔄 Eliminando {len(retweets)} retweets...")
        
        for i, rt in enumerate(retweets, 1):
            tweet_id = rt.get('id')
            source_id = extract_retweet_source_id(rt)
            
            if not source_id:
                if verbose:
                    print(f"  ⚠️  [{i}/{len(retweets)}] No se pudo extraer source_id del RT {tweet_id}")
                failed.append({
                    'tweet_id': tweet_id,
                    'type': 'retweet',
                    'error': 'No source_id found'
                })
                continue
            
            result = delete_single_retweet(user_id, source_id, session)
            
            if result['success']:
                retweets_deleted += 1
                if verbose:
                    print(f"  ✓ [{i}/{len(retweets)}] Retweet eliminado: {tweet_id} (source: {source_id})")
            else:
                failed.append({
                    'tweet_id': tweet_id,
                    'type': 'retweet',
                    'source_id': source_id,
                    'error': result.get('error')
                })
                if verbose:
                    print(f"  ✗ [{i}/{len(retweets)}] Error: {result.get('error')}")
            
            if i < len(retweets):
                time.sleep(delay_seconds)
    
    # Eliminar tweets originales
    if delete_originals and originals:
        if verbose:
            print(f"\n🗑️  Eliminando {len(originals)} tweets originales...")
        
        for i, tweet in enumerate(originals, 1):
            tweet_id = tweet.get('id')
            
            result = delete_single_tweet(tweet_id, session)
            
            if result['success']:
                tweets_deleted += 1
                if verbose:
                    print(f"  ✓ [{i}/{len(originals)}] Tweet eliminado: {tweet_id}")
            else:
                failed.append({
                    'tweet_id': tweet_id,
                    'type': 'original',
                    'error': result.get('error')
                })
                if verbose:
                    print(f"  ✗ [{i}/{len(originals)}] Error: {result.get('error')}")
            
            if i < len(originals):
                time.sleep(delay_seconds)
    
    end_time = time.time()
    execution_time = end_time - start_time
    
    if verbose:
        print(f"\n{'='*70}")
        print(f"RESULTADO")
        print(f"{'='*70}")
        print(f"Total procesado: {len(tweets)}")
        print(f"Retweets eliminados: {retweets_deleted}/{len(retweets)}")
        print(f"Tweets eliminados: {tweets_deleted}/{len(originals)}")
        print(f"Fallidos: {len(failed)}")
        print(f"Tiempo total: {execution_time:.2f}s")
        print(f"{'='*70}")
    
    return {
        'success': len(failed) == 0,
        'total_processed': len(tweets),
        'retweets_deleted': retweets_deleted,
        'tweets_deleted': tweets_deleted,
        'failed': failed,
        'execution_time': f"{execution_time:.2f}s",
        'execution_time_seconds': execution_time
    }


def delete_tweets_from_json(
    json_path: str,
    session: OAuth2Session = None,
    delete_retweets: bool = True,
    delete_originals: bool = True,
    delay_seconds: float = 1.0,
    save_report: bool = True
) -> Dict[str, Any]:
    """
    Elimina tweets desde un archivo JSON (generado por search_tweets.py)
    
    Args:
        json_path: Ruta al archivo JSON
        session: Sesión OAuth2 (si None, intenta cargar o crear nueva)
        delete_retweets: Si eliminar retweets
        delete_originals: Si eliminar tweets originales
        delay_seconds: Pausa entre eliminaciones
        save_report: Si guardar reporte de eliminación
        
    Returns:
        Resultado de delete_tweets_batch
    """
    print(f"Cargando tweets desde: {json_path}")
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return {
            'success': False,
            'error': f"Error leyendo JSON: {str(e)}"
        }
    
    if not data.get('success'):
        return {
            'success': False,
            'error': 'El JSON no contiene datos válidos'
        }
    
    tweets = data.get('tweets', [])
    user_id = data.get('user', {}).get('author_id')
    
    if not user_id:
        return {
            'success': False,
            'error': 'No se encontró user_id en el JSON'
        }
    
    print(f"Usuario: @{data['user']['username']}")
    print(f"Tweets en JSON: {len(tweets)}")
    
    # Obtener sesión OAuth2
    if session is None:
        session = OAuth2Session.load_session()
        
        if session is None:
            print("\n⚠️  No hay sesión guardada. Iniciando autorización...")
            session = authorize_user()
            
            if session is None:
                return {
                    'success': False,
                    'error': 'No se pudo autorizar el usuario'
                }
    
    result = delete_tweets_batch(
        tweets=tweets,
        user_id=user_id,
        session=session,
        delete_retweets=delete_retweets,
        delete_originals=delete_originals,
        delay_seconds=delay_seconds,
        verbose=True
    )
    
    # Guardar reporte
    if save_report:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"deletion_report_{timestamp}.json"
        
        report = {
            'source_json': json_path,
            'deletion_timestamp': datetime.now().isoformat(),
            'user': data.get('user'),
            'result': result
        }
        
        with open(report_filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\nReporte guardado: {report_filename}")
    
    return result


if __name__ == "__main__":
    print("="*70)
    print("DELETE_TWEETS.PY - Módulo de eliminación con OAuth 2.0")
    print("="*70)
    print("\nEste módulo usa OAuth 2.0 con PKCE")
    print("Cualquier usuario puede autorizar y eliminar sus tweets")
    print("\nEjemplo de uso:")
    print("  # 1. Autorizar usuario")
    print("  session = authorize_user()")
    print("\n  # 2. Eliminar desde JSON")
    print("  result = delete_tweets_from_json('tweets.json', session)")
    print("="*70)
"""
A1: Normalización y resolución de usuarios de Twitter/X
Objetivo: Dado un @handle o user_id, resolver a user_id canónico

Funcionalidades:
- Acepta @handle o user_id numérico
- Valida contra la API de X
- Maneja errores: 404, usuario suspendido, privado
- Logs estructurados con trace_id
"""

import requests
import re
import uuid
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_x_api_key

def setup_structured_logger(name: str = 'user_resolver') -> logging.Logger:
    """Configura logger con formato estructurado"""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger


logger = setup_structured_logger()



ERROR_CODES = {
    'USER_NOT_FOUND': 'Usuario no encontrado en la plataforma',
    'USER_SUSPENDED': 'Usuario suspendido por Twitter/X',
    'USER_PRIVATE': 'Usuario con cuenta privada (protegida)',
    'INVALID_INPUT': 'Input inválido - debe ser @handle o user_id numérico',
    'API_ERROR': 'Error en la API de Twitter/X',
    'RATE_LIMIT': 'Límite de tasa alcanzado',
    'AUTH_ERROR': 'Error de autenticación',
    'NETWORK_ERROR': 'Error de red o timeout',
    'UNKNOWN_ERROR': 'Error desconocido'
}



def normalize_handle(input_str: str) -> str:
    """
    Limpia y normaliza un handle de Twitter
    
    Args:
        input_str: Handle con o sin @
    
    Returns:
        Handle limpio sin @
    
    Examples:
        '@elonmusk' -> 'elonmusk'
        'elonmusk' -> 'elonmusk'
        '  @user_123  ' -> 'user_123'
    """
    if not input_str:
        return ''
    
    # Limpiar espacios
    cleaned = input_str.strip()
    
    # Remover @ inicial
    if cleaned.startswith('@'):
        cleaned = cleaned[1:]
    
    return cleaned


def is_valid_handle(handle: str) -> bool:
    """
    Valida que un handle cumpla las reglas de Twitter
    
    Reglas de Twitter:
    - 1-15 caracteres
    - Solo letras, números y guiones bajos
    - No puede ser solo números
    
    Args:
        handle: Handle a validar (sin @)
    
    Returns:
        True si es válido, False en caso contrario
    """
    if not handle:
        return False
    
    # Longitud entre 1 y 15
    if len(handle) < 1 or len(handle) > 15:
        return False
    
    # Solo alfanuméricos y guiones bajos
    if not re.match(r'^[a-zA-Z0-9_]+$', handle):
        return False
    
    # No puede ser solo números (para distinguir de user_id)
    if handle.isdigit():
        return False
    
    return True


def is_valid_user_id(user_id_str: str) -> bool:
    """
    Valida que una cadena sea un user_id numérico válido
    
    Args:
        user_id_str: String a validar
    
    Returns:
        True si es un user_id válido, False en caso contrario
    """
    if not user_id_str:
        return False
    
    # Debe ser solo dígitos
    if not user_id_str.isdigit():
        return False
    
    # Twitter user_ids son muy largos (típicamente 8-19 dígitos)
    if len(user_id_str) < 1 or len(user_id_str) > 20:
        return False
    
    return True


def classify_input(input_str: str) -> Dict[str, Any]:
    """
    Clasifica el input como handle o user_id
    
    Args:
        input_str: String a clasificar
    
    Returns:
        Dict con tipo y valor normalizado:
        {
            'type': 'handle' | 'user_id' | 'invalid',
            'value': str,
            'original': str
        }
    """
    original = input_str
    normalized = normalize_handle(input_str)
    
    # Vacío
    if not normalized:
        return {
            'type': 'invalid',
            'value': None,
            'original': original,
            'reason': 'Input vacío'
        }
    
    # Es user_id numérico
    if is_valid_user_id(normalized):
        return {
            'type': 'user_id',
            'value': normalized,
            'original': original
        }
    
    # Es handle
    if is_valid_handle(normalized):
        return {
            'type': 'handle',
            'value': normalized,
            'original': original
        }
    
    # Inválido
    return {
        'type': 'invalid',
        'value': normalized,
        'original': original,
        'reason': 'No cumple formato de handle ni user_id'
    }



def fetch_user_by_handle(handle: str, trace_id: str) -> Dict[str, Any]:
    """
    Obtiene información de usuario por handle desde la API de X
    
    Args:
        handle: Handle limpio (sin @)
        trace_id: ID de trazabilidad
    
    Returns:
        Dict con resultado:
        {
            'success': bool,
            'user_id': str | None,
            'username': str | None,
            'name': str | None,
            'data': dict | None,
            'error_code': str | None,
            'error_message': str | None,
            'trace_id': str
        }
    """
    try:
        token = get_x_api_key()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://api.twitter.com/2/users/by/username/{handle}"
        
        params = {
            "user.fields": "id,username,name,public_metrics,created_at,description,protected,verified"
        }
        
        logger.info(f"[{trace_id}] API Request: GET {url} | handle={handle}")
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        logger.info(
            f"[{trace_id}] API Response: status={response.status_code} | "
            f"rate_limit_remaining={response.headers.get('x-rate-limit-remaining', 'N/A')}"
        )
        
        # SUCCESS (200)
        if response.status_code == 200:
            data = response.json()
            user_data = data.get('data', {})
            
            result = {
                'success': True,
                'user_id': user_data.get('id'),
                'username': user_data.get('username'),
                'name': user_data.get('name'),
                'protected': user_data.get('protected', False),
                'verified': user_data.get('verified', False),
                'data': user_data,
                'error_code': None,
                'error_message': None,
                'trace_id': trace_id
            }
            
            logger.info(
                f"[{trace_id}] User resolved: @{result['username']} -> {result['user_id']} | "
                f"protected={result['protected']}"
            )
            
            return result
        
        # NOT FOUND (404)
        elif response.status_code == 404:
            logger.warning(f"[{trace_id}] User not found: @{handle}")
            return {
                'success': False,
                'user_id': None,
                'username': handle,
                'name': None,
                'data': None,
                'error_code': 'USER_NOT_FOUND',
                'error_message': ERROR_CODES['USER_NOT_FOUND'],
                'trace_id': trace_id
            }
        
        # RATE LIMIT (429)
        elif response.status_code == 429:
            reset_time = response.headers.get('x-rate-limit-reset', 'unknown')
            logger.error(f"[{trace_id}] Rate limit reached | reset_at={reset_time}")
            return {
                'success': False,
                'user_id': None,
                'username': handle,
                'name': None,
                'data': None,
                'error_code': 'RATE_LIMIT',
                'error_message': ERROR_CODES['RATE_LIMIT'],
                'rate_limit_reset': reset_time,
                'trace_id': trace_id
            }
        
        # AUTH ERROR (401, 403)
        elif response.status_code in [401, 403]:
            logger.error(f"[{trace_id}] Auth error: {response.status_code} | {response.text}")
            return {
                'success': False,
                'user_id': None,
                'username': handle,
                'name': None,
                'data': None,
                'error_code': 'AUTH_ERROR',
                'error_message': ERROR_CODES['AUTH_ERROR'],
                'trace_id': trace_id
            }
        
        # OTROS ERRORES
        else:
            logger.error(
                f"[{trace_id}] API error: status={response.status_code} | response={response.text[:200]}"
            )
            return {
                'success': False,
                'user_id': None,
                'username': handle,
                'name': None,
                'data': None,
                'error_code': 'API_ERROR',
                'error_message': f"API Error {response.status_code}: {response.text[:100]}",
                'trace_id': trace_id
            }
    
    except requests.Timeout:
        logger.error(f"[{trace_id}] Request timeout for handle: @{handle}")
        return {
            'success': False,
            'user_id': None,
            'username': handle,
            'name': None,
            'data': None,
            'error_code': 'NETWORK_ERROR',
            'error_message': 'Request timeout',
            'trace_id': trace_id
        }
    
    except Exception as e:
        logger.error(f"[{trace_id}] Unexpected error: {type(e).__name__} | {str(e)}")
        return {
            'success': False,
            'user_id': None,
            'username': handle,
            'name': None,
            'data': None,
            'error_code': 'UNKNOWN_ERROR',
            'error_message': str(e),
            'trace_id': trace_id
        }


def validate_user_id(user_id: str, trace_id: str) -> Dict[str, Any]:
    """
    Valida que un user_id exista consultando la API
    
    Args:
        user_id: User ID numérico
        trace_id: ID de trazabilidad
    
    Returns:
        Dict con resultado (mismo formato que fetch_user_by_handle)
    """
    try:
        token = get_x_api_key()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://api.twitter.com/2/users/{user_id}"
        
        params = {
            "user.fields": "id,username,name,public_metrics,created_at,description,protected,verified"
        }
        
        logger.info(f"[{trace_id}] API Request: GET {url} | user_id={user_id}")
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        logger.info(
            f"[{trace_id}] API Response: status={response.status_code} | "
            f"rate_limit_remaining={response.headers.get('x-rate-limit-remaining', 'N/A')}"
        )
        
        # SUCCESS (200)
        if response.status_code == 200:
            data = response.json()
            user_data = data.get('data', {})
            
            result = {
                'success': True,
                'user_id': user_data.get('id'),
                'username': user_data.get('username'),
                'name': user_data.get('name'),
                'protected': user_data.get('protected', False),
                'verified': user_data.get('verified', False),
                'data': user_data,
                'error_code': None,
                'error_message': None,
                'trace_id': trace_id
            }
            
            logger.info(
                f"[{trace_id}] User ID validated: {result['user_id']} -> @{result['username']} | "
                f"protected={result['protected']}"
            )
            
            return result
        
        # NOT FOUND (404)
        elif response.status_code == 404:
            logger.warning(f"[{trace_id}] User ID not found: {user_id}")
            return {
                'success': False,
                'user_id': user_id,
                'username': None,
                'name': None,
                'data': None,
                'error_code': 'USER_NOT_FOUND',
                'error_message': ERROR_CODES['USER_NOT_FOUND'],
                'trace_id': trace_id
            }
        
        # RATE LIMIT (429)
        elif response.status_code == 429:
            reset_time = response.headers.get('x-rate-limit-reset', 'unknown')
            logger.error(f"[{trace_id}] Rate limit reached | reset_at={reset_time}")
            return {
                'success': False,
                'user_id': user_id,
                'username': None,
                'name': None,
                'data': None,
                'error_code': 'RATE_LIMIT',
                'error_message': ERROR_CODES['RATE_LIMIT'],
                'rate_limit_reset': reset_time,
                'trace_id': trace_id
            }
        
        # AUTH ERROR (401, 403)
        elif response.status_code in [401, 403]:
            logger.error(f"[{trace_id}] Auth error: {response.status_code}")
            return {
                'success': False,
                'user_id': user_id,
                'username': None,
                'name': None,
                'data': None,
                'error_code': 'AUTH_ERROR',
                'error_message': ERROR_CODES['AUTH_ERROR'],
                'trace_id': trace_id
            }
        
        # OTROS ERRORES
        else:
            logger.error(f"[{trace_id}] API error: status={response.status_code}")
            return {
                'success': False,
                'user_id': user_id,
                'username': None,
                'name': None,
                'data': None,
                'error_code': 'API_ERROR',
                'error_message': f"API Error {response.status_code}",
                'trace_id': trace_id
            }
    
    except requests.Timeout:
        logger.error(f"[{trace_id}] Request timeout for user_id: {user_id}")
        return {
            'success': False,
            'user_id': user_id,
            'username': None,
            'name': None,
            'data': None,
            'error_code': 'NETWORK_ERROR',
            'error_message': 'Request timeout',
            'trace_id': trace_id
        }
    
    except Exception as e:
        logger.error(f"[{trace_id}] Unexpected error: {type(e).__name__} | {str(e)}")
        return {
            'success': False,
            'user_id': user_id,
            'username': None,
            'name': None,
            'data': None,
            'error_code': 'UNKNOWN_ERROR',
            'error_message': str(e),
            'trace_id': trace_id
        }


# ===============================================
# FUNCIÓN PRINCIPAL: RESOLVE_USER
# ===============================================

def resolve_user(handle_or_id: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    FUNCIÓN PRINCIPAL: Resuelve un handle o user_id a user_id canónico
    
    Esta es la función que cumple el requisito A1:
    - Acepta @handle o user_id
    - Normaliza el input
    - Consulta la API
    - Retorna user_id canónico o error
    
    Args:
        handle_or_id: Handle (@username) o user_id numérico
        trace_id: ID de trazabilidad (se genera automáticamente si no se provee)
    
    Returns:
        Dict con resultado:
        {
            'success': bool,
            'user_id': str | None,           # ID canónico del usuario
            'username': str | None,          # Handle actual del usuario
            'name': str | None,              # Nombre display
            'protected': bool | None,        # Si la cuenta es privada
            'verified': bool | None,         # Si está verificada
            'input_type': 'handle' | 'user_id',
            'original_input': str,
            'data': dict | None,             # Datos completos de la API
            'error_code': str | None,
            'error_message': str | None,
            'trace_id': str,
            'resolved_at': str
        }
    
    Examples:
        >>> resolve_user('@elonmusk')
        {'success': True, 'user_id': '44196397', 'username': 'elonmusk', ...}
        
        >>> resolve_user('44196397')
        {'success': True, 'user_id': '44196397', 'username': 'elonmusk', ...}
        
        >>> resolve_user('@usuario_inexistente_xyz')
        {'success': False, 'error_code': 'USER_NOT_FOUND', ...}
    """
    # Generar trace_id si no se provee
    if trace_id is None:
        trace_id = str(uuid.uuid4())[:8]
    
    timestamp = datetime.utcnow().isoformat()
    
    logger.info(f"[{trace_id}] resolve_user started | input='{handle_or_id}'")
    
    # PASO 1: Clasificar input
    classification = classify_input(handle_or_id)
    
    logger.info(
        f"[{trace_id}] Input classified: type={classification['type']} | "
        f"value={classification.get('value')}"
    )
    
    # PASO 2: Validar input
    if classification['type'] == 'invalid':
        logger.warning(
            f"[{trace_id}] Invalid input: {classification.get('reason')} | "
            f"original='{handle_or_id}'"
        )
        return {
            'success': False,
            'user_id': None,
            'username': None,
            'name': None,
            'protected': None,
            'verified': None,
            'input_type': 'invalid',
            'original_input': handle_or_id,
            'data': None,
            'error_code': 'INVALID_INPUT',
            'error_message': f"{ERROR_CODES['INVALID_INPUT']}: {classification.get('reason')}",
            'trace_id': trace_id,
            'resolved_at': timestamp
        }
    
    # PASO 3: Resolver según tipo
    if classification['type'] == 'handle':
        result = fetch_user_by_handle(classification['value'], trace_id)
        input_type = 'handle'
    else:  # user_id
        result = validate_user_id(classification['value'], trace_id)
        input_type = 'user_id'
    
    # PASO 4: Enriquecer resultado con metadata
    result['input_type'] = input_type
    result['original_input'] = handle_or_id
    result['resolved_at'] = timestamp
    
    # Log resultado
    if result['success']:
        logger.info(
            f"[{trace_id}] ✅ Resolution successful: "
            f"{handle_or_id} -> user_id={result['user_id']} (@{result['username']})"
        )
    else:
        logger.warning(
            f"[{trace_id}] ❌ Resolution failed: "
            f"{handle_or_id} -> error_code={result['error_code']}"
        )
    
    return result


# ===============================================
# FUNCIONES DE UTILIDAD
# ===============================================

def resolve_multiple_users(handles_or_ids: list, batch_size: int = 10) -> Dict[str, Any]:
    """
    Resuelve múltiples usuarios en lote
    
    Args:
        handles_or_ids: Lista de handles o user_ids
        batch_size: Tamaño del lote (para logging)
    
    Returns:
        Dict con resultados:
        {
            'total': int,
            'successful': int,
            'failed': int,
            'results': list,
            'errors': list
        }
    """
    trace_id = str(uuid.uuid4())[:8]
    
    logger.info(f"[{trace_id}] Batch resolution started: {len(handles_or_ids)} users")
    
    results = []
    errors = []
    
    for i, handle_or_id in enumerate(handles_or_ids, 1):
        logger.info(f"[{trace_id}] Processing {i}/{len(handles_or_ids)}: {handle_or_id}")
        
        result = resolve_user(handle_or_id, trace_id=f"{trace_id}-{i}")
        
        if result['success']:
            results.append(result)
        else:
            errors.append(result)
    
    summary = {
        'total': len(handles_or_ids),
        'successful': len(results),
        'failed': len(errors),
        'results': results,
        'errors': errors,
        'trace_id': trace_id
    }
    
    logger.info(
        f"[{trace_id}] Batch complete: "
        f"{summary['successful']}/{summary['total']} successful, "
        f"{summary['failed']} failed"
    )
    
    return summary


# ===============================================
# FUNCIONES DE PRUEBA PARA MAIN
# ===============================================

def test_resolution():
    """Prueba básica de resolución de usuarios"""
    print("\n" + "=" * 70)
    print("PRUEBA 1: RESOLUCIÓN DE USUARIOS")
    print("=" * 70)
    
    test_cases = [
        "@TheDarkraimola",          # Handle con @
        "TheDarkraimola",           # Handle sin @
        "44196397",                 # User ID (ejemplo de Elon Musk)
        "@usuario_que_no_existe",   # Handle inexistente
        "invalid@handle!",          # Input inválido
    ]
    
    results = []
    for test_input in test_cases:
        print(f"\n🔍 Input: '{test_input}'")
        print("-" * 70)
        
        result = resolve_user(test_input)
        results.append(result)
        
        if result['success']:
            print(f"✅ SUCCESS")
            print(f"   User ID: {result['user_id']}")
            print(f"   Username: @{result['username']}")
            print(f"   Name: {result['name']}")
            print(f"   Protected: {result['protected']}")
            print(f"   Input Type: {result['input_type']}")
        else:
            print(f"❌ FAILED")
            print(f"   Error Code: {result['error_code']}")
            print(f"   Error Message: {result['error_message']}")
        
        print(f"   Trace ID: {result['trace_id']}")
    
    return results


def test_validation():
    """Prueba de validación de existencia de usuarios"""
    print("\n" + "=" * 70)
    print("PRUEBA 2: VALIDACIÓN DE EXISTENCIA")
    print("=" * 70)
    

    test_username = "TheDarkraimola"
    print(f"\n🔍 Validando usuario: @{test_username}")
    print("-" * 70)
    
    result = resolve_user(test_username)
    
    if result['success']:
        print(f"✅ Usuario EXISTE y está activo")
        print(f"   User ID: {result['user_id']}")
        print(f"   Username: @{result['username']}")
        print(f"   Name: {result['name']}")
        print(f"   Protected: {result['protected']}")
        print(f"   Verified: {result['verified']}")
        
        if result.get('data'):
            metrics = result['data'].get('public_metrics', {})
            print(f"\n📊 Métricas públicas:")
            print(f"   Followers: {metrics.get('followers_count', 'N/A')}")
            print(f"   Following: {metrics.get('following_count', 'N/A')}")
            print(f"   Tweets: {metrics.get('tweet_count', 'N/A')}")
    else:
        print(f"❌ Usuario NO EXISTE o error")
        print(f"   Error: {result['error_message']}")
    
    return result



if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("USER_LOGIN.PY - MÓDULO DE RESOLUCIÓN DE USUARIOS")
    print("=" * 70)
    

    test_resolution()
    test_validation()
    
    print("\n" + "=" * 70)
    print("Pruebas completadas")
    print("=" * 70)
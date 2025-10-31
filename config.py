import os
from dotenv import load_dotenv

load_dotenv()

def get_x_api_key():
    key = os.getenv('X_BEARER_TOKEN')
    if not key:
        raise ValueError("X_BEARER_TOKEN no configurado")
    return key

def get_openai_api_key():
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        raise ValueError("OPENAI_API_KEY no configurada")
    return key
def get_oauth2_credentials():
    """
    Obtiene las credenciales OAuth 2.0 desde variables de entorno
    
    Returns:
        dict con client_id y client_secret
    """
    client_id = os.getenv('X_CLIENT_ID')
    client_secret = os.getenv('X_CLIENT_SECRET')
    redirect_uri = os.getenv('REDIRECT_URI')
    
    if not client_id:
        raise ValueError("X_CLIENT_ID no configurado en variables de entorno")
    if not client_secret:
        raise ValueError("X_CLIENT_SECRET no configurado en variables de entorno")
    
    return {
        'client_id': client_id,
        'client_secret': client_secret
    }
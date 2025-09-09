import os
from dotenv import load_dotenv

load_dotenv()

def get_x_api_key():
    key = os.getenv('X_API_KEY')
    if not key:
        raise ValueError("X_API_KEY no configurada")
    return key

def get_openai_api_key():
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        raise ValueError("OPENAI_API_KEY no configurada")
    return key
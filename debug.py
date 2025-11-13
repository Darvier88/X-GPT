"""
debug_token.py
Script para ver información del token actual (sin mostrar el token completo)
"""

import json
import os
from datetime import datetime
import base64

def debug_token():
    """Muestra información del token guardado para debugging"""
    
    print("="*70)
    print("DEBUG - INFORMACIÓN DEL TOKEN")
    print("="*70)
    
    session_files = [
        "twitter_session.json",
        "session.json",
        ".twitter_session.json"
    ]
    
    found = False
    
    for filename in session_files:
        if os.path.exists(filename):
            found = True
            print(f"\n📁 Archivo encontrado: {filename}")
            
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)
                
                print("\n📋 Estructura del JSON:")
                print(f"   Claves disponibles: {list(data.keys())}")
                
                # Info del usuario
                if 'user' in data:
                    user = data['user']
                    print(f"\n👤 Usuario:")
                    print(f"   Username: @{user.get('username', 'N/A')}")
                    print(f"   ID: {user.get('id', 'N/A')}")
                    print(f"   Name: {user.get('name', 'N/A')}")
                
                # Info del token (sin mostrar el token completo)
                if 'access_token' in data:
                    token = data['access_token']
                    print(f"\n🔑 Access Token:")
                    print(f"   Longitud: {len(token)} caracteres")
                    print(f"   Primeros 10 chars: {token[:10]}...")
                    print(f"   Últimos 10 chars: ...{token[-10:]}")
                    
                    # Intentar decodificar si es JWT
                    try:
                        # Los JWT tienen formato: header.payload.signature
                        parts = token.split('.')
                        if len(parts) == 3:
                            print(f"   Formato: JWT (3 partes)")
                            
                            # Decodificar payload (segunda parte)
                            payload = parts[1]
                            # Agregar padding si es necesario
                            padding = 4 - len(payload) % 4
                            if padding != 4:
                                payload += '=' * padding
                            
                            decoded = base64.urlsafe_b64decode(payload)
                            payload_data = json.loads(decoded)
                            
                            print(f"\n   📦 Payload del JWT:")
                            if 'exp' in payload_data:
                                exp_timestamp = payload_data['exp']
                                exp_date = datetime.fromtimestamp(exp_timestamp)
                                now = datetime.now()
                                
                                print(f"      Expira: {exp_date}")
                                print(f"      Ahora: {now}")
                                
                                if exp_date > now:
                                    time_left = exp_date - now
                                    print(f"      ✅ Válido (quedan {time_left})")
                                else:
                                    print(f"      ❌ EXPIRADO")
                            
                            if 'scope' in payload_data:
                                scopes = payload_data['scope'].split()
                                print(f"\n      🔐 Scopes en el token:")
                                for scope in scopes:
                                    emoji = "✅" if scope in ['tweet.write', 'tweet.read'] else "📝"
                                    print(f"         {emoji} {scope}")
                                
                                if 'tweet.write' not in scopes:
                                    print(f"\n      ❌ ¡PROBLEMA ENCONTRADO!")
                                    print(f"         El token NO tiene 'tweet.write'")
                                    print(f"         Por eso obtienes HTTP 403")
                        else:
                            print(f"   Formato: Bearer token (no JWT)")
                    
                    except Exception as e:
                        print(f"   No se pudo decodificar como JWT: {e}")
                
                if 'expires_in' in data:
                    print(f"\n⏰ Expiración:")
                    print(f"   Expira en: {data['expires_in']} segundos")
                
                if 'token_type' in data:
                    print(f"\n📌 Tipo de token: {data['token_type']}")
                
                if 'refresh_token' in data:
                    print(f"\n🔄 Refresh token: Disponible")
                
                print("\n" + "="*70)
                print("📊 ANÁLISIS")
                print("="*70)
                
                # Verificar si tiene los campos necesarios
                has_access_token = 'access_token' in data
                has_user = 'user' in data
                
                if has_access_token and has_user:
                    print("\n✅ Estructura del archivo de sesión: OK")
                else:
                    print("\n⚠️  Estructura del archivo de sesión: INCOMPLETA")
                
            except json.JSONDecodeError:
                print(f"   ❌ Error: El archivo no es un JSON válido")
            except Exception as e:
                print(f"   ❌ Error al leer archivo: {e}")
            
            print("\n" + "="*70)
    
    if not found:
        print("\n⚠️  No se encontró ningún archivo de sesión")
        print("   Esto es normal si nunca has hecho login")
        print("   o si acabas de eliminar las sesiones")
    
    print("\n" + "="*70)
    input("\nPresiona ENTER para salir...")


if __name__ == "__main__":
    debug_token()
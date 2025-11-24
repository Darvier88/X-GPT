"""
Script de Prueba para Twitter Analysis API v2.0
Flujo: Login OAuth → Obtener userName → Buscar/Clasificar/Eliminar
CORREGIDO: Alineado con estructuras JSON reales de los módulos
"""

import requests
import webbrowser
import time
from typing import Optional

BASE_URL = "http://localhost:8080"

class APIClient:
    """Cliente para probar la API con OAuth"""
    
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session_id: Optional[str] = None
        self.username: Optional[str] = None
    
    def test_health(self):
        """Verifica que la API esté funcionando"""
        print("\n" + "="*70)
        print("🏥 VERIFICANDO SALUD DE LA API")
        print("="*70)
        
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ API funcionando correctamente")
                print(f"   Status: {data['status']}")
                print(f"   Sesiones activas: {data['active_sessions']}")
                return True
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            print(f"❌ Error: No se puede conectar a {self.base_url}")
            print(f"   Asegúrate de que main.py esté corriendo")
            return False
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def login(self):
        """Paso 1: Inicia el proceso de login OAuth"""
        print("\n" + "="*70)
        print("🔐 PASO 1: INICIAR LOGIN OAUTH")
        print("="*70)
        
        try:
            response = requests.get(f"{self.base_url}/api/auth/login", timeout=10)
            
            if response.status_code != 200:
                print(f"❌ Error: HTTP {response.status_code}")
                return False
            
            data = response.json()
            auth_url = data['authorization_url']
            state = data['state']
            
            print(f"✅ URL de autorización generada")
            print(f"\n{'─'*70}")
            print(f"🌐 ABRIENDO NAVEGADOR...")
            print(f"{'─'*70}")
            print(f"\nSe abrirá tu navegador para autorizar la aplicación.")
            print(f"Después de autorizar, Twitter te redirigirá al callback.")
            print(f"\nLa API capturará automáticamente tu Session ID.")
            print(f"{'─'*70}\n")
            
            input("Presiona ENTER para abrir el navegador...")
            
            # Abrir navegador
            webbrowser.open(auth_url)
            
            print("\n⏳ Esperando callback de Twitter...")
            print("   (Esto puede tomar unos segundos)")
            
            # Esperar a que el usuario complete la autorización
            print("\nDespués de autorizar:")
            print("1. Deberías ver una página de confirmación")
            print("2. El Session ID se copiará automáticamente al portapapeles")
            print("3. Pégalo aquí abajo\n")
            
            session_id = input("📋 Pega tu Session ID aquí: ").strip()
            
            if not session_id:
                print("❌ No se proporcionó Session ID")
                return False
            
            self.session_id = session_id
            
            # Verificar sesión
            return self.get_current_user()
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def get_current_user(self):
        """Obtiene información del usuario autenticado"""
        if not self.session_id:
            print("❌ No hay session_id. Ejecuta login() primero")
            return False
        
        print("\n" + "="*70)
        print("👤 OBTENIENDO INFORMACIÓN DEL USUARIO")
        print("="*70)
        
        try:
            response = requests.get(
                f"{self.base_url}/api/auth/me",
                params={"session_id": self.session_id},
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ Error: HTTP {response.status_code}")
                return False
            
            data = response.json()
            user = data['user']
            
            self.username = user['username']
            
            print(f"✅ Usuario autenticado:")
            print(f"   Nombre: {user['name']}")
            print(f"   Usuario: @{user['username']}")
            print(f"   ID: {user['id']}")
            print(f"   Seguidores: {user['followers_count']:,}")
            print(f"   Siguiendo: {user['following_count']:,}")
            print(f"   Tweets: {user['tweet_count']:,}")
            print(f"   Verificado: {'✓' if user['verified'] else '✗'}")
            
            return True
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def search_my_tweets(self, max_tweets: int = 50):
        """Busca tweets del usuario autenticado"""
        if not self.session_id:
            print("❌ No hay sesión activa. Ejecuta login() primero")
            return None
        
        print("\n" + "="*70)
        print(f"🔍 BUSCANDO TWEETS DE @{self.username}")
        print("="*70)
        
        try:
            payload = {
                "max_tweets": max_tweets,
                "save_to_file": True
            }
            
            print(f"\n⏳ Obteniendo hasta {max_tweets} tweets...")
            
            response = requests.post(
                f"{self.base_url}/api/tweets/search",
                params={"session_id": self.session_id},
                json=payload,
                timeout=300  # 5 minutos
            )
            
            if response.status_code != 200:
                print(f"❌ Error: HTTP {response.status_code}")
                print(response.text)
                return None
            
            data = response.json()
            
            if not data['success']:
                print(f"❌ Error en búsqueda")
                return None
            
            # ESTRUCTURA CORRECTA: data contiene 'stats', 'tweets', 'user', etc.
            stats = data.get('stats', {})
            
            print(f"\n✅ Tweets obtenidos:")
            print(f"   Total: {stats.get('total_tweets', 0)}")
            print(f"   Retweets: {stats.get('retweet_count', 0)}")
            print(f"   Originales: {stats.get('original_count', 0)}")
            print(f"   Con medios: {stats.get('tweets_with_media', 0)}")
            print(f"   Total medios: {stats.get('total_media_count', 0)}")
            print(f"   Tiempo: {data.get('execution_time', 'N/A')}")
            
            if data.get('file_path'):
                print(f"   Guardado en: {data['file_path']}")
                return data['file_path']
            
            return True
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def classify_tweets(self, json_path: Optional[str] = None, max_tweets: int = 10):
        """Clasifica riesgos de tweets"""
        if not self.session_id:
            print("❌ No hay sesión activa")
            return False
        
        print("\n" + "="*70)
        print("🛡️ CLASIFICANDO RIESGOS DE TWEETS")
        print("="*70)
        
        try:
            if json_path:
                payload = {
                    "json_path": json_path,
                    "max_tweets": max_tweets
                }
                print(f"📂 Usando archivo: {json_path}")
                print(f"📊 Límite: {max_tweets} tweets")
            else:
                # Ejemplo con tweets directos
                payload = {
                    "tweets": [
                        "¡Hermoso día! 🌞",
                        "Este político es un idiota corrupto",
                        "Me encanta programar en Python",
                        "Estos inmigrantes son basura"
                    ]
                }
                print(f"📝 Usando tweets de ejemplo (4 tweets)")
            
            print(f"\n⏳ Clasificando tweets...")
            
            response = requests.post(
                f"{self.base_url}/api/risk/classify",
                params={"session_id": self.session_id},
                json=payload,
                timeout=300
            )
            
            if response.status_code != 200:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"   Respuesta: {response.text}")
                return False
            
            data = response.json()
            
            if not data.get('success'):
                print(f"❌ Error en clasificación")
                return False
            
            # ESTRUCTURA CORRECTA: data['summary'] contiene 'total_analyzed'
            summary = data.get('summary', {})
            
            total_analyzed = summary.get('total_analyzed', 0)
            errors = summary.get('errors', 0)
            exitosos = total_analyzed - errors
            
            print(f"\n✅ Clasificación completada:")
            print(f"   Total analizado: {total_analyzed}")
            print(f"   Exitosos: {exitosos}")
            print(f"   Errores: {errors}")
            
            risk_dist = summary.get('risk_distribution', {})
            print(f"\n   Distribución de riesgos:")
            print(f"      Low:  {risk_dist.get('low', 0)}")
            print(f"      Mid:  {risk_dist.get('mid', 0)}")
            print(f"      High: {risk_dist.get('high', 0)}")
            
            label_counts = summary.get('label_counts', {})
            if label_counts:
                print(f"\n   Labels detectados:")
                sorted_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)
                for label, count in sorted_labels[:5]:
                    print(f"      {label}: {count}")
            
            # Mostrar archivos guardados
            files = data.get('files', {})
            if files:
                print(f"\n   Archivos guardados:")
                if files.get('summary_file'):
                    print(f"      📄 Summary:  {files['summary_file']}")
                if files.get('detailed_file'):
                    print(f"      📄 Detailed: {files['detailed_file']}")
            
            # Mostrar algunos ejemplos de clasificación
            results = data.get('results', [])
            if results:
                print(f"\n   Ejemplos de clasificación (primeros 3):")
                for i, result in enumerate(results[:3], 1):
                    text = result.get('text', '')[:50] + '...' if len(result.get('text', '')) > 50 else result.get('text', '')
                    level = result.get('risk_level', 'N/A')
                    labels = ', '.join(result.get('labels', [])) or 'ninguno'
                    print(f"      {i}. [{level}] {labels}")
                    print(f"         \"{text}\"")
            
            # Mostrar tiempo de ejecución
            exec_time = data.get('execution_time')
            if exec_time:
                print(f"\n   Tiempo de ejecución: {exec_time}")
            
            return True
        
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def delete_tweets(self, json_path: str):
        """Elimina tweets del usuario"""
        if not self.session_id:
            print("❌ No hay sesión activa")
            return False
        
        print("\n" + "="*70)
        print("🗑️ ELIMINANDO TWEETS")
        print("="*70)
        
        confirm = input("\n⚠️  Esta acción es IRREVERSIBLE. ¿Continuar? (escribe 'SI' para confirmar): ")
        
        if confirm != 'SI':
            print("❌ Operación cancelada")
            return False
        
        try:
            payload = {
                "json_path": json_path,
                "delete_retweets": True,
                "delete_originals": False,  # Por seguridad, solo RTs
                "delay_seconds": 1.0
            }
            
            print(f"\n⏳ Eliminando tweets...")
            
            response = requests.post(
                f"{self.base_url}/api/tweets/delete",
                params={"session_id": self.session_id},
                json=payload,
                timeout=600
            )
            
            if response.status_code != 200:
                print(f"❌ Error: HTTP {response.status_code}")
                return False
            
            data = response.json()
            
            print(f"\n✅ Eliminación completada:")
            print(f"   Total procesado: {data.get('total_processed', 0)}")
            print(f"   Retweets eliminados: {data.get('retweets_deleted', 0)}")
            print(f"   Tweets eliminados: {data.get('tweets_deleted', 0)}")
            print(f"   Fallidos: {len(data.get('failed', []))}")
            print(f"   Tiempo: {data.get('execution_time', 'N/A')}")
            
            return True
        
        except Exception as e:
            print(f"❌ Error: {e}")
            return False


# ============================================================================
# FLUJO COMPLETO DE PRUEBA
# ============================================================================

def full_test_flow():
    """Ejecuta el flujo completo de prueba"""
    print("\n" + "="*70)
    print("🧪 PRUEBA COMPLETA DE API - FLUJO OAUTH")
    print("="*70)
    
    client = APIClient()
    
    # 1. Health check
    if not client.test_health():
        print("\n❌ La API no está disponible. Asegúrate de que main.py esté corriendo.")
        return
    
    # 2. Login OAuth
    print("\n" + "─"*70)
    input("Presiona ENTER para continuar con el login OAuth...")
    
    if not client.login():
        print("\n❌ Login fallido")
        return
    
    # 3. Buscar tweets
    print("\n" + "─"*70)
    input("Presiona ENTER para buscar tus tweets...")
    
    json_path = client.search_my_tweets(max_tweets=20)
    
    if not json_path:
        print("\n⚠️  No se pudieron obtener tweets, pero continuamos...")
    
    # 4. Clasificar tweets
    print("\n" + "─"*70)
    input("Presiona ENTER para clasificar tweets...")
    
    if json_path and isinstance(json_path, str):
        client.classify_tweets(json_path=json_path, max_tweets=5)
    else:
        print("Usando tweets de ejemplo...")
        client.classify_tweets(max_tweets=5)
    
    # 5. Resumen
    print("\n" + "="*70)
    print("✅ PRUEBA COMPLETA FINALIZADA")
    print("="*70)
    print(f"\nUsuario autenticado: @{client.username}")
    print(f"Session ID: {client.session_id}")
    print("\nPuedes usar este Session ID para hacer más requests a la API.")
    print("="*70)


def quick_test():
    """Prueba rápida sin login (solo endpoints públicos)"""
    print("\n" + "="*70)
    print("⚡ PRUEBA RÁPIDA - SIN LOGIN")
    print("="*70)
    
    client = APIClient()
    
    # Solo health check y root
    client.test_health()
    
    try:
        response = requests.get(f"{BASE_URL}/")
        if response.status_code == 200:
            data = response.json()
            print(f"\n✅ Endpoints disponibles:")
            for name, path in data.get('endpoints', {}).items():
                print(f"   {name}: {path}")
    except:
        pass


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        quick_test()
    else:
        full_test_flow()
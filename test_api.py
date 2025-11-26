"""
test_api.py - Suite de tests para la API de Twitter Analysis

Incluye tests para:
1. OAuth Login Flow
2. Search Tweets
3. Classify Risk
4. Firebase Integration

Uso:
    python test_api.py                    # Flujo completo interactivo
    python test_api.py --auto             # Flujo automático (requiere session_id)
    python test_api.py --session SESSION  # Usar session_id específico
"""

import requests
import json
import time
import sys
import argparse
from typing import Dict, Any, Optional
from datetime import datetime

# ============================================================================
# CONFIGURACIÓN
# ============================================================================

BASE_URL = "http://localhost:8080"
API_BASE = f"{BASE_URL}/api"

# Colores para la terminal
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

# ============================================================================
# FUNCIONES HELPER
# ============================================================================

def print_header(text: str):
    """Imprime un header bonito"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}{Colors.RESET}\n")

def print_success(text: str):
    """Imprime mensaje de éxito"""
    print(f"{Colors.GREEN}✅ {text}{Colors.RESET}")

def print_error(text: str):
    """Imprime mensaje de error"""
    print(f"{Colors.RED}❌ {text}{Colors.RESET}")

def print_warning(text: str):
    """Imprime mensaje de advertencia"""
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.RESET}")

def print_info(text: str):
    """Imprime mensaje informativo"""
    print(f"{Colors.CYAN}ℹ️  {text}{Colors.RESET}")

def print_step(number: int, text: str):
    """Imprime paso numerado"""
    print(f"\n{Colors.BOLD}{Colors.MAGENTA}[PASO {number}] {text}{Colors.RESET}")

# ============================================================================
# CLASE DE TESTING
# ============================================================================

class TwitterAPITester:
    def __init__(self):
        self.session_id: Optional[str] = None
        self.username: Optional[str] = None
        self.tweets_data: Optional[Dict] = None
        self.classification_data: Optional[Dict] = None
        self.firebase_doc_ids: Dict[str, str] = {}
        self.test_results: Dict[str, bool] = {}
        
    def test_health(self) -> bool:
        """Test 1: Verificar que la API está corriendo"""
        print_step(1, "Health Check - Verificando API")
        
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                print_success("API está corriendo correctamente")
                print_info(f"Status: {data.get('status')}")
                
                firebase_status = data.get('firebase_connected')
                if firebase_status:
                    print_success("Firebase conectado ✅")
                else:
                    print_error("Firebase NO conectado ❌")
                    print_warning("Los tests continuarán pero no se guardará en Firebase")
                
                print_info(f"Sesiones activas: {data.get('active_sessions', 0)}")
                
                self.test_results['health'] = True
                return True
            else:
                print_error(f"Error: Status code {response.status_code}")
                self.test_results['health'] = False
                return False
                
        except Exception as e:
            print_error(f"No se pudo conectar a la API: {str(e)}")
            print_warning("Asegúrate de que la API esté corriendo:")
            print_warning("  python main.py")
            self.test_results['health'] = False
            return False
    
    def test_oauth_login(self) -> bool:
        """Test 2: Iniciar proceso OAuth (requiere intervención manual)"""
        print_step(2, "OAuth Login - Proceso de Autenticación")
        
        try:
            response = requests.get(f"{API_BASE}/auth/login")
            
            if response.status_code == 200:
                data = response.json()
                self.session_id = data.get('session_id')
                
                print_success("URL de autorización generada correctamente")
                
                print(f"\n{Colors.BOLD}{Colors.YELLOW}{'='*70}")
                print("⚠️  ACCIÓN REQUERIDA - AUTORIZACIÓN EN TWITTER")
                print("="*70 + Colors.RESET)
                
                print(f"\n{Colors.BOLD}{Colors.GREEN}📋 SESSION ID (cópialo ahora):{Colors.RESET}")
                print(f"\n   {Colors.BOLD}{Colors.CYAN}{self.session_id}{Colors.RESET}\n")
                
                print(f"{Colors.CYAN}1. Abre esta URL en tu navegador:{Colors.RESET}")
                print(f"\n   {Colors.BOLD}{data.get('authorization_url')}{Colors.RESET}\n")
                print(f"{Colors.CYAN}2. Autoriza la aplicación en Twitter{Colors.RESET}")
                print(f"{Colors.CYAN}3. Después de la redirección, usa el SESSION ID de arriba{Colors.RESET}")
                print(f"\n{Colors.YELLOW}{'='*70}{Colors.RESET}\n")
                
                # Esperar a que el usuario autorice
                input(f"{Colors.GREEN}Presiona ENTER cuando hayas completado la autorización...{Colors.RESET}")
                
                self.test_results['oauth_login'] = True
                return True
            else:
                print_error(f"Error iniciando OAuth: {response.status_code}")
                self.test_results['oauth_login'] = False
                return False
                
        except Exception as e:
            print_error(f"Error en OAuth login: {str(e)}")
            self.test_results['oauth_login'] = False
            return False
    
    def set_session_manually(self, session_id: str, username: str = None):
        """Establecer sesión manualmente después del OAuth callback"""
        self.session_id = session_id
        self.username = username
        print_success(f"Sesión establecida: {session_id[:30]}...")
        if username:
            print_success(f"Usuario: @{username}")
    
    def test_get_user_info(self) -> bool:
        """Test 3: Obtener información del usuario autenticado"""
        print_step(3, "Get User Info - Verificando Usuario Autenticado")
        
        if not self.session_id:
            print_error("No hay session_id. Ejecuta OAuth login primero")
            self.test_results['user_info'] = False
            return False
        
        try:
            response = requests.get(
                f"{API_BASE}/auth/me",
                params={"session_id": self.session_id}
            )
            
            if response.status_code == 200:
                data = response.json()
                user = data.get('user', {})
                
                self.username = user.get('username')
                
                print_success("Usuario autenticado correctamente")
                print(f"\n{Colors.BOLD}Información del usuario:{Colors.RESET}")
                print(f"  Username:  @{user.get('username')}")
                print(f"  Nombre:    {user.get('name')}")
                print(f"  Followers: {user.get('followers_count'):,}")
                print(f"  Following: {user.get('following_count'):,}")
                print(f"  Tweets:    {user.get('tweet_count'):,}")
                print(f"  Verified:  {'✅ Sí' if user.get('verified') else '❌ No'}")
                
                self.test_results['user_info'] = True
                return True
            else:
                print_error(f"Error obteniendo usuario: {response.status_code}")
                print_error(response.text)
                self.test_results['user_info'] = False
                return False
                
        except Exception as e:
            print_error(f"Error: {str(e)}")
            self.test_results['user_info'] = False
            return False
    
    def test_search_tweets(self, max_tweets: int = 10) -> bool:
        """Test 4: Buscar tweets del usuario"""
        print_step(4, f"Search Tweets - Obteniendo últimos {max_tweets} tweets")
        
        if not self.session_id:
            print_error("No hay session_id disponible")
            self.test_results['search_tweets'] = False
            return False
        
        try:
            payload = {
                "max_tweets": max_tweets,
                "save_to_firebase": True
            }
            
            print_info(f"Buscando tweets de @{self.username}...")
            print_warning("Esto puede tomar unos segundos...")
            
            start_time = time.time()
            
            response = requests.post(
                f"{API_BASE}/tweets/search",
                params={"session_id": self.session_id},
                json=payload,
                timeout=60
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                self.tweets_data = data
                
                tweets = data.get('tweets', [])
                stats = data.get('stats', {})
                firebase_doc_id = data.get('firebase_doc_id')
                
                if firebase_doc_id:
                    self.firebase_doc_ids['tweets'] = firebase_doc_id
                
                print_success(f"Tweets obtenidos exitosamente en {elapsed:.2f}s")
                
                print(f"\n{Colors.BOLD}Estadísticas:{Colors.RESET}")
                print(f"  Total tweets:      {len(tweets)}")
                print(f"  Tweets originales: {stats.get('original_tweets', 0)}")
                print(f"  Retweets:          {stats.get('retweets', 0)}")
                print(f"  Páginas obtenidas: {data.get('pages_fetched', 0)}")
                print(f"  Tiempo ejecución:  {data.get('execution_time', 'N/A')}")
                
                if firebase_doc_id:
                    print_success(f"Guardado en Firebase: {firebase_doc_id}")
                else:
                    print_warning("No se guardó en Firebase (puede estar desconectado)")
                
                # Mostrar sample de tweets
                print(f"\n{Colors.BOLD}Muestra de tweets obtenidos:{Colors.RESET}")
                for i, tweet in enumerate(tweets[:3], 1):
                    tweet_type = "🔄 RT" if tweet.get('is_retweet') else "💬 Tweet"
                    print(f"\n  {i}. {tweet_type} [{tweet.get('id')}]")
                    text = tweet.get('text', '').replace('\n', ' ')[:100]
                    print(f"     {text}...")
                
                self.test_results['search_tweets'] = True
                return True
            else:
                print_error(f"Error buscando tweets: {response.status_code}")
                print_error(response.text)
                self.test_results['search_tweets'] = False
                return False
                
        except Exception as e:
            print_error(f"Error: {str(e)}")
            self.test_results['search_tweets'] = False
            return False
    
    def test_classify_risk(self, max_tweets: int = None) -> bool:
        """Test 5: Clasificar riesgos de los tweets"""
        print_step(5, "Classify Risk - Análisis de Riesgos con GPT")
        
        if not self.session_id:
            print_error("No hay session_id disponible")
            self.test_results['classify_risk'] = False
            return False
        
        if not self.tweets_data or not self.tweets_data.get('tweets'):
            print_error("No hay tweets para clasificar. Ejecuta search_tweets primero")
            self.test_results['classify_risk'] = False
            return False
        
        try:
            tweets = self.tweets_data.get('tweets', [])
            
            if max_tweets:
                tweets = tweets[:max_tweets]
            
            payload = {
                "tweets": tweets,
                "max_tweets": max_tweets
            }
            
            print_info(f"Clasificando {len(tweets)} tweets...")
            print_warning("Esto puede tomar varios minutos (depende del número de tweets)...")
            print_info("Estimación: ~3-5 segundos por tweet")
            
            start_time = time.time()
            
            response = requests.post(
                f"{API_BASE}/risk/classify",
                params={
                    "session_id": self.session_id,
                    "save_to_firebase": True
                },
                json=payload,
                timeout=600  # 10 minutos timeout
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                self.classification_data = data
                
                results = data.get('results', [])
                summary = data.get('summary', {})
                firebase_doc_id = data.get('firebase_doc_id')
                
                if firebase_doc_id:
                    self.firebase_doc_ids['classification'] = firebase_doc_id
                
                print_success(f"Clasificación completada en {elapsed:.2f}s ({elapsed/60:.1f} minutos)")
                print_info(f"Tweets analizados: {data.get('total_tweets', 0)}")
                
                # Distribución de riesgos
                dist = summary.get('risk_distribution', {})
                print(f"\n{Colors.BOLD}📊 Distribución de riesgos:{Colors.RESET}")
                print(f"  🟢 Sin riesgo:   {dist.get('no', 0):>3} tweets")
                print(f"  🟡 Riesgo bajo:  {dist.get('low', 0):>3} tweets")
                print(f"  🟠 Riesgo medio: {dist.get('mid', 0):>3} tweets")
                print(f"  🔴 Riesgo alto:  {dist.get('high', 0):>3} tweets")
                
                # Labels más comunes
                labels = summary.get('label_counts', {})
                if labels:
                    print(f"\n{Colors.BOLD}🏷️  Labels más comunes:{Colors.RESET}")
                    sorted_labels = sorted(labels.items(), key=lambda x: x[1], reverse=True)
                    for label, count in sorted_labels[:5]:
                        print(f"  • {label}: {count}")
                
                if firebase_doc_id:
                    print_success(f"\n💾 Guardado en Firebase: {firebase_doc_id}")
                
                # Mostrar sample de clasificaciones
                print(f"\n{Colors.BOLD}Ejemplos de clasificaciones:{Colors.RESET}")
                for i, result in enumerate(results[:3], 1):
                    risk_icons = {
                        'no': '🟢',
                        'low': '🟡',
                        'mid': '🟠',
                        'high': '🔴'
                    }
                    risk_level = result.get('risk_level', 'low')
                    icon = risk_icons.get(risk_level, '⚪')
                    
                    print(f"\n  {i}. {icon} Riesgo: {Colors.BOLD}{risk_level.upper()}{Colors.RESET}")
                    text = result.get('text', '').replace('\n', ' ')[:80]
                    print(f"     Tweet: {text}...")
                    print(f"     Labels: {', '.join(result.get('labels', []))}")
                    reason = result.get('reason', '')[:100].replace('\n', ' ')
                    print(f"     Razón: {reason}...")
                
                self.test_results['classify_risk'] = True
                return True
            else:
                print_error(f"Error clasificando: {response.status_code}")
                print_error(response.text)
                self.test_results['classify_risk'] = False
                return False
                
        except Exception as e:
            print_error(f"Error: {str(e)}")
            self.test_results['classify_risk'] = False
            return False
    
    def test_estimate_time(self) -> bool:
        """Test 6: Estimar tiempo de procesamiento"""
        print_step(6, "Estimate Time - Cálculo de Tiempo Total")
        
        if not self.session_id:
            print_error("No hay session_id disponible")
            self.test_results['estimate_time'] = False
            return False
        
        try:
            response = requests.get(
                f"{API_BASE}/estimate/time",
                params={"session_id": self.session_id}
            )
            
            if response.status_code == 200:
                data = response.json()
                tiempo = data.get('tiempo_estimado_total')
                
                print_success(f"Tiempo estimado para todos los tweets: {tiempo}")
                print_warning("Esta es una estimación basada en el total de tweets del usuario")
                print_info("El tiempo real puede variar según la carga del servidor")
                
                self.test_results['estimate_time'] = True
                return True
            else:
                print_error(f"Error estimando tiempo: {response.status_code}")
                self.test_results['estimate_time'] = False
                return False
                
        except Exception as e:
            print_error(f"Error: {str(e)}")
            self.test_results['estimate_time'] = False
            return False
    
    def print_summary(self):
        """Imprime un resumen completo de todos los tests"""
        print_header("RESUMEN FINAL DE TESTS")
        
        # Resultados de tests
        print(f"{Colors.BOLD}📋 Resultados de Tests:{Colors.RESET}")
        for test_name, result in self.test_results.items():
            icon = "✅" if result else "❌"
            status = f"{Colors.GREEN}PASS{Colors.RESET}" if result else f"{Colors.RED}FAIL{Colors.RESET}"
            print(f"  {icon} {test_name.replace('_', ' ').title()}: {status}")
        
        # Información de sesión
        if self.session_id:
            print(f"\n{Colors.BOLD}🔐 Información de Sesión:{Colors.RESET}")
            print(f"  Session ID: {self.session_id[:40]}...")
            print(f"  Username:   @{self.username or 'N/A'}")
        
        # Datos de tweets
        if self.tweets_data:
            print(f"\n{Colors.BOLD}🐦 Tweets Obtenidos:{Colors.RESET}")
            tweets = self.tweets_data.get('tweets', [])
            stats = self.tweets_data.get('stats', {})
            print(f"  Total:      {len(tweets)}")
            print(f"  Originales: {stats.get('original_tweets', 0)}")
            print(f"  Retweets:   {stats.get('retweets', 0)}")
            if self.firebase_doc_ids.get('tweets'):
                print(f"  Firebase:   {self.firebase_doc_ids['tweets']}")
        
        # Datos de clasificación
        if self.classification_data:
            print(f"\n{Colors.BOLD}🛡️  Clasificación de Riesgos:{Colors.RESET}")
            summary = self.classification_data.get('summary', {})
            dist = summary.get('risk_distribution', {})
            print(f"  Analizados: {self.classification_data.get('total_tweets', 0)}")
            print(f"  Sin riesgo: {dist.get('no', 0)}")
            print(f"  Bajo:       {dist.get('low', 0)}")
            print(f"  Medio:      {dist.get('mid', 0)}")
            print(f"  Alto:       {dist.get('high', 0)}")
            if self.firebase_doc_ids.get('classification'):
                print(f"  Firebase:   {self.firebase_doc_ids['classification']}")
        
        # Estadísticas finales
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result)
        
        print(f"\n{Colors.BOLD}📊 Estadísticas:{Colors.RESET}")
        print(f"  Tests ejecutados: {total_tests}")
        print(f"  Tests exitosos:   {passed_tests}")
        print(f"  Tests fallidos:   {total_tests - passed_tests}")
        print(f"  Tasa de éxito:    {(passed_tests/total_tests*100):.1f}%")
        
        # Firebase docs guardados
        if self.firebase_doc_ids:
            print(f"\n{Colors.BOLD}💾 Documentos en Firebase:{Colors.RESET}")
            for key, doc_id in self.firebase_doc_ids.items():
                print(f"  {key}: {doc_id}")
        
        # Mensaje final
        print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*70}")
        if passed_tests == total_tests:
            print("🎉 ¡TODOS LOS TESTS PASARON EXITOSAMENTE!")
        else:
            print(f"⚠️  {total_tests - passed_tests} TEST(S) FALLARON")
        print(f"{'='*70}{Colors.RESET}\n")

# ============================================================================
# FLUJO COMPLETO AUTOMÁTICO
# ============================================================================

def run_full_flow(session_id: str = None, max_tweets: int = 10):
    """Ejecuta el flujo completo de tests"""
    tester = TwitterAPITester()
    
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("="*70)
    print("  🧪 TWITTER ANALYSIS API - TEST SUITE COMPLETO")
    print("="*70)
    print(f"{Colors.RESET}")
    
    # Test 1: Health Check
    if not tester.test_health():
        print_error("\n❌ API no disponible. Abortando tests.")
        return
    
    # Test 2: OAuth Login o usar session_id provisto
    if session_id:
        print_step(2, "OAuth Login - Usando session_id provisto")
        tester.set_session_manually(session_id)
        tester.test_results['oauth_login'] = True
    else:
        if not tester.test_oauth_login():
            print_error("\n❌ OAuth login falló. Abortando tests.")
            return
        
        # Pedir session_id después de la autorización
        print(f"\n{Colors.YELLOW}Ingresa el session_id del callback:{Colors.RESET}")
        session_id = input("Session ID: ").strip()
        tester.set_session_manually(session_id)
    
    # Test 3: Get User Info
    if not tester.test_get_user_info():
        print_error("\n❌ No se pudo obtener información del usuario.")
        print_warning("Verifica que el session_id sea válido.")
        tester.print_summary()
        return
    
    # Test 4: Search Tweets
    print(f"\n{Colors.CYAN}¿Cuántos tweets quieres buscar? (default: {max_tweets}){Colors.RESET}")
    user_input = input("Número: ").strip()
    if user_input:
        try:
            max_tweets = int(user_input)
        except:
            print_warning(f"Valor inválido, usando default: {max_tweets}")
    
    if not tester.test_search_tweets(max_tweets):
        print_error("\n❌ Búsqueda de tweets falló.")
        tester.print_summary()
        return
    
    # Test 5: Classify Risk
    print(f"\n{Colors.CYAN}¿Clasificar todos los tweets obtenidos? (s/n){Colors.RESET}")
    classify_all = input().strip().lower()
    
    classify_max = None
    if classify_all != 's':
        print(f"{Colors.CYAN}¿Cuántos tweets clasificar?{Colors.RESET}")
        user_input = input("Número: ").strip()
        if user_input:
            try:
                classify_max = int(user_input)
            except:
                print_warning("Valor inválido, clasificando todos")
    
    if not tester.test_classify_risk(classify_max):
        print_error("\n❌ Clasificación de riesgos falló.")
        tester.print_summary()
        return
    
    # Test 6: Estimate Time
    tester.test_estimate_time()
    
    # Resumen final
    tester.print_summary()

# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Test Suite para Twitter Analysis API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  python test_api.py                          # Flujo interactivo completo
  python test_api.py --session ABC123         # Usar session_id específico
  python test_api.py --session ABC --tweets 5 # Buscar solo 5 tweets
        """
    )
    
    parser.add_argument(
        '--session',
        type=str,
        help='Session ID para usar (evita OAuth manual)'
    )
    
    parser.add_argument(
        '--tweets',
        type=int,
        default=10,
        help='Número de tweets a buscar (default: 10)'
    )
    
    args = parser.parse_args()
    
    # Ejecutar flujo completo
    run_full_flow(
        session_id=args.session,
        max_tweets=args.tweets
    )

if __name__ == "__main__":
    main()
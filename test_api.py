"""
test_dashboard_flow.py - Test del flujo completo Dashboard

Simula el flujo exacto que sigue el Dashboard:
1. OAuth Login
2. Get User Info
3. Search Tweets (guarda en Firebase)
4. Classify Risk (guarda en Firebase)
5. Get Data from Firebase (como Dashboard)

Uso:
    python test_dashboard_flow.py
"""

import requests
import json
import time
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
# CLASE DE TESTING DEL FLUJO DASHBOARD
# ============================================================================

class DashboardFlowTester:
    def __init__(self):
        self.session_id: Optional[str] = None
        self.username: Optional[str] = None
        self.tweets_firebase_id: Optional[str] = None
        self.classification_firebase_id: Optional[str] = None
        self.test_results: Dict[str, bool] = {}
        
    def step1_oauth_login(self) -> bool:
        """Paso 1: Iniciar OAuth (requiere intervención manual)"""
        print_step(1, "OAuth Login - Generar URL de autorización")
        
        try:
            response = requests.get(f"{API_BASE}/auth/login")
            
            if response.status_code == 200:
                data = response.json()
                self.session_id = data.get('session_id')
                
                print_success("URL de autorización generada")
                
                print(f"\n{Colors.BOLD}{Colors.GREEN}📋 SESSION ID (cópialo):{Colors.RESET}")
                print(f"\n   {Colors.BOLD}{Colors.CYAN}{self.session_id}{Colors.RESET}\n")
                
                print(f"{Colors.YELLOW}{'='*70}")
                print("⚠️  ACCIÓN REQUERIDA")
                print("="*70)
                print(f"1. Abre esta URL en tu navegador:")
                print(f"\n   {data.get('authorization_url')}\n")
                print(f"2. Autoriza la aplicación")
                print(f"3. Usa el SESSION ID de arriba")
                print(f"{'='*70}{Colors.RESET}\n")
                
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
    
    def step2_get_user_info(self) -> bool:
        """Paso 2: Obtener información del usuario (como OAuthCallback)"""
        print_step(2, "Get User Info - Verificar autenticación")
        
        if not self.session_id:
            print_error("No hay session_id. Ejecuta step1 primero")
            self.test_results['get_user_info'] = False
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
                print(f"  Tweets:    {user.get('tweet_count'):,}")
                
                # Simular lo que hace OAuthCallback (guardar en sessionStorage)
                print_info("Simulando sessionStorage:")
                print(f"  session_id: {self.session_id[:30]}...")
                print(f"  username: @{self.username}")
                print(f"  tweet_count: {user.get('tweet_count')}")
                
                self.test_results['get_user_info'] = True
                return True
            else:
                print_error(f"Error obteniendo usuario: {response.status_code}")
                print_error(response.text)
                self.test_results['get_user_info'] = False
                return False
                
        except Exception as e:
            print_error(f"Error: {str(e)}")
            self.test_results['get_user_info'] = False
            return False
    
    def step3_search_tweets(self, max_tweets: int = 10) -> bool:
        """Paso 3: Buscar tweets y guardar en Firebase (como Analyzing)"""
        print_step(3, f"Search Tweets - Buscar y guardar en Firebase")
        
        if not self.session_id:
            print_error("No hay session_id disponible")
            self.test_results['search_tweets'] = False
            return False
        
        try:
            payload = {
                "max_tweets": max_tweets,
                "save_to_firebase": True
            }
            
            print_info(f"Buscando {max_tweets} tweets de @{self.username}...")
            print_warning("Guardando en Firebase...")
            
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
                
                tweets = data.get('tweets', [])
                firebase_doc_id = data.get('firebase_doc_id')
                
                if firebase_doc_id:
                    self.tweets_firebase_id = firebase_doc_id
                
                print_success(f"Tweets obtenidos en {elapsed:.2f}s")
                print(f"\n{Colors.BOLD}Resultados:{Colors.RESET}")
                print(f"  Total tweets: {len(tweets)}")
                print(f"  Stats: {data.get('stats')}")
                
                if firebase_doc_id:
                    print_success(f"Guardado en Firebase: {firebase_doc_id}")
                    print_info("Simulando sessionStorage:")
                    print(f"  tweets_firebase_id: {firebase_doc_id}")
                else:
                    print_warning("No se guardó en Firebase")
                
                # Mostrar sample
                print(f"\n{Colors.BOLD}Sample de tweets:{Colors.RESET}")
                for i, tweet in enumerate(tweets[:3], 1):
                    print(f"\n  {i}. [{tweet.get('id')}]")
                    print(f"     {tweet.get('text', '')[:80]}...")
                
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
    
    def step4_classify_risk(self, max_tweets: int = None) -> bool:
        """Paso 4: Clasificar riesgos y guardar en Firebase (como Analyzing)"""
        print_step(4, "Classify Risk - Clasificar y guardar en Firebase")
        
        if not self.session_id:
            print_error("No hay session_id disponible")
            self.test_results['classify_risk'] = False
            return False
        
        if not self.tweets_firebase_id:
            print_error("No hay tweets. Ejecuta step3 primero")
            self.test_results['classify_risk'] = False
            return False
        
        try:
            # Primero necesitamos obtener los tweets para clasificarlos
            print_info("Obteniendo tweets desde Firebase...")
            
            # Obtener tweets de Firebase
            get_response = requests.get(
                f"{API_BASE}/firebase/get-data",
                params={
                    "session_id": self.session_id,
                    "tweets_doc_id": self.tweets_firebase_id
                }
            )
            
            if not get_response.ok:
                print_error("Error obteniendo tweets de Firebase")
                self.test_results['classify_risk'] = False
                return False
            
            firebase_data = get_response.json()
            tweets = firebase_data['data']['tweets_data']['tweets']
            
            if max_tweets:
                tweets = tweets[:max_tweets]
            
            print_info(f"Clasificando {len(tweets)} tweets...")
            print_warning("Guardando en Firebase...")
            
            payload = {
                "tweets": tweets,
                "max_tweets": max_tweets
            }
            
            start_time = time.time()
            
            response = requests.post(
                f"{API_BASE}/risk/classify",
                params={
                    "session_id": self.session_id,
                    "save_to_firebase": True
                },
                json=payload,
                timeout=600
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                
                results = data.get('results', [])
                summary = data.get('summary', {})
                firebase_doc_id = data.get('firebase_doc_id')
                
                if firebase_doc_id:
                    self.classification_firebase_id = firebase_doc_id
                
                print_success(f"Clasificación completada en {elapsed:.2f}s")
                print_info(f"Tweets analizados: {data.get('total_tweets', 0)}")
                
                # Distribución de riesgos
                dist = summary.get('risk_distribution', {})
                print(f"\n{Colors.BOLD}📊 Distribución:{Colors.RESET}")
                print(f"  🟢 Sin riesgo: {dist.get('no', 0)}")
                print(f"  🟡 Bajo: {dist.get('low', 0)}")
                print(f"  🟠 Medio: {dist.get('mid', 0)}")
                print(f"  🔴 Alto: {dist.get('high', 0)}")
                
                if firebase_doc_id:
                    print_success(f"\nGuardado en Firebase: {firebase_doc_id}")
                    print_info("Simulando sessionStorage:")
                    print(f"  classification_firebase_id: {firebase_doc_id}")
                
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
    
    def step5_get_firebase_data(self) -> bool:
        """Paso 5: Obtener datos de Firebase (como Dashboard)"""
        print_step(5, "Get Firebase Data - Cargar datos como Dashboard")
        
        if not self.session_id:
            print_error("No hay session_id disponible")
            self.test_results['get_firebase_data'] = False
            return False
        
        if not self.tweets_firebase_id or not self.classification_firebase_id:
            print_error("No hay Firebase Doc IDs. Ejecuta steps 3 y 4 primero")
            self.test_results['get_firebase_data'] = False
            return False
        
        try:
            print_info("Cargando datos desde Firebase (simulando Dashboard)...")
            print(f"\n{Colors.BOLD}Parámetros:{Colors.RESET}")
            print(f"  session_id: {self.session_id[:30]}...")
            print(f"  tweets_doc_id: {self.tweets_firebase_id}")
            print(f"  classification_doc_id: {self.classification_firebase_id}")
            
            response = requests.get(
                f"{API_BASE}/firebase/get-data",
                params={
                    "session_id": self.session_id,
                    "tweets_doc_id": self.tweets_firebase_id,
                    "classification_doc_id": self.classification_firebase_id
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                
                print_success("Datos cargados desde Firebase exitosamente")
                
                # Analizar estructura de datos
                firebase_data = data.get('data', {})
                tweets_data = firebase_data.get('tweets_data', {})
                classification_data = firebase_data.get('classification_data', {})
                
                print(f"\n{Colors.BOLD}📦 Datos obtenidos:{Colors.RESET}")
                
                # Tweets
                tweets = tweets_data.get('tweets', [])
                user_info = tweets_data.get('user_info', {})
                print(f"\n  🐦 Tweets:")
                print(f"     Total: {len(tweets)}")
                print(f"     Usuario: {user_info.get('username')}")
                print(f"     Avatar: {user_info.get('avatar_url', 'N/A')[:50]}...")
                
                # Clasificación
                results = classification_data.get('results', [])
                summary = classification_data.get('summary', {})
                dist = summary.get('risk_distribution', {})
                
                print(f"\n  🛡️  Clasificación:")
                print(f"     Total analizados: {classification_data.get('total_tweets', 0)}")
                print(f"     Distribución: No={dist.get('no', 0)}, Low={dist.get('low', 0)}, Mid={dist.get('mid', 0)}, High={dist.get('high', 0)}")
                print(f"     Labels: {list(summary.get('label_counts', {}).keys())[:5]}")
                
                # Validar estructura (como Dashboard)
                print(f"\n{Colors.BOLD}✅ Validación de estructura:{Colors.RESET}")
                
                checks = [
                    ("tweets_data existe", 'tweets_data' in firebase_data),
                    ("classification_data existe", 'classification_data' in firebase_data),
                    ("tweets array existe", len(tweets) > 0),
                    ("results array existe", len(results) > 0),
                    ("user_info existe", 'user_info' in tweets_data),
                    ("summary existe", 'summary' in classification_data),
                ]
                
                all_passed = True
                for check_name, check_result in checks:
                    if check_result:
                        print_success(f"{check_name}")
                    else:
                        print_error(f"{check_name}")
                        all_passed = False
                
                if all_passed:
                    print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 Todos los datos están correctos para Dashboard{Colors.RESET}")
                
                self.test_results['get_firebase_data'] = all_passed
                return all_passed
            else:
                print_error(f"Error obteniendo datos: {response.status_code}")
                print_error(response.text)
                self.test_results['get_firebase_data'] = False
                return False
                
        except Exception as e:
            print_error(f"Error: {str(e)}")
            import traceback
            traceback.print_exc()
            self.test_results['get_firebase_data'] = False
            return False
    
    def print_summary(self):
        """Imprime resumen final"""
        print_header("RESUMEN FINAL DEL FLUJO DASHBOARD")
        
        print(f"{Colors.BOLD}📋 Resultados de Tests:{Colors.RESET}")
        steps = [
            ("OAuth Login", self.test_results.get('oauth_login', False)),
            ("Get User Info", self.test_results.get('get_user_info', False)),
            ("Search Tweets", self.test_results.get('search_tweets', False)),
            ("Classify Risk", self.test_results.get('classify_risk', False)),
            ("Get Firebase Data", self.test_results.get('get_firebase_data', False)),
        ]
        
        for step_name, result in steps:
            icon = "✅" if result else "❌"
            status = f"{Colors.GREEN}PASS{Colors.RESET}" if result else f"{Colors.RED}FAIL{Colors.RESET}"
            print(f"  {icon} {step_name}: {status}")
        
        print(f"\n{Colors.BOLD}🔥 Firebase Doc IDs:{Colors.RESET}")
        print(f"  Tweets: {self.tweets_firebase_id or 'N/A'}")
        print(f"  Classification: {self.classification_firebase_id or 'N/A'}")
        
        print(f"\n{Colors.BOLD}📊 Estadísticas:{Colors.RESET}")
        total = len(steps)
        passed = sum(1 for _, result in steps if result)
        print(f"  Tests ejecutados: {total}")
        print(f"  Tests exitosos:   {passed}")
        print(f"  Tests fallidos:   {total - passed}")
        print(f"  Tasa de éxito:    {(passed/total*100):.1f}%")
        
        if passed == total:
            print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*70}")
            print("🎉 ¡FLUJO COMPLETO EXITOSO! Dashboard debería funcionar perfectamente")
            print(f"{'='*70}{Colors.RESET}\n")
        else:
            print(f"\n{Colors.BOLD}{Colors.RED}{'='*70}")
            print(f"⚠️  {total - passed} TEST(S) FALLARON - Revisa los errores arriba")
            print(f"{'='*70}{Colors.RESET}\n")

# ============================================================================
# MAIN
# ============================================================================

def main():
    """Ejecuta el flujo completo del Dashboard"""
    tester = DashboardFlowTester()
    
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("="*70)
    print("  🧪 DASHBOARD FLOW TEST - Flujo Completo")
    print("="*70)
    print(f"{Colors.RESET}")
    
    print(f"\n{Colors.CYAN}Este test simula el flujo exacto que sigue el Dashboard:")
    print("1. OAuth Login")
    print("2. Get User Info (OAuthCallback)")
    print("3. Search Tweets → Firebase (Analyzing)")
    print("4. Classify Risk → Firebase (Analyzing)")
    print("5. Get Firebase Data (Dashboard)")
    print(f"{Colors.RESET}\n")
    
    # Test 1: OAuth Login
    if not tester.step1_oauth_login():
        print_error("\n❌ OAuth login falló. Abortando tests.")
        tester.print_summary()
        return
    
    # Test 2: Get User Info
    if not tester.step2_get_user_info():
        print_error("\n❌ Get user info falló. Abortando tests.")
        tester.print_summary()
        return
    
    # Preguntar cuántos tweets
    print(f"\n{Colors.CYAN}Usando límite fijo de 10 tweets para el test{Colors.RESET}")
    max_tweets = 10
    
    # Test 3: Search Tweets
    if not tester.step3_search_tweets(max_tweets):
        print_error("\n❌ Search tweets falló. Abortando tests.")
        tester.print_summary()
        return
    
    # Test 4: Classify Risk
    if not tester.step4_classify_risk(max_tweets):
        print_error("\n❌ Classify risk falló. Abortando tests.")
        tester.print_summary()
        return
    
    # Test 5: Get Firebase Data (el más importante para Dashboard)
    if not tester.step5_get_firebase_data():
        print_error("\n❌ Get Firebase data falló.")
        tester.print_summary()
        return
    
    # Resumen final
    tester.print_summary()

if __name__ == "__main__":
    main()
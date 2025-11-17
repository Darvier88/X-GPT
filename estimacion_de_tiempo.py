import json
import time
from pathlib import Path
from datetime import datetime

# Importar módulos
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from X.search_tweets import fetch_user_tweets
from X.user_resolver import resolve_user
from GPT.risk_classifier_only_text import classify_risk_text_only, load_tweets_from_json


def format_time(seconds: float) -> str:
    """Formatea segundos en formato legible"""
    if seconds < 0:
        return "00:00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def estimate_user_resolution(username: str) -> dict:
    """Estima tiempo de resolución de usuario"""
    print(f"\n{'='*70}")
    print("📍 MÓDULO: USER RESOLVER")
    print(f"{'='*70}")
    print(f"Función: resolve_user('{username}')")
    
    start = time.time()
    result = resolve_user(username)
    elapsed = time.time() - start
    
    if result['success']:
        print(f"✅ Usuario resuelto en {elapsed:.2f}s")
        print(f"   @{result['username']} → user_id: {result['user_id']}")
    else:
        print(f"❌ Error: {result['error_message']}")
    
    return {
        "modulo": "user_resolver",
        "funcion": "resolve_user",
        "tiempo_real": f"{elapsed:.2f}s",
        "tiempo_segundos": round(elapsed, 2),
        "exito": result['success']
    }


def estimate_tweet_fetching(username: str, max_tweets: int) -> dict:
    """Estima tiempo de obtención de tweets"""
    print(f"\n{'='*70}")
    print("🐦 MÓDULO: SEARCH TWEETS")
    print(f"{'='*70}")
    print(f"Función: fetch_user_tweets('{username}', max_tweets={max_tweets})")
    print(f"Calculando tiempo estimado...")
    
    # Hacer una petición de prueba para obtener estimación
    start = time.time()
    result = fetch_user_tweets(username, max_tweets=max_tweets)
    elapsed = time.time() - start
    
    if result['success']:
        tiempo_estimado = result.get('execution_time', format_time(elapsed))
        print(f"✅ Tweets obtenidos: {result['stats']['total_tweets']}")
        print(f"⏱️  Tiempo total: {tiempo_estimado}")
        
        return {
            "modulo": "search_tweets",
            "funcion": "fetch_user_tweets",
            "parametros": {
                "username": username,
                "max_tweets": max_tweets
            },
            "tweets_obtenidos": result['stats']['total_tweets'],
            "tiempo_estimado": tiempo_estimado,
            "tiempo_real": format_time(elapsed),
            "tiempo_segundos": result.get('execution_time_seconds', elapsed),
            "exito": True
        }
    else:
        print(f"❌ Error: {result.get('error')}")
        return {
            "modulo": "search_tweets",
            "funcion": "fetch_user_tweets",
            "error": result.get('error'),
            "tiempo_real": format_time(elapsed),
            "exito": False
        }


def estimate_risk_classification(json_path: str, sample_size: int = 3, max_tweets_limit: int = None) -> dict:
    """Estima tiempo de clasificación de riesgos CON política"""
    print(f"\n{'='*70}")
    print("🛡️  MÓDULO: RISK CLASSIFIER")
    print(f"{'='*70}")
    
    try:
        tweets_data = load_tweets_from_json(json_path)
        tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
        total_tweets_in_file = len(tweets)
        
        # Si hay un límite de tweets, usarlo
        if max_tweets_limit and max_tweets_limit < total_tweets_in_file:
            total_tweets = max_tweets_limit
            tweets = tweets[:max_tweets_limit]
            print(f"Tweets en archivo: {total_tweets_in_file}")
            print(f"Límite aplicado: {total_tweets}")
        else:
            total_tweets = total_tweets_in_file
            print(f"Tweets cargados: {total_tweets}")
        
        print(f"Analizando {sample_size} tweets de muestra CON POLÍTICA v1.0...")
        
        # Analizar muestra CON política
        sample_times = []
        for i, tweet in enumerate(tweets[:sample_size], 1):
            print(f"   Muestra {i}/{sample_size}...", end=" ", flush=True)
            start = time.time()
            classify_risk_text_only(tweet)  # <-- CAMBIO AQUI
            elapsed = time.time() - start
            sample_times.append(elapsed)
            print(f"✓ ({elapsed:.2f}s)")
        
        # Calcular estimación
        avg_time = sum(sample_times) / len(sample_times)
        estimated_total = avg_time * total_tweets
        
        print(f"\n📊 ESTIMACIÓN:")
        print(f"   Tiempo promedio por tweet: {avg_time:.2f}s")
        print(f"   Total de tweets a analizar: {total_tweets}")
        print(f"   Tiempo estimado total: {format_time(estimated_total)}")
        
        return {
            "modulo": "risk_classifier",
            "funcion": "classify_risk",
            "total_tweets": total_tweets,
            "total_tweets_en_archivo": total_tweets_in_file,
            "muestra_analizada": sample_size,
            "tiempo_promedio_por_tweet": f"{avg_time:.2f}s",
            "tiempo_estimado_total": format_time(estimated_total),
            "tiempo_segundos": round(estimated_total, 2),
            "exito": True
        }
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return {
            "modulo": "risk_classifier",
            "error": str(e),
            "exito": False
        }


def quick_estimate_all(username: str, max_tweets: int, json_path: str, sample_size: int = 3) -> dict:
    """Realiza estimaciones rápidas de todos los módulos para mostrar tiempo total"""
    print(f"\n🔄 Calculando tiempo estimado total del proceso completo...")
    print(f"   Analizando muestras de {sample_size} tweets...\n")
    
    tiempos = {}
    
    # 1. User resolver (estimación rápida)
    print(f"   [1/3] User Resolver...", end=" ", flush=True)
    start = time.time()
    resolve_user(username)
    tiempos['user_resolver'] = time.time() - start
    print(f"✓ ({tiempos['user_resolver']:.2f}s)")
    
    # 2. Search tweets (estimación basada en max_tweets y rate limit)
    print(f"   [2/3] Search Tweets (estimando para {max_tweets} tweets)...", end=" ", flush=True)
    
    # Hacer una petición de prueba para obtener rate limit info
    try:
        import requests
        from config import get_x_api_key
        
        # Resolver user_id primero
        test_result = resolve_user(username)
        if test_result['success']:
            author_id = test_result['user_id']
            
            # Hacer petición de prueba
            token = get_x_api_key()
            headers = {"Authorization": f"Bearer {token}"}
            url = f"https://api.twitter.com/2/users/{author_id}/tweets"
            params = {"max_results": 100}
            
            test_response = requests.get(url, headers=headers, params=params, timeout=30)
            
            # Obtener rate limit info
            rate_limit_remaining = int(test_response.headers.get('x-rate-limit-remaining', 900))
            rate_limit_reset = int(test_response.headers.get('x-rate-limit-reset', 0))
            rate_limit_total = int(test_response.headers.get('x-rate-limit-limit', 900))
            
            # Calcular páginas necesarias
            pages_needed = (max_tweets + 99) // 100
            
            # Tiempo base de requests (2s por página)
            request_time = pages_needed * 2.0
            
            # Calcular si necesitará esperar por rate limit
            wait_time = 0
            if pages_needed > rate_limit_remaining:
                # Necesitará esperar
                current_time = int(time.time())
                time_until_reset = max(0, rate_limit_reset - current_time)
                
                # Calcular cuántos ciclos de espera necesita
                pages_after_limit = pages_needed - rate_limit_remaining
                if pages_after_limit > 0:
                    wait_cycles = (pages_after_limit + rate_limit_total - 1) // rate_limit_total
                    wait_time = time_until_reset + (wait_cycles * 900)  # 900s = 15 min
            
            tiempos['search_tweets'] = request_time + wait_time
            
            if wait_time > 0:
                print(f"✓ (~{tiempos['search_tweets']:.0f}s | incluye ~{format_time(wait_time)} de espera por rate limit)")
            else:
                print(f"✓ (~{tiempos['search_tweets']:.0f}s | sin esperas de rate limit)")
        else:
            # Si no puede resolver el usuario, usar estimación conservadora
            pages_needed = (max_tweets + 99) // 100
            tiempos['search_tweets'] = pages_needed * 2.0
            print(f"✓ (~{tiempos['search_tweets']:.0f}s | estimación sin rate limit)")
    except Exception as e:
        # Fallback a estimación simple
        pages_needed = (max_tweets + 99) // 100
        tiempos['search_tweets'] = pages_needed * 2.0
        print(f"✓ (~{tiempos['search_tweets']:.0f}s | estimación sin rate limit)")
    
    # 3. Risk classifier CON política - Usar max_tweets (NO limitado por archivo)
    try:
        tweets_data = load_tweets_from_json(json_path)  # <-- YA ESTÁ CORRECTO
        tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
        # Siempre usar max_tweets para la estimación, aunque el archivo tenga menos
        total_tweets = max_tweets
        
        print(f"   [3/3] Risk Classifier CON política ({sample_size} muestras para estimar {total_tweets} tweets)...", end=" ", flush=True)
        
        sample_times = []
        for tweet in tweets[:sample_size]:
            start = time.time()
            classify_risk_text_only(tweet)  # <-- CAMBIO AQUI
            sample_times.append(time.time() - start)
        
        avg_time = sum(sample_times) / len(sample_times)
        tiempos['risk_classifier_with_policy'] = avg_time * total_tweets
        print(f"✓ (~{tiempos['risk_classifier_with_policy']:.0f}s para {total_tweets} tweets)")
    except:
        tiempos['risk_classifier_with_policy'] = 0
        print(f"✗ (archivo no encontrado)")
    
    # Calcular tiempo total
    tiempo_total = sum(tiempos.values())
    
    return {
        'tiempos_individuales': tiempos,
        'tiempo_total_segundos': tiempo_total,
        'tiempo_total_formateado': format_time(tiempo_total),
        'tweets_analizados': max_tweets
    }


def main():
    """Función principal que ejecuta todas las estimaciones"""
    print("\n" + "="*70)
    print("⏱️  CALCULADOR DE TIEMPOS ESTIMADOS - SISTEMA DE ANÁLISIS DE TWEETS")
    print("="*70)
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Configuración
    username = "@TheDarkraimola"
    max_tweets = 5000
    default_json = Path(__file__).resolve().parent / "tweets_TheDarkraimola_20251011_100125.json"
    
    # ========================================================================
    # CALCULAR Y MOSTRAR TIEMPO ESTIMADO TOTAL AL INICIO
    # ========================================================================
    estimacion_inicial = quick_estimate_all(username, max_tweets, str(default_json))
    
    print(f"\n{'='*70}")
    print("⏰ TIEMPO ESTIMADO TOTAL DEL PROCESO COMPLETO")
    print(f"{'='*70}")
    print(f"   Configuración: {max_tweets} tweets a analizar")
    print(f"   {'─'*68}")
    print(f"   User Resolver:              {format_time(estimacion_inicial['tiempos_individuales'].get('user_resolver', 0))}")
    print(f"   Search Tweets:              {format_time(estimacion_inicial['tiempos_individuales'].get('search_tweets', 0))}")
    print(f"   Risk Classifier (Política): {format_time(estimacion_inicial['tiempos_individuales'].get('risk_classifier_with_policy', 0))}")
    print(f"   {'─'*68}")
    print(f"   TOTAL ESTIMADO:             {estimacion_inicial['tiempo_total_formateado']}")
    print(f"{'='*70}")
    
    # Almacenar resultados
    resultados = {
        "timestamp": datetime.now().isoformat(),
        "tiempo_estimado_total": estimacion_inicial['tiempo_total_formateado'],
        "tiempo_estimado_segundos": round(estimacion_inicial['tiempo_total_segundos'], 2),
        "configuracion": {
            "usuario": username,
            "max_tweets": max_tweets,
            "archivo_tweets": str(default_json)
        },
        "estimaciones": []
    }
    
    # 1. User Resolver
    try:
        result = estimate_user_resolution(username)
        resultados["estimaciones"].append(result)
    except Exception as e:
        print(f"❌ Error en user_resolver: {e}")
        resultados["estimaciones"].append({
            "modulo": "user_resolver",
            "error": str(e),
            "exito": False
        })
    
    # 2. Search Tweets
    try:
        result = estimate_tweet_fetching(username, max_tweets)
        resultados["estimaciones"].append(result)
    except Exception as e:
        print(f"❌ Error en search_tweets: {e}")
        resultados["estimaciones"].append({
            "modulo": "search_tweets",
            "error": str(e),
            "exito": False
        })
    
    # 3. Risk Classifier
    if default_json.exists():
        try:
            result = estimate_risk_classification(str(default_json), max_tweets_limit=max_tweets)
            resultados["estimaciones"].append(result)
        except Exception as e:
            print(f"❌ Error en risk_classifier: {e}")
            resultados["estimaciones"].append({
                "modulo": "risk_classifier",
                "error": str(e),
                "exito": False
            })
    else:
        print(f"\n⚠️  Archivo no encontrado: {default_json}")
        print("   Saltando clasificación de riesgos")
    
    # Resumen final
    print(f"\n{'='*70}")
    print("📋 RESUMEN DE TIEMPOS ESTIMADOS")
    print(f"{'='*70}")
    
    for est in resultados["estimaciones"]:
        if est["exito"]:
            print(f"\n✅ {est['modulo'].upper()}")
            if "tiempo_estimado_total" in est:
                print(f"   Tiempo estimado: {est['tiempo_estimado_total']}")
                if "total_tweets" in est:
                    print(f"   Tweets a analizar: {est['total_tweets']}")
            elif "tiempo_estimado" in est:
                print(f"   Tiempo estimado: {est['tiempo_estimado']}")
        else:
            print(f"\n❌ {est['modulo'].upper()}")
            print(f"   Error: {est.get('error', 'Error desconocido')}")
    
    # Guardar resultados en JSON
    output_file = Path("tiempos_estimados_completos.json")
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Resultados guardados en: {output_file}")
    print(f"\n{'='*70}")
    print("✨ Cálculo de tiempos completado")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
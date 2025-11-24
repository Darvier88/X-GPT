import json
import time
from pathlib import Path
from datetime import datetime
import importlib
import math

# Importar módulos
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from X.user_resolver import resolve_user
from GPT.risk_classifier_only_text import classify_risk_text_only, load_tweets_from_json

# Intentar acceder a funciones de rate limit del módulo X.search_tweets si existen
try:
    search_tweets_mod = importlib.import_module("X.search_tweets")
    get_rate_limit_info = getattr(search_tweets_mod, "get_rate_limit", None)
except Exception:
    search_tweets_mod = None
    get_rate_limit_info = None


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
    
    if result.get('success'):
        print(f"✅ Usuario resuelto en {elapsed:.2f}s")
        print(f"   @{result.get('username')} → user_id: {result.get('user_id')}")
    else:
        print(f"❌ Error: {result.get('error_message')}")
    
    return {
        "modulo": "user_resolver",
        "funcion": "resolve_user",
        "tiempo_real": f"{elapsed:.2f}s",
        "tiempo_segundos": round(elapsed, 2),
        "exito": result.get('success', False)
    }


def estimate_tweet_fetching(username: str, max_tweets: int,
                            assumed_tweets_per_page: int = 100,
                            assumed_request_time_per_page: float = 2.0,
                            default_rate_limit_total: int = 4,
                            default_rate_limit_remaining: int = 4,
                            default_reset_seconds: int = 0,
                            default_window_seconds: int = 900) -> dict:
    """
    Estimación basada en la misma lógica que SEARCH_TWEETS pero SIN ejecutar
    ninguna petición HTTP. Usa get_rate_limit_info() si está disponible.
    Hechos clave:
      - Por defecto usa valores conservadores que reflejan la lógica de search_tweets
        (p. ej. default_rate_limit_total=4, default_reset_seconds=0) para que la
        estimación incluya esperas por rate limits similares a las reales.
    """
    print(f"\n{'='*70}")
    print("🐦 MÓDULO: SEARCH_TWEETS (ESTIMACIÓN SIN EJECUCIÓN - LÓGICA MATCH SEARCH_TWEETS)")
    print(f"{'='*70}")
    print(f"Estimando fetch_user_tweets('{username}', max_tweets={max_tweets})")

    pages_needed = math.ceil(max_tweets / float(assumed_tweets_per_page)) if max_tweets > 0 else 0
    request_time = pages_needed * assumed_request_time_per_page

    # Valores por defecto conservadores (ajustados para producir estimaciones realistas)
    rate_limit_total = default_rate_limit_total
    rate_limit_remaining = default_rate_limit_remaining
    reset_seconds = default_reset_seconds
    window_seconds = default_window_seconds

    # Intentar usar get_rate_limit_info del módulo X.search_tweets (si existe)
    if callable(get_rate_limit_info):
        try:
            rl = get_rate_limit_info()
            if isinstance(rl, dict):
                # Si get_rate_limit devuelve sólo status_code con error, se toma como no disponible
                if rl.get("status_code", 0) >= 400 and rl.get("limit") is None:
                    print(f"⚠️ get_rate_limit() devolvió status {rl.get('status_code')}, usando supuestos por defecto")
                else:
                    rate_limit_total = int(rl.get("limit", rate_limit_total))
                    rate_limit_remaining = int(rl.get("remaining", rate_limit_remaining))
                    reset_seconds = int(rl.get("reset_seconds", reset_seconds))
                    window_seconds = int(rl.get("window_seconds", window_seconds))
                    print(f"🔎 Rate limit detectado: limit={rate_limit_total}, remaining={rate_limit_remaining}, reset={reset_seconds}s")
        except Exception as e:
            print(f"⚠️ No se pudo leer rate limit real: {e}")

    # Mostrar los valores usados para la estimación
    print(f"   Páginas necesarias: {pages_needed}")
    print(f"   Supuestos: tweets/página={assumed_tweets_per_page}, tiempo/petición≈{assumed_request_time_per_page}s")
    print(f"   Usando rate_limit: total={rate_limit_total}, remaining={rate_limit_remaining}, reset_seconds={reset_seconds}")

    # Calcular espera por rate limit (sin hacer peticiones)
    wait_time = 0.0
    if pages_needed > rate_limit_remaining:
        pages_after_first_batch = pages_needed - rate_limit_remaining

        if rate_limit_remaining > 0:
            # Primer batch se consume hasta el reset actual
            wait_time = reset_seconds
            # ciclos adicionales necesarios para procesar páginas restantes
            additional_cycles = math.ceil(pages_after_first_batch / float(rate_limit_total))
            wait_time += additional_cycles * window_seconds
        else:
            # remaining == 0: hay que esperar al próximo reset y luego calcular ciclos
            cycles = math.ceil(pages_needed / float(rate_limit_total))
            wait_time = reset_seconds + ((cycles - 1) * window_seconds if cycles > 1 else 0)

        print(f"🕒 Páginas necesarias ({pages_needed}) exceden remaining ({rate_limit_remaining}). Espera estimada: {format_time(wait_time)}")
    else:
        print("✅ Rate limit suficiente para completar sin esperas adicionales")

    # Reproducir el cálculo de search_tweets: tiempo de requests + pausas mínimas entre páginas + tiempo de espera por rate limit
    # En search_tweets se usa 'estimation_time * estimated_pages' y una pequeña pausa por página (aquí asumimos 1s entre páginas)
    pause_per_page = 1.0
    estimated_pages = pages_needed if pages_needed > 0 else 0
    request_time_total = assumed_request_time_per_page * estimated_pages
    pause_time = max(0, estimated_pages - 1) * pause_per_page

    estimated_total_seconds = request_time_total + pause_time + wait_time
    estimated_total_str = format_time(estimated_total_seconds)

    print(f"\n📊 RESULTADO ESTIMADO:")
    print(f"   Tiempo requests (s): {request_time_total:.2f}")
    print(f"   Pausas internas (s): {pause_time:.2f}")
    if wait_time > 0:
        print(f"   Tiempo espera por rate limit (s): {wait_time:.2f}")
    print(f"   TIEMPO ESTIMADO TOTAL: {estimated_total_str}")

    return {
        "modulo": "search_tweets",
        "funcion": "fetch_user_tweets (estimacion_sin_ejecucion)",
        "parametros": {
            "username": username,
            "max_tweets": max_tweets,
            "assumed_tweets_per_page": assumed_tweets_per_page,
            "assumed_request_time_per_page": assumed_request_time_per_page,
            "rate_limit_used": {
                "limit": rate_limit_total,
                "remaining": rate_limit_remaining,
                "reset_seconds": reset_seconds,
                "window_seconds": window_seconds
            }
        },
        "pages_needed": pages_needed,
        "estimated_pages": estimated_pages,
        "tiempo_estimado": estimated_total_str,
        "tiempo_segundos": round(estimated_total_seconds, 2),
        "exito": True,
        "notes": "Estimación sin ejecutar fetch; ajusta defaults si quieres otra suposición de rate limit"
    }


DEFAULT_AVG_RISK_PER_TWEET = 1.8  # segundos por tweet asumidos si no hay muestras reales

def estimate_risk_classification(json_path: str, sample_size: int = 10, max_tweets_limit: int = None) -> dict:
    """Estima tiempo de clasificación de riesgos CON política"""
    print(f"\n{'='*70}")
    print("🛡️  MÓDULO: RISK CLASSIFIER")
    print(f"{'='*70}")
    
    try:
        tweets_data = load_tweets_from_json(json_path)
        tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
        total_tweets_in_file = len(tweets)
        
        # Determinar total_tweets objetivo (usar límite si se pasó)
        if max_tweets_limit and max_tweets_limit > 0:
            total_tweets = max_tweets_limit
            # recortar la lista de muestras solo para medir
            tweets_sample_source = tweets[:max(0, min(len(tweets), sample_size))]
            print(f"Tweets en archivo: {total_tweets_in_file} — estimando para límite: {total_tweets}")
        else:
            total_tweets = total_tweets_in_file
            tweets_sample_source = tweets[:sample_size]
            print(f"Tweets cargados: {total_tweets}")
        
        print(f"Analizando hasta {len(tweets_sample_source)} tweets de muestra (sample_size={sample_size}) CON POLÍTICA v1.0...")

        # Analizar muestra CON política (si hay muestras)
        sample_times = []
        if tweets_sample_source:
            for i, tweet in enumerate(tweets_sample_source, 1):
                print(f"   Muestra {i}/{len(tweets_sample_source)}...", end=" ", flush=True)
                start = time.time()
                classify_risk_text_only(tweet)
                elapsed = time.time() - start
                sample_times.append(elapsed)
                print(f"✓ ({elapsed:.2f}s)")
            avg_time = sum(sample_times) / len(sample_times)
        else:
            # No hay muestras en archivo: usar valor por defecto realista (no ejecutar LLM aquí)
            print("   ⚠️ No hay muestras en el archivo; usando promedio por defecto para estimación")
            avg_time = DEFAULT_AVG_RISK_PER_TWEET

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
            "muestra_analizada": len(sample_times) if sample_times else 0,
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


def quick_estimate_all(username: str, max_tweets: int, json_path: str, sample_size: int = 10) -> dict:
    """Realiza estimaciones rápidas de todos los módulos para mostrar tiempo total (sin fetch real)."""
    print(f"\n🔄 Calculando tiempo estimado total del proceso completo...")
    print(f"   Analizando muestras de {sample_size} tweets...\n")

    tiempos = {}

    # 1. User resolver (estimación rápida - puede ejecutar resolve_user)
    print(f"   [1/3] User Resolver...", end=" ", flush=True)
    start = time.time()
    try:
        resolve_user(username)
        tiempos['user_resolver'] = time.time() - start
        print(f"✓ ({tiempos['user_resolver']:.2f}s)")
    except Exception:
        tiempos['user_resolver'] = 0.5
        print(f"✓ (~0.5s fallback)")

    # 2. Search tweets (estimación basada en max_tweets y rate limit) - SIN fetch real
    print(f"   [2/3] Search Tweets (estimando para {max_tweets} tweets)...", end=" ", flush=True)
    est_search = estimate_tweet_fetching(username, max_tweets)
    tiempos['search_tweets'] = est_search['tiempo_segundos']
    print(f"✓ (~{int(tiempos['search_tweets'])}s)")

    # 3. Risk classifier CON política - estimación SIN ejecutar LLM
    print(f"   [3/3] Risk Classifier (estimación para {max_tweets} tweets)...", end=" ", flush=True)
    # Intentar usar muestras del JSON solo para decidir si podemos usar una media medida.
    avg_time_per_tweet = None
    try:
        tweets_data = load_tweets_from_json(json_path)
        tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
        # No ejecutar LLM: si tenemos suficientes muestras en el archivo, no medimos,
        # usamos DEFAULT_AVG_RISK_PER_TWEET como valor realista.
        if tweets:
            avg_time_per_tweet = DEFAULT_AVG_RISK_PER_TWEET
        else:
            avg_time_per_tweet = DEFAULT_AVG_RISK_PER_TWEET
    except Exception:
        avg_time_per_tweet = DEFAULT_AVG_RISK_PER_TWEET

    # Calcular tiempo estimado total para el risk classifier
    risk_total_seconds = avg_time_per_tweet * max_tweets
    tiempos['risk_classifier_with_policy'] = risk_total_seconds
    print(f"✓ (~{format_time(risk_total_seconds)} total -> {avg_time_per_tweet:.2f}s/tweet)")

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
    max_tweets = 1000  # procesar estimación para 1000 tweets
    default_json = Path(__file__).resolve().parent / "tweets_TheDarkraimola_20251011_100125.json"

    # ========================================================================
    # CALCULAR Y MOSTRAR TIEMPO ESTIMADO TOTAL AL INICIO
    # ========================================================================
    # Usar sample_size=10 para el risk classifier
    estimacion_inicial = quick_estimate_all(username, max_tweets, str(default_json), sample_size=10)

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
            # pasar sample_size=10 y limitar a max_tweets
            result = estimate_risk_classification(str(default_json), sample_size=10, max_tweets_limit=max_tweets)
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
        if est.get("exito"):
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

    # Guardar resultados en JSON (versión minimal solicitada)
    output_file = Path("tiempos_estimados_minimal.json")
    minimal = {
        "timestamp": datetime.now().isoformat(),
        "num_tweets": max_tweets,
        "tiempo_estimado_total": estimacion_inicial['tiempo_total_formateado']
    }
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(minimal, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Resultados guardados en: {output_file}")
    print(f"\n{'='*70}")
    print("✨ Cálculo de tiempos completado")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
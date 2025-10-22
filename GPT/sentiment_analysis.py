"""
Cliente LLM ULTRA-SIMPLIFICADO con:
- reintentos (max 2 retries)
- timeout por tweet (<10s)
- errores tipificados (error_code)
- circuit breaker simple
- tamaño de lotes por 50
- cálculo de tiempo estimado
"""

import time
import json
import re
from typing import Optional, List, Dict, Any
from openai import OpenAI, APIError, RateLimitError, APITimeoutError
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_openai_api_key

# Configuración
MAX_RETRIES = 2                 # máximo de reintentos (2 retries -> hasta 3 intentos)
REQUEST_TIMEOUT = 9             # timeout por petición individual (segundos) < 10s
TIMEOUT_PER_TWEET = 9           # timeout total por tweet (segundos) < 10s
CIRCUIT_THRESHOLD = 5           # fallos consecutivos para abrir circuit breaker
CIRCUIT_COOLDOWN = 60           # segundos de cooldown del circuit breaker
BATCH_SIZE = 50                 # tamaño de lotes


# Errores tipificados
ERROR_CODES = {
    'timeout': 'timeout',
    'rate_limit': 'rate_limit',
    'api_error': 'api_error',
    'auth_error': 'auth_error',
    'content_filtered': 'content_filtered',
    'truncated': 'truncated',
    'circuit_open': 'circuit_open',
    'tweet_timeout': 'tweet_timeout',
    'unknown': 'unknown'
}


class CircuitBreaker:
    def __init__(self, threshold: int = CIRCUIT_THRESHOLD, cooldown: int = CIRCUIT_COOLDOWN):
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: Optional[float] = None

    def record_success(self):
        self.failures = 0
        self.opened_at = None

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.monotonic()

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        elapsed = time.monotonic() - self.opened_at
        if elapsed >= self.cooldown:
            # reset after cooldown
            self.failures = 0
            self.opened_at = None
            return False
        return True


circuit = CircuitBreaker()


def analyze_sentiment_simple(tweet_text: str) -> Dict[str, Any]:
    """
    Versión con reintentos limitados, timeout por tweet, circuit breaker y errores tipificados.
    Retorna dict con keys:
      - sentiment, score, raw_text, finish_reason, attempt  (on success)
      - error_code, error, finish_reason, attempt        (on failure)
    """
    start_time = time.monotonic()

    # circuit breaker check
    if circuit.is_open():
        return {
            "error_code": ERROR_CODES['circuit_open'],
            "error": "Circuit breaker abierto; intentar más tarde"
        }

    try:
        client = OpenAI(api_key=get_openai_api_key())
    except Exception as e:
        circuit.record_failure()
        return {
            "error_code": ERROR_CODES['auth_error'],
            "error": f"No se pudo crear cliente: {e}"
        }

    prompt = f'''Analiza el sentimiento: "{tweet_text}"

Responde SOLO con JSON:
{{"sentiment": "pos", "score": 0.8}}

Sentimientos: pos (positivo), neu (neutral), neg (negativo)
Score: -1.0 (muy negativo) a 1.0 (muy positivo)'''

    attempts_allowed = MAX_RETRIES + 1

    # CORRECCIÓN: incluir el último intento
    for attempt in range(1, attempts_allowed + 1):  # 1..attempts_allowed
        # Respect tweet-level timeout
        if time.monotonic() - start_time >= TIMEOUT_PER_TWEET:
            circuit.record_failure()
            return {
                "error_code": ERROR_CODES['tweet_timeout'],
                "error": "Timeout total por tweet excedido",
                "attempt": attempt
            }

        try:
            response = client.chat.completions.create(
                model="gpt-5-nano",
                messages=[
                    {"role": "system", "content": "Eres un analizador de sentimientos. Responde solo con JSON."},
                    {"role": "user", "content": prompt}
                ],
                timeout=REQUEST_TIMEOUT
            )

            # Simple extracción sin validaciones complejas
            if not getattr(response, "choices", None):
                # considerar como fallo y reintentar
                circuit.record_failure()
                print(f"[attempt {attempt}] Sin choices en la respuesta, reintentando...")
                time.sleep(0.5)
                continue

            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", "unknown")

            # Si modelo devuelve contenido vacío por truncado
            content = ""
            if hasattr(choice, "message") and getattr(choice.message, "content", None) is not None:
                content = choice.message.content or ""
            elif hasattr(choice, "text"):
                content = choice.text or ""
            content = content.strip()

            if finish_reason in ("content_filter", "content_filtered"):
                circuit.record_failure()
                return {
                    "error_code": ERROR_CODES['content_filtered'],
                    "error": "Contenido bloqueado por moderación",
                    "finish_reason": finish_reason,
                    "attempt": attempt
                }

            if finish_reason == "length" and not content:
                # truncado sin contenido útil
                circuit.record_failure()
                print(f"[attempt {attempt}] finish_reason=length y contenido vacío.")
                if attempt < attempts_allowed:
                    # reintentar una vez más con menos tokens
                    max_comp_tokens = max(16, int(max_comp_tokens / 2))
                    time.sleep(0.5)
                    continue
                else:
                    return {
                        "error_code": ERROR_CODES['truncated'],
                        "error": "Respuesta truncada sin contenido",
                        "finish_reason": finish_reason,
                        "attempt": attempt
                    }

            # Si no hay contenido, reintentar
            if not content:
                circuit.record_failure()
                print(f"[attempt {attempt}] contenido vacío, reintentando...")
                time.sleep(0.5)
                continue

            # Intentar parsear JSON simple
            try:
                data = json.loads(content)
            except Exception:
                m = re.search(r'\{[\s\S]*\}', content)
                if m:
                    try:
                        data = json.loads(m.group(0))
                    except Exception:
                        data = None
                else:
                    data = None

            # Si no se pudo parsear, fallback heurístico
            if not isinstance(data, dict):
                low = tweet_text.lower()
                if any(w in low for w in ["encanta", "increíble", "love", "excelente", "fantástico"]):
                    sentiment, score = "pos", 0.9
                elif any(w in low for w in ["terrible", "no lo recomiendo", "malo", "odio"]):
                    sentiment, score = "neg", 0.9
                else:
                    sentiment, score = "neu", 0.0
            else:
                sentiment = str(data.get("sentiment", "neu")).lower()
                if sentiment in ['positive', 'pos', 'positivo']:
                    sentiment = 'pos'
                elif sentiment in ['negative', 'neg', 'negativo']:
                    sentiment = 'neg'
                else:
                    sentiment = 'neu'
                try:
                    score = float(data.get("score", 0.0))
                except Exception:
                    score = 0.0

            # Éxito
            circuit.record_success()
            return {
                "sentiment": sentiment,
                "score": float(max(-1.0, min(1.0, score))),
                "raw_text": content,
                "finish_reason": finish_reason,
                "attempt": attempt
            }

        except APITimeoutError as e:
            circuit.record_failure()
            print(f"[attempt {attempt}] APITimeoutError: {e}")
            # mapear a timeout y reintentar si quedan intentos
            if time.monotonic() - start_time >= TIMEOUT_PER_TWEET:
                return {
                    "error_code": ERROR_CODES['timeout'],
                    "error": "Timeout en la petición y timeout por tweet alcanzado",
                    "attempt": attempt
                }
            time.sleep(0.5)
            continue

        except RateLimitError as e:
            circuit.record_failure()
            print(f"[attempt {attempt}] RateLimitError: {e}")
            # Exponer error tipificado; reintentar después de breve espera
            time.sleep(1)
            if attempt >= attempts_allowed:
                return {
                    "error_code": ERROR_CODES['rate_limit'],
                    "error": "Rate limit",
                    "attempt": attempt
                }
            continue

        except APIError as e:
            circuit.record_failure()
            print(f"[attempt {attempt}] APIError: {e}")
            time.sleep(0.5)
            if attempt >= attempts_allowed:
                return {
                    "error_code": ERROR_CODES['api_error'],
                    "error": f"API error: {e}",
                    "attempt": attempt
                }
            continue

        except Exception as e:
            circuit.record_failure()
            print(f"[attempt {attempt}] Exception: {e}")
            time.sleep(0.5)
            if attempt >= attempts_allowed:
                return {
                    "error_code": ERROR_CODES['unknown'],
                    "error": f"Error desconocido: {e}",
                    "attempt": attempt
                }
            continue

    # Si sale del loop sin resultado
    return {
        "error_code": ERROR_CODES['unknown'],
        "error": "Todos los intentos fallaron",
        "attempts": attempts_allowed
    }


def load_tweets_from_json(json_path: str) -> List[str]:
    """
    Lee el archivo JSON con la estructura proporcionada y devuelve
    una lista de strings (campo 'text' de cada tweet).
    """
    p = Path(json_path)
    if not p.exists():
        raise FileNotFoundError(f"No existe: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    tweets = data.get("tweets", [])
    texts: List[str] = []
    for t in tweets:
        if isinstance(t, dict):
            txt = t.get("text")
            if isinstance(txt, str) and txt.strip():
                texts.append(txt.strip())
    return texts


# ========================================================================
# PRUEBA en lotes CON CÁLCULO DE TIEMPO
# ========================================================================
if __name__ == "__main__":
    print("\n" + "="*70)
    print("🧪 ANÁLISIS DE SENTIMIENTO SIMPLIFICADO (con circuit breaker y batching)")
    print("="*70)

    # Ruta por defecto: archivo junto a la raíz del repo
    default_json = Path(__file__).resolve().parents[1] / "tweets_TheDarkraimola_20251011_100125.json"
    try:
        test_tweets = load_tweets_from_json(str(default_json))
        print(f"📥 Cargados {len(test_tweets)} tweets desde: {default_json}")
    except Exception as e:
        print(f"⚠️ Error cargando tweets JSON: {e}")
        # Fallback mínimo para pruebas
        test_tweets = [
            "¡Me encanta este producto! Es increíble 😊",
            "Terrible experiencia, no lo recomiendo",
            "El clima hoy está nublado",
        ]

    total = len(test_tweets)
    
    print(f"\n📊 Analizando {total} tweets en lotes de {BATCH_SIZE}...")
    print("⏱️  Calculando tiempo estimado...\n")

    # Estadísticas para tiempo estimado
    tweet_times = []
    program_start_time = time.monotonic()
    estimated_time_str = None
    estimated_total_seconds = None

    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_index, batch_start in enumerate(range(0, total, BATCH_SIZE), start=1):
        batch = test_tweets[batch_start:batch_start + BATCH_SIZE]
        batch_size = len(batch)
        batch_global_start = batch_start + 1
        batch_global_end = batch_start + batch_size
        print("\n" + "="*60)
        print(f"🔁 Analizando lote {batch_index}/{total_batches} — tweets {batch_global_start}-{batch_global_end} (tamaño lote: {batch_size})")
        print("="*60)

        for idx, tweet in enumerate(batch, start=batch_global_start):
            within_batch_idx = idx - batch_start  # 1..batch_size
            # Mostrar progreso tipo "1/50"
            print(f"\n🐦 Lote {batch_index}/{total_batches} — Tweet {within_batch_idx}/{batch_size} (global {idx}/{total})")
            print(f"Texto: {tweet}")

            tweet_start = time.monotonic()
            result = analyze_sentiment_simple(tweet)
            tweet_time = time.monotonic() - tweet_start
            tweet_times.append(tweet_time)

            # Mostrar solo el JSON pedido por tweet
            output = {
                "tweet_id": idx,
                "text": tweet,
                "sentiment": result.get("sentiment"),
                "score": result.get("score"),
                "error_code": result.get("error_code"),
                "error": result.get("error")
            }
            print(json.dumps(output, ensure_ascii=False))
            
            # Mostrar tiempo estimado después de procesar algunos tweets
            if len(tweet_times) == 3 and estimated_time_str is None:
                estimated_total = sum(tweet_times[:3]) * total / 3
                estimated_total_seconds = estimated_total
                est_hours = int(estimated_total // 3600)
                est_minutes = int((estimated_total % 3600) // 60)
                est_seconds = int(estimated_total % 60)
                
                if est_hours > 0:
                    estimated_time_str = f"≈ {est_hours}h {est_minutes}m {est_seconds}s"
                elif est_minutes > 0:
                    estimated_time_str = f"≈ {est_minutes}m {est_seconds}s"
                else:
                    estimated_time_str = f"≈ {est_seconds}s"
                
                # Mostrar el tiempo estimado calculado
                print(f"\n{'='*60}")
                print(f"✅ TIEMPO ESTIMADO: {estimated_time_str}")
                print(f"{'='*60}")
                
                # Imprimir JSON con total_tweets y tiempo_estimado
                timing_results = {
                    "total_tweets": total,
                    "tiempo_estimado": estimated_time_str
                }
                print("\n📊 RESUMEN EN JSON:")
                print(json.dumps(timing_results, ensure_ascii=False, indent=2))
                print(f"{'='*60}\n")
            
            time.sleep(0.2)

    # Cálculo de tiempo real
    total_program_time = time.monotonic() - program_start_time
    total_hours = int(total_program_time // 3600)
    total_minutes = int((total_program_time % 3600) // 60)
    total_seconds = int(total_program_time % 60)
    
    if total_hours > 0:
        actual_time = f"{total_hours}h {total_minutes}m {total_seconds}s"
    elif total_minutes > 0:
        actual_time = f"{total_minutes}m {total_seconds}s"
    else:
        actual_time = f"{total_seconds}s"

    print("\n" + "="*70)
    print("✨ Prueba completada")
    print("="*70)
    
    # Mostrar comparación de tiempos
    print(f"\n⏱️  COMPARACIÓN DE TIEMPOS:")
    print(f"   - Tiempo real: {actual_time}")
    if estimated_time_str is not None:
        print(f"   - Tiempo estimado: {estimated_time_str}")
    
    print("\n" + "="*70)
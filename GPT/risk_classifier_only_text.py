"""Clasificador de Riesgos para Tweets (B3) - SIN ANÁLISIS DE MEDIA
- Análisis SOLO de texto
- Prompts simplificados para velocidad
- Modelo más rápido: gpt-4o-mini
- Token Budget Tracker mejorado
"""

import time
import json
import re
from typing import Optional, List, Dict, Any, Tuple
from collections import deque
from openai import OpenAI, APIError, RateLimitError, APITimeoutError
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_openai_api_key

# ========================================================================
# POLÍTICA v1.0 - VERSIÓN COMPACTA (mismo significado)
# ========================================================================

POLICY_COMPACT = {
    "version": "v1.0",
    "categories": {
        "toxic": "Insultos, lenguaje denigrante a personas/grupos",
        "hate": "Ataques por identidad protegida (raza, religión, género, etc.)",
        "political_sensitivity": "Extremismo, conspiración, desinformación política",
        "nsfw": "Contenido sexual explícito o pornográfico",
        "bullying": "Intimidación, acoso persistente, doxxing",
        "violence": "Amenazas, incitación a violencia, autolesiones",
        "legal_privacy": "Difamación, PII sensible (tel, dirección, doc)"
    },
    "levels": {
        "no": "Sin riesgo",
        "low": "Riesgo menor/incierto",
        "mid": "Riesgo claro, daño reputacional posible",
        "high": "Riesgo severo, violación probable"
    },
    "rules": {
        "escalate": ["hate/violence → high", "PII sensible → high"],
        "deescalate": ["Cita/sarcasmo evidente → bajar"]
    }
}

# Configuración optimizada
MAX_RETRIES = 2
REQUEST_TIMEOUT = 20
TIMEOUT_PER_TWEET = 40
CIRCUIT_THRESHOLD = 10
CIRCUIT_COOLDOWN = 120
DELAY_BETWEEN_TWEETS = 0.8
DELAY_AFTER_RATE_LIMIT = 10

ERROR_CODES = {
    'timeout': 'timeout',
    'rate_limit': 'rate_limit',
    'api_error': 'api_error',
    'auth_error': 'auth_error',
    'content_filtered': 'content_filtered',
    'circuit_open': 'circuit_open',
    'tweet_timeout': 'tweet_timeout',
    'unknown': 'unknown'
}


# ========================================================================
# TOKEN BUDGET TRACKER
# ========================================================================

class TokenBudgetTracker:
    """Rastrea el uso de tokens para evitar rate limits proactivamente."""
    
    def __init__(self, tokens_per_minute: int = 140000):  # 70% del límite (más conservador)
        self.tokens_per_minute = tokens_per_minute
        self.window_seconds = 60
        self.requests = deque()
        
    def get_current_usage(self) -> int:
        now = time.time()
        cutoff = now - self.window_seconds
        while self.requests and self.requests[0][0] < cutoff:
            self.requests.popleft()
        return sum(tokens for _, tokens in self.requests)
    
    def can_make_request(self, estimated_tokens: int) -> bool:
        current = self.get_current_usage()
        return (current + estimated_tokens) <= self.tokens_per_minute
    
    def wait_for_budget(self, estimated_tokens: int) -> float:
        if self.can_make_request(estimated_tokens):
            return 0.0
        
        now = time.time()
        while self.requests:
            oldest_time, oldest_tokens = self.requests[0]
            if oldest_time < (now - self.window_seconds):
                self.requests.popleft()
                continue
            
            wait_time = (oldest_time + self.window_seconds) - now + 1.5
            return max(0.0, wait_time)
        
        return 1.0
    
    def record_request(self, tokens_used: int):
        self.requests.append((time.time(), tokens_used))
    
    def get_usage_percentage(self) -> float:
        return (self.get_current_usage() / self.tokens_per_minute) * 100


token_tracker = TokenBudgetTracker(tokens_per_minute=140000)  # 70% del límite


# ========================================================================
# ESTIMACIÓN DE TOKENS
# ========================================================================

def estimate_tokens(text: str) -> int:
    """Estima tokens solo para texto."""
    base_tokens = 600  # Prompt simplificado
    text_tokens = len(text) // 3
    response_tokens = 250
    
    return base_tokens + text_tokens + response_tokens


# ========================================================================
# CIRCUIT BREAKER
# ========================================================================

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
            self.failures = 0
            self.opened_at = None
            return False
        return True


circuit_with_policy = CircuitBreaker()


# ========================================================================
# PROMPT SIMPLIFICADO (SOLO TEXTO)
# ========================================================================

def build_text_prompt(tweet_text: str) -> str:
    """
    Prompt compacto para analizar SOLO texto.
    Versión simplificada pero mantiene significado de la política.
    """
    
    categories = "\n".join([f"- {k}: {v}" for k, v in POLICY_COMPACT["categories"].items()])

    prompt = f"""Clasifica riesgo según Política v1.0 (compacta).

CATEGORÍAS:
{categories}

NIVELES: low (menor), mid (claro), high (severo)

REGLAS:
- hate/violence → high
- Cita/sarcasmo evidente → bajar nivel
- PII (tel/dirección) → high

EJEMPLOS:

Tweet: "People who believe X are idiots."
{{"labels":["toxic"],"risk_level":"mid","rationale":"Insulto genérico sin slur","spans":[{{"text":"idiots","start":24,"end":30,"label":"toxic"}}],"confidence":0.78}}

Tweet: "Estos inmigrantes son basura"
{{"labels":["hate","toxic"],"risk_level":"high","rationale":"Deshumanización de grupo protegido","spans":[{{"text":"Estos inmigrantes son basura","start":0,"end":28,"label":"hate"}}],"confidence":0.89}}

TWEET: "{tweet_text}"

Responde SOLO JSON:
{{"labels":[...],"risk_level":"low|mid|high","rationale":"breve","spans":[...],"confidence":0.0-1.0}}"""
    
    return prompt


# ========================================================================
# CLASIFICACIÓN (SOLO TEXTO)
# ========================================================================

def classify_risk_text_only(tweet_text: str) -> Dict[str, Any]:
    """
    Analiza SOLO texto (sin media).
    Más rápido y eficiente.
    """
    start_time = time.monotonic()

    if circuit_with_policy.is_open():
        return {
            "error_code": ERROR_CODES['circuit_open'],
            "error": "Circuit breaker abierto"
        }

    # Estimar tokens
    estimated_tokens = estimate_tokens(tweet_text)
    
    # THROTTLING
    wait_time = token_tracker.wait_for_budget(estimated_tokens)
    if wait_time > 0:
        print(f" ⏳{wait_time:.1f}s", end="", flush=True)
        time.sleep(wait_time)

    try:
        client = OpenAI(api_key=get_openai_api_key())
    except Exception as e:
        circuit_with_policy.record_failure()
        return {"error_code": ERROR_CODES['auth_error'], "error": str(e)}

    prompt = build_text_prompt(tweet_text)
    
    messages = [
        {"role": "system", "content": "Clasificador de riesgos. Responde SOLO JSON válido."},
        {"role": "user", "content": prompt}
    ]

    attempts_allowed = MAX_RETRIES + 1

    for attempt in range(1, attempts_allowed + 1):
        if time.monotonic() - start_time >= TIMEOUT_PER_TWEET:
            circuit_with_policy.record_failure()
            return {"error_code": ERROR_CODES['tweet_timeout'], "error": "Timeout", "attempt": attempt}

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # Modelo rápido y económico
                messages=messages,
                temperature=0.2,  # Más determinístico
                max_tokens=400,  # Reducido para respuestas más rápidas
                timeout=REQUEST_TIMEOUT
            )
            
            # Registrar tokens
            tokens_used = response.usage.total_tokens if hasattr(response, 'usage') else estimated_tokens
            token_tracker.record_request(tokens_used)

            if not getattr(response, "choices", None):
                print(f" R{attempt}", end="", flush=True)
                time.sleep(0.3)
                continue

            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", "unknown")
            content = getattr(choice.message, "content", "").strip()

            if finish_reason in ("content_filter", "content_filtered"):
                circuit_with_policy.record_failure()
                return {"error_code": ERROR_CODES['content_filtered'], "error": "Filtrado", "attempt": attempt}

            if not content:
                print(f" E{attempt}", end="", flush=True)
                time.sleep(0.3)
                continue

            # Parsear JSON
            try:
                json_match = re.search(r'\{[\s\S]*\}', content)
                data = json.loads(json_match.group(0) if json_match else content)
            except Exception as e:
                if attempt >= attempts_allowed:
                    return {
                        "labels": [], "risk_level": "no", "rationale": "Error parseando",
                        "spans": [], "attempt": attempt, "parse_error": str(e)
                    }
                time.sleep(0.3)
                continue

            # Validar
            labels = [l for l in data.get("labels", []) if l in POLICY_COMPACT["categories"]]
            # permitir 'no' como valor válido y usarlo por defecto
            risk_level = data.get("risk_level", "no")
            if risk_level not in ["no", "low", "mid", "high"]:
                risk_level = "no"
            
            rationale = data.get("rationale", "")
            confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
            spans = [s for s in data.get("spans", []) if isinstance(s, dict) and "text" in s]
            
            if labels and not spans:
                spans = extract_spans_fallback(tweet_text, labels)

            if not labels:
                # Si no hay etiquetas explícitas, marcar como 'no' (sin riesgo)
                risk_level = "no"

            # Aplicar reglas de política
            original_level = risk_level
            policy_applied = None
            risk_level, policy_applied = apply_policy_rules(labels, risk_level, tweet_text)

            circuit_with_policy.record_success()
            
            result = {
                "labels": labels,
                "risk_level": risk_level,
                "rationale": rationale,
                "spans": spans,
                "confidence": confidence,
                "attempt": attempt,
                "finish_reason": finish_reason,
                "policy_applied": policy_applied
            }
            
            if original_level != risk_level:
                result["original_risk_level"] = original_level
            
            return result

        except RateLimitError as e:
            circuit_with_policy.record_failure()
            print(f" RL{attempt}", end="", flush=True)
            
            # Esperas PROGRESIVAS: cada intento espera más
            error_msg = str(e)
            base_wait = 5.0
            
            match = re.search(r'try again in (\d+)ms', error_msg)
            if match:
                ms_to_wait = float(match.group(1))
                base_wait = (ms_to_wait / 1000.0) + 3.0
            
            # Espera progresiva: intento 1=5s, intento 2=10s, intento 3=15s
            wait_time = max(base_wait * attempt, 5.0)
            
            print(f"({wait_time:.1f}s)", end="", flush=True)
            time.sleep(wait_time)
            
            if attempt >= attempts_allowed:
                return {"error_code": ERROR_CODES['rate_limit'], "error": "Rate limit", "attempt": attempt}
            continue

        except (APITimeoutError, APIError) as e:
            circuit_with_policy.record_failure()
            print(f" E{attempt}", end="", flush=True)
            
            if isinstance(e, APITimeoutError) and time.monotonic() - start_time >= TIMEOUT_PER_TWEET:
                return {"error_code": ERROR_CODES['timeout'], "error": "Timeout", "attempt": attempt}
            
            time.sleep(0.5)
            if attempt >= attempts_allowed:
                return {"error_code": ERROR_CODES['api_error'], "error": str(e), "attempt": attempt}
            continue

        except Exception as e:
            circuit_with_policy.record_failure()
            print(f" X{attempt}", end="", flush=True)
            time.sleep(0.5)
            if attempt >= attempts_allowed:
                return {"error_code": ERROR_CODES['unknown'], "error": str(e), "attempt": attempt}
            continue

    return {"error_code": ERROR_CODES['unknown'], "error": "Fallos múltiples", "attempts": attempts_allowed}


# ========================================================================
# REGLAS DE POLÍTICA
# ========================================================================

def apply_policy_rules(labels: List[str], risk_level: str, text: str) -> Tuple[str, str]:
    """Aplica reglas compactas de política."""
    reasoning = []
    
    # Si hay hate/violence escalar incluso desde 'no' o 'low' o 'mid'
    if ("hate" in labels or "violence" in labels) and risk_level in ("no", "low", "mid"):
        risk_level = "high"
        reasoning.append("hate/violence→high")
    
    serious_labels = {"hate", "violence", "legal_privacy"}
    if len([l for l in labels if l in serious_labels]) > 1:
        risk_level = "high"
        reasoning.append("múltiples serios→high")
    
    if ("RT:" in text or "Cita:" in text or "ironía" in text.lower() or "sarcasmo" in text.lower()):
        if risk_level == "high":
            risk_level = "mid"
            reasoning.append("cita/sarcasmo→mid")
    
    return risk_level, " | ".join(reasoning) if reasoning else "sin cambios"


# ========================================================================
# EXTRACCIÓN DE SPANS (FALLBACK)
# ========================================================================

def extract_spans_fallback(tweet_text: str, labels: List[str]) -> List[Dict[str, Any]]:
    """Extracción heurística básica."""
    spans = []
    patterns = {
        'toxic': [r'\b(idiota|estúpido|imbécil|pendejo|cabrón|mierda|basura|fuck|shit|bitch)\b'],
        'violence': [r'\b(matar|golpear|partir|romper|atacar)\b.*\b(cara|cabeza)\b'],
        'hate': [r'\b(nazi|fascista|terrorista)\b'],
        'bullying': [r'\b(acoso|hostigar|te voy a encontrar)\b'],
        'legal_privacy': [r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b']
    }
    
    for label in labels:
        if label in patterns:
            for pattern in patterns[label]:
                for match in re.finditer(pattern, tweet_text, re.IGNORECASE):
                    spans.append({
                        'text': match.group(0),
                        'start': match.start(),
                        'end': match.end(),
                        'label': label
                    })
    
    return spans


# ========================================================================
# CARGA DE TWEETS
# ========================================================================

def load_tweets_from_json(json_path: str) -> List[Dict[str, Any]]:
    """Carga tweets desde JSON."""
    p = Path(json_path)
    if not p.exists():
        raise FileNotFoundError(f"No existe: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    if "tweets" in data:
        return data.get("tweets", [])
    return data


BATCH_SIZE = 50


# ========================================================================
# MAIN OPTIMIZADO
# ========================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🛡️  CLASIFICADOR OPTIMIZADO v1.0 - Solo Texto")
    print("   ⚡ Prompts compactos | Modelo rápido | Sin análisis de media")
    print("="*70)

    default_json = Path(__file__).resolve().parents[1] / "tweets_TheDarkraimola_20251120_180501.json"
    try:
        result_data = load_tweets_from_json(str(default_json))
        
        if isinstance(result_data, dict) and "tweets" in result_data:
            tweets_data = result_data["tweets"]
        elif isinstance(result_data, list):
            tweets_data = result_data
        else:
            tweets_data = []
        
        test_tweets = []
        for t in tweets_data:
            if isinstance(t, dict):
                tweet_text = t.get("text", "")
                if tweet_text.strip():
                    test_tweets.append(tweet_text)
        
        print(f"📥 {len(test_tweets)} tweets cargados")
    except Exception as e:
        print(f"⚠️ Error: {e}")
        test_tweets = [
            "¡Hermoso día! 🌞",
            "Este político es un idiota corrupto",
        ]

    total = len(test_tweets)
    print(f"\n📊 Analizando {total} tweets...\n")

    results = []
    stats = {
        "risk_distribution": {"no": 0, "low": 0, "mid": 0, "high": 0},
        "label_counts": {},
        "errors": 0,
        "times": [],
        "throttle_waits": 0
    }
    
    program_start = time.monotonic()
    estimated_time_str = None

    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    
    for batch_idx, batch_start in enumerate(range(0, total, BATCH_SIZE), start=1):
        batch = test_tweets[batch_start:batch_start + BATCH_SIZE]
        print(f"\n{'='*60}")
        print(f"🔁 Lote {batch_idx}/{total_batches} — {batch_start+1}-{batch_start+len(batch)}")
        print(f"{'='*60}\n")

        for idx, tweet_text in enumerate(batch, start=batch_start+1):
            # Mostrar progreso compacto
            usage_pct = token_tracker.get_usage_percentage()
            print(f"🐦 {idx:3d}/{total} [{usage_pct:3.0f}%] ", end="", flush=True)
            
            # Throttling preventivo MÁS AGRESIVO
            if usage_pct > 60:  # Bajado de 70% a 60%
                wait_time = 8.0  # Aumentado de 5s a 8s
                print(f"⚠️ {wait_time}s", end="", flush=True)
                time.sleep(wait_time)
                stats["throttle_waits"] += 1

            start = time.monotonic()
            result = classify_risk_text_only(tweet_text)
            elapsed = time.monotonic() - start
            stats["times"].append(elapsed)
            
            if "error_code" not in result:
                level = result.get("risk_level", "low")
                stats["risk_distribution"][level] += 1
                for label in result.get("labels", []):
                    stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1
            else:
                stats["errors"] += 1
            
            result["tweet_id"] = idx
            result["text"] = tweet_text
            results.append(result)
            
            # Mostrar resultado compacto
            risk_str = result.get('risk_level', 'ERR')
            labels_str = ",".join(result.get('labels', []))[:20]
            print(f" → {risk_str:4s} {labels_str:20s} ({elapsed:.1f}s)")
            
            # Estimación mejorada después de 10 tweets (más representativo)
            if len(stats["times"]) == 10 and not estimated_time_str:
                # Calcular tiempo real total incluido delays
                elapsed_so_far = time.monotonic() - program_start
                avg_time_per_tweet = elapsed_so_far / 10  # Incluye TODO (análisis + delays + throttles)
                
                # Proyectar para tweets restantes
                remaining_tweets = total - 10
                est_remaining = avg_time_per_tweet * remaining_tweets
                est_total = elapsed_so_far + est_remaining
                
                est_hours = int(est_total // 3600)
                est_min = int((est_total % 3600) // 60)
                est_sec = int(est_total % 60)
                
                if est_hours > 0:
                    estimated_time_str = f"≈{est_hours}h{est_min}m"
                elif est_min > 0:
                    estimated_time_str = f"≈{est_min}m{est_sec}s"
                else:
                    estimated_time_str = f"≈{est_sec}s"
                
                print(f"\n{'='*60}")
                print(f"⏱️  TIEMPO ESTIMADO TOTAL: {estimated_time_str}")
                print(f"   (Basado en {elapsed_so_far:.1f}s para primeros 10 tweets)")
                print(f"   Velocidad: {avg_time_per_tweet:.2f}s por tweet")
                print(f"{'='*60}\n")
                
                # Guardar estimación
                timing_file = Path("tiempo_estimado.json")
                timing_file.write_text(json.dumps({
                    "num_tweets": total,
                    "tweets_procesados": 10,
                    "tiempo_transcurrido": f"{int(elapsed_so_far)}s",
                    "tiempo_estimado_total": estimated_time_str,
                    "velocidad_promedio": f"{avg_time_per_tweet:.2f}s/tweet"
                }, ensure_ascii=False, indent=2), encoding="utf-8")

            # Delay adaptativo más conservador
            usage_pct = token_tracker.get_usage_percentage()
            if usage_pct > 55:  # Mayor a 55%
                time.sleep(DELAY_BETWEEN_TWEETS * 4.0)  # 3.2s
            elif usage_pct > 40:  # Mayor a 40%
                time.sleep(DELAY_BETWEEN_TWEETS * 2.5)  # 2.0s
            else:  # Menor a 40%
                time.sleep(DELAY_BETWEEN_TWEETS)  # 0.8s

    # Resumen final
    total_time = time.monotonic() - program_start
    total_min = int(total_time // 60)
    total_sec = int(total_time % 60)
    actual_time = f"{total_min}m{total_sec}s" if total_min else f"{total_sec}s"

    print("\n" + "="*70)
    print(f"📈 RESUMEN - Tiempo: {actual_time}")
    print("="*70)

    successful = total - stats["errors"]
    print(f"\n✅ Exitosos: {successful}/{total}")
    print(f"❌ Errores: {stats['errors']}/{total}")
    print(f"⏸️  Throttles: {stats['throttle_waits']}")
    
    if successful > 0:
        print(f"\n📊 Distribución:")
        for level in ["no", "low", "mid", "high"]:
            count = stats['risk_distribution'][level]
            pct = (count/successful*100)
            print(f"  {level:4s}: {count:3d} ({pct:5.1f}%)")
        
        print(f"\n🏷️  Labels:")
        for label, count in sorted(stats["label_counts"].items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {label:20s}: {count:3d}")

    # Guardar resultados
    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tiempo_total": actual_time,
        "total_tweets": total,
        "exitosos": successful,
        "errores": stats["errors"],
        "distribucion": stats["risk_distribution"],
        "labels": stats["label_counts"]
    }

    Path("risk_summary_text_only.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("risk_detailed_text_only.json").write_text(json.dumps({"resultados": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    
    print(f"\n💾 Guardado: risk_summary_text_only.json")
    print(f"\n💾 Guardado: risk_detailed_text_only.json")
    print("\n" + "="*70)
    print("✨ Completado")
    print("="*70)
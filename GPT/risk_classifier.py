"""Clasificador de Riesgos para Tweets (B3) - Con Política v1.0 integrada
- Comparación: CON política vs SIN política
- Detección de spans ofensivos en el texto
- Niveles de riesgo: low, mid, high
- Compatible con circuit breaker y timeouts
"""

import time
import json
import re
from typing import Optional, List, Dict, Any, Tuple
from openai import OpenAI, APIError, RateLimitError, APITimeoutError
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_openai_api_key

# ========================================================================
# POLÍTICA v1.0 - TAXONOMÍA INTEGRADA
# ========================================================================

POLICY = {
    "version": "v1.0",
    "jurisdiction_hint": "US-first, global-aware",
    "audience_hint": "Millennial, English/Spanish mixed content; slang and sarcasm common.",
    "taxonomy": {
        "toxic": {
            "name": "Ofensivo/Tóxico",
            "definition": "Insultos, descalificaciones, lenguaje denigrante dirigido a personas o grupos.",
            "includes": ["insultos directos o velados", "profanidad dirigida", "slurs"],
            "excludes": ["crítica dura a ideas sin insultos", "citas condenatorias del insulto"]
        },
        "hate": {
            "name": "Odio/Discriminación",
            "definition": "Ataques o deshumanización por identidad protegida (raza, religión, género, orientación, discapacidad, nacionalidad).",
            "includes": ["slurs hacia grupos protegidos", "llamados a excluir o dañar"],
            "excludes": ["debate de políticas públicas sin deshumanización"]
        },
        "political_sensitivity": {
            "name": "Sensibilidad Socio-Política",
            "definition": "Contenido que probablemente cause controversia marcada (extremismo, conspiraciones, desinformación, llamados antidemocráticos).",
            "includes": ["apoyo a violencia política", "teorías conspirativas dañinas"],
            "excludes": ["opinión política legítima sin desinformación/ataque"]
        },
        "nsfw": {
            "name": "NSFW/Adulto",
            "definition": "Contenido sexualmente explícito, pornográfico o que vulnera normas de plataforma.",
            "includes": ["descripciones explícitas", "imágenes sexualizadas"],
            "excludes": ["afecto no sexual", "bromas suaves sin sexualización"]
        },
        "bullying": {
            "name": "Acoso/Hostigamiento",
            "definition": "Intimidación persistente o incitación a que otros hostiguen.",
            "includes": ["llamados a doxxear", "campañas para ridiculizar"],
            "excludes": ["respuesta aislada sin patrón"]
        },
        "violence": {
            "name": "Violencia/Autolesiones",
            "definition": "Amenazas creíbles, celebración de daño, incitación a violencia.",
            "includes": ["amenazas directas", "apoyo a daño físico"],
            "excludes": ["metáforas obvias sin objetivo real"]
        },
        "legal_privacy": {
            "name": "Riesgo Legal/Privacidad",
            "definition": "Difamación, doxxing, datos personales sensibles (teléfono, dirección, documento).",
            "includes": ["difusión de PII", "acusaciones factuales sin evidencia"],
            "excludes": ["opiniones sin imputación de delitos"]
        }
    },
    "severity_thresholds": {
        "low": {
            "description": "Riesgo menor o incierto; puede molestar pero es poco accionable.",
            "heuristics": [
                "Lenguaje ácido/opinión dura sin insultos ni grupos protegidos.",
                "Ambigüedad alta (sarcasmo/cita/negación).",
                "NSFW leve o insinuaciones no explícitas."
            ]
        },
        "mid": {
            "description": "Riesgo claro y contextual; podría dañar reputación.",
            "heuristics": [
                "Insultos directos sin slurs; bullying puntual; teorías conspirativas.",
                "PII parcial o acusaciones vagas con nombres.",
                "NSFW moderado."
            ]
        },
        "high": {
            "description": "Riesgo severo; probable violación a políticas.",
            "heuristics": [
                "Slurs o discurso de odio; amenazas; incitación a violencia.",
                "Doxxing/PII sensible; acusaciones delictivas específicas.",
                "Explícitamente sexual/violento; llamados a acoso coordinado."
            ]
        }
    },
    "label_to_severity": {
        "toxic": "mid",
        "hate": "high",
        "political_sensitivity": "low",
        "nsfw": "mid",
        "bullying": "mid",
        "violence": "high",
        "legal_privacy": "high"
    },
    "escalate_rules": [
        "Si múltiples labels incluyen hate o violence → high.",
        "Si incluye PII sensible (teléfono/dirección/doc) → high.",
        "Reincidencia de insultos + llamado a acción → high."
    ],
    "deescalate_rules": [
        "Cita condenatoria o sarcasmo evidente → bajar una banda."
    ]
}

# Configuración
MAX_RETRIES = 2
REQUEST_TIMEOUT = 15
TIMEOUT_PER_TWEET = 15
CIRCUIT_THRESHOLD = 5
CIRCUIT_COOLDOWN = 60

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
circuit_without_policy = CircuitBreaker()


def build_risk_classification_prompt(tweet_text: str, use_policy: bool = True, context_policy: Optional[str] = None) -> str:
    """
    Construye el prompt con few-shots según use_policy.
    """
    if use_policy:
        policy_context = context_policy or "Política estándar de moderación v1.0 con principios de caridad interpretativa."
        
        taxonomy_desc = "\n".join([
            f"- {key}: {meta['name']} - {meta['definition']}"
            for key, meta in POLICY["taxonomy"].items()
        ])
        
        prompt = f"""Analiza el siguiente tweet según Política v1.0 de moderación de contenido.

PRINCIPIOS CLAVE:
1. Caridad interpretativa: si hay ambigüedad clara, degradar severidad.
2. No confundir citas/denuncias/ironía con apoyo al contenido ofensivo.
3. Contexto mínimo: priorizar el texto del tweet.
4. Buscar la mínima secuencia que explica el riesgo (palabra/frase).

TAXONOMÍA DE RIESGO:
{taxonomy_desc}

CONTEXTO DE POLÍTICA: {policy_context}

EJEMPLOS POR POLÍTICA v1.0:

Tweet: "People who believe X are idiots."
{{
  "labels": ["toxic"],
  "risk_level": "mid",
  "rationale": "Insulto genérico a un grupo por ideas; tóxico sin slur ni identidad protegida.",
  "spans": [{{"text": "idiots", "start": 24, "end": 30, "label": "toxic"}}],
  "confidence": 0.78
}}

Tweet: "RT: 'We should harm them' — awful take"
{{
  "labels": ["violence","political_sensitivity"],
  "risk_level": "mid",
  "rationale": "Cita que promueve daño; autor la condena. Degradado por condena clara.",
  "spans": [{{"text": "We should harm them", "start": 5, "end": 24, "label": "violence"}}],
  "confidence": 0.72
}}

Tweet: "Estos inmigrantes son basura y deberían ser deportados todos"
{{
  "labels": ["hate","toxic"],
  "risk_level": "high",
  "rationale": "Slur implícito ('basura') + deshumanización de grupo protegido. Discurso de odio.",
  "spans": [
    {{"text": "Estos inmigrantes son basura", "start": 0, "end": 28, "label": "hate"}},
    {{"text": "deberían ser deportados todos", "start": 31, "end": 60, "label": "hate"}}
  ],
  "confidence": 0.89
}}

TWEET A ANALIZAR:
"{tweet_text}"

Responde SOLO con JSON válido. Estructura exacta:
{{
  "labels": [lista de keys de taxonomía],
  "risk_level": "low" | "mid" | "high",
  "rationale": "explicación ≤120 palabras",
  "spans": [{{"text": "fragmento", "start": int, "end": int, "label": "key"}}],
  "confidence": float [0.0, 1.0]
}}

JSON:"""
    else:
        prompt = f"""Analiza el siguiente tweet y clasifica los riesgos potenciales sin política específica.

Categorías de riesgo:
1. offensive: Insultos, slurs, lenguaje vulgar o tóxico
2. sociopolitical: Odio, extremismo, desinformación política/social
3. nsfw: Contenido sexual explícito o adulto
4. bullying: Acoso, hostigamiento, intimidación dirigida
5. violence: Amenazas, incitación a violencia o autolesiones
6. legal_risk: Difamación, doxxing, exposición de datos personales

EJEMPLOS:

Tweet: "Este político es un idiota corrupto que debería irse del país"
{{
  "labels": ["offensive", "sociopolitical"],
  "risk_level": "med",
  "rationale": "Contiene insultos directos hacia figura pública y lenguaje polarizante político.",
  "spans": [
    {{"text": "idiota corrupto", "start": 19, "end": 34, "label": "offensive"}},
    {{"text": "debería irse del país", "start": 39, "end": 60, "label": "sociopolitical"}}
  ],
  "confidence": 0.75
}}

Tweet: "Te voy a encontrar en la calle y te voy a partir la cara"
{{
  "labels": ["violence", "bullying"],
  "risk_level": "high",
  "rationale": "Amenaza directa de violencia física con intención intimidatoria clara.",
  "spans": [
    {{"text": "Te voy a encontrar en la calle", "start": 0, "end": 30, "label": "bullying"}},
    {{"text": "te voy a partir la cara", "start": 33, "end": 56, "label": "violence"}}
  ],
  "confidence": 0.92
}}

TWEET A ANALIZAR:
"{tweet_text}"

Responde SOLO con JSON válido:
{{
  "labels": [lista de labels],
  "risk_level": "low" | "med" | "high",
  "rationale": "explicación breve",
  "spans": [{{"text": "fragmento", "start": int, "end": int, "label": "key"}}],
  "confidence": float [0.0, 1.0]
}}

JSON:"""
    
    return prompt


def apply_policy_rules(labels: List[str], risk_level: str, text: str) -> Tuple[str, str]:
    """
    Aplica reglas de escalamiento/desescalamiento según Política v1.0.
    """
    reasoning = []
    
    if ("hate" in labels or "violence" in labels):
        if risk_level in ("low", "mid"):
            risk_level = "high"
            reasoning.append("Escalado: hate/violence → high")
    
    serious_labels = {"hate", "violence", "legal_privacy"}
    if len([l for l in labels if l in serious_labels]) > 1:
        risk_level = "high"
        reasoning.append("Escalado: múltiples labels serios → high")
    
    if ("RT:" in text or "Cita:" in text or "ironía" in text.lower() or "sarcasmo" in text.lower()):
        if risk_level == "high":
            risk_level = "mid"
            reasoning.append("Desescalado: sarcasmo/cita detectada")
    
    reasoning_str = " | ".join(reasoning) if reasoning else "Sin cambios por reglas de política"
    return risk_level, reasoning_str


def extract_spans_fallback(tweet_text: str, labels: List[str]) -> List[Dict[str, Any]]:
    """
    Extracción heurística de spans si el LLM no los proporciona.
    """
    spans = []
    patterns = {
        'toxic': [
            r'\b(idiota|estúpido|imbécil|pendejo|cabrón|mierda|basura)\b',
            r'\b(fuck|shit|damn|bitch|asshole)\b'
        ],
        'violence': [
            r'\b(matar|golpear|partir|romper|destrozar|atacar)\b.*\b(cara|cabeza|huesos)\b',
            r'\b(amenaza|voy a|te voy)\b.*\b(lastimar|hacer daño)\b'
        ],
        'political_sensitivity': [
            r'\b(nazi|fascista|comunista|terrorista)\b',
            r'\b(deportar|expulsar|eliminar).*\b(todos|grupo)\b'
        ],
        'bullying': [
            r'\b(acoso|hostigar|intimidar|acosar)\b',
            r'\b(te voy a encontrar|sé donde vives)\b'
        ],
        'legal_privacy': [
            r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        ]
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


def classify_risk(tweet_text: str, use_policy: bool = True, context_policy: Optional[str] = None) -> Dict[str, Any]:
    """
    Clasifica el nivel de riesgo de un tweet.
    """
    start_time = time.monotonic()
    circuit = circuit_with_policy if use_policy else circuit_without_policy

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

    prompt = build_risk_classification_prompt(tweet_text, use_policy, context_policy)
    attempts_allowed = MAX_RETRIES + 1

    for attempt in range(1, attempts_allowed + 1):
        if time.monotonic() - start_time >= TIMEOUT_PER_TWEET:
            circuit.record_failure()
            return {
                "error_code": ERROR_CODES['tweet_timeout'],
                "error": "Timeout total por tweet excedido",
                "attempt": attempt
            }

        try:
            system_msg = "Eres un clasificador de riesgos según Política v1.0. Responde SOLO con JSON válido." if use_policy else "Eres un clasificador de riesgos de contenido. Responde SOLO con JSON válido."
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": system_msg
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                timeout=REQUEST_TIMEOUT
            )

            if not getattr(response, "choices", None):
                circuit.record_failure()
                print(f"[attempt {attempt}] Sin choices en respuesta, reintentando...")
                time.sleep(0.5)
                continue

            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", "unknown")

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

            if not content:
                circuit.record_failure()
                print(f"[attempt {attempt}] contenido vacío, reintentando...")
                time.sleep(0.5)
                continue

            try:
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    data = json.loads(json_match.group(0))
                else:
                    data = json.loads(content)
            except Exception as e:
                print(f"[attempt {attempt}] Error parseando JSON: {e}")
                if attempt >= attempts_allowed:
                    return {
                        "labels": [],
                        "risk_level": "low",
                        "rationale": "No se pudo analizar adecuadamente.",
                        "spans": [],
                        "attempt": attempt,
                        "parse_error": str(e)
                    }
                time.sleep(0.5)
                continue

            # Validar y normalizar
            labels = data.get("labels", [])
            if use_policy:
                labels = [l for l in labels if l in POLICY["taxonomy"]]
            else:
                valid_labels = ["offensive", "sociopolitical", "nsfw", "bullying", "violence", "legal_risk"]
                labels = [l for l in labels if l in valid_labels]
            
            risk_level = data.get("risk_level", "low")
            # Normalizar "med" a "mid"
            if risk_level == "med":
                risk_level = "mid"
            if risk_level not in ["low", "mid", "high"]:
                risk_level = "low"
            if not labels:
                risk_level = "low"
            
            rationale = data.get("rationale", "Sin observaciones de riesgo.")
            confidence = float(data.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
            
            spans = [s for s in data.get("spans", []) if isinstance(s, dict) and "text" in s and "start" in s and "end" in s]
            if labels and not spans:
                spans = extract_spans_fallback(tweet_text, labels)

            # Aplicar reglas de Política v1.0 si use_policy es True
            original_level = risk_level
            policy_applied = None
            if use_policy:
                risk_level, policy_applied = apply_policy_rules(labels, risk_level, tweet_text)

            circuit.record_success()
            result = {
                "labels": labels,
                "risk_level": risk_level,
                "rationale": rationale,
                "spans": spans,
                "confidence": confidence,
                "attempt": attempt,
                "finish_reason": finish_reason
            }
            
            if use_policy:
                result["policy_applied"] = policy_applied
                if original_level != risk_level:
                    result["original_risk_level"] = original_level
            
            return result

        except (APITimeoutError, RateLimitError, APIError) as e:
            circuit.record_failure()
            print(f"[attempt {attempt}] {type(e).__name__}: {e}")
            if isinstance(e, APITimeoutError) and time.monotonic() - start_time >= TIMEOUT_PER_TWEET:
                return {
                    "error_code": ERROR_CODES['timeout'],
                    "error": "Timeout en la petición",
                    "attempt": attempt
                }
            if isinstance(e, RateLimitError):
                time.sleep(1)
            else:
                time.sleep(0.5)
            if attempt >= attempts_allowed:
                return {
                    "error_code": ERROR_CODES.get(type(e).__name__.lower(), 'api_error'),
                    "error": f"{type(e).__name__}: {e}",
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

    return {
        "error_code": ERROR_CODES['unknown'],
        "error": "Todos los intentos fallaron",
        "attempts": attempts_allowed
    }


def load_tweets_from_json(json_path: str) -> List[Dict[str, Any]]:
    """
    Carga tweets desde archivo JSON.
    """
    p = Path(json_path)
    if not p.exists():
        raise FileNotFoundError(f"No existe: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("tweets", [])


BATCH_SIZE = 50


if __name__ == "__main__":
    print("\n" + "="*70)
    print("🛡️  CLASIFICADOR DE RIESGOS v1.0 - COMPARACIÓN CON/SIN POLÍTICA")
    print("="*70)

    default_json = Path(__file__).resolve().parents[1] / "tweets_TheDarkraimola_20251011_100125.json"
    try:
        tweets_data = load_tweets_from_json(str(default_json))
        test_tweets = [t.get("text", "") for t in tweets_data if t.get("text", "").strip()]
        print(f"📥 Cargados {len(test_tweets)} tweets desde: {default_json}")
    except Exception as e:
        print(f"⚠️ Error cargando tweets JSON: {e}")
        test_tweets = [
            "¡Qué día tan hermoso! Me encanta este clima 🌞",
            "Este político es un idiota corrupto que debería renunciar ya",
            "Te voy a encontrar y te voy a romper la cara, ya verás",
            "Aquí está la dirección de Juan: Calle Falsa 123, tel 555-1234",
            "Esta gente es basura y deberían irse todos del país",
            "No estoy de acuerdo con esa política económica",
            "@usuario eres un estúpido, nadie te quiere aquí",
            "¡Me encanta este producto! Es increíble 😊",
            "Terrible experiencia, no lo recomiendo",
            "El clima hoy está nublado",
        ]

    total = len(test_tweets)
    print(f"\n📊 Analizando {total} tweets (CON POLÍTICA vs SIN POLÍTICA)...\n")

    # Almacenar resultados de ambas clasificaciones
    results_with_policy = []
    results_without_policy = []
    
    # Estadísticas
    stats_with_policy = {
        "risk_distribution": {"low": 0, "mid": 0, "high": 0},
        "label_counts": {},
        "errors": 0,
        "times": []
    }
    
    stats_without_policy = {
        "risk_distribution": {"low": 0, "mid": 0, "high": 0},
        "label_counts": {},
        "errors": 0,
        "times": []
    }
    
    program_start_time = time.monotonic()
    estimated_time_str_with = None
    estimated_time_str_without = None

    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_index, batch_start in enumerate(range(0, total, BATCH_SIZE), start=1):
        batch = test_tweets[batch_start:batch_start + BATCH_SIZE]
        batch_size = len(batch)
        batch_global_start = batch_start + 1
        batch_global_end = batch_start + batch_size
        print("\n" + "="*60)
        print(f"🔁 Lote {batch_index}/{total_batches} — tweets {batch_global_start}-{batch_global_end}")
        print("="*60)

        for idx, tweet in enumerate(batch, start=batch_global_start):
            within_batch_idx = idx - batch_start
            print(f"\n🐦 Tweet {within_batch_idx}/{batch_size} (global {idx}/{total})")
            print(f"   {tweet[:80]}{'...' if len(tweet) > 80 else ''}")

            # Clasificar CON política
            print("   [CON POLÍTICA]", end=" ", flush=True)
            start_with = time.monotonic()
            result_with = classify_risk(tweet, use_policy=True)
            time_with = time.monotonic() - start_with
            stats_with_policy["times"].append(time_with)
            
            if "error_code" not in result_with:
                level = result_with.get("risk_level", "low")
                stats_with_policy["risk_distribution"][level] += 1
                for label in result_with.get("labels", []):
                    stats_with_policy["label_counts"][label] = stats_with_policy["label_counts"].get(label, 0) + 1
            else:
                stats_with_policy["errors"] += 1
            
            result_with["tweet_id"] = idx
            result_with["text"] = tweet
            results_with_policy.append(result_with)
            print(f"✓ ({time_with:.2f}s) | {result_with.get('risk_level', 'error')}", flush=True)

            # Clasificar SIN política
            print("   [SIN POLÍTICA]", end=" ", flush=True)
            start_without = time.monotonic()
            result_without = classify_risk(tweet, use_policy=False)
            time_without = time.monotonic() - start_without
            stats_without_policy["times"].append(time_without)
            
            if "error_code" not in result_without:
                level = result_without.get("risk_level", "low")
                stats_without_policy["risk_distribution"][level] += 1
                for label in result_without.get("labels", []):
                    stats_without_policy["label_counts"][label] = stats_without_policy["label_counts"].get(label, 0) + 1
            else:
                stats_without_policy["errors"] += 1
            
            result_without["tweet_id"] = idx
            result_without["text"] = tweet
            results_without_policy.append(result_without)
            print(f"✓ ({time_without:.2f}s) | {result_without.get('risk_level', 'error')}", flush=True)

            # Calcular tiempo estimado después de 3 tweets
            if len(stats_with_policy["times"]) == 3 and estimated_time_str_with is None:
                avg_time = sum(stats_with_policy["times"]) / 3
                estimated_total = avg_time * total
                
                est_hours = int(estimated_total // 3600)
                est_minutes = int((estimated_total % 3600) // 60)
                est_seconds = int(estimated_total % 60)
                
                if est_hours > 0:
                    estimated_time_str_with = f"≈ {est_hours}h {est_minutes}m {est_seconds}s"
                elif est_minutes > 0:
                    estimated_time_str_with = f"≈ {est_minutes}m {est_seconds}s"
                else:
                    estimated_time_str_with = f"≈ {est_seconds}s"
                
                print(f"\n{'='*60}")
                print(f"✅ TIEMPO ESTIMADO (por tweet): {estimated_time_str_with}")
                print(f"{'='*60}")
                
                # Imprimir JSON con tiempo estimado
                timing_results = {
                    "num_tweets": total,
                    "tiempo_estimado": estimated_time_str_with
                }
                print("\n📊 RESUMEN EN JSON:")
                print(json.dumps(timing_results, ensure_ascii=False, indent=2))
                print(f"{'='*60}\n")
                
                # Guardar JSON independiente de tiempo estimado
                timing_file = Path("tiempo_estimado.json")
                with timing_file.open("w", encoding="utf-8") as f:
                    json.dump(timing_results, f, ensure_ascii=False, indent=2)
                print(f"💾 Tiempo estimado guardado en: {timing_file}\n")

            time.sleep(0.1)

    # Cálculo de tiempos reales
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
    print("📈 RESUMEN COMPARATIVO: CON POLÍTICA vs SIN POLÍTICA")
    print("="*70)
    print(f"\n⏱️  TIEMPO TOTAL: {actual_time}")

    successful_with = total - stats_with_policy["errors"]
    successful_without = total - stats_without_policy["errors"]

    print(f"\n{'─'*70}")
    print("📊 CON POLÍTICA v1.0")
    print(f"{'─'*70}")
    print(f"Análisis exitosos: {successful_with}/{total}")
    print(f"Fallos: {stats_with_policy['errors']}/{total}")
    
    if successful_with > 0:
        print(f"\nDistribución de riesgos:")
        print(f"  - Low:  {stats_with_policy['risk_distribution']['low']} ({stats_with_policy['risk_distribution']['low']/successful_with*100:.1f}%)")
        print(f"  - Mid:  {stats_with_policy['risk_distribution']['mid']} ({stats_with_policy['risk_distribution']['mid']/successful_with*100:.1f}%)")
        print(f"  - High: {stats_with_policy['risk_distribution']['high']} ({stats_with_policy['risk_distribution']['high']/successful_with*100:.1f}%)")
        
        if stats_with_policy["label_counts"]:
            print(f"\nLabels detectados:")
            for label, count in sorted(stats_with_policy["label_counts"].items(), key=lambda x: x[1], reverse=True):
                name = POLICY["taxonomy"].get(label, {}).get("name", label)
                print(f"  - {label}: {count} ({name})")

    print(f"\n{'─'*70}")
    print("📊 SIN POLÍTICA (Clasificación Básica)")
    print(f"{'─'*70}")
    print(f"Análisis exitosos: {successful_without}/{total}")
    print(f"Fallos: {stats_without_policy['errors']}/{total}")
    
    if successful_without > 0:
        print(f"\nDistribución de riesgos:")
        print(f"  - Low:  {stats_without_policy['risk_distribution']['low']} ({stats_without_policy['risk_distribution']['low']/successful_without*100:.1f}%)")
        print(f"  - Mid:  {stats_without_policy['risk_distribution']['mid']} ({stats_without_policy['risk_distribution']['mid']/successful_without*100:.1f}%)")
        print(f"  - High: {stats_without_policy['risk_distribution']['high']} ({stats_without_policy['risk_distribution']['high']/successful_without*100:.1f}%)")
        
        if stats_without_policy["label_counts"]:
            print(f"\nLabels detectados:")
            for label, count in sorted(stats_without_policy["label_counts"].items(), key=lambda x: x[1], reverse=True):
                print(f"  - {label}: {count}")

    # Comparativa
    print(f"\n{'─'*70}")
    print("🔄 COMPARATIVA")
    print(f"{'─'*70}")
    
    high_with = stats_with_policy['risk_distribution']['high']
    high_without = stats_without_policy['risk_distribution']['high']
    high_diff = high_with - high_without
    
    mid_with = stats_with_policy['risk_distribution']['mid']
    mid_without = stats_without_policy['risk_distribution']['mid']
    mid_diff = mid_with - mid_without
    
    low_with = stats_with_policy['risk_distribution']['low']
    low_without = stats_without_policy['risk_distribution']['low']
    low_diff = low_with - low_without
    
    print(f"High: {high_with} (con) vs {high_without} (sin) | Diferencia: {high_diff:+d}")
    print(f"Mid:  {mid_with} (con) vs {mid_without} (sin) | Diferencia: {mid_diff:+d}")
    print(f"Low:  {low_with} (con) vs {low_without} (sin) | Diferencia: {low_diff:+d}")

    # Guardar resultados JSON comparativos
    summary_json = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tiempo_total": actual_time,
        "total_tweets": total,
        "comparativa": {
            "con_politica_v1": {
                "version": POLICY["version"],
                "tiempo_total": actual_time,
                "exitosos": successful_with,
                "fallos": stats_with_policy["errors"],
                "distribucion_riesgos": stats_with_policy["risk_distribution"],
                "labels_detectados": stats_with_policy["label_counts"],
                "resumen_labels": {
                    label: {
                        "nombre": POLICY["taxonomy"].get(label, {}).get("name", label),
                        "cantidad": count
                    }
                    for label, count in stats_with_policy["label_counts"].items()
                }
            },
            "sin_politica": {
                "tiempo_total": actual_time,
                "exitosos": successful_without,
                "fallos": stats_without_policy["errors"],
                "distribucion_riesgos": stats_without_policy["risk_distribution"],
                "labels_detectados": stats_without_policy["label_counts"]
            },
            "diferencias": {
                "high": high_diff,
                "mid": mid_diff,
                "low": low_diff
            }
        }
    }

    output_summary = Path("risk_classification_summary.json")
    with output_summary.open("w", encoding="utf-8") as f:
        json.dump(summary_json, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Resumen comparativo guardado en: {output_summary}")

    # Guardar resultados detallados
    output_detailed = Path("risk_classification_detailed.json")
    with output_detailed.open("w", encoding="utf-8") as f:
        json.dump({
            "con_politica": results_with_policy,
            "sin_politica": results_without_policy
        }, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Resultados detallados guardados en: {output_detailed}")
    
    print("\n" + "="*70)
    print("✨ Análisis comparativo completado")
    print("="*70)
"""Clasificador de Riesgos HÍBRIDO - Separa procesamiento por tipo
- Filtra tweets CON y SIN media
- CALIBRA tiempo estimado con primeros 10 de cada tipo
- Procesa primero TEXTO, luego MEDIA
- Maximiza eficiencia y precisión
"""

import time
import json
from typing import List, Dict, Any, Tuple
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Importar funciones específicas de cada módulo
from GPT.risk_classifier_only_text import (
    classify_risk_text_only,
    token_tracker as text_tracker
)
from GPT.risk_classifier_media import (
    classify_risk_unified,
    token_tracker as media_tracker
)


# ========================================================================
# SEPARACIÓN Y FILTRADO DE TWEETS
# ========================================================================

def separate_tweets_by_media(tweets: List[Dict[str, Any]]) -> tuple[List[Dict], List[Dict]]:
    """
    Separa tweets en dos grupos: con media y sin media.
    Retorna: (tweets_sin_media, tweets_con_media)
    """
    tweets_sin_media = []
    tweets_con_media = []
    
    for idx, tweet in enumerate(tweets):
        media_list = tweet.get("media", [])
        tweet_obj = {
            "id": idx + 1,
            "text": tweet.get("text", ""),
            "media": media_list
        }
        
        if media_list and len(media_list) > 0:
            tweets_con_media.append(tweet_obj)
        else:
            tweets_sin_media.append(tweet_obj)
    
    return tweets_sin_media, tweets_con_media


# ========================================================================
# CALIBRACIÓN - PRIMEROS 10 TWEETS
# ========================================================================

def calibrate_text_speed(tweets: List[Dict], num_samples: int = 10) -> Tuple[List[Dict], float]:
    """
    Procesa los primeros 10 tweets SIN media para calibrar velocidad.
    Retorna: (resultados, tiempo_promedio_por_tweet)
    """
    if not tweets:
        return [], 0.0
    
    samples = tweets[:min(num_samples, len(tweets))]
    results = []
    
    print(f"\n🔬 CALIBRANDO con primeros {len(samples)} tweets SIN media...")
    print("="*60 + "\n")
    
    start_time = time.monotonic()
    
    for tweet_obj in samples:
        idx = tweet_obj["id"]
        tweet_text = tweet_obj["text"]
        
        usage_pct = text_tracker.get_usage_percentage()
        print(f"🐦 {idx:3d} [{usage_pct:3.0f}%] ", end="", flush=True)
        
        if usage_pct > 60:
            wait_time = 8.0
            print(f"⚠️ {wait_time}s", end="", flush=True)
            time.sleep(wait_time)
        
        start = time.monotonic()
        result = classify_risk_text_only(tweet_text)
        elapsed = time.monotonic() - start
        
        result["tweet_id"] = idx
        result["text"] = tweet_text
        result["has_media"] = False
        results.append(result)
        
        risk_str = result.get('risk_level', 'ERR')
        labels_str = ",".join(result.get('labels', []))[:20]
        print(f" → {risk_str:4s} {labels_str:20s} ({elapsed:.1f}s)")
        
        # Delay adaptativo
        usage_pct = text_tracker.get_usage_percentage()
        if usage_pct > 55:
            time.sleep(3.2)
        elif usage_pct > 40:
            time.sleep(2.0)
        else:
            time.sleep(0.8)
    
    total_time = time.monotonic() - start_time
    avg_time = total_time / len(samples)
    
    return results, avg_time


def calibrate_media_speed(tweets: List[Dict], num_samples: int = 10) -> Tuple[List[Dict], float]:
    """
    Procesa los primeros 10 tweets CON media para calibrar velocidad.
    Retorna: (resultados, tiempo_promedio_por_tweet)
    """
    if not tweets:
        return [], 0.0
    
    samples = tweets[:min(num_samples, len(tweets))]
    results = []
    
    print(f"\n🔬 CALIBRANDO con primeros {len(samples)} tweets CON media...")
    print("="*60 + "\n")
    
    start_time = time.monotonic()
    
    for tweet_obj in samples:
        idx = tweet_obj["id"]
        tweet_text = tweet_obj["text"]
        media_list = tweet_obj["media"]
        
        usage_pct = media_tracker.get_usage_percentage()
        media_count = len(media_list)
        print(f"🐦 {idx:3d} 📷{media_count} [{usage_pct:3.0f}%] ", end="", flush=True)
        
        if usage_pct > 55:
            wait_time = 10.0
            print(f"⚠️ {wait_time}s", end="", flush=True)
            time.sleep(wait_time)
        
        start = time.monotonic()
        result = classify_risk_unified(tweet_text, media_list)
        elapsed = time.monotonic() - start
        
        result["tweet_id"] = idx
        result["text"] = tweet_text
        results.append(result)
        
        risk_str = result.get('risk_level', 'ERR')
        labels_str = ",".join(result.get('labels', []))[:20]
        print(f" → {risk_str:4s} {labels_str:20s} ({elapsed:.1f}s)")
        
        # Delay adaptativo más conservador para media
        usage_pct = media_tracker.get_usage_percentage()
        if usage_pct > 50:
            time.sleep(4.0)
        elif usage_pct > 35:
            time.sleep(2.5)
        else:
            time.sleep(1.2)
    
    total_time = time.monotonic() - start_time
    avg_time = total_time / len(samples)
    
    return results, avg_time


# ========================================================================
# PROCESAMIENTO COMPLETO (SIN CALIBRACIÓN)
# ========================================================================

def process_remaining_text_tweets(tweets: List[Dict], start_idx: int, batch_size: int = 50) -> List[Dict]:
    """Procesa tweets SIN media restantes después de calibración."""
    if start_idx >= len(tweets):
        return []
    
    results = []
    remaining = tweets[start_idx:]
    total = len(tweets)
    
    print(f"\n📝 Procesando {len(remaining)} tweets SIN media restantes...")
    
    for batch_idx, batch_start in enumerate(range(0, len(remaining), batch_size), start=1):
        batch = remaining[batch_start:batch_start + batch_size]
        print(f"\n{'='*60}")
        print(f"🔁 Lote {batch_idx} (texto) — {start_idx + batch_start + 1}-{start_idx + batch_start + len(batch)}")
        print(f"{'='*60}\n")
        
        for tweet_obj in batch:
            idx = tweet_obj["id"]
            tweet_text = tweet_obj["text"]
            
            usage_pct = text_tracker.get_usage_percentage()
            print(f"🐦 {idx:3d}/{total} [{usage_pct:3.0f}%] ", end="", flush=True)
            
            if usage_pct > 60:
                wait_time = 8.0
                print(f"⚠️ {wait_time}s", end="", flush=True)
                time.sleep(wait_time)
            
            start = time.monotonic()
            result = classify_risk_text_only(tweet_text)
            elapsed = time.monotonic() - start
            
            result["tweet_id"] = idx
            result["text"] = tweet_text
            result["has_media"] = False
            results.append(result)
            
            risk_str = result.get('risk_level', 'ERR')
            labels_str = ",".join(result.get('labels', []))[:20]
            print(f" → {risk_str:4s} {labels_str:20s} ({elapsed:.1f}s)")
            
            usage_pct = text_tracker.get_usage_percentage()
            if usage_pct > 55:
                time.sleep(3.2)
            elif usage_pct > 40:
                time.sleep(2.0)
            else:
                time.sleep(0.8)
    
    return results


def process_remaining_media_tweets(tweets: List[Dict], start_idx: int, batch_size: int = 50) -> List[Dict]:
    """Procesa tweets CON media restantes después de calibración."""
    if start_idx >= len(tweets):
        return []
    
    results = []
    remaining = tweets[start_idx:]
    total = len(tweets)
    
    print(f"\n📷 Procesando {len(remaining)} tweets CON media restantes...")
    
    for batch_idx, batch_start in enumerate(range(0, len(remaining), batch_size), start=1):
        batch = remaining[batch_start:batch_start + batch_size]
        print(f"\n{'='*60}")
        print(f"🔁 Lote {batch_idx} (media) — {start_idx + batch_start + 1}-{start_idx + batch_start + len(batch)}")
        print(f"{'='*60}\n")
        
        for tweet_obj in batch:
            idx = tweet_obj["id"]
            tweet_text = tweet_obj["text"]
            media_list = tweet_obj["media"]
            
            usage_pct = media_tracker.get_usage_percentage()
            media_count = len(media_list)
            print(f"🐦 {idx:3d}/{total} 📷{media_count} [{usage_pct:3.0f}%] ", end="", flush=True)
            
            if usage_pct > 55:
                wait_time = 10.0
                print(f"⚠️ {wait_time}s", end="", flush=True)
                time.sleep(wait_time)
            
            start = time.monotonic()
            result = classify_risk_unified(tweet_text, media_list)
            elapsed = time.monotonic() - start
            
            result["tweet_id"] = idx
            result["text"] = tweet_text
            results.append(result)
            
            risk_str = result.get('risk_level', 'ERR')
            labels_str = ",".join(result.get('labels', []))[:20]
            print(f" → {risk_str:4s} {labels_str:20s} ({elapsed:.1f}s)")
            
            usage_pct = media_tracker.get_usage_percentage()
            if usage_pct > 50:
                time.sleep(4.0)
            elif usage_pct > 35:
                time.sleep(2.5)
            else:
                time.sleep(1.2)
    
    return results


# ========================================================================
# ESTADÍSTICAS Y REPORTE
# ========================================================================

def calculate_statistics(results: List[Dict]) -> Dict:
    """Calcula estadísticas de los resultados."""
    stats = {
        "risk_distribution": {"low": 0, "mid": 0, "high": 0},
        "label_counts": {},
        "errors": 0,
        "with_media": 0,
        "without_media": 0
    }
    
    for result in results:
        if "error_code" in result:
            stats["errors"] += 1
            continue
        
        level = result.get("risk_level", "low")
        stats["risk_distribution"][level] += 1
        
        for label in result.get("labels", []):
            stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1
        
        if result.get("has_media", False):
            stats["with_media"] += 1
        else:
            stats["without_media"] += 1
    
    return stats


def print_summary(stats: Dict, total_time: float, total_tweets: int, text_time: float, media_time: float, calib_time: float):
    """Imprime resumen final."""
    total_min = int(total_time // 60)
    total_sec = int(total_time % 60)
    actual_time = f"{total_min}m{total_sec}s" if total_min else f"{total_sec}s"
    
    print("\n" + "="*70)
    print(f"📈 RESUMEN FINAL - Tiempo Total: {actual_time}")
    print("="*70)
    
    successful = total_tweets - stats["errors"]
    print(f"\n✅ Exitosos: {successful}/{total_tweets}")
    print(f"❌ Errores: {stats['errors']}/{total_tweets}")
    print(f"📝 Sin media: {stats['without_media']}")
    print(f"📷 Con media: {stats['with_media']}")
    
    print(f"\n⏱️  Desglose de tiempos:")
    print(f"   Calibración: {int(calib_time//60)}m{int(calib_time%60)}s")
    print(f"   Texto: {int(text_time//60)}m{int(text_time%60)}s")
    print(f"   Media: {int(media_time//60)}m{int(media_time%60)}s")
    
    if successful > 0:
        print(f"\n📊 Distribución de Riesgo:")
        for level in ["low", "mid", "high"]:
            count = stats['risk_distribution'][level]
            pct = (count/successful*100) if successful > 0 else 0
            print(f"  {level:4s}: {count:3d} ({pct:5.1f}%)")
        
        if stats["label_counts"]:
            print(f"\n🏷️  Top 10 Labels:")
            sorted_labels = sorted(stats["label_counts"].items(), 
                                 key=lambda x: x[1], reverse=True)[:10]
            for label, count in sorted_labels:
                print(f"  {label:20s}: {count:3d}")


# ========================================================================
# CARGA DE DATOS
# ========================================================================

def load_tweets_from_json(json_path: str) -> List[Dict[str, Any]]:
    """Carga tweets desde JSON."""
    p = Path(json_path)
    if not p.exists():
        raise FileNotFoundError(f"No existe: {p}")
    
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    
    if isinstance(data, dict) and "tweets" in data:
        tweets_data = data["tweets"]
    elif isinstance(data, list):
        tweets_data = data
    else:
        tweets_data = []
    
    # Filtrar tweets válidos
    valid_tweets = []
    for t in tweets_data:
        if isinstance(t, dict) and t.get("text", "").strip():
            valid_tweets.append(t)
    
    return valid_tweets


# ========================================================================
# MAIN - PROCESAMIENTO CON CALIBRACIÓN INICIAL
# ========================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🛡️  CLASIFICADOR HÍBRIDO v2.0 - Con Calibración Inicial")
    print("   1️⃣  Calibra con primeros 10 de cada tipo")
    print("   2️⃣  Calcula tiempo estimado TOTAL preciso")
    print("   3️⃣  Procesa TEXTO completo")
    print("   4️⃣  Procesa MEDIA completo")
    print("="*70)
    
    # Cargar tweets
    default_json = Path(__file__).resolve().parents[1] / "tweets_TheDarkraimola_20251023_173729.json"
    
    try:
        all_tweets = load_tweets_from_json(str(default_json))
        print(f"\n📥 Cargados: {len(all_tweets)} tweets")
    except Exception as e:
        print(f"⚠️ Error cargando tweets: {e}")
        all_tweets = [
            {"text": "¡Hermoso día! 🌞", "media": []},
            {"text": "Este político es un idiota", "media": []},
        ]
    
    program_start = time.monotonic()
    
    # ==========================================
    # PASO 1: SEPARAR POR TIPO
    # ==========================================
    print("\n" + "="*70)
    print("🔍 PASO 1: Separando tweets por tipo...")
    print("="*70)
    
    tweets_sin_media, tweets_con_media = separate_tweets_by_media(all_tweets)
    
    print(f"\n✅ Separación completada")
    print(f"   📝 Sin media: {len(tweets_sin_media)}")
    print(f"   📷 Con media: {len(tweets_con_media)}")
    
    # ==========================================
    # PASO 2: CALIBRACIÓN CON PRIMEROS 10
    # ==========================================
    print("\n" + "="*70)
    print("🔬 PASO 2: CALIBRANDO velocidades (primeros 10 de cada tipo)")
    print("="*70)
    
    calibration_start = time.monotonic()
    
    # Calibrar texto
    calib_text_results = []
    avg_text_speed = 1.5  # Default
    if tweets_sin_media:
        calib_text_results, avg_text_speed = calibrate_text_speed(tweets_sin_media, num_samples=10)
        print(f"\n✅ Calibración TEXTO: {avg_text_speed:.2f}s por tweet")
    
    # Calibrar media
    calib_media_results = []
    avg_media_speed = 4.0  # Default
    if tweets_con_media:
        calib_media_results, avg_media_speed = calibrate_media_speed(tweets_con_media, num_samples=10)
        print(f"\n✅ Calibración MEDIA: {avg_media_speed:.2f}s por tweet")
    
    calibration_time = time.monotonic() - calibration_start
    
    # ==========================================
    # ESTIMACIÓN TOTAL CALIBRADA
    # ==========================================
    print("\n" + "="*70)
    print("⏱️  TIEMPO ESTIMADO TOTAL (basado en calibración real)")
    print("="*70)
    
    remaining_text = len(tweets_sin_media) - len(calib_text_results)
    remaining_media = len(tweets_con_media) - len(calib_media_results)
    
    est_text_time = remaining_text * avg_text_speed
    est_media_time = remaining_media * avg_media_speed
    est_total_seconds = est_text_time + est_media_time
    
    est_hours = int(est_total_seconds // 3600)
    est_min = int((est_total_seconds % 3600) // 60)
    est_sec = int(est_total_seconds % 60)
    
    if est_hours > 0:
        est_total_str = f"≈{est_hours}h{est_min}m{est_sec}s"
    elif est_min > 0:
        est_total_str = f"≈{est_min}m{est_sec}s"
    else:
        est_total_str = f"≈{est_sec}s"
    
    est_text_min = int(est_text_time // 60)
    est_text_sec = int(est_text_time % 60)
    est_media_min = int(est_media_time // 60)
    est_media_sec = int(est_media_time % 60)
    
    print(f"\n📊 Velocidades calibradas:")
    print(f"   📝 Texto: {avg_text_speed:.2f}s/tweet × {remaining_text} tweets = {est_text_min}m{est_text_sec}s")
    print(f"   📷 Media: {avg_media_speed:.2f}s/tweet × {remaining_media} tweets = {est_media_min}m{est_media_sec}s")
    print(f"\n🎯 TIEMPO ESTIMADO RESTANTE: {est_total_str}")
    print("="*70)
    
    # ==========================================
    # PASO 3: PROCESAR TEXTO COMPLETO
    # ==========================================
    print("\n" + "="*70)
    print("📝 PASO 3: Procesando TODOS los tweets SIN media")
    print("="*70)
    
    text_start = time.monotonic()
    remaining_text_results = process_remaining_text_tweets(tweets_sin_media, start_idx=len(calib_text_results))
    text_time = time.monotonic() - text_start
    
    all_text_results = calib_text_results + remaining_text_results
    
    print(f"\n✅ Procesamiento TEXTO completado en {int(text_time//60)}m{int(text_time%60)}s")
    print(f"   Total procesados: {len(all_text_results)}")
    
    # ==========================================
    # PASO 4: PROCESAR MEDIA COMPLETO
    # ==========================================
    print("\n" + "="*70)
    print("📷 PASO 4: Procesando TODOS los tweets CON media")
    print("="*70)
    
    media_start = time.monotonic()
    remaining_media_results = process_remaining_media_tweets(tweets_con_media, start_idx=len(calib_media_results))
    media_time = time.monotonic() - media_start
    
    all_media_results = calib_media_results + remaining_media_results
    
    print(f"\n✅ Procesamiento MEDIA completado en {int(media_time//60)}m{int(media_time%60)}s")
    print(f"   Total procesados: {len(all_media_results)}")
    
    # ==========================================
    # COMBINAR Y FINALIZAR
    # ==========================================
    all_results = all_text_results + all_media_results
    all_results.sort(key=lambda x: x.get("tweet_id", 0))
    
    total_time = time.monotonic() - program_start
    
    # Estadísticas y guardado
    stats = calculate_statistics(all_results)
    print_summary(stats, total_time, len(all_tweets), text_time, media_time, calibration_time)
    
    # Guardar resultados
    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tiempo_total": f"{int(total_time//60)}m{int(total_time%60)}s",
        "tiempo_calibracion": f"{int(calibration_time//60)}m{int(calibration_time%60)}s",
        "tiempo_texto": f"{int(text_time//60)}m{int(text_time%60)}s",
        "tiempo_media": f"{int(media_time//60)}m{int(media_time%60)}s",
        "velocidad_calibrada_texto": f"{avg_text_speed:.2f}s/tweet",
        "velocidad_calibrada_media": f"{avg_media_speed:.2f}s/tweet",
        "total_tweets": len(all_tweets),
        "tweets_sin_media": len(tweets_sin_media),
        "tweets_con_media": len(tweets_con_media),
        "exitosos": len(all_tweets) - stats["errors"],
        "errores": stats["errors"],
        "distribucion": stats["risk_distribution"],
        "labels": stats["label_counts"]
    }
    
    output_dir = Path(__file__).resolve().parent
    summary_path = output_dir / "risk_summary_hybrid.json"
    detailed_path = output_dir / "risk_detailed_hybrid.json"
    
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    detailed_path.write_text(
        json.dumps({"resultados": all_results}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    print(f"\n💾 Guardado: {summary_path.name}")
    print(f"💾 Guardado: {detailed_path.name}")
    
    # Métricas de eficiencia
    print(f"\n⚡ MÉTRICAS DE EFICIENCIA:")
    if all_text_results:
        real_text_speed = (calibration_time + text_time) / len(all_text_results)
        print(f"   Velocidad real (texto): {real_text_speed:.2f}s/tweet")
    if all_media_results:
        real_media_speed = (calibration_time + media_time) / len(all_media_results)
        print(f"   Velocidad real (media): {real_media_speed:.2f}s/tweet")
    print(f"   Velocidad promedio (total): {total_time/len(all_tweets):.2f}s/tweet")
    
    print("\n" + "="*70)
    print("✨ Procesamiento híbrido completado exitosamente")
    print("="*70)
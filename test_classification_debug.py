"""
Script de prueba EXACTO - Simula process_tweets_search_background COMPLETO
Incluyendo la llamada real a fetch_user_tweets_with_progress
"""

import sys
from pathlib import Path
import time
from datetime import datetime

# Simular el mismo sys.path que main.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Importar EXACTAMENTE lo mismo que main.py
from X.search_tweets import fetch_user_tweets_with_progress
from GPT.risk_classifier_only_text import classify_risk_text_only

# ============================================================================
# TWEETS SIMULADOS (como si vinieran de Twitter API)
# Estructura EXACTA de lo que retorna la API de Twitter v2
# ============================================================================

fake_twitter_response = {
    'success': True,
    'user': {
        'author_id': '123456789',
        'username': 'test_user',
        'name': 'Test User',
        'followers': 100,
        'account_created': '2020-01-01T00:00:00.000Z',
        'profile_image_url': 'https://example.com/image.jpg'
    },
    'tweets': [
        {
            "id": "1234567890123456789",
            "text": "¡Qué hermoso día! Me encanta el clima ☀️",
            "is_retweet": False,
            "author_id": "123456789",
            "created_at": "2024-01-15T10:30:00.000Z",
            "public_metrics": {
                "retweet_count": 5,
                "reply_count": 2,
                "like_count": 10
            }
        },
        {
            "id": "9876543210987654321",
            "text": "Estos políticos son unos corruptos e idiotas",
            "is_retweet": False,
            "author_id": "123456789",
            "created_at": "2024-01-15T11:00:00.000Z",
            "public_metrics": {
                "retweet_count": 1,
                "reply_count": 3,
                "like_count": 5
            }
        },
        {
            "id": "5555555555555555555",
            "text": "RT @usuario: Este es un retweet de ejemplo",
            "is_retweet": True,
            "author_id": "123456789",
            "created_at": "2024-01-15T12:00:00.000Z",
            "referenced_tweets": [
                {"type": "retweeted", "id": "9999999999999999999"}
            ]
        },
        {
            "id": "7777777777777777777",
            "text": "Los inmigrantes son basura y deberían irse",
            "is_retweet": False,
            "author_id": "123456789",
            "created_at": "2024-01-15T13:00:00.000Z",
            "public_metrics": {
                "retweet_count": 0,
                "reply_count": 10,
                "like_count": 2
            }
        },
        {
            "id": "8888888888888888888",
            "text": "Hoy voy a comer pizza 🍕",
            "is_retweet": False,
            "author_id": "123456789",
            "created_at": "2024-01-15T14:00:00.000Z",
            "public_metrics": {
                "retweet_count": 0,
                "reply_count": 1,
                "like_count": 3
            }
        }
    ],
    'stats': {
        'total_tweets': 5,
        'retweets': 1,
        'original_tweets': 4,
        'tweets_with_media': 0,
        'total_media_count': 0
    },
    'pages_fetched': 1,
    'fetched_at': datetime.now().isoformat(),
    'execution_time': '00:00:05',
    'execution_time_seconds': 5.0
}

# ============================================================================
# SIMULACIÓN EXACTA DE process_tweets_search_background
# ============================================================================

def simulate_process_tweets_search_background():
    """
    Simula EXACTAMENTE lo que hace process_tweets_search_background
    """
    job_id = "test_job_123"
    username = "test_user"
    
    print("\n" + "="*70)
    print(f"🔄 SIMULACIÓN EXACTA: process_tweets_search_background")
    print("="*70)
    print(f"   Job ID: {job_id}")
    print(f"   Usuario: @{username}")
    print("="*70 + "\n")
    
    try:
        # ═══════════════════════════════════════════════════════════════════
        # PASO 1: Obtener tweets (SIMULADO - en tu caso viene de la API real)
        # ═══════════════════════════════════════════════════════════════════
        print("📥 PASO 1: Obteniendo tweets...")
        
        # En lugar de llamar a fetch_user_tweets_with_progress (que requiere API key)
        # usamos la respuesta simulada
        result = fake_twitter_response
        
        if not result.get('success'):
            print(f"❌ Error obteniendo tweets: {result.get('error')}")
            return
        
        print(f"✅ Tweets obtenidos: {len(result.get('tweets', []))}")
        
        # ═══════════════════════════════════════════════════════════════════
        # PASO 2: AUTO-CLASIFICACIÓN (EXACTO como en main.py línea ~1290)
        # ═══════════════════════════════════════════════════════════════════
        print(f"\n{'='*70}")
        print(f"🤖 PASO 2: AUTO-CLASIFICACIÓN")
        print(f"{'='*70}\n")
        
        # Obtener tweets para clasificar (LÍNEA ~1293 de main.py)
        tweets_to_classify = result.get('tweets', [])
        
        print(f"🔍 DEBUG: ¿Qué contiene 'result'?")
        print(f"   - Keys en result: {list(result.keys())}")
        print(f"   - Tipo de result['tweets']: {type(result.get('tweets'))}")
        print(f"   - Cantidad de tweets: {len(tweets_to_classify)}")
        
        if not tweets_to_classify:
            print("⚠️ No hay tweets para clasificar")
            return
        
        print(f"\n🔍 DEBUG: ¿Qué contiene el primer tweet?")
        primer_tweet = tweets_to_classify[0]
        print(f"   - Tipo: {type(primer_tweet)}")
        print(f"   - Keys: {list(primer_tweet.keys())}")
        print(f"   - Tiene 'text': {'text' in primer_tweet}")
        if 'text' in primer_tweet:
            print(f"   - Valor de 'text': {repr(primer_tweet['text'][:50])}...")
        else:
            print(f"   - ⚠️ NO TIENE CAMPO 'text'")
            print(f"   - Contenido completo: {primer_tweet}")
        
        print(f"\n🔍 Clasificando {len(tweets_to_classify)} tweets...\n")
        
        # ═══════════════════════════════════════════════════════════════════
        # CLASIFICACIÓN DIRECTA (EXACTO como main.py línea ~1298-1340)
        # ═══════════════════════════════════════════════════════════════════
        start_time = time.time()
        classification_results = []
        stats = {
            "total_analyzed": len(tweets_to_classify),
            "risk_distribution": {"no": 0, "low": 0, "mid": 0, "high": 0},
            "label_counts": {},
            "errors": 0
        }
        
        for i, tweet_obj in enumerate(tweets_to_classify, 1):
            print(f"{'='*70}")
            print(f"🐦 Tweet {i}/{len(tweets_to_classify)}")
            print(f"{'='*70}")
            
            # Extraer campos (LÍNEA ~1298-1300)
            tweet_text = tweet_obj.get("text", "")
            tweet_id = tweet_obj.get("id")
            is_retweet = tweet_obj.get("is_retweet", False)
            
            print(f"📝 Datos extraídos:")
            print(f"   - tweet_text: {repr(tweet_text[:50])}..." if tweet_text else "   - tweet_text: EMPTY/NONE")
            print(f"   - tweet_id: {tweet_id}")
            print(f"   - is_retweet: {is_retweet}")
            
            # Filtro (LÍNEA ~1302-1303)
            if not tweet_text.strip():
                print(f"⚠️  SALTADO: tweet_text.strip() está vacío\n")
                continue
            
            print(f"✅ Pasa filtro: tweet_text tiene contenido\n")
            
            # Clasificar (LÍNEA ~1305-1308)
            print(f"🔧 Llamando a classify_risk_text_only...")
            try:
                classification_result = classify_risk_text_only(
                    tweet_text, 
                    tweet_id=str(tweet_id) if tweet_id else None
                )
                
                print(f"📦 Resultado:")
                print(f"   - tweet_id: {classification_result.get('tweet_id', 'N/A')}")
                print(f"   - text: {classification_result.get('text', 'NO TEXT')[:30] if classification_result.get('text') else '❌ NO TEXT'}")
                print(f"   - risk_level: {classification_result.get('risk_level', 'N/A')}")
                print(f"   - labels: {classification_result.get('labels', [])}")
                print(f"   - Tiene error_code: {'error_code' in classification_result}")
                
            except Exception as e:
                print(f"❌ EXCEPCIÓN: {type(e).__name__}: {str(e)}")
                import traceback
                traceback.print_exc()
                classification_result = {
                    "tweet_id": str(tweet_id) if tweet_id else None,
                    "text": tweet_text,
                    "error_code": "exception",
                    "error": str(e)
                }
            
            # Añadir metadata (LÍNEA ~1309-1315)
            classification_result["is_retweet"] = is_retweet
            
            for key in ['author_id', 'created_at', 'referenced_tweets']:
                if key in tweet_obj:
                    classification_result[key] = tweet_obj[key]
            
            classification_results.append(classification_result)
            
            # Actualizar stats (LÍNEA ~1317-1326)
            if "error_code" not in classification_result:
                level = classification_result.get("risk_level", "low")
                stats["risk_distribution"][level] += 1
                for label in classification_result.get("labels", []):
                    stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1
            else:
                stats["errors"] += 1
            
            print(f"\n✅ Tweet procesado\n")
            
            # Log cada 10 tweets (LÍNEA ~1328-1329)
            if i % 10 == 0 or i == len(tweets_to_classify):
                print(f"   ✅ Clasificados: {i}/{len(tweets_to_classify)}\n")
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # ═══════════════════════════════════════════════════════════════════
        # RESULTADOS FINALES
        # ═══════════════════════════════════════════════════════════════════
        print(f"\n{'='*70}")
        print(f"✅ CLASIFICACIÓN COMPLETADA")
        print(f"{'='*70}")
        print(f"   Tiempo: {execution_time:.2f}s")
        print(f"   Total clasificados: {len(classification_results)}")
        print(f"   Errores: {stats['errors']}")
        print(f"\n📊 Distribución de riesgos:")
        for level, count in stats["risk_distribution"].items():
            print(f"      {level}: {count}")
        
        print(f"\n🏷️  Labels:")
        for label, count in sorted(stats["label_counts"].items(), key=lambda x: x[1], reverse=True):
            print(f"      {label}: {count}")
        
        print(f"\n{'='*70}")
        print(f"🔍 DETALLE DE CADA RESULTADO:")
        print(f"{'='*70}\n")
        
        for i, result in enumerate(classification_results, 1):
            print(f"{i}. ID: {result.get('tweet_id', 'N/A')}")
            print(f"   Text: {result.get('text', '❌ NO TEXT')[:60]}...")
            print(f"   Risk: {result.get('risk_level', 'N/A')}")
            print(f"   Labels: {result.get('labels', [])}")
            if 'error_code' in result:
                print(f"   ❌ ERROR: {result.get('error')}")
            print()
        
        print(f"{'='*70}\n")
        
    except Exception as e:
        print(f"\n{'='*70}")
        print(f"❌ ERROR EN SIMULACIÓN")
        print(f"{'='*70}")
        print(f"Error: {str(e)}")
        print(f"{'='*70}\n")
        
        import traceback
        traceback.print_exc()


# ============================================================================
# EJECUTAR SIMULACIÓN
# ============================================================================

if __name__ == "__main__":
    simulate_process_tweets_search_background()
"""
Módulo para obtener tweets de usuarios de Twitter/X
Versión simplificada - sin filtros de año ni keywords
Con temporizadores de tiempo total y tiempo restante estimado
Con validación de rate limits desde el inicio
Con JSON de tiempo estimado al inicio
CON EXTRACCIÓN DE MEDIOS (imágenes/videos)
"""
import requests
import time
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from pathlib import Path
import sys
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_x_api_key


def format_time(seconds: float) -> str:
    """Formatea segundos en formato legible (HH:MM:SS)"""
    if seconds < 0:
        return "00:00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def get_author_id(username: str) -> dict:
    """Obtiene el author_id y avatar de un usuario por su username"""
    try:
        token = get_x_api_key()
        headers = {"Authorization": f"Bearer {token}"}
        clean_username = username.lstrip('@')
        
        url = f"https://api.twitter.com/2/users/by/username/{clean_username}"
        params = {"user.fields": "id,username,name,public_metrics,created_at,profile_image_url"}
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json().get('data', {})
            return {
                'success': True,
                'author_id': data.get('id'),
                'username': data.get('username'),
                'name': data.get('name'),
                'followers': data.get('public_metrics', {}).get('followers_count', 0),
                'account_created': data.get('created_at'),
                'profile_image_url': data.get('profile_image_url')
            }
        else:
            return {
                'success': False,
                'error': f'Error {response.status_code}: {response.text}'
            }
    except Exception as e:
        return {'success': False, 'error': str(e)}


def is_retweet(tweet: dict) -> bool:
    """Determina si un tweet es un retweet"""
    referenced = tweet.get('referenced_tweets', [])
    for ref in referenced:
        if ref.get('type') == 'retweeted':
            return True
    
    text = tweet.get('text', '')
    if text.startswith('RT @'):
        return True
    
    return False


def extract_media_info(tweet: Dict[str, Any], media_objects: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Extrae información de medios (imágenes/videos) de un tweet
    
    Args:
        tweet: Datos del tweet
        media_objects: Lista de objetos de media desde 'includes.media'
        
    Returns:
        Lista de dicts con info de medios
    """
    media_list = []
    
    # Obtener media_keys del tweet
    attachments = tweet.get('attachments', {})
    media_keys = attachments.get('media_keys', [])
    
    if not media_keys:
        return media_list
    
    for media_key in media_keys:
        # Encontrar el objeto de media correspondiente
        media_obj = next((m for m in media_objects if m.get('media_key') == media_key), None)
        
        if media_obj:
            media_type = media_obj.get('type')  # 'photo', 'video', 'animated_gif'
            
            media_info = {
                'media_key': media_key,
                'type': media_type,
                'url': None,
                'preview_url': None,
                'video_url': None,
                'alt_text': media_obj.get('alt_text'),
                'width': media_obj.get('width'),
                'height': media_obj.get('height'),
                'duration_ms': media_obj.get('duration_ms')
            }
            
            # Obtener URL según el tipo
            if media_type == 'photo':
                # Para fotos, simplemente usar la URL directa
                media_info['url'] = media_obj.get('url')
                
            elif media_type in ['video', 'animated_gif']:
                # Para videos/GIFs: preview (JPG) + URL de video si está disponible
                media_info['preview_url'] = media_obj.get('preview_image_url')
                
                # Intentar obtener la mejor variante de video
                variants = media_obj.get('variants', [])
                if variants:
                    # Filtrar solo variantes de video (mp4)
                    video_variants = [v for v in variants if v.get('content_type') == 'video/mp4']
                    
                    if video_variants:
                        # Ordenar por bitrate (mayor calidad primero)
                        video_variants.sort(key=lambda x: x.get('bit_rate', 0), reverse=True)
                        best_variant = video_variants[0]
                        media_info['video_url'] = best_variant.get('url')
                        media_info['bitrate'] = best_variant.get('bit_rate')
                
                # Para análisis de riesgos, usar el preview (más rápido)
                # pero guardar el video_url para referencia
                media_info['url'] = media_info['preview_url']
            
            media_list.append(media_info)
    
    return media_list


import time
import requests
from datetime import datetime
background_jobs = {}

def fetch_user_tweets_with_progress(
    username: str,
    max_tweets: Optional[int],
    job_id: str,
    db: Any
) -> Dict[str, Any]:
    """
    ✅ Versión OPTIMIZADA de fetch_user_tweets_with_progress
    Solo escribe en Firebase cuando alcanza rate limit (CRÍTICO)
    El resto del progreso solo actualiza memoria
    """
    from X.search_tweets import get_author_id, is_retweet, extract_media_info
    from config import get_x_api_key
    
    start_time = time.time()
    
    try:
        # Obtener author_id
        print(f"🔍 Buscando usuario {username}...")
        user_result = get_author_id(username)
        
        if not user_result['success']:
            return user_result
        
        author_id = user_result['author_id']
        print(f"✅ Usuario encontrado: {user_result['name']} (@{user_result['username']})")
        
        # ❌ NO ESCRIBIR: Solo actualizar memoria
        if job_id and job_id in background_jobs:
            background_jobs[job_id]['message'] = f"Usuario encontrado: @{user_result['username']}"
            background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
        
        # Configurar búsqueda
        token = get_x_api_key()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://api.twitter.com/2/users/{author_id}/tweets"
        
        all_tweets = []
        next_token = None
        page = 1
        
        print(f"\n📥 Obteniendo tweets CON MEDIOS...")
        
        while True:
            if max_tweets and len(all_tweets) >= max_tweets:
                print(f"   ✅ Alcanzado limite de {max_tweets} tweets")
                break
            
            page_start = time.time()
            
            print(f"\n📄 Página {page}...")
            
            # ❌ NO ESCRIBIR EN FIREBASE: Solo memoria (progreso normal)
            if job_id and job_id in background_jobs:
                tweets_so_far = len(all_tweets)
                progress = min(int((tweets_so_far / max_tweets) * 100), 99) if max_tweets else 0
                
                background_jobs[job_id]['progress'] = progress
                background_jobs[job_id]['current_page'] = page
                background_jobs[job_id]['total_tweets'] = tweets_so_far
                background_jobs[job_id]['message'] = f"Página {page} • {tweets_so_far} tweets"
                background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
                
                # 📊 Mostrar en consola con formato bonito
                print(f"   📊 Progreso: {progress}% | Tweets: {tweets_so_far} | Página: {page}")
            
            params = {
                "max_results": min(max_tweets, 100) if max_tweets else 100,
                "tweet.fields": "id,text,created_at,public_metrics,author_id,lang,conversation_id,referenced_tweets,attachments",
                "user.fields": "id,username,name,profile_image_url",
                "media.fields": "media_key,type,url,preview_image_url,alt_text,width,height,duration_ms,variants",
                "expansions": "author_id,referenced_tweets.id,attachments.media_keys"
            }
            
            if max_tweets:
                remaining = max_tweets - len(all_tweets)
                if remaining < 100 and remaining >= 5:
                    params["max_results"] = remaining
            
            if next_token:
                params["pagination_token"] = next_token
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            remaining_requests = response.headers.get('x-rate-limit-remaining', 'N/A')
            print(f"   🔢 Rate limit restante: {remaining_requests}")
            
            # ✅ CRÍTICO: RATE LIMIT ALCANZADO - ESCRIBIR EN FIREBASE Y ESPERAR
            if response.status_code == 429:
                reset_time = int(response.headers.get('x-rate-limit-reset', 0))
                wait_time = max(reset_time - int(time.time()), 0)
                
                print(f"\n{'='*70}")
                print(f"⏳ RATE LIMIT ALCANZADO - GUARDANDO ESTADO EN FIREBASE")
                print(f"{'='*70}")
                print(f"   Tweets obtenidos hasta ahora: {len(all_tweets)}")
                print(f"   Tiempo de espera: {format_time(wait_time)}")
                print(f"   Reanudación estimada: {datetime.fromtimestamp(reset_time).strftime('%H:%M:%S')}")
                print(f"{'='*70}")
                
                # 🔥 ESCRIBIR EN FIREBASE: Estado de rate limit (CRÍTICO)
                if job_id and job_id in background_jobs:
                    background_jobs[job_id]['status'] = 'waiting_rate_limit'
                    background_jobs[job_id]['wait_until'] = datetime.fromtimestamp(reset_time).isoformat()
                    background_jobs[job_id]['wait_seconds'] = wait_time
                    background_jobs[job_id]['message'] = f"⏳ Rate limit alcanzado. Reanudación automática en {format_time(wait_time)}"
                    background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
                    
                    if db:
                        try:
                            db.collection('background_jobs').document(job_id).update({
                                'status': 'waiting_rate_limit',
                                'wait_until': datetime.fromtimestamp(reset_time).isoformat(),
                                'wait_seconds': wait_time,
                                'message': f"Rate limit alcanzado. Esperando {format_time(wait_time)}...",
                                'updated_at': datetime.now(),
                                'tweets_fetched_so_far': len(all_tweets),
                                'total_tweets': len(all_tweets),
                                'progress': min(int((len(all_tweets) / max_tweets) * 100), 99) if max_tweets else 0
                            })
                            print(f"✅ [Firebase] Estado de rate limit guardado")
                        except Exception as e:
                            print(f"⚠️ [Firebase] Error guardando rate limit: {e}")
                
                # ⏰ ESPERAR el tiempo necesario
                print(f"\n⏳ Esperando {format_time(wait_time)} para reanudar...")
                
                # Esperar con actualizaciones cada 30 segundos
                for elapsed in range(0, wait_time, 30):
                    remaining = wait_time - elapsed
                    
                    # Solo actualizar memoria (rápido)
                    if job_id and job_id in background_jobs:
                        background_jobs[job_id]['message'] = f"⏳ Esperando rate limit: {format_time(remaining)} restantes"
                        background_jobs[job_id]['wait_seconds'] = remaining
                        background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
                    
                    print(f"   ⏳ Tiempo restante: {format_time(remaining)}")
                    time.sleep(min(30, remaining))
                
                # ✅ Reanudar búsqueda
                if job_id and job_id in background_jobs:
                    background_jobs[job_id]['status'] = 'searching'
                    background_jobs[job_id]['message'] = '✅ Rate limit reiniciado, reanudando búsqueda...'
                    background_jobs[job_id]['wait_until'] = None
                    background_jobs[job_id]['wait_seconds'] = None
                    background_jobs[job_id]['updated_at'] = datetime.now().isoformat()
                    
                    # Actualizar Firebase que reanudamos
                    if db:
                        try:
                            db.collection('background_jobs').document(job_id).update({
                                'status': 'searching',
                                'message': 'Rate limit reiniciado, reanudando...',
                                'wait_until': None,
                                'wait_seconds': None,
                                'updated_at': datetime.now()
                            })
                            print(f"✅ [Firebase] Status actualizado a 'searching'")
                        except Exception as e:
                            print(f"⚠️ [Firebase] Error actualizando reanudación: {e}")
                
                print(f"   ✅ Rate limit reiniciado, continuando búsqueda...")
                time.sleep(2)
                continue
            
            if response.status_code != 200:
                error_msg = f'Error {response.status_code}: {response.text}'
                print(f"❌ Error: {error_msg}")
                
                if page == 1:
                    return {'success': False, 'error': error_msg}
                else:
                    print(f"⚠️ Error en página {page}, usando {len(all_tweets)} tweets obtenidos")
                    break
            
            data = response.json()
            tweets = data.get('data', [])
            includes = data.get('includes', {})
            media_objects = includes.get('media', [])
            
            if not tweets:
                print("   ℹ️  No hay más tweets disponibles")
                break
            
            # Procesar tweets
            for tweet in tweets:
                tweet['is_retweet'] = is_retweet(tweet)
                media_info = extract_media_info(tweet, media_objects)
                tweet['media'] = media_info
            
            all_tweets.extend(tweets)
            print(f"   ✅ Obtenidos {len(tweets)} tweets (Total acumulado: {len(all_tweets)})")
            
            next_token = data.get('meta', {}).get('next_token')
            
            if not next_token:
                print("   ℹ️  No hay más páginas")
                break
            
            page += 1
            time.sleep(1)  # Rate limiting preventivo
        
        # Calcular estadísticas finales
        end_time = time.time()
        total_time = end_time - start_time
        
        retweets_count = sum(1 for t in all_tweets if t.get('is_retweet'))
        tweets_with_media = sum(1 for t in all_tweets if t.get('media'))
        total_media = sum(len(t.get('media', [])) for t in all_tweets)
        
        stats = {
            'total_tweets': len(all_tweets),
            'retweets': retweets_count,
            'original_tweets': len(all_tweets) - retweets_count,
            'tweets_with_media': tweets_with_media,
            'total_media_count': total_media
        }
        
        print(f"\n✅ Búsqueda completada:")
        print(f"   Total tweets: {len(all_tweets)}")
        print(f"   Páginas procesadas: {page}")
        print(f"   Tiempo total: {format_time(total_time)}")
        
        return {
            'success': True,
            'user': user_result,
            'tweets': all_tweets,
            'stats': stats,
            'pages_fetched': page,
            'fetched_at': datetime.now().isoformat(),
            'execution_time': format_time(total_time),
            'execution_time_seconds': round(total_time, 2)
        }
        
    except Exception as e:
        print(f"❌ Error en fetch_user_tweets_with_progress_optimized: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': f'Error: {str(e)}'}


def format_time(seconds: float) -> str:
    """Formatea segundos en formato legible (HH:MM:SS)"""
    if seconds < 0:
        return "00:00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def save_tweets_to_file(result: dict, filename: str = None):
    """
    Guarda tweets en archivo JSON
    
    Args:
        result: Resultado de fetch_user_tweets
        filename: Nombre del archivo (sin extension)
    """
    if not result['success']:
        print(f"No se pueden guardar: {result.get('error')}")
        return
    
    if filename is None:
        username = result['user']['username']
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"tweets_{username}_{timestamp}"
    
    if filename.endswith('.json'):
        filename = filename[:-5]
    
    filepath = f"{filename}.json"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\nGuardado: {filepath}")
    print(f"   Tweets: {result['stats']['total_tweets']}")
    print(f"   Tweets con medios: {result['stats'].get('tweets_with_media', 0)}")
    print(f"   Total medios: {result['stats'].get('total_media_count', 0)}")
    print(f"   Tamaño: {len(json.dumps(result)) / 1024:.2f} KB")
    if 'execution_time' in result:
        print(f"   Tiempo de obtención: {result['execution_time']}")
    
    return filepath


if __name__ == "__main__":
    print("=" * 70)
    print("SEARCH_TWEETS.PY - OBTENCIÓN DE TWEETS CON MEDIOS")
    print("Con validación de rate limits y temporizadores")
    print("=" * 70)
    
    result1 = fetch_user_tweets_with_progress(
        username="@TheDarkraimola",
        max_tweets=20
    )
    
    if result1['success']:
        print("\nExito")
        save_tweets_to_file(result1)
    else:
        print(f"\nError: {result1.get('error')}")
    
    print("\n" + "=" * 70)
    print("Pruebas completadas")
    print("=" * 70)
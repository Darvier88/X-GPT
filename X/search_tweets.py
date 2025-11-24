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


def fetch_user_tweets(username: str, max_tweets: Optional[int] = None) -> Dict[str, Any]:
    """
    Obtiene tweets de un usuario (versión simplificada con temporizadores)
    AHORA CON EXTRACCIÓN DE MEDIOS + AVATAR DEL USUARIO
    
    Args:
        username: Username del usuario (con o sin @)
        max_tweets: Límite máximo de tweets a obtener (None = todos los disponibles)
    
    Returns:
        Dict con resultado incluyendo avatar_url del usuario
    """
    # INICIO DEL TEMPORIZADOR
    start_time = time.time()
    
    try:
        # 1. Obtener author_id
        print(f"Buscando usuario {username}...")
        user_result = get_author_id(username)
        
        if not user_result['success']:
            return user_result
        
        author_id = user_result['author_id']
        print(f"Usuario encontrado: {user_result['name']} (@{user_result['username']})")
        print(f"   Seguidores: {user_result['followers']:,}")
        if user_result.get('account_created'):
            print(f"   Cuenta creada: {user_result['account_created']}")
        
        # OBTENER AVATAR DEL USUARIO
        avatar_url = user_result.get('profile_image_url')
        if avatar_url:
            print(f"   Avatar: {avatar_url}")
        
        print(f"\nObteniendo tweets CON MEDIOS...")
        if max_tweets:
            print(f"   Límite: {max_tweets} tweets")
        else:
            print(f"   Límite: Sin límite (todos los disponibles)")
        
        # 2. Obtener tweets
        token = get_x_api_key()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"https://api.twitter.com/2/users/{author_id}/tweets"
        
        all_tweets = []
        next_token = None
        page = 1
        
        # Variables para estimación de tiempo
        page_start_times = []
        estimated_total_time = None
        estimated_pages = None
        estimated_time_str = None
        
        # Estadísticas de medios
        total_media_count = 0
        tweets_with_media = 0
        
        # ESTIMACIÓN INICIAL DEL TIEMPO
        print(f"\nCalculando tiempo estimado...")
        estimation_start = time.time()
        
        # Hacer primera request para estimar (AHORA CON EXPANSIONES DE MEDIA + USUARIO)
        test_params = {
            "max_results": 100,
            "tweet.fields": "id,text,created_at,public_metrics,author_id,lang,conversation_id,referenced_tweets,attachments",
            "user.fields": "id,username,name,profile_image_url",
            "media.fields": "media_key,type,url,preview_image_url,alt_text,width,height,duration_ms,variants",
            "expansions": "author_id,referenced_tweets.id,attachments.media_keys"
        }
        
        test_response = requests.get(url, headers=headers, params=test_params, timeout=30)
        estimation_time = time.time() - estimation_start
        
        # VALIDAR RATE LIMITS DESDE EL INICIO
        rate_limit_remaining = int(test_response.headers.get('x-rate-limit-remaining', 0))
        rate_limit_reset = int(test_response.headers.get('x-rate-limit-reset', 0))
        rate_limit_total = int(test_response.headers.get('x-rate-limit-limit', 900))
        
        current_time = int(time.time())
        time_until_reset = max(0, rate_limit_reset - current_time)
        
        print(f"   Rate limit actual: {rate_limit_remaining}/{rate_limit_total}")
        
        # CASO 1: Rate limit agotado desde el inicio
        if rate_limit_remaining == 0:
            print(f"\n{'='*70}")
            print(f"RATE LIMIT AGOTADO")
            print(f"{'='*70}")
            print(f"   No hay requests disponibles en este momento")
            print(f"   El rate limit se reiniciará en: {format_time(time_until_reset)}")
            print(f"   Hora de reset: {datetime.fromtimestamp(rate_limit_reset).strftime('%H:%M:%S')}")
            print(f"\nOpciones:")
            print(f"   1. Esperar {format_time(time_until_reset)} para que se reinicie")
            print(f"   2. Intentar más tarde")
            print(f"   3. Usar otra API key si tienes disponible")
            print(f"{'='*70}")
            
            user_input = input(f"\nDeseas esperar {format_time(time_until_reset)} para continuar? (s/n): ").strip().lower()
            
            if user_input == 's':
                print(f"\nEsperando {format_time(time_until_reset)}...")
                print(f"   Se reanudará a las {datetime.fromtimestamp(rate_limit_reset).strftime('%H:%M:%S')}")
                
                for remaining in range(time_until_reset, 0, -1):
                    mins, secs = divmod(remaining, 60)
                    print(f"\r   Tiempo restante: {mins:02d}:{secs:02d}", end='', flush=True)
                    time.sleep(1)
                
                print(f"\n   Esperado completado. Reiniciando...")
                
                estimation_start = time.time()
                test_response = requests.get(url, headers=headers, params=test_params, timeout=30)
                estimation_time = time.time() - estimation_start
                
                rate_limit_remaining = int(test_response.headers.get('x-rate-limit-remaining', 0))
                rate_limit_reset = int(test_response.headers.get('x-rate-limit-reset', 0))
                
                if rate_limit_remaining == 0:
                    end_time = time.time()
                    total_time = end_time - start_time
                    return {
                        'success': False,
                        'error': 'Rate limit aún agotado después de esperar',
                        'execution_time': format_time(total_time)
                    }
            else:
                end_time = time.time()
                total_time = end_time - start_time
                return {
                    'success': False,
                    'error': 'Operación cancelada por el usuario - Rate limit agotado',
                    'rate_limit_info': {
                        'remaining': rate_limit_remaining,
                        'total': rate_limit_total,
                        'reset_time': datetime.fromtimestamp(rate_limit_reset).isoformat(),
                        'wait_time_seconds': time_until_reset
                    },
                    'execution_time': format_time(total_time)
                }
        
        # CASO 2: Rate limit muy bajo (menos de 10 requests)
        if rate_limit_remaining < 10 and rate_limit_remaining > 0:
            print(f"\nRate limit bajo ({rate_limit_remaining} requests disponibles)")
            print(f"   Reset en: {format_time(time_until_reset)}")
            if max_tweets and max_tweets > rate_limit_remaining * 100:
                print(f"   Se requerirán esperas para completar los {max_tweets} tweets solicitados")
        
        # Continuar con la estimación normal
        if test_response.status_code == 200:
            test_data = test_response.json()
            test_tweets = test_data.get('data', [])
            test_includes = test_data.get('includes', {})
            test_media = test_includes.get('media', [])
            
            if test_tweets:
                # PROCESAR MEDIOS EN TWEETS DE PRUEBA
                for tweet in test_tweets:
                    tweet['is_retweet'] = is_retweet(tweet)
                    media_info = extract_media_info(tweet, test_media)
                    tweet['media'] = media_info
                    
                    if media_info:
                        tweets_with_media += 1
                        total_media_count += len(media_info)
                
                tweets_per_page = len(test_tweets)
                
                if max_tweets:
                    pages_needed_total = (max_tweets + tweets_per_page - 1) // tweets_per_page
                    estimated_pages = pages_needed_total
                    
                    wait_time = 0
                    wait_cycles = 0
                    
                    if pages_needed_total > rate_limit_remaining:
                        pages_after_first_batch = pages_needed_total - rate_limit_remaining
                        
                        if rate_limit_remaining > 0:
                            wait_cycles = 1
                            wait_time = time_until_reset
                        
                        if pages_after_first_batch > 0:
                            additional_cycles = (pages_after_first_batch + rate_limit_total - 1) // rate_limit_total
                            wait_cycles += additional_cycles
                            wait_time += (additional_cycles * 900)
                else:
                    estimated_pages = rate_limit_remaining
                    wait_time = 0
                    wait_cycles = 0
                
                # CÁLCULO FINAL DEL TIEMPO ESTIMADO TOTAL
                request_time = estimation_time * estimated_pages
                pause_time = estimated_pages - 1
                estimated_total_time = request_time + pause_time + wait_time
                
                # Convertir a formato legible
                est_hours = int(estimated_total_time // 3600)
                est_minutes = int((estimated_total_time % 3600) // 60)
                est_seconds = int(estimated_total_time % 60)
                
                estimated_time_str = f"{est_hours:02d}:{est_minutes:02d}:{est_seconds:02d}"
                
                print(f"   Estimacion completada")
                print(f"   Tweets por pagina: ~{tweets_per_page}")
                if max_tweets:
                    print(f"   Meta: {max_tweets} tweets")
                print(f"   Rate limit: {rate_limit_remaining}/{rate_limit_total}")
                print(f"\n   TIEMPO ESTIMADO TOTAL: {estimated_time_str}")
                    
            elif not max_tweets:
                estimated_pages = None
                estimated_total_time = None
                print(f"   Sin límite establecido - no se puede estimar tiempo total")
                print(f"   Rate limit disponible: {rate_limit_remaining}/{rate_limit_total}")
            
            all_tweets.extend(test_tweets)
            next_token = test_data.get('meta', {}).get('next_token')
            page_start_times.append(estimation_time)
            
            print(f"   Primera pagina obtenida: {len(test_tweets)} tweets")
            print(f"   Tweets con medios: {tweets_with_media}")
            print(f"   Total medios: {total_media_count}")
            page += 1
            time.sleep(1)
        else:
            print(f"   No se pudo realizar estimacion inicial")
        
        # Imprimir JSON con total_tweets y tiempo_estimado al inicio
        if estimated_time_str:
            print(f"\n{'='*70}")
            print(f"RESUMEN EN JSON:")
            timing_results = {
                "total_tweets": max_tweets if max_tweets else "sin_limite",
                "tiempo_estimado": estimated_time_str
            }
            print(json.dumps(timing_results, ensure_ascii=False, indent=2))
            print(f"{'='*70}\n")
        
        print(f"\n{'─'*70}")
        
        # 3. Paginar
        while True:
            if max_tweets and len(all_tweets) >= max_tweets:
                print(f"   Alcanzado limite de {max_tweets} tweets")
                break
            
            page_start = time.time()
            
            print(f"\nObteniendo pagina {page}...")
            
            params = {
                "max_results": 100,
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
            print(f"   Rate limit restante: {remaining_requests}")
            
            # Manejar rate limit agotado EN MEDIO de la ejecución
            if response.status_code == 429:
                reset_time = int(response.headers.get('x-rate-limit-reset', 0))
                wait_time = max(reset_time - int(time.time()), 0)
                
                print(f"\n{'='*70}")
                print(f"RATE LIMIT ALCANZADO EN MEDIO DE LA EJECUCIÓN")
                print(f"{'='*70}")
                print(f"   Progreso actual: {len(all_tweets)} tweets obtenidos de {max_tweets if max_tweets else 'infinito'}")
                print(f"   Paginas completadas: {page - 1}")
                print(f"   Tiempo de espera necesario: {format_time(wait_time)}")
                print(f"   Se reanudará a las: {datetime.fromtimestamp(reset_time).strftime('%H:%M:%S')}")
                print(f"{'='*70}")
                
                if estimated_total_time:
                    new_estimated_total = (time.time() - start_time) + wait_time
                    if estimated_pages:
                        pages_remaining = estimated_pages - (page - 1)
                        new_estimated_total += pages_remaining * (sum(page_start_times) / len(page_start_times) if page_start_times else 1)
                    print(f"   Tiempo total estimado actualizado: {format_time(new_estimated_total)}")
                    print(f"   Tiempo transcurrido hasta ahora: {format_time(time.time() - start_time)}")
                    print(f"{'='*70}")
                
                user_input = input(f"\nDeseas esperar {format_time(wait_time)} para continuar? (s/n): ").strip().lower()
                
                if user_input != 's':
                    print(f"\nOperacion cancelada por el usuario")
                    print(f"   Tweets obtenidos antes de cancelar: {len(all_tweets)}")
                    
                    if len(all_tweets) > 0:
                        print(f"   Se guardarán los {len(all_tweets)} tweets obtenidos")
                        break
                    else:
                        end_time = time.time()
                        total_time = end_time - start_time
                        return {
                            'success': False,
                            'error': 'Operacion cancelada - Rate limit alcanzado en medio de ejecucion',
                            'partial_tweets': len(all_tweets),
                            'execution_time': format_time(total_time)
                        }
                
                print(f"\nEsperando {format_time(wait_time)} para que se reinicie el rate limit...")
                print(f"   Reanudacion programada: {datetime.fromtimestamp(reset_time).strftime('%H:%M:%S')}")
                
                for remaining in range(wait_time, 0, -1):
                    mins, secs = divmod(remaining, 60)
                    hours, mins = divmod(mins, 60)
                    
                    if hours > 0:
                        time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"
                    else:
                        time_str = f"{mins:02d}:{secs:02d}"
                    
                    print(f"\r   Tiempo restante: {time_str} | Tweets obtenidos: {len(all_tweets)}", end='', flush=True)
                    time.sleep(1)
                
                print(f"\n   Espera completada. Reanudando obtención de tweets...")
                print(f"   Continuando desde el tweet #{len(all_tweets) + 1}")
                print(f"{'─'*70}")
                
                time.sleep(2)
                continue
            
            if response.status_code != 200:
                error_msg = f'Error {response.status_code}: {response.text}'
                print(f"Error: {error_msg}")
                
                if page == 1:
                    return {
                        'success': False,
                        'error': error_msg
                    }
                else:
                    print(f"Error en pagina {page}, usando {len(all_tweets)} tweets obtenidos")
                    break
            
            data = response.json()
            tweets = data.get('data', [])
            includes = data.get('includes', {})
            media_objects = includes.get('media', [])
            
            if not tweets:
                print("   No hay mas tweets disponibles")
                break
            
            # PROCESAR MEDIOS PARA CADA TWEET
            page_media_count = 0
            page_tweets_with_media = 0
            
            for tweet in tweets:
                tweet['is_retweet'] = is_retweet(tweet)
                media_info = extract_media_info(tweet, media_objects)
                tweet['media'] = media_info
                
                if media_info:
                    page_tweets_with_media += 1
                    page_media_count += len(media_info)
                    tweets_with_media += 1
                    total_media_count += len(media_info)
            
            all_tweets.extend(tweets)
            
            page_end = time.time()
            page_duration = page_end - page_start
            page_start_times.append(page_duration)
            
            # CALCULAR TIEMPO ESTIMADO RESTANTE
            current_elapsed = time.time() - start_time
            
            if estimated_pages and estimated_pages > 0:
                pages_completed = page - 1
                progress_pages = pages_completed / estimated_pages
                
                if progress_pages > 0 and progress_pages <= 1:
                    estimated_total_real = current_elapsed / progress_pages
                    estimated_remaining_real = estimated_total_real - current_elapsed
                    
                    if estimated_total_time:
                        time_difference = estimated_total_real - estimated_total_time
                        percentage_diff = (time_difference / estimated_total_time * 100)
                        
                        if abs(percentage_diff) < 5:
                            status = "En tiempo"
                        elif percentage_diff < 0:
                            status = f"{abs(percentage_diff):.1f}% mas rapido"
                        else:
                            status = f"{percentage_diff:.1f}% mas lento"
                    else:
                        status = "Calculando..."
                    
                    print(f"   Obtenidos {len(tweets)} tweets (Total: {len(all_tweets)})")
                    print(f"   Medios en esta página: {page_media_count} | Total medios: {total_media_count}")
                    print(f"   Paginas: {pages_completed}/{estimated_pages} ({progress_pages*100:.1f}%)")
                    print(f"   Tiempo transcurrido: {format_time(current_elapsed)}")
                    print(f"   Tiempo restante (estimado): {format_time(estimated_remaining_real)}")
                    
                    if estimated_total_time:
                        print(f"   Estimacion inicial: {estimated_time_str} -> Proyeccion actual: {format_time(estimated_total_real)}")
                        print(f"   Estado: {status}")
                else:
                    print(f"   Obtenidos {len(tweets)} tweets (Total: {len(all_tweets)})")
                    print(f"   Medios en esta página: {page_media_count}")
                    print(f"   Paginas: {pages_completed}/{estimated_pages}")
            else:
                avg_page_time = sum(page_start_times) / len(page_start_times) if page_start_times else 0
                print(f"   Obtenidos {len(tweets)} tweets (Total: {len(all_tweets)})")
                print(f"   Medios en esta página: {page_media_count}")
                print(f"   Tiempo transcurrido: {format_time(current_elapsed)}")
                if avg_page_time > 0:
                    print(f"   Tiempo promedio por pagina: {avg_page_time:.2f}s")
            
            if max_tweets and len(all_tweets) > max_tweets:
                all_tweets = all_tweets[:max_tweets]
                print(f"   Truncado a {max_tweets} tweets")
                break
            
            next_token = data.get('meta', {}).get('next_token')
            
            if not next_token:
                print("   No hay mas paginas")
                break
            
            page += 1
            time.sleep(1)
        
        # FIN DEL TEMPORIZADOR
        end_time = time.time()
        total_time = end_time - start_time
        
        # 4. Calcular estadísticas
        retweet_count = sum(1 for t in all_tweets if t.get('is_retweet', False))
        original_count = len(all_tweets) - retweet_count
        
        if all_tweets:
            dates = [datetime.fromisoformat(t['created_at'].replace('Z', '+00:00')) 
                    for t in all_tweets if 'created_at' in t]
            if dates:
                oldest = min(dates)
                newest = max(dates)
                date_range = {
                    'start': oldest.isoformat(),
                    'end': newest.isoformat()
                }
            else:
                date_range = None
        else:
            date_range = None
        
        languages = {}
        for tweet in all_tweets:
            lang = tweet.get('lang', 'unknown')
            languages[lang] = languages.get(lang, 0) + 1
        
        # Estadísticas de medios
        media_types = {}
        video_stats = {"with_video_url": 0, "only_preview": 0}
        
        for tweet in all_tweets:
            for media in tweet.get('media', []):
                media_type = media.get('type', 'unknown')
                media_types[media_type] = media_types.get(media_type, 0) + 1
                
                # Contar videos con URL real vs solo preview
                if media_type in ['video', 'animated_gif']:
                    if media.get('video_url'):
                        video_stats['with_video_url'] += 1
                    else:
                        video_stats['only_preview'] += 1
        
        print(f"\n{'='*70}")
        print(f"ESTADÍSTICAS FINALES")
        print(f"{'='*70}")
        print(f"   Total tweets: {len(all_tweets)}")
        print(f"   Retweets: {retweet_count}")
        print(f"   Originales: {original_count}")
        print(f"   Tweets con medios: {tweets_with_media} ({tweets_with_media/len(all_tweets)*100:.1f}%)")
        print(f"   Total medios extraídos: {total_media_count}")
        if media_types:
            print(f"   Tipos de medios: {dict(sorted(media_types.items(), key=lambda x: x[1], reverse=True))}")
            if video_stats['with_video_url'] > 0 or video_stats['only_preview'] > 0:
                print(f"   Videos/GIFs con URL: {video_stats['with_video_url']}")
                print(f"   Videos/GIFs solo preview: {video_stats['only_preview']}")
        if date_range:
            print(f"   Rango: {date_range['start']} a {date_range['end']}")
        print(f"   Idiomas: {dict(sorted(languages.items(), key=lambda x: x[1], reverse=True))}")
        print(f"   Paginas obtenidas: {page}")
        print(f"\n   TIEMPO TOTAL DE EJECUCIÓN: {format_time(total_time)}")
        
        if estimated_total_time:
            time_difference = total_time - estimated_total_time
            percentage_diff = (time_difference / estimated_total_time * 100)
            
            print(f"\n   COMPARACIÓN DE TIEMPO:")
            print(f"   Estimado: {estimated_time_str}")
            print(f"   Real: {format_time(total_time)}")
            print(f"   Diferencia: {format_time(abs(time_difference))} ({abs(percentage_diff):.1f}%)")
            
            if abs(percentage_diff) < 5:
                print(f"   Precision: Excelente")
            elif abs(percentage_diff) < 15:
                print(f"   Precision: Buena")
            else:
                if time_difference < 0:
                    print(f"   Completado {abs(percentage_diff):.1f}% mas rapido")
                else:
                    print(f"   Tardó {percentage_diff:.1f}% mas tiempo")
        
        print(f"   Velocidad: {len(all_tweets)/total_time:.2f} tweets/segundo")
        print(f"{'='*70}")
        
        # 5. Retornar resultado
        return {
            'success': True,
            'user': {
                **user_result
            },
            'tweets': all_tweets,
            'stats': {
                'total_tweets': len(all_tweets),
                'retweet_count': retweet_count,
                'original_count': original_count,
                'tweets_with_media': tweets_with_media,
                'total_media_count': total_media_count,
                'media_types': media_types,
                'date_range': date_range,
                'languages': languages
            },
            'pages_fetched': page,
            'fetched_at': datetime.now().isoformat(),
            'execution_time': format_time(total_time),
            'execution_time_seconds': round(total_time, 2)
        }
        
    except Exception as e:
        end_time = time.time()
        total_time = end_time - start_time
        print(f"\nTiempo antes del error: {format_time(total_time)}")
        
        return {
            'success': False,
            'error': f'Error: {str(e)}',
            'execution_time': format_time(total_time)
        }


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
    
    result1 = fetch_user_tweets(
        username="@TheDarkraimola",
        max_tweets=100
    )
    
    if result1['success']:
        print("\nExito")
        save_tweets_to_file(result1)
    else:
        print(f"\nError: {result1.get('error')}")
    
    print("\n" + "=" * 70)
    print("Pruebas completadas")
    print("=" * 70)
import requests
import json
import os
from datetime import datetime, timedelta
from config import get_x_api_key

# Variable global para tracking del último request
_last_request_time = None

def get_tweets_by_query(query):
    """Obtiene tweets por query con rate limiting y campos expandidos, guardado automático"""
    global _last_request_time
    
    try:
        max_results = 10
        
        if _last_request_time is not None:
            time_since_last = datetime.now() - _last_request_time
            wait_time = timedelta(minutes=15)
            
            if time_since_last < wait_time:
                remaining_time = wait_time - time_since_last
                remaining_minutes = int(remaining_time.total_seconds() / 60)
                remaining_seconds = int(remaining_time.total_seconds() % 60)
                
                return {
                    'success': False,
                    'error': f'Rate limit: espera {remaining_minutes}m {remaining_seconds}s más',
                    'remaining_minutes': remaining_minutes,
                    'remaining_seconds': remaining_seconds,
                    'total_wait_seconds': int(remaining_time.total_seconds())
                }
        
        token = get_x_api_key()
        
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "query": query,
            "max_results": max_results,
            "tweet.fields": "id,text,author_id,created_at,public_metrics,context_annotations,entities,lang,possibly_sensitive,reply_settings,source",
            "user.fields": "id,name,username,verified,public_metrics,description,location,created_at",
            "expansions": "author_id"
        }
        
        response = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers=headers,
            params=params,
            timeout=10
        )
        
        # Actualizar el tiempo del último request exitoso
        _last_request_time = datetime.now()
        
        if response.status_code == 200:
            data = response.json()
            tweets = data.get('data', [])
            users = {user['id']: user for user in data.get('includes', {}).get('users', [])}
            
            # Procesar tweets con información expandida
            processed_tweets = []
            texts = []
            
            for tweet in tweets:
                author_info = users.get(tweet['author_id'], {})
                
                processed_tweet = {
                    'id': tweet['id'],
                    'text': tweet['text'],
                    'author_verified': author_info.get('verified', False),
                    'created_at': tweet['created_at'],
                    'retweet_count': tweet.get('public_metrics', {}).get('retweet_count', 0),
                    'like_count': tweet.get('public_metrics', {}).get('like_count', 0),
                    'reply_count': tweet.get('public_metrics', {}).get('reply_count', 0),
                    'language': tweet.get('lang', 'unknown'),
                    'source': tweet.get('source', 'unknown'),
                }
                
                processed_tweets.append(processed_tweet)
                texts.append(tweet['text'])
            
            result = {
                'success': True,
                'texts': texts,
                'tweets_detailed': processed_tweets,
                'count': len(texts),
                'query': query,
                'api_metadata': {
                    'total_tweets': len(tweets),
                    'languages': list(set([t.get('lang', 'unknown') for t in tweets])),
                    'date_range': {
                        'oldest': min([t['created_at'] for t in tweets]) if tweets else None,
                        'newest': max([t['created_at'] for t in tweets]) if tweets else None
                    },
                    'engagement_summary': {
                        'total_likes': sum([t.get('public_metrics', {}).get('like_count', 0) for t in tweets]),
                        'total_retweets': sum([t.get('public_metrics', {}).get('retweet_count', 0) for t in tweets]),
                        'total_replies': sum([t.get('public_metrics', {}).get('reply_count', 0) for t in tweets]),
                        'avg_likes': round(sum([t.get('public_metrics', {}).get('like_count', 0) for t in tweets]) / len(tweets), 1) if tweets else 0
                    },
                    'verified_authors': len([t for t in processed_tweets if t['author_verified']])
                }
            }
            
            # Guardado automático siempre
            if texts:
                save_result = save_tweets_to_json(result)
                result['file_saved'] = save_result
            
            return result
        
        elif response.status_code == 401:
            return {'success': False, 'error': 'X API token inválido'}
        elif response.status_code == 429:
            return {'success': False, 'error': 'Rate limit excedido'}
        else:
            return {'success': False, 'error': f'Error X API: {response.status_code}'}
            
    except requests.exceptions.Timeout:
        return {'success': False, 'error': 'Timeout conectando a X'}
    except Exception as e:
        return {'success': False, 'error': f'Error X: {str(e)}'}

def save_tweets_to_json(tweets_data):
    """Guarda automáticamente los tweets con toda la información expandida"""
    try:
        if not tweets_data.get('success', False):
            return {'success': False, 'error': 'No hay datos válidos para guardar'}
        
        # Crear nombre del archivo automáticamente
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        query_safe = tweets_data['query'].replace(' ', '_').replace('#', '').replace('@', '').replace('/', '_')
        filename = f"tweets_{query_safe}_{timestamp}.json"
        
        # Crear directorio si no existe
        os.makedirs('tweets_data', exist_ok=True)
        filepath = os.path.join('tweets_data', filename)
        
        # Incluir toda la información expandida
        data_to_save = {
            'metadata': {
                'query': tweets_data['query'],
                'count': tweets_data['count'],
                'timestamp': datetime.now().isoformat(),
                'retrieved_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'api_metadata': tweets_data.get('api_metadata', {})
            },
            'tweets': tweets_data['tweets_detailed']
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        
        return {
            'success': True,
            'filename': filename,
            'filepath': filepath,
            'tweets_saved': len(tweets_data['tweets_detailed'])
        }
        
    except Exception as e:
        return {'success': False, 'error': f'Error guardando JSON: {str(e)}'}

def load_tweets_from_json(filepath):
    """Carga tweets desde un archivo JSON"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return {
            'success': True,
            'texts': [tweet['text'] for tweet in data['tweets']],
            'tweets_detailed': data['tweets'],
            'count': len(data['tweets']),
            'query': data['metadata']['query'],
            'api_metadata': data['metadata'].get('api_metadata', {}),
            'metadata': data['metadata']
        }
        
    except Exception as e:
        return {'success': False, 'error': f'Error cargando JSON: {str(e)}'}
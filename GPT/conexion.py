from openai import OpenAI
import json
import os
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import get_openai_api_key

def generate_summary(tweets_data):
    """Genera resumen usando ChatGPT y lo guarda automáticamente"""
    try:
        client = OpenAI(api_key=get_openai_api_key())
        
        if not tweets_data['success']:
            return {'success': False, 'error': tweets_data['error']}
        
        texts = tweets_data['texts']
        query = tweets_data['query']
        
        prompt = f"""
Analyze these {len(texts)} tweets about "{query}" and create a 5-10 line summary:
Tweets:
{chr(10).join([f"- {text}" for text in texts[:5]])}
Provide a clear and objective summary of the main topics mentioned. In Spanish.
"""
        
        response = client.chat.completions.create(
            model="gpt-4.1",  
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.7
        )
        
        summary = response.choices[0].message.content.strip()
        
        result = {
            'success': True,
            'summary': summary,
            'tweets_analyzed': len(texts),
            'query': query,
            'generated_at': datetime.now().isoformat(),
            'model_used': 'gpt-4'
        }
        

        save_result = save_summary_to_json(result, tweets_data)
        result['summary_file_saved'] = save_result
        
        return result
        
    except Exception as e:
        return {'success': False, 'error': f'Error OpenAI: {str(e)}'}

def save_summary_to_json(summary_data, tweets_data):
    """Guarda automáticamente el resumen con metadata completa"""
    try:

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        query_safe = summary_data['query'].replace(' ', '_').replace('#', '').replace('@', '').replace('/', '_')
        filename = f"summary_{query_safe}_{timestamp}.json"

        os.makedirs('summaries_data', exist_ok=True)
        filepath = os.path.join('summaries_data', filename)
        
        data_to_save = {
            'summary_metadata': {
                'query': summary_data['query'],
                'tweets_analyzed': summary_data['tweets_analyzed'],
                'generated_at': summary_data['generated_at'],
                'model_used': summary_data['model_used'],
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            'summary': {
                'content': summary_data['summary'],
                'language': 'spanish',
                'type': '5-10 line summary'
            },
            'source_data': {
                'x_api_metadata': tweets_data.get('api_metadata', {}),
                'tweets_count': tweets_data.get('count', 0),
                'original_query': tweets_data.get('query', ''),
                'tweets_file': tweets_data.get('file_saved', {}).get('filename', 'N/A') if 'file_saved' in tweets_data else 'N/A'
            },
            'sample_tweets': [
                text[:100] + '...' if len(text) > 100 else text 
                for text in tweets_data.get('texts', [])[:3]
            ]
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        
        return {
            'success': True,
            'filename': filename,
            'filepath': filepath,
            'summary_saved': True
        }
        
    except Exception as e:
        return {'success': False, 'error': f'Error guardando resumen JSON: {str(e)}'}

def load_summary_from_json(filepath):
    """Carga un resumen desde archivo JSON"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return {
            'success': True,
            'summary': data['summary']['content'],
            'query': data['summary_metadata']['query'],
            'tweets_analyzed': data['summary_metadata']['tweets_analyzed'],
            'generated_at': data['summary_metadata']['generated_at'],
            'model_used': data['summary_metadata']['model_used'],
            'metadata': data
        }
        
    except Exception as e:
        return {'success': False, 'error': f'Error cargando resumen JSON: {str(e)}'}
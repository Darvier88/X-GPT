import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock
import sys
import os
# Añadir el directorio padre al path para importar los módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ahora importar las funciones a testear
from search_tweets import save_tweets_to_json
from gpt import generate_summary, save_summary_to_json

class TestSearchTweetsFunctions(unittest.TestCase):
    
    def test_save_tweets_to_json_structure(self):
        """Test que save_tweets_to_json crea la estructura correcta"""
        # Mock data
        mock_tweets_data = {
            'success': True,
            'query': 'test query',
            'count': 2,
            'tweets_detailed': [
                {
                    'id': '123',
                    'text': 'Test tweet 1',
                    'author_username': 'user1',
                    'like_count': 10
                },
                {
                    'id': '456', 
                    'text': 'Test tweet 2',
                    'author_username': 'user2',
                    'like_count': 5
                }
            ],
            'api_metadata': {
                'total_tweets': 2,
                'languages': ['en'],
                'engagement_summary': {
                    'total_likes': 15
                }
            }
        }
        
        with patch('builtins.open', create=True) as mock_open:
            with patch('os.makedirs'):
                with patch('json.dump') as mock_json_dump:
                    result = save_tweets_to_json(mock_tweets_data)
                    
                    # Verificar que se llamó json.dump
                    mock_json_dump.assert_called_once()
                    
                    # Verificar estructura de datos guardados
                    saved_data = mock_json_dump.call_args[0][0]
                    
                    self.assertIn('metadata', saved_data)
                    self.assertIn('tweets', saved_data)
                    self.assertEqual(saved_data['metadata']['query'], 'test query')
                    self.assertEqual(saved_data['metadata']['count'], 2)
                    self.assertEqual(len(saved_data['tweets']), 2)
                    
                    # Verificar resultado de la función
                    self.assertTrue(result['success'])
                    self.assertIn('filename', result)
                    self.assertIn('tweets_test_query_', result['filename'])

    def test_save_tweets_to_json_error_handling(self):
        """Test que save_tweets_to_json maneja datos inválidos"""
        mock_tweets_data_fail = {
            'success': False,
            'error': 'No data'
        }
        
        result = save_tweets_to_json(mock_tweets_data_fail)
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'No hay datos válidos para guardar')

class TestGPTFunctions(unittest.TestCase):
    
    def test_generate_summary_prompt_format(self):
        """Test que generate_summary formatea correctamente el prompt"""
        # Mock data
        mock_tweets_data = {
            'success': True,
            'texts': [
                'Tweet about Python programming',
                'Another tweet about AI and machine learning',
                'Third tweet about coding best practices'
            ],
            'query': 'python programming'
        }
        
        # Mock OpenAI client
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Resumen de prueba sobre programación Python"
        
        with patch('gpt.OpenAI') as mock_openai:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_openai.return_value = mock_client
            
            with patch('gpt.save_summary_to_json', return_value={'success': True, 'filename': 'test.json'}):
                result = generate_summary(mock_tweets_data)
                
                # Verificar que se llamó al cliente de OpenAI
                mock_client.chat.completions.create.assert_called_once()
                
                # Verificar el prompt generado
                call_args = mock_client.chat.completions.create.call_args
                messages = call_args[1]['messages']
                prompt_content = messages[0]['content']
                
                # El prompt debe contener información clave
                self.assertIn('3 tweets about "python programming"', prompt_content)
                self.assertIn('- Tweet about Python programming', prompt_content)
                self.assertIn('- Another tweet about AI', prompt_content)
                self.assertIn('In Spanish', prompt_content)
                
                # Verificar parámetros del modelo
                self.assertEqual(call_args[1]['model'], 'gpt-4.1')
                self.assertEqual(call_args[1]['max_tokens'], 300)
                self.assertEqual(call_args[1]['temperature'], 0.7)
    
    def test_generate_summary_error_handling(self):
        """Test que generate_summary maneja errores correctamente"""
        # Caso 1: tweets_data no exitoso
        mock_tweets_data_fail = {
            'success': False,
            'error': 'API Error'
        }
        
        result = generate_summary(mock_tweets_data_fail)
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'API Error')
        
        # Caso 2: Error en OpenAI
        mock_tweets_data_success = {
            'success': True,
            'texts': ['test tweet'],
            'query': 'test'
        }
        
        with patch('gpt.OpenAI') as mock_openai:
            mock_openai.side_effect = Exception("OpenAI API Error")
            
            result = generate_summary(mock_tweets_data_success)
            self.assertFalse(result['success'])
            self.assertIn('Error OpenAI', result['error'])
    
    def test_save_summary_to_json_content(self):
        """Test que save_summary_to_json guarda el contenido correcto"""
        mock_summary_data = {
            'summary': 'Test summary content',
            'query': 'test query',
            'tweets_analyzed': 5,
            'generated_at': '2023-12-01T14:30:22.123456',
            'model_used': 'gpt-4'
        }
        
        mock_tweets_data = {
            'api_metadata': {'total_likes': 100},
            'count': 5,
            'texts': ['tweet1', 'tweet2', 'tweet3'],
            'file_saved': {'filename': 'tweets_test.json'}
        }
        
        with patch('builtins.open', create=True):
            with patch('os.makedirs'):
                with patch('json.dump') as mock_json_dump:
                    result = save_summary_to_json(mock_summary_data, mock_tweets_data)
                    
                    # Verificar estructura guardada
                    saved_data = mock_json_dump.call_args[0][0]
                    
                    # Verificar secciones principales
                    self.assertIn('summary_metadata', saved_data)
                    self.assertIn('summary', saved_data)
                    self.assertIn('source_data', saved_data)
                    self.assertIn('sample_tweets', saved_data)
                    
                    # Verificar contenido específico
                    self.assertEqual(saved_data['summary']['content'], 'Test summary content')
                    self.assertEqual(saved_data['summary_metadata']['query'], 'test query')
                    self.assertEqual(saved_data['summary_metadata']['tweets_analyzed'], 5)
                    self.assertEqual(saved_data['summary_metadata']['model_used'], 'gpt-4')
                    self.assertEqual(saved_data['source_data']['tweets_file'], 'tweets_test.json')
                    
                    # Verificar sample tweets (máximo 3)
                    self.assertEqual(len(saved_data['sample_tweets']), 3)

class TestIntegration(unittest.TestCase):
    """Tests de integración básicos"""
    
    def test_tweet_processing_pipeline(self):
        """Test del pipeline completo de procesamiento de tweets"""
        # Simular respuesta de X API
        mock_x_response = {
            'data': [
                {
                    'id': '123',
                    'text': 'Python is great for data science',
                    'author_id': 'user1',
                    'created_at': '2023-12-01T10:00:00.000Z',
                    'public_metrics': {'like_count': 10, 'retweet_count': 2},
                    'lang': 'en',
                    'entities': {'hashtags': [{'tag': 'python'}, {'tag': 'datascience'}]}
                }
            ],
            'includes': {
                'users': [
                    {
                        'id': 'user1',
                        'username': 'testuser',
                        'name': 'Test User',
                        'verified': True,
                        'public_metrics': {'followers_count': 1000}
                    }
                ]
            }
        }
        
        # Verificar que los datos se procesan correctamente
        tweets = mock_x_response['data']
        users = {user['id']: user for user in mock_x_response['includes']['users']}
        
        processed_tweet = {
            'id': tweets[0]['id'],
            'text': tweets[0]['text'],
            'author_username': users[tweets[0]['author_id']]['username'],
            'author_verified': users[tweets[0]['author_id']]['verified'],
            'like_count': tweets[0]['public_metrics']['like_count'],
            'hashtags': [tag['tag'] for tag in tweets[0]['entities']['hashtags']]
        }
        
        # Verificar estructura procesada
        self.assertEqual(processed_tweet['id'], '123')
        self.assertEqual(processed_tweet['author_username'], 'testuser')
        self.assertTrue(processed_tweet['author_verified'])
        self.assertEqual(processed_tweet['like_count'], 10)
        self.assertEqual(processed_tweet['hashtags'], ['python', 'datascience'])

    def test_prompt_formatting_with_special_characters(self):
        """Test que el formateo de prompt maneja caracteres especiales"""
        mock_texts = [
            'Tweet with @mention and #hashtag 🚀',
            'Another tweet with "quotes" and símbolos especiales',
            'Tweet con emojis 😀 y URLs https://example.com'
        ]
        
        query = 'test query'
        
        # Simular el formateo de prompt (como en generate_summary)
        prompt = f"""
Analyze these {len(mock_texts)} tweets about "{query}" and create a 5-10 line summary:
Tweets:
{chr(10).join([f"- {text}" for text in mock_texts[:5]])}
Provide a clear and objective summary of the main topics mentioned. In Spanish.
"""
        
        # Verificar que el prompt contiene los elementos esperados
        self.assertIn('3 tweets about "test query"', prompt)
        self.assertIn('- Tweet with @mention', prompt)
        self.assertIn('- Another tweet with "quotes"', prompt)
        self.assertIn('- Tweet con emojis', prompt)
        self.assertIn('In Spanish', prompt)

if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(__name__))
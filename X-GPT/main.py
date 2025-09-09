from search_tweets import get_tweets_by_query
from gpt import generate_summary
import sys

def main():
    """CLI donde el usuario ingresa el query"""
    
    print("X + ChatGPT Integration")
    print("=" * 40)
    
    # Verificar configuración
    try:
        from config import get_x_api_key, get_openai_api_key
        x_key = get_x_api_key()
        openai_key = get_openai_api_key()
        
        if not x_key or not openai_key:
            raise ValueError("API keys no configuradas")
            
        print("Configuración OK")
    except Exception as e:
        print(f"Error de configuración: {e}")
        print("\nPara configurar:")
        print("1. Crea un archivo .env en la raíz del proyecto")
        print("2. Añade las siguientes líneas:")
        print("   X_API_KEY=tu_bearer_token_de_x")
        print("   OPENAI_API_KEY=tu_api_key_de_openai")
        print("3. Reinicia la aplicación")
        return
    
    # Loop principal
    while True:
        print("\n" + "-" * 40)
        
        # El usuario ingresa su query aquí
        query = input("¿Qué quieres buscar en X? (o 'quit' para salir): ").strip()
        
        if query.lower() in ['quit', 'exit', 'salir', 'q']:
            print("Hasta luego!")
            break
        
        if not query:
            print("Por favor ingresa una consulta válida")
            continue
        
        # Procesar la búsqueda del usuario
        print(f"\nBuscando: '{query}'...")
        
        # 1. Obtener tweets
        tweets_result = get_tweets_by_query(query)
        
        if not tweets_result['success']:
            print(tweets_result)
            error_msg = tweets_result['error']
            print(f"Error: {error_msg}")
            
            # Sugerencias basadas en el tipo de error
            if 'Rate limit' in error_msg and 'remaining_minutes' in tweets_result:
                minutes = tweets_result['remaining_minutes']
                seconds = tweets_result['remaining_seconds']
                total_seconds = tweets_result['total_wait_seconds']
                
                if total_seconds > 60:
                    print(f"Sugerencia: Debes esperar {minutes} minutos y {seconds} segundos antes de hacer otra consulta")
                else:
                    print(f"Sugerencia: Debes esperar {total_seconds} segundos antes de hacer otra consulta")

            elif 'token inválido' in error_msg:
                print("Sugerencia: Verifica tu X API token en el archivo .env")
            elif 'Timeout' in error_msg:
                print("Sugerencia: Verifica tu conexión a internet")
            else:
                print("Sugerencia: Intenta con otra búsqueda o verifica tu configuración")
            continue
            
        if tweets_result['count'] == 0:
            print(f"No se encontraron tweets recientes para '{query}'")
            print("Intenta con:")
            print("   - Términos más generales")
            print("   - Hashtags populares (#ejemplo)")
            print("   - Palabras clave en inglés")
            continue
        
        print(f"Encontrados {tweets_result['count']} tweets")
        
        # Mostrar información del archivo guardado
        if 'file_saved' in tweets_result and tweets_result['file_saved']['success']:
            print(f"Guardado automáticamente en: {tweets_result['file_saved']['filename']}")
        
        # 2. Generar resumen
        print("Generando resumen con ChatGPT...")
        
        summary_result = generate_summary(tweets_result)
        
        if not summary_result['success']:
            error_msg = summary_result['error']
            print(f"Error generando resumen: {error_msg}")
            
            # Sugerencias para errores de OpenAI
            if 'API key' in error_msg or 'Unauthorized' in error_msg:
                print("Sugerencia: Verifica tu OpenAI API key en el archivo .env")
            elif 'quota' in error_msg.lower() or 'billing' in error_msg.lower():
                print("Sugerencia: Verifica tu saldo/créditos en tu cuenta de OpenAI")
            else:
                print("Sugerencia: Intenta nuevamente en unos momentos")
            continue
        
        # 3. Mostrar resultado exitoso con campos clave de X
        print(f"\nRESUMEN DE '{query.upper()}'")
        print("=" * 60)
        print(summary_result['summary'])
        print("=" * 60)

        print("ARCHIVOS GENERADOS:")
        if 'file_saved' in tweets_result and tweets_result['file_saved']['success']:
            print(f"   Datos de tweets: {tweets_result['file_saved']['filename']}")

        if 'summary_file_saved' in summary_result and summary_result['summary_file_saved']['success']:
            print(f"   Resumen generado: {summary_result['summary_file_saved']['filename']}")

        # Mostrar campos clave de X detalladamente
        metadata = tweets_result.get('api_metadata', {})
        engagement = metadata.get('engagement_summary', {})
        
        print(f"CAMPOS CLAVE DE X:")
        print(f"   Tweets analizados: {summary_result['tweets_analyzed']}")
        print(f"   Rango temporal: {metadata.get('date_range', {}).get('oldest', 'N/A')[:10] if metadata.get('date_range', {}).get('oldest') else 'N/A'} - {metadata.get('date_range', {}).get('newest', 'N/A')[:10] if metadata.get('date_range', {}).get('newest') else 'N/A'}")
        print(f"   Idiomas detectados: {', '.join(metadata.get('languages', []))}")
        print(f"   Total interacciones: {engagement.get('total_likes', 0)} likes, {engagement.get('total_retweets', 0)} retweets")
        print(f"   Total respuestas: {engagement.get('total_replies', 0)}")
        print(f"   Promedio likes/tweet: {engagement.get('avg_likes', 0)}")
        print(f"   Autores verificados: {metadata.get('verified_authors', 0)}")
        print(f"   Consulta original: '{summary_result['query']}'")
        print(f"   Procesado con: OpenAI GPT-4")
        print(f"   Fuente: X API v2 (búsqueda reciente)")
        print(f"   Archivo JSON: {tweets_result['file_saved']['filename']}")
        
        print(f"\nResumen completado exitosamente")

def handle_keyboard_interrupt():
    """Maneja Ctrl+C de forma elegante"""
    print("\n\nAplicación interrumpida por el usuario. Hasta luego!")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        handle_keyboard_interrupt()
    except Exception as e:
        print(f"\nError inesperado: {e}")
        print("Contacta al administrador si el problema persiste")
        sys.exit(1)
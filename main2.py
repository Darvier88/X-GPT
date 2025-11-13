"""
Twitter Manager - Aplicación de Consola Completa
Flujo: Login OAuth 2.0 → Buscar/Cargar Tweets → Revisar → Eliminar
Integra funciones de X-login.py, search_tweets.py y deleate_tweets_rts.py
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import sys
import glob
from typing import Optional, Dict, Any

# Importar funciones de los módulos existentes
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Importar desde X-login.py
from X.X_login import (
    initiate_login_with_scope_testing,  # Nueva función que incluye prueba de scopes
    save_test_results,                  # Nueva función para guardar resultados
    test_users_read,                    # Función de prueba específica
    test_tweet_read,                    # Función de prueba específica
    test_tweet_write                    # Función de prueba específica
)

# Importar desde search_tweets.py
from X.search_tweets import (
    fetch_user_tweets,
    save_tweets_to_file,
    get_author_id
)

# Importar desde deleate_tweets_rts.py
from X.deleate_tweets_rts import (
    OAuth2Session,
    delete_single_tweet,
    delete_single_retweet,
    extract_retweet_source_id,
    delete_tweets_batch,
    authorize_user
)


# ==================== UTILIDADES ====================

def clear_screen():
    """Limpia la pantalla de la consola"""
    import os
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(title: str):
    """Imprime un encabezado formateado"""
    print("\n" + "=" * 70)
    print(title.center(70))
    print("=" * 70)


def print_section(title: str):
    """Imprime una sección formateada"""
    print(f"\n{title}")
    print("─" * 70)


def show_tweet_preview(tweet: dict, index: int):
    """Muestra un preview de un tweet"""
    tweet_id = tweet.get('id')
    text = tweet.get('text', '')[:100]
    created_at = tweet.get('created_at', '')
    is_rt = tweet.get('is_retweet', False)
    
    tipo = "🔄 RT" if is_rt else "📝 Tweet"
    
    print(f"\n[{index}] {tipo} - ID: {tweet_id}")
    print(f"    Fecha: {created_at[:10] if created_at else 'N/A'}")
    print(f"    Texto: {text}{'...' if len(tweet.get('text', '')) > 100 else ''}")
    
    metrics = tweet.get('public_metrics', {})
    if metrics:
        print(f"    ❤️  {metrics.get('like_count', 0)} | "
              f"🔄 {metrics.get('retweet_count', 0)} | "
              f"💬 {metrics.get('reply_count', 0)}")


def display_tweets_list(tweets: list, show_all: bool = False):
    """Muestra lista completa de tweets con índices"""
    originals = [t for t in tweets if not t.get('is_retweet', False)]
    retweets = [t for t in tweets if t.get('is_retweet', False)]
    
    print_section(f"TWEETS ORIGINALES ({len(originals)})")
    
    display_count = len(originals) if show_all else min(10, len(originals))
    
    for i, tweet in enumerate(originals[:display_count], 1):
        show_tweet_preview(tweet, i)
    
    if len(originals) > display_count:
        print(f"\n   ... y {len(originals) - display_count} tweets originales más")
    
    print_section(f"RETWEETS ({len(retweets)})")
    
    display_count_rt = len(retweets) if show_all else min(10, len(retweets))
    
    for i, rt in enumerate(retweets[:display_count_rt], 1):
        show_tweet_preview(rt, i)
    
    if len(retweets) > display_count_rt:
        print(f"\n   ... y {len(retweets) - display_count_rt} retweets más")


def load_tweets_from_json(filepath: str) -> dict:
    """Carga tweets desde un archivo JSON"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validar estructura del JSON
        if 'tweets' not in data:
            return {'success': False, 'error': 'El archivo JSON no tiene el formato correcto'}
        
        return {
            'success': True,
            'tweets': data['tweets'],
            'filepath': filepath,
            'user_id': data.get('user_id') or data.get('author_id')
        }
    
    except FileNotFoundError:
        return {'success': False, 'error': f'Archivo no encontrado: {filepath}'}
    except json.JSONDecodeError:
        return {'success': False, 'error': 'Error al leer el archivo JSON'}
    except Exception as e:
        return {'success': False, 'error': f'Error inesperado: {str(e)}'}


def load_session() -> Optional[Dict[str, Any]]:
    """
    Carga la sesión guardada desde el archivo JSON.
    Retorna None si no existe o hay error.
    """
    session_file = Path(__file__).parent / "session.json"
    
    if not session_file.exists():
        return None
    
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            session = json.load(f)
            
        # Validar campos mínimos requeridos
        required_fields = ["access_token", "user"]
        if not all(field in session for field in required_fields):
            print("⚠️  Archivo de sesión corrupto o incompleto")
            return None
            
        return session
        
    except Exception as e:
        print(f"⚠️  Error al cargar sesión: {e}")
        return None


# ==================== MENÚ PRINCIPAL ====================

def main_menu():
    """Menú principal de la aplicación"""
    clear_screen()
    print_header("TWITTER MANAGER - GESTIÓN DE TWEETS")
    
    print("""
    Este programa te permite:
    1. Hacer login con tu cuenta de Twitter (OAuth 2.0)
    2. Buscar y descargar tus tweets O cargar un JSON existente
    3. Revisar los tweets encontrados
    4. Eliminar tweets seleccionados (individual o batch)
    
    Presiona ENTER para continuar...""")
    
    input()


# ==================== PASO 1: LOGIN ====================

def step_login():
    """Paso 1: Login OAuth 2.0"""
    print_header("PASO 1: LOGIN CON TWITTER")
    
    # Verificar si hay sesión guardada
    print("\n🔍 Verificando sesión existente...")
    existing_session = load_session()
    
    if existing_session:
        access_token = existing_session.get('access_token')
        user = existing_session.get('user', {})
        username = user.get('username', 'Unknown')
        
        print(f"\n✓ Sesión encontrada: @{username}")
        
        # Probar si el token sigue válido usando la nueva función test_users_read
        print("   Verificando validez del token...")
        success, _ = test_users_read(access_token)
        if success:
            print("   ✓ Token válido")
            
            use_existing = input("\n¿Usar esta sesión? (s/n): ").strip().lower()
            if use_existing == 's':
                return existing_session
        else:
            print("   ✗ Token expirado o inválido")
    
    # Login nuevo usando la nueva función que incluye prueba de scopes
    print("\n🔐 Iniciando proceso de login...")
    print("   Se abrirá tu navegador para autorizar la aplicación")
    
    input("\nPresiona ENTER para continuar...")
    
    credentials = initiate_login_with_scope_testing()
    
    if credentials and credentials.get('success'):
        print("\n✓ Login exitoso!")
        
        # Guardar sesión usando la nueva función
        save_choice = input("\n💾 ¿Guardar sesión para uso futuro? (s/n): ").strip().lower()
        if save_choice == 's':
            save_test_results(credentials)
        
        return credentials
    else:
        print("\n✗ Error en el login")
        return None


"""
Función mejorada de diagnóstico - Prueba real de permisos
Agregar al archivo twitter_manager.py
"""

def diagnose_oauth_permissions(session: dict):
    """Diagnostica permisos OAuth 2.0 haciendo pruebas reales usando las nuevas funciones"""
    print_header("DIAGNÓSTICO DE PERMISOS OAUTH 2.0")
    
    access_token = session.get('access_token')
    user_id = session.get('user', {}).get('id')
    
    if not access_token:
        print("\n❌ No hay access token disponible")
        return False
    
    print("\n🔍 Verificando permisos del token...")
    
    # Usar las nuevas funciones de prueba
    read_success, read_msg = test_tweet_read(access_token, user_id)
    write_success, write_msg = test_tweet_write(access_token)
    user_success, user_msg = test_users_read(access_token)
    
    print("\n[tweet.read]")
    print(f"  {read_msg}")
    
    print("\n[tweet.write]")
    print(f"  {write_msg}")
    
    print("\n[users.read]")
    print(f"  {user_msg}")
    
    # El token necesita al menos read y write para funcionar
    return read_success and write_success


# ==================== PASO 2: BUSCAR O CARGAR TWEETS ====================

def step_get_tweets(session: dict):
    """Paso 2: Buscar tweets o cargar desde JSON"""
    print_header("PASO 2: OBTENER TWEETS")
    
    print("\n¿Qué deseas hacer?")
    print("   1. Buscar tweets desde Twitter")
    print("   2. Cargar tweets desde un archivo JSON")
    print("   0. Cancelar")
    
    choice = input("\nOpción: ").strip()
    
    if choice == '1':
        return step_search_tweets(session)
    elif choice == '2':
        return step_load_tweets_from_file(session)
    else:
        print("\n❌ Operación cancelada")
        return None


def step_search_tweets(session: dict):
    """Buscar tweets del usuario desde Twitter"""
    print_section("Buscar tweets desde Twitter")
    
    user = session.get('user', {})
    username = user.get('username')
    user_id = user.get('id')
    
    print(f"\n👤 Usuario: @{username}")
    print(f"   ID: {user_id}")
    
    # Pedir cantidad de tweets
    print("\n¿Cuántos tweets deseas buscar?")
    print("   - Ingresa un número (ejemplo: 100, 500, 1000)")
    print("   - Presiona ENTER para buscar todos los disponibles")
    
    max_tweets_input = input("\nCantidad: ")

    # Validar entrada de cantidad de tweets
    if max_tweets_input:
        try:
            max_tweets = int(max_tweets_input)
            if max_tweets <= 0:
                print("\n⚠️  Cantidad inválida, buscando todos los tweets...")
                max_tweets = None
        except ValueError:
            print("\n⚠️  Entrada inválida, buscando todos los tweets...")
            max_tweets = None
    else:
        max_tweets = None
    
    # Buscar tweets
    print_section("Iniciando búsqueda")
    
    result = fetch_user_tweets(username=username, max_tweets=max_tweets)
    
    if not result.get('success'):
        print(f"\n✗ Error: {result.get('error')}")
        return None
    
    # Guardar en archivo
    print_section("Guardando resultados")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"tweets_{username}_{timestamp}"
    filepath = save_tweets_to_file(result, filename)
    
    return {
        'result': result,
        'filepath': filepath,
        'tweets': result.get('tweets', []),
        'user_id': user_id
    }


def step_load_tweets_from_file(session: dict):
    """Cargar tweets desde un archivo JSON"""
    print_section("Cargar tweets desde archivo JSON")
    
    # Buscar archivos JSON en el directorio
    json_files = glob.glob("tweets_*.json")
    
    if json_files:
        print("\n📁 Archivos JSON encontrados:")
        for i, file in enumerate(json_files[:10], 1):
            print(f"   [{i}] {file}")
        
        if len(json_files) > 10:
            print(f"   ... y {len(json_files) - 10} archivos más")
    else:
        print("\n⚠️  No se encontraron archivos JSON en el directorio actual")
    
    print("\nIngresa el nombre del archivo JSON (con o sin extensión):")
    print("Ejemplo: tweets_username_20241031_123456 o tweets_username_20241031_123456.json")
    
    filename = input("\nArchivo: ").strip()
    
    if not filename:
        print("\n❌ No se ingresó ningún archivo")
        return None
    
    # Agregar .json si no lo tiene
    if not filename.endswith('.json'):
        filename += '.json'
    
    # Cargar el archivo
    print(f"\n📂 Cargando: {filename}")
    result = load_tweets_from_json(filename)
    
    if not result.get('success'):
        print(f"\n✗ Error: {result.get('error')}")
        return None
    
    print(f"\n✓ Archivo cargado exitosamente")
    print(f"   Tweets encontrados: {len(result['tweets'])}")
    
    # Si no tiene user_id, intentar obtenerlo de la sesión
    if not result.get('user_id'):
        result['user_id'] = session.get('user', {}).get('id')
    
    return result


# ==================== PASO 3: REVISAR TWEETS ====================

def step_review_tweets(search_data: dict):
    """Paso 3: Revisar tweets encontrados"""
    print_header("PASO 3: REVISAR TWEETS")
    
    tweets = search_data['tweets']
    
    if not tweets:
        print("\n⚠️  No se encontraron tweets")
        return None
    
    # Separar tweets y retweets
    originals = [t for t in tweets if not t.get('is_retweet', False)]
    retweets = [t for t in tweets if t.get('is_retweet', False)]
    
    print(f"\n📊 Total encontrado: {len(tweets)} tweets")
    print(f"   📝 Originales: {len(originals)}")
    print(f"   🔄 Retweets: {len(retweets)}")
    
    # Mostrar tweets
    print("\n¿Deseas ver todos los tweets ahora? (s/n): ", end='')
    show_all = input().strip().lower() == 's'
    
    display_tweets_list(tweets, show_all=show_all)
    
    input("\n\nPresiona ENTER para continuar...")
    
    return search_data


# ==================== PASO 4: ELIMINAR TWEETS ====================

def step_delete_individual(tweets: list, user_id: str, session: dict):
    """Modo individual: revisar y eliminar/deshacer uno por uno"""
    
    if not tweets:
        print("\n⚠️  No hay tweets disponibles")
        input("\nPresiona ENTER para continuar...")
        return None
    
    # Crear sesión OAuth2
    oauth_session = OAuth2Session()
    oauth_session.access_token = session.get('access_token')
    oauth_session.refresh_token = session.get('refresh_token')
    oauth_session.token_expires_at = datetime.now() + timedelta(seconds=session.get('expires_in', 7200))
    
    deleted_count = 0
    undone_count = 0
    skipped_count = 0
    errors = []
    
    current_index = 0
    
    while current_index < len(tweets):
        clear_screen()
        print_header(f"MODO INDIVIDUAL - Tweet {current_index + 1}/{len(tweets)}")
        
        tweet = tweets[current_index]
        is_rt = tweet.get('is_retweet', False)
        action_type = "DESHACER RT" if is_rt else "ELIMINAR TWEET"
        
        print(f"\n🎯 Acción: {action_type}")
        print("─" * 70)
        
        # Mostrar el tweet completo
        show_tweet_preview(tweet, current_index + 1)
        
        print("\n" + "─" * 70)
        print("\n📊 Progreso:")
        print(f"   ✅ Tweets eliminados: {deleted_count}")
        print(f"   ✅ RTs deshechos: {undone_count}")
        print(f"   ⏭️  Omitidos: {skipped_count}")
        
        print("\n" + "─" * 70)
        print("\n¿Qué deseas hacer?")
        print(f"   1. {action_type}")
        print("   2. Saltar (siguiente)")
        print("   3. Ver texto completo")
        print("   0. Terminar y volver al menú")
        
        choice = input("\nOpción: ").strip()
        
        if choice == '1':
            # Confirmar acción
            confirm = input(f"\n⚠️  ¿Confirmar {action_type}? (s/n): ").strip().lower()
            
            if confirm == 's':
                try:
                    if is_rt:
                        # Deshacer retweet
                        print(f"\n🔄 Deshaciendo RT {tweet.get('id')}...")
                        success = delete_single_retweet(
                            user_id=user_id,
                            tweet_id=tweet.get('id'),
                            session=oauth_session
                        )
                        if success:
                            print("✅ RT deshecho exitosamente")
                            undone_count += 1
                        else:
                            print("❌ Error al deshacer RT")
                            errors.append({'id': tweet.get('id'), 'type': 'retweet'})
                    else:
                        # Eliminar tweet
                        print(f"\n🗑️  Eliminando tweet {tweet.get('id')}...")
                        success = delete_single_tweet(
                            tweet_id=tweet.get('id'),
                            session=oauth_session
                        )
                        if success:
                            print("✅ Tweet eliminado exitosamente")
                            deleted_count += 1
                        else:
                            print("❌ Error al eliminar tweet")
                            errors.append({'id': tweet.get('id'), 'type': 'tweet'})
                    
                    time.sleep(1)
                    current_index += 1
                
                except Exception as e:
                    print(f"❌ Error: {e}")
                    errors.append({'id': tweet.get('id'), 'error': str(e)})
                    input("\nPresiona ENTER para continuar...")
                    current_index += 1
            else:
                print("\n⏭️  Acción cancelada")
                time.sleep(0.5)
        
        elif choice == '2':
            print("\n⏭️  Omitiendo...")
            skipped_count += 1
            time.sleep(0.5)
            current_index += 1
        
        elif choice == '3':
            # Mostrar texto completo
            print("\n" + "─" * 70)
            print("TEXTO COMPLETO:")
            print("─" * 70)
            print(tweet.get('text', 'Sin texto'))
            print("─" * 70)
            input("\nPresiona ENTER para continuar...")
        
        elif choice == '0':
            print("\n🛑 Terminando modo individual...")
            break
        
        else:
            print("\n❌ Opción inválida")
            time.sleep(1)
    
    # Resumen final
    clear_screen()
    print_header("RESUMEN - MODO INDIVIDUAL")
    
    print(f"\n📊 Resultados:")
    print(f"   ✅ Tweets eliminados: {deleted_count}")
    print(f"   ✅ RTs deshechos: {undone_count}")
    print(f"   ⏭️  Omitidos: {skipped_count}")
    print(f"   ❌ Errores: {len(errors)}")
    print(f"   📌 Total procesado: {current_index}/{len(tweets)}")
    
    if errors:
        print("\n⚠️  Errores encontrados:")
        for err in errors[:5]:
            print(f"   - ID: {err.get('id')} ({err.get('type', 'unknown')})")
        if len(errors) > 5:
            print(f"   ... y {len(errors) - 5} errores más")
    
    input("\n\nPresiona ENTER para volver al menú...")
    
    return {
        'tweets_deleted': deleted_count,
        'retweets_deleted': undone_count,
        'skipped': skipped_count,
        'errors': errors,
        'processed': current_index
    }


def step_delete_tweets(search_data: dict, session: dict):
    """Paso 4: Eliminar tweets con vista continua"""
    
    tweets = search_data['tweets']
    user_id = search_data['user_id']
    
    while True:
        clear_screen()
        print_header("PASO 4: ELIMINAR TWEETS")
        
        # Mostrar resumen
        originals = [t for t in tweets if not t.get('is_retweet', False)]
        retweets = [t for t in tweets if t.get('is_retweet', False)]
        
        print(f"\n📊 TWEETS DISPONIBLES:")
        print(f"   📝 Originales: {len(originals)}")
        print(f"   🔄 Retweets: {len(retweets)}")
        print(f"   📌 Total: {len(tweets)}")
        
        # Mostrar lista de tweets
        display_tweets_list(tweets, show_all=False)
        
        # Opciones
        print_section("OPCIONES DE ELIMINACIÓN/DESHACER")
        print("\n   1. Eliminar/Deshacer TODOS (batch)")
        print("   2. Deshacer solo retweets (batch)")
        print("   3. Eliminar solo tweets originales (batch)")
        print("   4. Ingresar IDs - el programa detecta tipo automáticamente")
        print("   5. Modo individual - seleccionar uno por uno")
        print("   6. Ver todos los tweets completos")
        print("   0. Cancelar y salir")
        
        choice = input("\nOpción: ").strip()
        
        if choice == '0':
            print("\n❌ Operación cancelada")
            return None
        
        elif choice == '5':
            # Modo individual - seleccionar uno por uno
            result = step_delete_individual(tweets, user_id, session)
            if result:
                return result
            continue
        
        elif choice == '6':
            clear_screen()
            print_header("LISTA COMPLETA DE TWEETS")
            display_tweets_list(tweets, show_all=True)
            input("\n\nPresiona ENTER para volver al menú...")
            continue
        
        # Preparar para eliminación
        delete_originals = False
        delete_retweets = False
        specific_ids = None
        
        if choice == '1':
            delete_originals = True
            delete_retweets = True
            tweets_to_delete = tweets
            print("\n⚠️  Se eliminarán tweets originales y se deshacerán retweets (TODOS)")
        
        elif choice == '2':
            delete_retweets = True
            delete_originals = False
            tweets_to_delete = retweets
            print("\n⚠️  Se deshacerán SOLO los retweets")
        
        elif choice == '3':
            delete_originals = True
            delete_retweets = False
            tweets_to_delete = originals
            print("\n⚠️  Se eliminarán SOLO los tweets originales")
        
        elif choice == '4':
            # Ingresar IDs - detección automática
            clear_screen()
            print_header("INGRESAR IDs - DETECCIÓN AUTOMÁTICA")
            display_tweets_list(tweets, show_all=True)
            
            print("\n" + "─" * 70)
            print("\nINGRESA LOS IDs (separados por comas):")
            print("El programa detectará automáticamente:")
            print("  🔄 RT → Se deshace automáticamente")
            print("  📝 Tweet → Se elimina automáticamente")
            print("\nEjemplo: 1234567890,9876543210,1111111111")
            ids_input = input("\nIDs: ").strip()
            
            if not ids_input:
                print("\n❌ No se ingresaron IDs")
                input("\nPresiona ENTER para continuar...")
                continue
            
            specific_ids = [id.strip() for id in ids_input.split(',')]
            tweets_to_delete = [t for t in tweets if t.get('id') in specific_ids]
            
            if not tweets_to_delete:
                print("\n⚠️  No se encontraron tweets con esos IDs")
                input("\nPresiona ENTER para continuar...")
                continue
            
            # Separar por tipo AUTOMÁTICAMENTE
            to_delete_originals = [t for t in tweets_to_delete if not t.get('is_retweet', False)]
            to_undo_retweets = [t for t in tweets_to_delete if t.get('is_retweet', False)]
            
            print(f"\n✅ DETECCIÓN COMPLETADA - {len(tweets_to_delete)} items encontrados:")
            print(f"   🗑️  ELIMINAR automáticamente: {len(to_delete_originals)} tweets")
            print(f"   🔄 DESHACER automáticamente: {len(to_undo_retweets)} RTs")
            
            # Mostrar lista detallada
            print_section("ITEMS DETECTADOS Y ACCIÓN AUTOMÁTICA")
            
            if to_delete_originals:
                print("\n🗑️  TWEETS A ELIMINAR:")
                for i, tweet in enumerate(to_delete_originals, 1):
                    print(f"\n  [{i}] ID: {tweet.get('id')}")
                    text = tweet.get('text', '')[:80]
                    print(f"      Texto: {text}{'...' if len(tweet.get('text', '')) > 80 else ''}")
            
            if to_undo_retweets:
                print("\n🔄 RTs A DESHACER:")
                for i, rt in enumerate(to_undo_retweets, 1):
                    print(f"\n  [{i}] ID: {rt.get('id')}")
                    text = rt.get('text', '')[:80]
                    print(f"      Texto: {text}{'...' if len(rt.get('text', '')) > 80 else ''}")
            
            delete_originals = len(to_delete_originals) > 0
            delete_retweets = len(to_undo_retweets) > 0
            
            print("\n" + "─" * 70)
        
        else:
            print("\n❌ Opción inválida")
            input("\nPresiona ENTER para continuar...")
            continue
        
        # Confirmación final
        originals_count = sum(1 for t in tweets_to_delete if not t.get('is_retweet', False))
        retweets_count = sum(1 for t in tweets_to_delete if t.get('is_retweet', False))
        
        print(f"\n{'='*70}")
        print(f"CONFIRMACIÓN DE ACCIÓN")
        print(f"{'='*70}")
        print(f"   📝 Tweets a ELIMINAR: {originals_count}")
        print(f"   🔄 RTs a DESHACER: {retweets_count}")
        print(f"   📌 TOTAL: {len(tweets_to_delete)}")
        print(f"{'='*70}")
        print("\n⚠️  ADVERTENCIA: Esta acción NO se puede deshacer")
        print("   • Los tweets eliminados se borran permanentemente")
        print("   • Los RTs deshacerán el retweet")
        
        confirm = input("\n¿Continuar? Escribe 'CONFIRMAR' para proceder: ").strip()
        
        if confirm != 'CONFIRMAR':
            print("\n❌ Operación cancelada por el usuario")
            input("\nPresiona ENTER para continuar...")
            continue
        
        # Crear sesión OAuth2 para eliminación
        print("\n🔐 Preparando sesión OAuth2...")
        
        oauth_session = OAuth2Session()
        oauth_session.access_token = session.get('access_token')
        oauth_session.refresh_token = session.get('refresh_token')
        oauth_session.token_expires_at = datetime.now() + timedelta(seconds=session.get('expires_in', 7200))
        
        # Ejecutar eliminación/deshacer
        print_section("Procesando (Eliminando/Deshaciendo)")
        
        result = delete_tweets_batch(
            tweets=tweets_to_delete,
            user_id=user_id,
            session=oauth_session,
            delete_retweets=delete_retweets,
            delete_originals=delete_originals,
            delay_seconds=1.0,
            verbose=True
        )
        
        # Guardar reporte
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"deletion_report_{timestamp}.json"
        
        report = {
            'source_json': search_data.get('filepath'),
            'deletion_timestamp': datetime.now().isoformat(),
            'result': result
        }
        
        with open(report_filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n💾 Reporte guardado: {report_filename}")
        
        return result


# ==================== FLUJO PRINCIPAL ====================

# Integrar en el flujo principal - modificar main():
def main():
    """Flujo principal de la aplicación"""
    try:
        main_menu()
        
        # Paso 1: Login
        session = step_login()
        if not session:
            print("\n❌ No se pudo completar el login")
            return
        
        # DIAGNÓSTICO AUTOMÁTICO después del login
        clear_screen()
        print_header("VERIFICACIÓN DE PERMISOS")
        print("\n🔍 Verificando que el token tenga permisos de escritura...")
        print("   (Necesario para eliminar tweets)")
        
        has_permissions = diagnose_oauth_permissions(session)
        
        if not has_permissions:
            print("\n" + "="*70)
            print("⚠️  NO PUEDES CONTINUAR SIN PERMISOS DE ESCRITURA")
            print("="*70)
            print("\nDebes configurar los permisos en el Developer Portal")
            print("y volver a hacer login.")
            
            retry = input("\n¿Deseas salir ahora? (s/n): ").strip().lower()
            if retry == 's':
                print("\n👋 Adiós. Configura los permisos y vuelve pronto!")
                return
            else:
                print("\n⚠️  Continuando de todas formas (las eliminaciones fallarán)...")
        else:
            print("\n✅ Permisos verificados correctamente")
        
        input("\nPresiona ENTER para continuar...")
        clear_screen()
        
        # Paso 2: Buscar o cargar tweets
        search_data = step_get_tweets(session)
        if not search_data:
            print("\n❌ No se pudieron obtener los tweets")
            return
        
        input("\n✓ Tweets obtenidos. Presiona ENTER para continuar...")
        clear_screen()
        
        # Paso 3: Revisar tweets
        review_data = step_review_tweets(search_data)
        if not review_data:
            print("\n❌ No hay tweets para revisar")
            return
        
        # Paso 4: ¿Desea eliminar tweets?
        clear_screen()
        print_header("PASO 4: OPCIONES DE ELIMINACIÓN")
        
        delete_choice = input("\n¿Deseas eliminar tweets? (s/n): ").strip().lower()
        
        if delete_choice == 's':
            deletion_result = step_delete_tweets(review_data, session)
            
            if deletion_result:
                clear_screen()
                print_header("✓ PROCESO COMPLETADO")
                print(f"\n   Tweets eliminados: {deletion_result.get('tweets_deleted', 0)}")
                print(f"   Retweets eliminados: {deletion_result.get('retweets_deleted', 0)}")
                print(f"   Fallidos: {len(deletion_result.get('failed', []))}")
                print(f"   Tiempo total: {deletion_result.get('execution_time', 'N/A')}")
                
                if deletion_result.get('failed'):
                    print("\n⚠️  Si todos fallaron con HTTP 403:")
                    print("   → El token NO tiene permiso 'tweet.write'")
                    print("   → Configura permisos en Developer Portal")
            else:
                print("\n⚠️  Eliminación cancelada o con errores")
        else:
            print("\n✓ Proceso completado sin eliminar tweets")
        
        print("\n" + "="*70)
        print("Gracias por usar Twitter Manager")
        print("="*70)
    
    except KeyboardInterrupt:
        print("\n\n❌ Proceso interrumpido por el usuario")
    except Exception as e:
        print(f"\n\n❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()

    




        
        # ... resto del código igual ...


if __name__ == "__main__":
    main()
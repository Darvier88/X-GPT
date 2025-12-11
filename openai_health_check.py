"""
Sistema de Health Check Automático para OpenAI
Se ejecuta al iniciar la aplicación y verifica la conexión
"""

import os
import time
from typing import Dict, Any
from openai import OpenAI

def test_openai_connection() -> Dict[str, Any]:
    """
    Prueba la conexión con OpenAI API
    Retorna dict con resultado del test
    """
    result = {
        "success": False,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "environment": os.getenv('RAILWAY_ENVIRONMENT', 'local'),
        "checks": {}
    }
    
    print("\n" + "="*70)
    print("🏥 HEALTH CHECK: Conexión con OpenAI API")
    print("="*70)
    
    # ═══════════════════════════════════════════════════════════════════
    # CHECK 1: Variable de entorno
    # ═══════════════════════════════════════════════════════════════════
    print("\n1️⃣  Verificando variable de entorno...")
    
    api_key = os.getenv('OPENAI_API_KEY')
    
    if not api_key:
        print("   ❌ OPENAI_API_KEY no encontrada")
        result["checks"]["env_var"] = {
            "status": "FAIL",
            "error": "OPENAI_API_KEY not found in environment"
        }
        print("="*70 + "\n")
        return result
    
    print(f"   ✅ OPENAI_API_KEY encontrada")
    print(f"   📏 Longitud: {len(api_key)} caracteres")
    print(f"   🔑 Primeros 10 chars: {api_key[:10]}")
    print(f"   🔑 Últimos 4 chars: ...{api_key[-4:]}")
    
    # Verificar formato
    has_quotes = api_key.startswith('"') or api_key.startswith("'")
    starts_with_sk = api_key.startswith('sk-')
    
    result["checks"]["env_var"] = {
        "status": "OK",
        "length": len(api_key),
        "starts_with_sk": starts_with_sk,
        "has_quotes": has_quotes
    }
    
    if has_quotes:
        print(f"   ⚠️  WARNING: La key tiene comillas (esto puede causar problemas)")
    
    if not starts_with_sk:
        print(f"   ⚠️  WARNING: La key no empieza con 'sk-' (formato inusual)")
    
    # ═══════════════════════════════════════════════════════════════════
    # CHECK 2: Crear cliente OpenAI
    # ═══════════════════════════════════════════════════════════════════
    print("\n2️⃣  Creando cliente OpenAI...")
    
    try:
        client = OpenAI(api_key=api_key)
        print("   ✅ Cliente creado exitosamente")
        result["checks"]["client_creation"] = {
            "status": "OK"
        }
    except Exception as e:
        print(f"   ❌ Error creando cliente: {type(e).__name__}: {str(e)}")
        result["checks"]["client_creation"] = {
            "status": "FAIL",
            "error": str(e),
            "error_type": type(e).__name__
        }
        print("="*70 + "\n")
        return result
    
    # ═══════════════════════════════════════════════════════════════════
    # CHECK 3: Test de API simple (modelo más barato)
    # ═══════════════════════════════════════════════════════════════════
    print("\n3️⃣  Probando conexión real con API...")
    print("   (Usando gpt-4o-mini con 1 token para minimizar costo)")
    
    try:
        start_time = time.time()
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": "Hi"}
            ],
            max_tokens=1,  # Solo 1 token para minimizar costo
            timeout=10
        )
        
        elapsed = time.time() - start_time
        
        print(f"   ✅ Conexión exitosa!")
        print(f"   ⏱️  Tiempo de respuesta: {elapsed:.2f}s")
        print(f"   📊 Modelo: {response.model}")
        print(f"   🎫 Tokens usados: {response.usage.total_tokens if hasattr(response, 'usage') else 'N/A'}")
        
        result["checks"]["api_connection"] = {
            "status": "OK",
            "response_time_seconds": round(elapsed, 2),
            "model": response.model,
            "tokens_used": response.usage.total_tokens if hasattr(response, 'usage') else None
        }
        
        result["success"] = True
        
    except Exception as e:
        print(f"   ❌ Error conectando con API: {type(e).__name__}: {str(e)}")
        result["checks"]["api_connection"] = {
            "status": "FAIL",
            "error": str(e),
            "error_type": type(e).__name__
        }
        print("="*70 + "\n")
        return result
    
    # ═══════════════════════════════════════════════════════════════════
    # CHECK 4: Test de clasificación (opcional, solo si todo funciona)
    # ═══════════════════════════════════════════════════════════════════
    print("\n4️⃣  Probando función de clasificación...")
    
    try:
        from GPT.risk_classifier_only_text import classify_risk_text_only
        
        test_tweet = "Este es un tweet de prueba 🎉"
        test_result = classify_risk_text_only(test_tweet, tweet_id="test_123")
        
        has_error = "error_code" in test_result
        
        if has_error:
            print(f"   ⚠️  Clasificación retornó error: {test_result.get('error_code')}")
            result["checks"]["classification_test"] = {
                "status": "WARN",
                "error_code": test_result.get('error_code'),
                "error": test_result.get('error')
            }
        else:
            print(f"   ✅ Clasificación funcional")
            print(f"   🎯 Risk level: {test_result.get('risk_level')}")
            print(f"   🏷️  Labels: {test_result.get('labels', [])}")
            result["checks"]["classification_test"] = {
                "status": "OK",
                "risk_level": test_result.get('risk_level'),
                "has_rationale": test_result.get('rationale') is not None
            }
        
    except Exception as e:
        print(f"   ⚠️  Error en test de clasificación: {type(e).__name__}: {str(e)}")
        result["checks"]["classification_test"] = {
            "status": "WARN",
            "error": str(e),
            "error_type": type(e).__name__
        }
    
    # ═══════════════════════════════════════════════════════════════════
    # RESUMEN FINAL
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    if result["success"]:
        print("✅ HEALTH CHECK COMPLETADO - TODO FUNCIONAL")
    else:
        print("❌ HEALTH CHECK FALLÓ - REVISAR ERRORES ARRIBA")
    print("="*70 + "\n")
    
    return result


def run_startup_health_check():
    """
    Ejecuta el health check al iniciar la aplicación
    Si falla, imprime advertencias pero NO detiene el servidor
    """
    print("\n🚀 Ejecutando health check de inicio...")
    
    try:
        result = test_openai_connection()
        
        if not result["success"]:
            print("\n⚠️  " + "="*68)
            print("⚠️  ADVERTENCIA: OpenAI API no está funcionando correctamente")
            print("⚠️  La clasificación de tweets NO funcionará")
            print("⚠️  Revisa los errores arriba y configura OPENAI_API_KEY")
            print("⚠️  " + "="*68 + "\n")
        
        return result
        
    except Exception as e:
        print(f"\n❌ Error crítico en health check: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "checks": {}
        }


# ============================================================================
# Para usar en FastAPI
# ============================================================================

# Variable global para almacenar el resultado del último health check
last_health_check_result = None

def get_last_health_check():
    """Retorna el resultado del último health check"""
    return last_health_check_result
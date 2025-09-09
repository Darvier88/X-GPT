# X-GPT: Integración API de X (Twitter) + ChatGPT (OpenAI)

## Descripción

Servicio CLI que permite buscar tweets recientes en X (Twitter) usando una consulta, y genera un resumen claro en lenguaje natural con ChatGPT (OpenAI).  
Ideal para obtener explicaciones rápidas y enriquecidas sobre tendencias, temas o hashtags en X.

## Requisitos

- Python 3.10+
- API Key de X (Twitter)
- API Key de OpenAI

## Instalación

1. **Clona el repositorio:**
   ```sh
   git clone https://github.com/tuusuario/x-gpt.git
   cd x-gpt
   ```

2. **Instala dependencias:**
   ```sh
   pip install -r requirements.txt
   ```

3. **Configura las variables de entorno:**
   - Crea un archivo `.env` en la raíz del proyecto con el siguiente contenido:
     ```
     X_API_KEY=tu_bearer_token_de_x
     OPENAI_API_KEY=tu_api_key_de_openai
     ```

## Ejecución

### CLI

```sh
python main.py
```

Sigue las instrucciones en pantalla para ingresar tu consulta.

### Ejemplo de uso

```
¿Qué quieres buscar en X? (o 'quit' para salir): Pokemon
```

**Respuesta esperada:**
```json
{
  "summary": "Resumen generado por ChatGPT sobre los tweets de 'Pokemon'...",
  "tweets_analyzed": 10,
  "campos_clave": {
    "idiomas": ["es", "en"],
    "likes_totales": 120,
    "retweets_totales": 30,
    "autores_verificados": 2
  }
}
```

## Manejo de errores

- **Sin API keys:**  
  El sistema explica cómo configurarlas y no ejecuta la consulta.
- **Consulta inválida:**  
  Mensaje claro y sugerencias para mejorar la búsqueda.
- **Rate limit o X caído:**  
  Mensaje indicando el tiempo de espera necesario o el error detectado.

## Pruebas

Incluye pruebas mínimas para funciones clave.  
Ejecuta los tests con:

```sh
python -m unittest tests.test_functions -v 
```
## Áreas de mejora

- Implementar un endpoint REST (por ejemplo, usando FastAPI) para facilitar la integración con otros sistemas.
- Mejorar la cobertura de pruebas unitarias y agregar pruebas de integración.
- Permitir la configuración de parámetros avanzados de búsqueda (rango de fechas, idioma, cantidad de tweets).
- Añadir paginación y manejo de grandes volúmenes de datos.
- Internacionalización del resumen (permitir elegir idioma de salida).
- Mejorar el manejo de errores y mensajes al usuario.
- Optimizar el guardado y carga de archivos para mayor eficiencia.
- Agregar autenticación y autorización para el uso del servicio en producción.

## Nota técnica

- Stack: Python, requests, OpenAI SDK.
- Decisiones: Se priorizó la simplicidad y claridad en el manejo de errores y la estructura de los datos.
- Supuestos: El usuario tiene las API keys válidas y acceso a la API


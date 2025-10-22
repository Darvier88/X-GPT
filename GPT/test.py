# Test simple
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

try: 
    response = client.chat.completions.create(
                model="gpt-5-nano",
                messages=[
                    {"role": "system", "content": "Eres un analizador de sentimientos. Responde solo con JSON."}
                ],
            )
    print("✅ API Key funciona correctamente")
    print(f"Respuesta: {response.choices[0].message.content}")
    print(f"Tokens usados: {response.usage.total_tokens}")
except Exception as e:
    print(f"❌ Error: {e}")

resp = client.chat.completions.create(
    model="gpt-5-nano",
    messages=[{"role":"system","content":"Hola"}],
)
print("request_id:", getattr(resp, "_request_id", None))
print("usage:", getattr(resp, "usage", None))
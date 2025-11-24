import sys
import os
import json
from pathlib import Path

# Asegurar que el package root esté en sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from X.search_tweets import get_rate_limit

def fetch_and_print_rate_limit(access_token: str | None = None) -> dict:
    """
    Llama a get_rate_limit(access_token).
    No modifica variables de entorno: pasa el token directamente.
    """
    rl = get_rate_limit(access_token)
    if rl is None:
        print("⚠️  get_rate_limit() devolvió None (no se pudo obtener info).")
        return {}
    # Si la función devolvió solo status_code por error
    if isinstance(rl, dict) and rl.get("status_code", 0) >= 400 and rl.get("limit") is None:
        print(f"⚠️  Request returned status {rl.get('status_code')}; token inválido o permisos insuficientes.")
        print(json.dumps(rl, ensure_ascii=False, indent=2))
        return rl

    print("🔎 Rate limit info:")
    print(json.dumps(rl, ensure_ascii=False, indent=2))
    return rl

def main():
    """
    Uso:
      python main_rate_limit.py              # usa get_x_api_key() o session.json
      python main_rate_limit.py <ACCESS_TOKEN>
    """
    token = None
    if len(sys.argv) > 1:
        token = sys.argv[1].strip()
    fetch_and_print_rate_limit(token)

if __name__ == "__main__":
    main()
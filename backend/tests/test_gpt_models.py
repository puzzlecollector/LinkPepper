# Minimal GPT-5 connectivity test (hard-coded key, no env/venv/sys.argv)
# Requires: pip install --upgrade openai

from openai import OpenAI
import openai  # for exception classes in this package

# === 1) YOUR RAW KEY AS-IS (including extra quotes/comma you provided) ===
API_KEY_RAW = '""",'

# Normalize obvious paste artifacts while still hard-coding the value
API_KEY = API_KEY_RAW.replace('"', '').replace(',', '').strip()

client = OpenAI(api_key=API_KEY)

def try_model(model_id: str) -> bool:
    print(f"\n--- Testing model: {model_id} ---")
    try:
        resp = client.responses.create(
            model=model_id,
            input="Respond with exactly: PONG",
            # Optional: if GPT-5 is available, these params are supported
            # reasoning: {"effort": "minimal"},
            # verbosity="low",
        )
        out = getattr(resp, "output_text", None) or str(resp)
        print(f"SUCCESS [{model_id}]: {out}")
        return True

    except openai.APIStatusError as e:
        # HTTP status-based errors (4xx/5xx)
        code = getattr(e, "status_code", None)
        detail = ""
        try:
            # Some SDK versions expose e.response.json(); fall back to text
            detail = e.response.text if hasattr(e, "response") else ""
        except Exception:
            pass

        if code == 401:
            print(f"AUTH ERROR 401 for [{model_id}]: Invalid API key or not authorized.\n{detail}")
        elif code == 403:
            print(f"PERMISSION DENIED 403 for [{model_id}]: Model not enabled for this key.\n{detail}")
        elif code == 404:
            print(f"NOT FOUND 404 for [{model_id}]: Model ID doesn’t exist for this account/region.\n{detail}")
        elif code == 429:
            print(f"RATE LIMITED 429 for [{model_id}]: Too many requests or quota exhausted.\n{detail}")
        else:
            print(f"API STATUS ERROR {code} for [{model_id}]:\n{detail}")
        return False

    except openai.APIConnectionError as e:
        print(f"CONNECTION ERROR for [{model_id}]: {e}")
        return False

    except openai.APIError as e:
        # Base class for other API errors in this SDK
        print(f"GENERAL API ERROR for [{model_id}]: {e}")
        return False

    except Exception as e:
        print(f"UNEXPECTED ERROR for [{model_id}]: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    # 1) Probe GPT-5 (primary goal)
    ok = try_model("gpt-5")

    # 2) If GPT-5 fails, verify the key works at all by probing GPT-4.1
    if not ok:
        try_model("gpt-4.1")

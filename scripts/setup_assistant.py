"""Create (or update, if VAPI_ASSISTANT_ID is set) the Vapi assistant."""
import json
import sys

from app import config, vapi_client
from app.assistant import build_assistant

if __name__ == "__main__":
    if not config.PUBLIC_SERVER_URL:
        sys.exit("Set PUBLIC_SERVER_URL in .env to your public tunnel URL (e.g. https://xyz.ngrok-free.app)")
    body = build_assistant()
    if "--print" in sys.argv:
        print(json.dumps(body, indent=2))
        sys.exit(0)
    res = vapi_client.upsert_assistant(body, config.VAPI_ASSISTANT_ID)
    action = "Updated" if config.VAPI_ASSISTANT_ID else "Created"
    print(f"{action} assistant {res['id']}")
    if not config.VAPI_ASSISTANT_ID:
        print(f"Add this to .env:\nVAPI_ASSISTANT_ID={res['id']}")

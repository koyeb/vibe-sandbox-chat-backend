from koyeb import Sandbox
import os

def get_sandbox_url(service_id: str) -> str:
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        raise ValueError("KOYEB_API_TOKEN not set") 

    sandbox = Sandbox.get_from_id(service_id, api_token=api_token)
    if not sandbox:
        raise ValueError(f"Sandbox with ID {service_id} not found")

    return sandbox.get_domain() or ""
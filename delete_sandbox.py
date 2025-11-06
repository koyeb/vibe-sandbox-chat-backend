from koyeb import Sandbox
import os

def delete_sandbox(service_id: str) -> str:
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        raise ValueError("KOYEB_API_TOKEN not set") 

    sandbox = Sandbox.get_from_id(service_id, api_token=api_token)
    if not sandbox:
        raise ValueError(f"Sandbox with ID {service_id} not found")

    sandbox.delete()
    return f"Sandbox with ID {service_id} has been deleted."
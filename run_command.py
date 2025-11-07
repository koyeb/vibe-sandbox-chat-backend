import os
from koyeb import Sandbox

def run_command(service_id: str, command: str, timeout: int = 300) -> str:  # 5 minutes default
    print(f"Running command in sandbox {service_id}: {command}")
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        raise ValueError("KOYEB_API_TOKEN not set") 

    sandbox = Sandbox.get_from_id(service_id, api_token=api_token)
    if not sandbox:
        raise ValueError(f"Sandbox with ID {service_id} not found")

    # Add timeout parameter to exec call
    result = sandbox.exec(command, timeout=timeout)
    return result.stdout.strip()
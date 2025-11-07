from koyeb import Sandbox
import os

from koyeb.sandbox import sandbox

def expose_endpoint(service_id: str, port: int) -> str:
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        raise ValueError("KOYEB_API_TOKEN not set")
    sandbox = Sandbox.get_from_id(service_id, api_token=api_token)
    if not sandbox:
        raise ValueError(f"Sandbox with ID {service_id} not found")

    exposed = sandbox.expose_port(port)
    print(f"Port exposed: {exposed.port}")
    print(f"Exposed at: {exposed.exposed_at}")
    return f"Exposed port: {exposed.exposed_at}"

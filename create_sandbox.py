import os
from koyeb import Sandbox

def create_sandbox_client(image: str = "koyeb/sandbox", name: str = "example-sandbox"):
    api_token = os.getenv("KOYEB_API_TOKEN")
    print(api_token)
    if not api_token:
        print("Error: KOYEB_API_TOKEN not set")
        return

    sandbox = None
    try:
        sandbox = Sandbox.create(
            image=image,
            name=name,
            wait_ready=True,
            api_token=api_token,
            instance_type="small"
        )

        # Check status
        status = sandbox.status()
        is_healthy = sandbox.is_healthy()
        print(f"Status: {status}, Healthy: {is_healthy}")

        # Test command
        result = sandbox.exec("echo 'Sandbox is ready!'")
        print(result.stdout.strip())
        print(f"Sandbox ID: {sandbox.service_id}")
        return sandbox.service_id

    except Exception as e:
        print(f"Error: {e}")
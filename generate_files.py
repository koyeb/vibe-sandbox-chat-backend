
from koyeb import Sandbox
import os

def create_file_and_add_code(service_id: str, file_path: str, code: str):
    print(f"Creating file at {file_path} in sandbox {service_id} with code:\n{code}")
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        print("Error: KOYEB_API_TOKEN not set")
        return
    print(f"file_path: {file_path}")
    sandbox = None
    try:
        sandbox = Sandbox.get_from_id(service_id, api_token=api_token)

        fs = sandbox.filesystem
        # Create file if it doesn't exist
        # Write file
        fs.write_file(file_path, code)

        # Read file
        file_info = fs.read_file(file_path)
        print(file_info.content)

        # Write Python script
        # python_code = "#!/usr/bin/env python3\nprint('Hello from Python!')\n"
        # fs.write_file("/tmp/script.py", python_code)
        # sandbox.exec("chmod +x /tmp/script.py")
        # result = sandbox.exec("/tmp/script.py")
        # print(result.stdout.strip())
        return f"File created at {file_path} and code added successfully."
    except Exception as e:
        print(f"Error: {e}")
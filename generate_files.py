
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
        # Ensure directory exists
        dir_path = os.path.dirname(file_path)
        if dir_path:
            sandbox.exec(f"mkdir -p {dir_path}")
        # Write file
        fs.write_file(file_path, code)

        # Read file
        file_info = fs.read_file(file_path)
        print(file_info.content)

        return f"File created at {file_path} and code added successfully: {file_info.content}."
    except Exception as e:
        print(f"Error: {e}")

def read_file(file_path: str, service_id: str) -> str:
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        print("Error: KOYEB_API_TOKEN not set")
        return ""
    sandbox = None
    try:
        sandbox = Sandbox.get_from_id(service_id, api_token=api_token)

        fs = sandbox.filesystem
        # Ensure directory exists

        if not fs.exists(file_path):
            return f"File {file_path} does not exist."

        # Read file
        file_info = fs.read_file(file_path)
        print(file_info.content)

        return file_info.content
    except Exception as e:
        print(f"Error: {e}")
        return f"Error reading file: {e}"
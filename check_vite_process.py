from koyeb import Sandbox
from typing import Tuple, Optional

def check_vite_process(service_id: str, api_token: str) -> Tuple[bool, Optional[any], str]:
    """
    Check if a Vite development server is already running.
    
    Args:
        service_id: The sandbox service ID
        api_token: Koyeb API token
        
    Returns:
        Tuple of (is_running, process_object, status_string)
    """
    try:
        sandbox = Sandbox.get_from_id(service_id, api_token=api_token)
        processes = sandbox.list_processes()
        
        for process in processes:
            # Check if it's a Vite/npm dev process
            if process.status == "running" and ('npm run dev' in process.command or 'vite' in process.command.lower()):
                print(f"Found existing Vite process: {process.id} - Status: {process.status}")
                return True, process, process.status
        
        return False, None, "not_found"
    except Exception as e:
        print(f"Error checking for Vite process: {e}")
        return False, None, "error"
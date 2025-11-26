import os
import asyncio
from typing import Optional
from koyeb import Sandbox

# Import from the new websocket utils module
from utils.websocket_utils import broadcast_log, queue_log_for_broadcast

def run_background_command(service_id: str, command: str, timeout: int = 300, log_service_id: Optional[str] = None) -> str:
    """
    Launch a background process and broadcast logs to WebSocket clients
    log_service_id: The service ID to broadcast logs to (may be different from execution service_id)
    """
    print(f"Launching background process in sandbox {service_id}: {command}")
    
    # Use log_service_id if provided, otherwise use service_id
    broadcast_to = log_service_id or service_id
    
    # Improved safe async task creation with better error handling
    def safe_broadcast(service_id: str, log_type: str, message: str, data: Optional[dict] = None):
        try:
            loop = asyncio.get_running_loop()
            task = asyncio.create_task(broadcast_log(service_id, log_type, message, data))
            print(f"[WebSocket] Broadcasted {log_type}: {message}")
        except RuntimeError:
            # No running loop - queue for later processing
            queue_log_for_broadcast(service_id, log_type, message, data)
        except Exception as e:
            print(f"[WebSocket Error] Failed to broadcast {log_type}: {e}")
    
    # Broadcast command start
    safe_broadcast(
        broadcast_to, 
        "command_start", 
        f"🔧 Launching background process: {command}",
        {"command": command, "timeout": timeout}
    )
    
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        error_msg = "KOYEB_API_TOKEN not set"
        safe_broadcast(broadcast_to, "command_error", f"❌ {error_msg}")
        raise ValueError(error_msg)

    sandbox = Sandbox.get_from_id(service_id, api_token=api_token)
    if not sandbox:
        error_msg = f"Sandbox with ID {service_id} not found"
        safe_broadcast(broadcast_to, "command_error", f"❌ {error_msg}")
        raise ValueError(error_msg)

    try:
        # Launch process in background - returns process ID
        process_id = sandbox.launch_process(command)
        
        print(f"[DEBUG] Background process launched with ID: {process_id}")
        
        # Broadcast that process was launched
        safe_broadcast(
            broadcast_to,
            "process_launched",
            f"✅ Background process started",
            {"process_id": process_id, "command": command}
        )
        
        # Wait a moment for process to initialize
        import time
        time.sleep(2)
        
        # Get process status
        processes = sandbox.list_processes()
        process_info = None
        
        for process in processes:
            if process.id == process_id:
                process_info = process
                break
        
        if process_info:
            safe_broadcast(
                broadcast_to,
                "process_status",
                f"📊 Process status: {process_info.status}",
                {
                    "process_id": process_info.id,
                    "command": process_info.command,
                    "status": process_info.status
                }
            )
            
            print(f"[DEBUG] Process status:")
            print(f"  ID: {process_info.id}")
            print(f"  Command: {process_info.command}")
            print(f"  Status: {process_info.status}")
        else:
            safe_broadcast(
                broadcast_to,
                "process_warning",
                "⚠️ Process launched but status unknown",
                {"process_id": process_id}
            )
        
        # Broadcast completion
        safe_broadcast(
            broadcast_to,
            "command_complete",
            f"✅ Background process running",
            {"process_id": process_id}
        )
        
        return f"Background process started with ID: {process_id}"
        
    except Exception as e:
        # Broadcast execution error
        error_msg = f"❌ Failed to launch background process: {str(e)}"
        print(f"[DEBUG] Process launch failed: {e}")
        safe_broadcast(broadcast_to, "command_error", error_msg, {"error": str(e)})
        raise
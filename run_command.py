import os
import asyncio
from typing import Optional
from koyeb import Sandbox

# Import from the new websocket utils module
from utils.websocket_utils import broadcast_log, queue_log_for_broadcast

def run_command(service_id: str, command: str, timeout: int = 300, log_service_id: Optional[str] = None) -> str:
    """
    Execute command and broadcast logs to WebSocket clients
    log_service_id: The service ID to broadcast logs to (may be different from execution service_id)
    """
    print(f"Running command in sandbox {service_id}: {command}")
    
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
        f"🔧 Executing: {command}",
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
        # Execute command
        result = sandbox.exec(command, timeout=timeout, on_stdout=lambda data:                     safe_broadcast(
                        broadcast_to,
                        "command_output",
                        data.strip(),
                        {"output_type": "stdout"}
                    ))
        
        # Broadcast output line by line
        if result.stdout:
            lines = result.stdout.split('\n')
            for i, line in enumerate(lines):
                if line.strip():  # Only send non-empty lines
                    safe_broadcast(
                        broadcast_to,
                        "command_output",
                        line,
                        {"output_type": "stdout"}
                    )
        else:
            print("[DEBUG] No stdout from command")
        
        # Broadcast errors if any
        if result.stderr:
            safe_broadcast(
                broadcast_to,
                "command_error",
                f"🟡 Error: {result.stderr}",
                {"output_type": "stderr"}
            )
        
        # Broadcast completion
        safe_broadcast(
            broadcast_to,
            "command_complete",
            f"✅ Command completed successfully",
            {"exit_code": getattr(result, 'exit_code', 0)}
        )
        
        return result.stdout.strip()
        
    except Exception as e:
        # Broadcast execution error
        error_msg = f"❌ Command failed: {str(e)}"
        print(f"[DEBUG] Command failed: {e}")
        safe_broadcast(broadcast_to, "command_error", error_msg, {"error": str(e)})
        raise
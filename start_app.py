from koyeb import Sandbox
import os
import asyncio
from typing import Optional
from generate_files import create_file_and_add_code
from run_command import run_command
from get_sandbox_url import get_sandbox_url
from websocket_utils import broadcast_log, queue_log_for_broadcast

def start_app(service_id: str, log_service_id: Optional[str] = None) -> str:
    # Use log_service_id if provided, otherwise use service_id
    broadcast_to = log_service_id or service_id
    
    # Safe broadcast function for sync context
    def safe_broadcast(service_id: str, log_type: str, message: str, data: Optional[dict] = None):
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(broadcast_log(service_id, log_type, message, data))
        except RuntimeError:
            # No running loop - queue for later processing
            queue_log_for_broadcast(service_id, log_type, message, data)
            print(f"[LOG] Queued for broadcast - {log_type}: {message}")
        except Exception as e:
            print(f"[WebSocket Error] Failed to broadcast {log_type}: {e}")
    
    # Broadcast start of app startup
    safe_broadcast(
        broadcast_to,
        "app_start",
        "🚀 Starting React application...",
        {"service_id": service_id}
    )
    
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        error_msg = "KOYEB_API_TOKEN not set"
        safe_broadcast(broadcast_to, "app_error", f"❌ {error_msg}")
        raise ValueError(error_msg)

    try: 
        # Broadcast vite config update
        safe_broadcast(
            broadcast_to,
            "file_operation",
            "📝 Updating Vite configuration...",
            {"file_path": "/tmp/my-project/vite.config.js"}  # Fixed path
        )
        
        sandbox_url = get_sandbox_url(service_id)
        
        # Fixed the f-string syntax
        code = f"""import {{ defineConfig }} from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({{
  plugins: [react()],
  server: {{
    host: '0.0.0.0',
    port: 80,
    allowedHosts: ['{sandbox_url.split('//')[1].split(':')[0]}']
  }}
}})"""
        
        update_vite = create_file_and_add_code(service_id, '/tmp/my-project/vite.config.js', code)  # Fixed path
        
        safe_broadcast(
            broadcast_to,
            "file_complete",
            "✅ Vite configuration updated successfully"
        )
        
        # Broadcast server start
        safe_broadcast(
            broadcast_to,
            "server_start", 
            "🎯 Starting development server on port 80...",
            {"port": 80, "command": "npm run dev"}
        )
        
        # Note: This run_command will also broadcast its own logs
        start_server = run_command(
            service_id, 
            'cd /tmp/my-project && npm run dev -- --host 0.0.0.0 --port 80',
            log_service_id=log_service_id  # Pass through log routing
        )
        
        safe_broadcast(
            broadcast_to,
            "app_complete",
            "🎉 React application started successfully!",
            {"server_output": start_server[:200]}  # First 200 chars of output
        )
        
        return f"Vite Update: {update_vite}\nServer Start: {start_server}\nRunning at {sandbox_url}"
        
    except Exception as e:
        error_msg = f"Failed to start app: {str(e)}"
        safe_broadcast(
            broadcast_to,
            "app_error", 
            f"❌ {error_msg}",
            {"error": str(e)}
        )
        return f"Error: {str(e)}"

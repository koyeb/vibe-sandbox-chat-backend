from koyeb import Sandbox
import os
import asyncio
from typing import Optional
from generate_files import create_file_and_add_code
from run_command import run_command
from get_sandbox_url import get_sandbox_url
from expose_endpoint import expose_endpoint
from utils.websocket_utils import broadcast_log, queue_log_for_broadcast
from run_background_command import run_background_command

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
        # Step 0: Check if something is already running on port 80
        safe_broadcast(
            broadcast_to,
            "port_check",
            "🔍 Checking if port 80 is already in use...",
            {"port": 80}
        )
        
        # Check for existing processes using port 80
        port_check_command = "lsof -ti:80 || echo 'Port 80 is free'"
        port_check_result = run_command(service_id, port_check_command, log_service_id=broadcast_to)
        
        # Also check running processes for npm/vite
        sandbox = Sandbox.get_from_id(service_id, api_token=api_token)
        processes = sandbox.list_processes()
        vite_already_running = False
        existing_process = None
        
        for process in processes:
            if process.status == "running" and ('npm run dev' in process.command or 'vite' in process.command.lower()):
                vite_already_running = True
                existing_process = process
                print(f"Found existing Vite process: {process.id} - Status: {process.status}")
                break
        
        if vite_already_running:
            safe_broadcast(
                broadcast_to,
                "server_exists",
                "ℹ️ Development server is already running on port 80",
                {"process_id": existing_process.id, "status": existing_process.status}
            )
            
            # Get the public URL
            sandbox_url = get_sandbox_url(service_id)
            
            safe_broadcast(
                broadcast_to,
                "app_complete",
                f"✅ React application already accessible at {sandbox_url}",
                {"url": sandbox_url, "process_id": existing_process.id}
            )
            
            return f"""ℹ️ React app is already running!

Dev Server: running
Process ID: {existing_process.id}
Public URL: {sandbox_url}

Your app is already accessible at: {sandbox_url}"""
        
        safe_broadcast(
            broadcast_to,
            "port_available",
            "✅ Port 80 is available, proceeding with startup...",
            {"port": 80}
        )
        
        # Step 1: Update Vite config with allowedHosts: true
        safe_broadcast(
            broadcast_to,
            "file_operation",
            "📝 Updating Vite configuration...",
            {"file_path": "/tmp/my-project/vite.config.js"}
        )
        
        # Enable external access with allowedHosts: true
        code = """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 80,
    strictPort: true,
    allowedHosts: true
  }
})"""
        
        update_vite = create_file_and_add_code(service_id, '/tmp/my-project/vite.config.js', code)
        
        safe_broadcast(
            broadcast_to,
            "file_complete",
            "✅ Vite configuration updated successfully"
        )
        
        # Step 2: Expose port 80 BEFORE starting the server
        safe_broadcast(
            broadcast_to,
            "expose_start",
            "🌐 Exposing port 80 for external access...",
            {"port": 80}
        )
        
        expose_result = expose_endpoint(service_id, 80)
        print(f"Port exposure result: {expose_result}")
        
        safe_broadcast(
            broadcast_to,
            "expose_complete",
            f"✅ Port 80 exposed successfully",
            {"expose_result": expose_result}
        )
        
        # Step 3: Start the dev server IN THE BACKGROUND
        safe_broadcast(
            broadcast_to,
            "server_start", 
            "🎯 Starting development server on port 80...",
            {"port": 80, "command": "npm run dev"}
        )

        # Use the background command runner
        start_result = run_background_command(
            service_id, 
            'cd /tmp/my-project && npm run dev -- --host 0.0.0.0 --port 80',
            log_service_id=log_service_id
        )

        print(f"Background server start result: {start_result}")

        # Give the server a moment to start
        safe_broadcast(
            broadcast_to,
            "server_starting",
            "⏳ Waiting for server to initialize...",
            {"wait_time": "3 seconds"}
        )

        import time
        time.sleep(3)

        # Check if process is still running
        sandbox = Sandbox.get_from_id(service_id, api_token=api_token)
        processes = sandbox.list_processes()
        vite_process = None
        process_status = "unknown"
        
        for process in processes:
            if 'npm run dev' in process.command or 'vite' in process.command.lower():
                vite_process = process
                process_status = process.status
                print(f"Found Vite process: {process.id} - Status: {process.status}")
                break

        if vite_process and vite_process.status == "running":
            safe_broadcast(
                broadcast_to,
                "server_ready",
                "✅ Development server is running",
                {"process_id": vite_process.id, "status": vite_process.status}
            )
        else:
            safe_broadcast(
                broadcast_to,
                "server_warning",
                "⚠️ Server may still be starting...",
                {"status": process_status}
            )
        
        # Step 4: Get the public URL
        sandbox_url = get_sandbox_url(service_id)
        
        safe_broadcast(
            broadcast_to,
            "app_complete",
            f"🎉 React application started and accessible at {sandbox_url}",
            {"url": sandbox_url, "process_id": vite_process.id if vite_process else None}
        )
        
        return f"""✅ React app deployed successfully!

Vite Config: Updated with external access enabled
Port 80: {expose_result}
Dev Server: {process_status}
Process ID: {vite_process.id if vite_process else 'Unknown'}
Public URL: {sandbox_url}

Access your app at: {sandbox_url}

Background process started: {start_result}"""
        
    except Exception as e:
        error_msg = f"Failed to start app: {str(e)}"
        print(f"[ERROR] {error_msg}")
        import traceback
        traceback.print_exc()
        
        safe_broadcast(
            broadcast_to,
            "app_error", 
            f"❌ {error_msg}",
            {"error": str(e)}
        )
        return f"Error: {str(e)}"

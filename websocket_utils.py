import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import WebSocket
from queue import Queue
import threading

# Store active log connections per serviceId
log_connections: Dict[str, List[WebSocket]] = {}

# Queue for logs from sync contexts
log_queue: Queue = Queue()

async def broadcast_log(service_id: str, log_type: str, message: str, data: Optional[Dict[str, Any]] = None):
    """Broadcast log messages to all connected log clients for a service"""
    
    if service_id not in log_connections:
        return
    
    # Use Dict[str, Any] to allow mixed value types
    log_message: Dict[str, Any] = {
        "type": log_type,
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "service_id": service_id
    }
    
    if data is not None:
        log_message["data"] = data
    
    # Send to all connected log clients for this service
    disconnected = []
    successful_sends = 0
    
    for websocket in log_connections[service_id]:
        try:
            await websocket.send_json(log_message)
            successful_sends += 1
        except Exception as e:
            disconnected.append(websocket)
        
    # Remove disconnected websockets
    for ws in disconnected:
        log_connections[service_id].remove(ws)

def queue_log_for_broadcast(service_id: str, log_type: str, message: str, data: Optional[Dict[str, Any]] = None):
    """Queue a log message for broadcasting from sync context"""
    log_item = {
        "service_id": service_id,
        "log_type": log_type,
        "message": message,
        "data": data,
        "timestamp": datetime.now().isoformat()
    }
    log_queue.put(log_item)

async def process_queued_logs():
    """Process queued logs and broadcast them"""
    processed_count = 0
    
    while not log_queue.empty():
        try:
            log_item = log_queue.get_nowait()
            await broadcast_log(
                log_item["service_id"],
                log_item["log_type"], 
                log_item["message"],
                log_item["data"]
            )
            processed_count += 1
        except Exception as e:
            break  # Stop processing on error
    
    if processed_count > 0:
        print(f"[WebSocket Debug] Processed {processed_count} queued logs")

def add_log_connection(service_id: str, websocket: WebSocket):
    """Add a websocket connection to the log connections"""
    if service_id not in log_connections:
        log_connections[service_id] = []
    log_connections[service_id].append(websocket)

def remove_log_connection(service_id: str, websocket: WebSocket):
    """Remove a websocket connection from log connections"""
    if service_id in log_connections:
        if websocket in log_connections[service_id]:
            log_connections[service_id].remove(websocket)
        if not log_connections[service_id]:
            del log_connections[service_id]

def get_queue_size():
    """Get current queue size for debugging"""
    return log_queue.qsize()
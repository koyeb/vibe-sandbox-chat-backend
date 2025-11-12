import asyncio
from typing import Optional, Union, List, Any
from pydantic import BaseModel
from huggingface_hub import InferenceClient

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import os
from datetime import datetime

from sandbox_agent import process_chat_with_tools, tools 
from delete_sandbox import delete_sandbox
from websocket_utils import broadcast_log, add_log_connection, remove_log_connection, log_connections, process_queued_logs, get_queue_size

app = FastAPI()
HF_TOKEN = os.getenv("HF_TOKEN")
print(f"Using HF_TOKEN: {HF_TOKEN}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

class Message(BaseModel):
    role: str  # "user", "assistant", or "system"
    content: str

class ChatRequest(BaseModel):
    model: str = "Qwen/Qwen2.5-7B-Instruct"
    messages: List[Message]
    serviceId: Optional[str] = None

class DeleteRequest(BaseModel):
    serviceId: str

AVAILABLE_MODELS = {
  "Qwen/Qwen2.5-7B-Instruct": "Qwen 2.5 7B Instruct",
  "meta-llama/Llama-3.1-8B-Instruct": "Llama 3.1 8B Instruct",
  "meta-llama/Llama-3.1-70B-Instruct": "Llama 3.1 70B Instruct",
  "meta-llama/Llama-3.3-70B-Instruct": "Llama 3.3 70B Instruct",
  "google/gemma-2-9b-it": "Gemma 2 9B It",
  "mistralai/Mistral-7B-Instruct-v0.3": "Mistral 7B Instruct v0.3",
}

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.post("/chat")
def generate_chat(request: ChatRequest):
    client = InferenceClient(request.model, token=HF_TOKEN)
    messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    print(f"serviceId: {request.serviceId}")
    print(f"model: {request.model}")
    
    # Add serviceId to system prompt if provided
    if request.serviceId:
        messages_dict.insert(0, {"role": "system", "content": f"The current service ID is {request.serviceId}. Use this ID when creating files in the sandbox."})

    # Remove the websocket parameter
    result = process_chat_with_tools(
        client=client,
        messages_dict=messages_dict,
        tools=tools,
        service_id=request.serviceId,
        max_iterations=10,
        log_service_id=request.serviceId  # Keep this for log routing
    )
    
    # Add additional metadata for API response
    result.update({
        "model": request.model,
        "message_count": len(request.messages)
    })
    
    return result

@app.get("/file-structure")
def get_file_structure(serviceId: str):
    from run_command import run_command
    
    # Exclude node cache and show actual project files
    command = "find /tmp -type f -o -type d | grep -v node-compile-cache | head -50"
    output = run_command(serviceId, command)
    return {"file_structure": output}

@app.post("/delete-sandbox")
def delete_sandbox_request(request: DeleteRequest):
    delete_sandbox(request.serviceId)
    return {"message": f"Sandbox with ID {request.serviceId} has been deleted."}

# Websocket endpoint that updates the client when any logs are generated on the server side
@app.websocket("/ws/logs/{serviceId}")
async def websocket_logs_endpoint(websocket: WebSocket, serviceId: str):
    """Dedicated endpoint for streaming tool execution logs"""
    await websocket.accept()
    
    # Add this connection using the utility function
    add_log_connection(serviceId, websocket)
    
    # Local heartbeat counter for this connection
    heartbeat_counter = 0
    
    try:
        await websocket.send_json({
            "type": "connection_status",
            "message": f"📡 Connected to sandbox {serviceId} logs"
        })
        
        # Keep connection alive and process queued logs
        while True:
            # Process any queued logs from sync contexts
            await process_queued_logs()
            
            await asyncio.sleep(1)  # Check for logs every second
            
            # Increment heartbeat counter
            heartbeat_counter += 1
                
            # Send heartbeat every 30 iterations (30 seconds)
            if heartbeat_counter >= 30:
                await websocket.send_json({
                    "type": "heartbeat", 
                    "message": "💓 Connection alive"
                })
                heartbeat_counter = 0  # Reset counter
            
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"❌ Log stream error: {str(e)}"
            })
        except:
            pass
    finally:
        # Remove connection using the utility function
        remove_log_connection(serviceId, websocket)
        await websocket.close()

@app.websocket("/ws/chat/{serviceId}")
async def websocket_chat_endpoint(websocket: WebSocket, serviceId: str):
    """Dedicated endpoint for chat responses only"""
    await websocket.accept()
    
    try:
        while True:
            # Receive chat request from client
            data = await websocket.receive_json()
            
            # Send typing indicator
            await websocket.send_json({
                "type": "typing",
                "message": "Assistant is thinking..."
            })
            
            # Extract chat parameters
            model = data.get("model", "Qwen/Qwen2.5-7B-Instruct")
            messages = data.get("messages", [])
            
            client = InferenceClient(model, token=HF_TOKEN)
            messages_dict = [{"role": msg["role"], "content": msg["content"]} for msg in messages]
            
            # Add serviceId to system prompt
            if serviceId:
                messages_dict.insert(0, {"role": "system", "content": f"The current service ID is {serviceId}. Use this ID when creating files in the sandbox."})

            # Process chat with tools (logs will go to separate log connections)
            result = process_chat_with_tools(
                client=client,
                messages_dict=messages_dict,
                tools=tools,
                service_id=serviceId,
                max_iterations=5,
                log_service_id=serviceId  # Pass serviceId for log routing
            )
            
            # Send only the chat response (no logs)
            await websocket.send_json({
                "type": "assistant_response",
                "message": result.get("response", ""),
                "metadata": {
                    "model": model,
                    "message_count": len(messages),
                    "tool_calls": result.get("tool_calls_made", 0)
                }
            })
            
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": f"❌ Chat error: {str(e)}"
        })
    finally:
        await websocket.close()

@app.get("/debug/queue-status")
def get_queue_status():
    """Debug endpoint to check log queue status"""
    return {
        "queue_size": get_queue_size(),
        "active_connections": {
            service_id: len(connections) 
            for service_id, connections in log_connections.items()
        }
    }

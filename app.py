import asyncio
from typing import Optional, List, AsyncGenerator
from pydantic import BaseModel
from huggingface_hub import InferenceClient
import json

from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os

# Import model configuration
from model_config import AVAILABLE_MODELS, MODEL_ROUTING

# Fix the import - make sure this function exists and is properly imported
try:
    from get_sandbox_url import get_sandbox_url
except ImportError as e:
    print(f"Warning: Could not import get_sandbox_url: {e}")
    def get_sandbox_url(service_id: str) -> str:
        """Fallback function if import fails"""
        return f"https://sandbox-{service_id}.koyeb.app"

from sandbox_agent import process_chat_with_tools_streaming, tools 
from delete_sandbox import delete_sandbox
from websocket_utils import add_log_connection, remove_log_connection, log_connections, process_queued_logs, get_queue_size

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

@app.get("/")
def read_root():
    return {"Hello": "World"}

# Helper function to create InferenceClient based on model routing
def create_inference_client(model: str) -> tuple[InferenceClient, Optional[str]]:
    """
    Create an InferenceClient for the given model.
    Returns (client, endpoint_url) where endpoint_url is None for local models.
    """
    if model in MODEL_ROUTING:
        # External endpoint
        endpoint_config = MODEL_ROUTING[model]
        client = InferenceClient(model=endpoint_config["endpoint"], token=HF_TOKEN)
        return client, endpoint_config["endpoint"]
    else:
        # Local HF model
        client = InferenceClient(model, token=HF_TOKEN)
        return client, None

@app.post("/chat")
async def generate_chat(request: ChatRequest):
    """Streaming chat endpoint"""
    
    async def event_generator() -> AsyncGenerator[str, None]:
        # Create client based on model routing
        client, endpoint_url = create_inference_client(request.model)
        
        if endpoint_url:
            print(f"Using external endpoint for {request.model}: {endpoint_url}")
        else:
            print(f"Using local HF Inference API for {request.model}")
        
        # Prepare messages
        messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        try:
            # Stream the response
            async for chunk in process_chat_with_tools_streaming(
                client=client,
                messages_dict=messages_dict,
                tools=tools,
                service_id=request.serviceId,
                max_iterations=10,
                log_service_id=request.serviceId,
                model=request.model
            ):
                # Send as Server-Sent Events (SSE) format
                yield f"data: {json.dumps(chunk)}\n\n"
                
        except Exception as e:
            print(f"Error processing chat: {e}")
            error_chunk = {
                "type": "error",
                "error": str(e),
                "model": request.model,
                "message": f"Error connecting to {request.model}" + (f" endpoint ({endpoint_url})" if endpoint_url else "")
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
        
        # Send final done message
        done_chunk = {
            "type": "done",
            "model": request.model
        }
        yield f"data: {json.dumps(done_chunk)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )

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
    print(f"New WebSocket log connection for serviceId: {serviceId}")
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
            print(f"WebSocket log connection error for {serviceId}: {e}")
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

@app.get("/url/{serviceId}")
def get_service_url(serviceId: str):
    """Get the URL for a specific service"""
    try:
        url = get_sandbox_url(serviceId)
        return {"url": url}
    except Exception as e:
        print(f"Error getting sandbox URL for {serviceId}: {e}")
        return {
            "url": None,
            "error": f"Could not retrieve URL for service {serviceId}: {str(e)}"
        }

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

@app.get("/models")
def get_models():
    """Get available models with routing information"""
    return {
        "models": AVAILABLE_MODELS,
        "routing": {
            "local": [model for model in AVAILABLE_MODELS.keys() if model not in MODEL_ROUTING],
            "external": {
                model: config["endpoint"] 
                for model, config in MODEL_ROUTING.items()
            }
        }
    }



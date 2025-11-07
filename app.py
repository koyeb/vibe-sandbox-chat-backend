from typing import Optional, Union, List, Any
from pydantic import BaseModel
from huggingface_hub import InferenceClient

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from sandbox_agent import process_chat_with_tools, tools 
from delete_sandbox import delete_sandbox

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
  "meta-llama/Meta-Llama-3.1-8B-Instruct": "Meta Llama 3.1 8B Instruct",
  "meta-llama/Llama-3.1-70B-Instruct": "Llama 3.1 70B Instruct",
  "google/gemma-2-9b-it": "Gemma 2 9B It",
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

    # Use the abstracted function from sandbox_agent
    result = process_chat_with_tools(
        client=client,
        messages_dict=messages_dict,
        tools=tools,
        service_id=request.serviceId,
        max_iterations=5
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
async def websocket_logs_endpoint(websocket, serviceId: str):
    from koyeb import Sandbox
    import os
    import asyncio

    await websocket.accept()
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        await websocket.send_text("Error: KOYEB_API_TOKEN not set")
        await websocket.close()
        return
    sandbox = Sandbox.get_from_id(serviceId, api_token=api_token)
    if not sandbox:
        await websocket.send_text(f"Error: Sandbox with ID {serviceId} not found")
        await websocket.close()
        return 
    try:
        while True:
            # logs = sandbox.get_logs(tail=10)
            # for log in logs:
            #     await websocket.send_text(log)
            await asyncio.sleep(5)  # Poll every 5 seconds
    except Exception as e:
        await websocket.send_text(f"Error: {str(e)}")
    finally:
        await websocket.close()

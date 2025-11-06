from typing import Optional, Union, List, Any
from pydantic import BaseModel
from huggingface_hub import InferenceClient

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from sandbox_agent import process_chat_with_tools, tools 
from delete_sandbox import delete_sandbox

app = FastAPI()
# MODEL_URL = os.getenv("MODEL_URL", "Qwen/Qwen2.5-7B-Instruct") 
MODEL_URL = "Qwen/Qwen2.5-7B-Instruct"
HF_TOKEN = os.getenv("HF_TOKEN")
print(f"Using HF_TOKEN: {HF_TOKEN}")
print(f"Using MODEL_URL: {MODEL_URL}")
client = InferenceClient(MODEL_URL, token=HF_TOKEN) 

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
}

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.post("/chat")
def generate_chat(request: ChatRequest):
    messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    print(f"serviceId: {request.serviceId}")
    # Add serviceId to system prompt if provided
    if request.serviceId:
        messages_dict.insert(0, {"role": "system", "content": f"The current service ID is {request.serviceId}. Use this ID when creating files in the sandbox."})
        print(f"Using service ID: {request.serviceId}")

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

@app.post("/delete-sandbox")
def delete_sandbox_request(request: DeleteRequest):
    delete_sandbox(request.serviceId)
    return {"message": f"Sandbox with ID {request.serviceId} has been deleted."}
    


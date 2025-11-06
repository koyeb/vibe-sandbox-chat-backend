from typing import Optional, Union, List, Any
from pydantic import BaseModel
from huggingface_hub import InferenceClient

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI()
import os
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

    # Add serviceId to system prompt if provided
    if request.serviceId:
        messages_dict.insert(0, {"role": "system", "content": f"The current service ID is {request.serviceId}. Use this ID when creating files in the sandbox."})

    all_tool_results = []
    conversation_messages = messages_dict.copy()
    max_iterations = 5  # Prevent infinite loops
    current_service_id = request.serviceId  # Track service ID

    try:
        for iteration in range(max_iterations):
            print(f"Iteration {iteration + 1}")
            
            response = client.chat_completion(
                messages=conversation_messages,
                tools=tools,
            )
            
            if not response.choices:
                return {"error": "No response from model"}
            
            message = response.choices[0].message
            
            # Check if the model wants to use tools
            if hasattr(message, 'tool_calls') and message.tool_calls:
                print(f"Model requested {len(message.tool_calls)} tool calls")
                
                # Add assistant message
                assistant_message = {
                    "role": "assistant", 
                    "content": message.content or ""
                }
                conversation_messages.append(assistant_message)
                
                # Execute each tool call and add results to conversation
                for tool_call in message.tool_calls:
                    result = execute_tool_call(tool_call)
                    
                    # Extract sandbox_id if this was a create_sandbox_client call
                    if tool_call.function.name == "create_sandbox_client" and isinstance(result, dict) and "result" in result:
                        sandbox_result = result["result"]
                        # sandbox_result is already the service_id string, not a dict with "id" field
                        if isinstance(sandbox_result, str):
                            current_service_id = sandbox_result
                            print(f"Created new sandbox with ID: {current_service_id}")
                    
                    # Store results for final response
                    all_tool_results.append({
                        "tool_call_id": tool_call.id,
                        "function_name": tool_call.function.name,
                        "result": result
                    })
                    
                    # Add tool result to conversation for next iteration
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result)
                    }
                    conversation_messages.append(tool_message)
                
                # Continue to next iteration
                continue
            
            else:
                # No more tool calls - return final response
                return {
                    "content": message.content,
                    "service_id": current_service_id,  # Include sandbox_id
                    "tool_calls": all_tool_results if all_tool_results else None,
                    "tool_results": all_tool_results,
                    "model": request.model,
                    "message_count": len(request.messages),
                    "iterations": iteration + 1
                }
        
        # If we hit max iterations
        return {
            "content": "Maximum tool call iterations reached",
            "service_id": current_service_id,  # Include service_id
            "tool_calls": all_tool_results if all_tool_results else None,
            "tool_results": all_tool_results,
            "model": request.model,
            "message_count": len(request.messages),
            "iterations": max_iterations,
            "warning": "Stopped due to iteration limit"
        }
            
    except Exception as e:
        print(f"Error in conversation loop: {e}")
        return {
            "error": f"Error during tool execution: {str(e)}",
            "sandbox_id": current_service_id,  # Include sandbox_id even in errors
            "tool_results": all_tool_results
        }


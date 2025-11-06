from typing import Optional, Union, List, Any
from pydantic import BaseModel
from huggingface_hub import InferenceClient


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os

from koyeb import Sandbox
# import prompt.md as a string 
with open("prompt.md", "r") as f:
    PROMPT = f.read()

with open("create-sandbox.md", "r") as f:
    CREATE_SANDBOX_PROMPT = f.read()

app = FastAPI()
# define the value of MODEL_URL from environment variable or default
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
    sandboxId: Optional[str] = None

AVAILABLE_MODELS = {
  "Qwen/Qwen2.5-7B-Instruct": "Qwen 2.5 7B Instruct",
  "meta-llama/Meta-Llama-3.1-8B-Instruct": "Meta Llama 3.1 8B Instruct",
}

# Function to handle tool calls
def execute_tool_call(tool_call):
    """Execute a tool call and return the result"""
    function_name = tool_call.function.name
    arguments = tool_call.function.arguments
    
    # Parse arguments if they're a JSON string
    if isinstance(arguments, str):
        import json
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON arguments: {arguments}"}
    
    # Dispatch to the appropriate function
    if function_name == "create_sandbox_client":
        result = create_sandbox_client(
            image=arguments.get("image", "koyeb/sandbox"),
            name=arguments.get("name", "example-sandbox")
        )
        return {"result": result}
    
    elif function_name == "create_file_and_add_code":
        result = create_file_and_add_code(
            sandbox_id=arguments.get("sandbox_id"),
            file_path=arguments.get("file_path"),
            code=arguments.get("code")
        )
        return {"result": result}
    
    else:
        return {"error": f"Unknown function: {function_name}"}

def create_sandbox_client(image: str = "koyeb/sandbox", name: str = "example-sandbox"):
    api_token = os.getenv("KOYEB_API_TOKEN")
    print(api_token)
    if not api_token:
        print("Error: KOYEB_API_TOKEN not set")
        return

    sandbox = None
    try:
        sandbox = Sandbox.create(
            image=image,
            name=name,
            wait_ready=True,
            api_token=api_token,
        )

        # Check status
        status = sandbox.status()
        is_healthy = sandbox.is_healthy()
        print(f"Status: {status}, Healthy: {is_healthy}")

        # Test command
        result = sandbox.exec("echo 'Sandbox is ready!'")
        print(result.stdout.strip())
        return sandbox.sandbox_id

    except Exception as e:
        print(f"Error: {e}")

def create_file_and_add_code(sandbox_id: str, file_path: str, code: str):
    print(f"Creating file at {file_path} in sandbox {sandbox_id} with code:\n{code}")
    api_token = os.getenv("KOYEB_API_TOKEN")
    if not api_token:
        print("Error: KOYEB_API_TOKEN not set")
        return

    sandbox = None
    try:
        sandbox = Sandbox.get_from_id(sandbox_id, api_token=api_token)

        fs = sandbox.filesystem

        # Write file
        fs.write_file(file_path, code)

        # Read file
        file_info = fs.read_file(file_path)
        print(file_info.content)

        # Write Python script
        # python_code = "#!/usr/bin/env python3\nprint('Hello from Python!')\n"
        # fs.write_file("/tmp/script.py", python_code)
        # sandbox.exec("chmod +x /tmp/script.py")
        # result = sandbox.exec("/tmp/script.py")
        # print(result.stdout.strip())
        return f"File created at {file_path} and code added successfully."
    except Exception as e:
        print(f"Error: {e}")

# Tools defined for use with the HuggingFace InferenceClient
tools: List[Any] = [
    {
        "type": "function",
        "function": {
            "name": "create_sandbox_client",
            # "description": "Create a new Koyeb sandbox client. Use only once at the start of a session. If a user makes a request that requires a sandbox and one does not yet exist, first call this function to create one. This function returns the sandbox_id which can be used for subsequent file operations.",
            "description": CREATE_SANDBOX_PROMPT,
            "parameters": {
                "type": "object",
                "properties": {
                    "image": {
                        "type": "string",
                        "description": "The name of the sandbox image to use. Defaults to koyeb/sandbox",
                    },
                    "name": {
                        "type": "string",
                        "description": "The name of the sandbox instance, defaults to example-sandbox",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file_and_add_code",
            "description": "Create a new file in the sandbox and add code to it. If you don't yet have a sandbox, first call create_sandbox_client to create one. Use this to create or modify files within the sandbox at the user's request",
            "parameters": {
                "type": "object",
                "properties": {
                    "sandbox_id": {
                        "type": "string",
                        "description": "The ID of the sandbox to use, as returned by create_sandbox_client or provided by the user.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to create or modify within the sandbox.",
                    },
                    "code": {
                        "type": "string",
                        "description": "The code content to write into the file.",
                    },
                },
                "required": ["sandbox_id", "file_path", "code"],
            },
        },
    }
]

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.post("/chat")
def generate_chat(request: ChatRequest):
    messages_dict = [{"role": msg.role, "content": msg.content} for msg in request.messages]
    # add sandboxId to system prompt if provided
    if request.sandboxId:
        messages_dict.insert(0, {"role": "system", "content": f"The current sandbox ID is {request.sandboxId}. Use this ID when creating files in the sandbox."})
    try:
        # First try with tools enabled
        response = client.chat_completion(
            messages=messages_dict,
            tools=tools,
        )
        
        print(f"Response: {response}")
        
        if response.choices:
            message = response.choices[0].message
            
            # Check if the model wants to use tools
            if hasattr(message, 'tool_calls') and message.tool_calls:
                # Execute each tool call
                tool_results = []
                for tool_call in message.tool_calls:
                    result = execute_tool_call(tool_call)
                    tool_results.append({
                        "tool_call_id": tool_call.id,
                        "function_name": tool_call.function.name,
                        "result": result
                    })
                
                return {
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                    "tool_results": tool_results,
                    "model": request.model,
                    "message_count": len(request.messages),
                }
            else:
                return {
                    "content": message.content,
                    "tool_calls": None,
                    "model": request.model,
                    "message_count": len(request.messages),
                }
        else:
            return {"error": "No response from model"}
            
    except Exception as e:
        print(f"Error with tools: {e}")
        # If the server doesn't support tool_choice="auto", try without tool_choice
        try:
            response = client.chat_completion(
                messages=messages_dict,
                tools=tools,
            )
            # Handle response same as above...
            if response.choices:
                message = response.choices[0].message
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    tool_results = []
                    for tool_call in message.tool_calls:
                        result = execute_tool_call(tool_call)
                        tool_results.append({
                            "tool_call_id": tool_call.id,
                            "function_name": tool_call.function.name,
                            "result": result
                        })
                    
                    return {
                        "content": message.content,
                        "tool_calls": message.tool_calls,
                        "tool_results": tool_results,
                        "model": request.model,
                        "message_count": len(request.messages),
                    }
                else:
                    return {
                        "content": message.content,
                        "tool_calls": None,
                        "model": request.model,
                        "message_count": len(request.messages),
                        "note": "Model chose not to use tools"
                    }
        except Exception as fallback_error:
            return {"error": f"Tool error: {str(e)}. Fallback error: {str(fallback_error)}"}


@app.get("/test")
def read_item():
    create_sandbox_client()
    return "done"


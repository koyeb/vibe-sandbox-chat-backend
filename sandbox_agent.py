from typing import Optional, Union, List, Any
import time
import asyncio

from koyeb import Sandbox
from create_sandbox import create_sandbox_client
from get_sandbox_url import get_sandbox_url
from generate_files import create_file_and_add_code
from run_command import run_command

with open("prompt.md", "r") as f:
    PROMPT = f.read()
with open("create-sandbox.md", "r") as f:
    CREATE_SANDBOX_PROMPT = f.read()
with open("generate-files.md", "r") as f:
    GENERATE_FILES_PROMPT = f.read()
with open("get-sandbox-url.md", "r") as f:
    GET_SANDBOX_URL_PROMPT = f.read()
with open("run-command.md", "r") as f:
    RUN_COMMAND_PROMPT = f.read()

def is_provisioning_error(error_message):
    """Check if error indicates sandbox is still provisioning"""
    error_str = str(error_message).lower()
    return ("could not find instance for sandbox" in error_str and 
            "the sandbox may not be fully provisioned yet" in error_str)

def execute_with_retry(func, *args, **kwargs):
    """Execute a function with retry logic for provisioning errors"""
    max_retries = 2
    retry_delay = 15  # seconds
    
    for attempt in range(max_retries + 1):  # 0, 1, 2 (3 total attempts)
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if is_provisioning_error(str(e)) and attempt < max_retries:
                print(f"Sandbox provisioning error detected (attempt {attempt + 1}/{max_retries + 1}). Retrying in {retry_delay} seconds...")
                print(f"Error: {e}")
                time.sleep(retry_delay)
                continue
            else:
                # Either not a provisioning error, or we've exhausted retries
                raise e

def process_chat_with_tools(client, messages_dict, tools, service_id=None, max_iterations=5):
    """
    Process a chat conversation with tool calling capabilities
    """
    print(f"Starting chat processing with service_id: {service_id}")
    all_tool_results = []
    current_service_id = service_id
    conversation_messages = messages_dict.copy()
    consecutive_errors = 0  # Track consecutive errors
    
    # Create system prompt with clear tool instructions
    if current_service_id:
        system_prompt = f"""You are a helpful coding assistant that can create and manage sandboxes.

IMPORTANT: You already have access to sandbox with service_id: {current_service_id}
DO NOT create a new sandbox - use the existing one.

The sandbox that you have access to is built with Go and packaged as a Docker container based on Ubuntu 22.04. It includes common utilities like curl, wget, git, python3, and jq, making it suitable for various automation and testing scenarios. If you need additional software, you should install it using standard package managers like apt. For example, to install Node.js and npm, you can run:
```
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash

```
Be sure to reload the current shell environment after installing new software to ensure all environment variables are set correctly.
AVAILABLE TOOLS ONLY:
1. create_file_and_add_code - Create or modify files in the sandbox. If creating files in directories, first ensure the directory exists by using run_command to create it if needed.
2. run_command - Execute shell commands in the sandbox. When creating files, you may need to run commands to install dependencies or start services, and when creating a new project, first use this to make a new working directory that any files will be in, ex mkdir -p /tmp/my_project/src. Use -y in commands as needed for automatic yes to prompts.
3. get_sandbox_url - Get the sandbox URL

DO NOT try to call any other tools. Only use the tools listed above.
If you try to call a non-existent tool, you will get an error.

If a specific type of application is requested, ensure you set it up correctly by running any standard initialization commands *first* and installing dependencies before creating necessary files."""
    else:
        system_prompt = f"""You are a helpful coding assistant that can create and manage sandboxes.

AVAILABLE TOOLS ONLY:
1. create_sandbox_client - Create a new sandbox (use first if no sandbox exists)
2. create_file_and_add_code - Create or modify files in a sandbox  
3. run_command - Execute shell commands in a sandbox
4. get_sandbox_url - Get the sandbox URL

DO NOT try to call any other tools. Only use the tools listed above.
If you try to call a non-existent tool, you will get an error."""

    conversation_messages.insert(0, {"role": "system", "content": system_prompt})

    try:
        for iteration in range(max_iterations):
            print(f"Iteration {iteration + 1}")
            
            # Stop if we have too many consecutive errors
            if consecutive_errors >= 2:
                return {
                    "content": "I encountered repeated errors trying to call tools. I'll stop here to avoid further issues.",
                    "service_id": current_service_id,
                    "tool_calls": all_tool_results if all_tool_results else None,
                    "tool_results": all_tool_results,
                    "iterations": iteration + 1,
                    "error": "Too many consecutive tool errors",
                    "success": False
                }
            
            response = client.chat_completion(
                messages=conversation_messages,
                tools=tools,
            )
            
            if not response.choices:
                return {"error": "No response from model"}
            
            message = response.choices[0].message
            print(f"Assistant message: {message.content}")
            
            # Check if the model wants to use tools
            if hasattr(message, 'tool_calls') and message.tool_calls:
                print(f"Model requested {len(message.tool_calls)} tool calls")
                print(f"Tool calls: {[tool_call.function.name for tool_call in message.tool_calls]}")
                
                # Add assistant message
                assistant_message = {
                    "role": "assistant", 
                    "content": message.content or f"I'm going to call {len(message.tool_calls)} tool(s) to help you."
                }
                conversation_messages.append(assistant_message)
                
                # Execute each tool call
                has_errors = False
                for tool_call in message.tool_calls:
                    result = execute_tool_call(tool_call, current_service_id)
                    print(f"Tool {tool_call.function.name} result: {result}")
                    
                    # Check for errors
                    if isinstance(result, dict) and "error" in result:
                        has_errors = True
                        print(f"Tool error: {result['error']}")
                    
                    # Extract service_id if this was a create_sandbox_client call
                    if tool_call.function.name == "create_sandbox_client" and isinstance(result, dict) and "result" in result:
                        sandbox_result = result["result"]
                        if isinstance(sandbox_result, str):
                            current_service_id = sandbox_result
                            print(f"Created new sandbox with ID: {current_service_id}")
                    
                    # Store results for final response
                    all_tool_results.append({
                        "tool_call_id": tool_call.id,
                        "function_name": tool_call.function.name,
                        "result": result
                    })
                    
                    # Add tool result to conversation
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result)
                    }
                    conversation_messages.append(tool_message)
                
                # Update error counter
                if has_errors:
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0  # Reset on success
                
                continue
            
            else:
                # No more tool calls - return final response
                consecutive_errors = 0  # Reset on normal completion
                return {
                    "content": message.content,
                    "service_id": current_service_id,
                    "tool_calls": all_tool_results if all_tool_results else None,
                    "tool_results": all_tool_results,
                    "iterations": iteration + 1,
                    "success": True
                }
        
        # If we hit max iterations
        return {
            "content": "I've completed as much as I could within the iteration limit.",
            "service_id": current_service_id,
            "tool_calls": all_tool_results if all_tool_results else None,
            "tool_results": all_tool_results,
            "iterations": max_iterations,
            "warning": "Stopped due to iteration limit",
            "success": True
        }
            
    except Exception as e:
        print(f"Error in conversation loop: {e}")
        return {
            "error": f"Error during tool execution: {str(e)}",
            "service_id": current_service_id,
            "tool_results": all_tool_results,
            "success": False
        }

# Function to handle tool calls
def execute_tool_call(tool_call, existing_service_id=None):
    """Execute a tool call and return the result"""
    function_name = tool_call.function.name
    arguments = tool_call.function.arguments
    
    # List of valid tool names for validation
    valid_tools = [
        "create_sandbox_client",
        "create_file_and_add_code", 
        "run_command",
        "get_sandbox_url"
    ]
    
    # Validate tool name
    if function_name not in valid_tools:
        return {
            "error": f"Unknown function: {function_name}. Available tools are: {', '.join(valid_tools)}. Please use one of the available tools instead."
        }
    
    # Parse arguments if they're a JSON string
    if isinstance(arguments, str):
        import json
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON arguments: {arguments}"}
    
    # Dispatch to the appropriate function with retry logic
    try:
        if function_name == "create_sandbox_client":
            result = execute_with_retry(
                create_sandbox_client,
                image=arguments.get("image", "koyeb/sandbox"),
                name=arguments.get("name", "example-sandbox")
            )
            return {"result": result}
        
        elif function_name == "create_file_and_add_code":
            service_id = arguments.get("service_id") or existing_service_id
            
            if not service_id:
                print("No service_id available, creating sandbox automatically...")
                sandbox_result = execute_with_retry(
                    create_sandbox_client,
                    image="koyeb/sandbox",
                    name="auto-created-sandbox"
                )
                
                if sandbox_result:
                    service_id = sandbox_result
                    print(f"Auto-created sandbox with ID: {service_id}")
                else:
                    return {"error": "Failed to create sandbox automatically"}
            
            result = execute_with_retry(
                create_file_and_add_code,
                service_id=service_id,
                file_path=arguments.get("file_path"),
                code=arguments.get("code")
            )
            return {"result": result}
        
        elif function_name == "get_sandbox_url":
            service_id = arguments.get("service_id") or existing_service_id
            
            if not service_id:
                return {"error": "No service_id available. Create a sandbox first."}
            
            result = execute_with_retry(
                get_sandbox_url,
                service_id=service_id
            )
            return {"result": result}
        
        elif function_name == "run_command":
            service_id = arguments.get("service_id") or existing_service_id
            command = arguments.get("command", "")
            
            if not service_id:
                return {"error": "No service_id available. Create a sandbox first."}
            
            result = execute_with_retry(
                run_command,
                service_id=service_id,
                command=command
            )
            return {"result": result}

        else:
            return {"error": f"Unknown function: {function_name}"}
            
    except Exception as e:
        error_msg = str(e)
        if is_provisioning_error(error_msg):
            return {"error": f"Sandbox provisioning failed after retries: {error_msg}"}
        else:
            return {"error": error_msg}

# Tools defined for use with the HuggingFace InferenceClient
tools: List[Any] = [
    {
        "type": "function",
        "function": {
            "name": "create_sandbox_client",
            "description": "Create a new Koyeb sandbox environment. Use this first if no sandbox exists yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image": {
                        "type": "string",
                        "description": "Docker image for the sandbox (default: koyeb/sandbox)"
                    },
                    "name": {
                        "type": "string",
                        "description": "Name for the sandbox instance (default: example-sandbox)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_file_and_add_code",
            "description": "Create or modify a file in the sandbox with specified content. Use for creating new files or updating existing ones.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox (required)"
                    },
                    "file_path": {
                        "type": "string", 
                        "description": "Path to the file (e.g., 'src/App.js', 'package.json')"
                    },
                    "code": {
                        "type": "string",
                        "description": "The complete content to write to the file"
                    }
                },
                "required": ["service_id", "file_path", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command in the sandbox. Use for installing packages, running scripts, or other terminal operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox (required)"
                    },
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute (e.g., 'npm install', 'python app.py')"
                    }
                },
                "required": ["service_id", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sandbox_url",
            "description": "Get the public URL for accessing the running sandbox application.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox (required)"
                    }
                },
                "required": ["service_id"]
            }
        }
    }
]
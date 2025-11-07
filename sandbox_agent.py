from typing import Optional, Union, List, Any
import time
import asyncio

from koyeb import Sandbox
from create_sandbox import create_sandbox_client
from get_sandbox_url import get_sandbox_url
from generate_files import create_file_and_add_code
from run_command import run_command
from expose_endpoint import expose_endpoint

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
    
    # Set longer timeout for installation commands
    if 'command' in kwargs:
        command = kwargs.get('command', '')
        if any(keyword in command for keyword in ['install', 'setup', 'curl', 'apt-get', 'npm install', 'create-react-app']):
            kwargs['timeout'] = 600  # 10 minutes for installation commands
        else:
            kwargs['timeout'] = 300  # 5 minutes for regular commands
    
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
    
    # Single system prompt - prepend service_id info if it exists
    system_prompt = f"""You are a helpful coding assistant that can create and manage sandboxes and their React applications running on Vite.

{f"IMPORTANT: You already have access to sandbox with service_id: {current_service_id}" if current_service_id else ""}

CRITICAL BEHAVIOR RULES:
- Perform all steps required to complete the entire user request
- ALWAYS use tools to perform actions rather than just describing them
- Call tools immediately when the user requests an action
- Only provide a final summary AFTER all tools have been executed

TOOLS:
1. {"create_sandbox_client - Create a new sandbox (use first if no sandbox exists)" if not current_service_id else ""}
2. run_command - Execute shell commands in the sandbox
3. create_file_and_add_code - Create or modify files in the sandbox
4. get_sandbox_url - Get the sandbox URL
5. expose_endpoint - Expose a port on the sandbox to make it publicly accessible

The environment resets with every command you make. When running shell commands, you must combine and run all commands as a single command string.
Only create files or projects in the /tmp directory.

When the user asks you to create something:
1. {"First call create_sandbox_client if no sandbox exists" if not current_service_id else "Set up the environment with run_command if needed"}

2. !!Important Use this COMPLETE setup command (wait for it to finish):
curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && apt-get install -y nodejs && node --version && npm --version && rm -rf /tmp/my-project && cd /tmp && printf "No\n" | npx create-vite my-project --template react-ts && cd my-project && npm install && npm install tailwindcss @tailwindcss/vite

This command installs Node.js, verifies installation, creates the /tmp/my-project directory, and initializes a React app there with the following structure:
  README.md
  eslint.config.js
  node_modules/
  package.json
  public/
    favicon.ico
  index.html
  src/
    App.css
    App.js
    App.test.js
    index.css
    index.js
    logo.svg
  tsconfig.app.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
You should write in these existing files or create new ones only as needed.
3. Call create_file_and_add_code to modify files as needed !!Important: create files ONLY in /tmp/my-project for React apps and first run the setup command above
4. After you have made changes to all necessary files, call this command to start the React app:
cd /tmp/my-project && npm run dev -- --host 0.0.0.0 --port 80

5. Call get_sandbox_url to retrieve the URL
6. Only THEN provide a brief summary with the URL

IMPORTANT: The React setup command in step 2 does everything: installs Node.js, verifies installation, creates directory, and initializes React app. Wait for this complete command to finish before proceeding to file modifications.

DO NOT describe your plan - execute it directly with tools."""
    
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
                
                # Add assistant message - but keep it simple
                assistant_message = {
                    "role": "assistant", 
                    "content": message.content or "Working on your request..."
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
                # No tool calls - check if we should continue
                user_request = ' '.join([msg['content'] for msg in messages_dict if msg['role'] == 'user']).lower()
                
                # Check if this looks like an incomplete workflow
                if iteration < max_iterations - 1:
                    needs_continuation = False
                    
                    # If user asked for creation but we haven't done much
                    if any(keyword in user_request for keyword in ['create', 'build', 'make', 'generate']):
                        if len(all_tool_results) < 3:  # Haven't done enough steps
                            needs_continuation = True
                        elif len(all_tool_results) >= 1:
                            # Check what we've accomplished
                            recent_tools = [r['function_name'] for r in all_tool_results[-3:]]
                            
                            # If we've only run basic setup, continue
                            if 'run_command' in recent_tools and 'create_file_and_add_code' not in recent_tools:
                                needs_continuation = True
                            
                            # If we've created files but haven't exposed/finished
                            elif 'create_file_and_add_code' in recent_tools and 'expose_endpoint' not in recent_tools:
                                needs_continuation = True
                    
                    if needs_continuation:
                        encouragement = {
                            "role": "system", 
                            "content": f"Continue with the next steps. You've completed {len(all_tool_results)} steps but the workflow isn't finished. Keep calling tools to complete the user's request."
                        }
                        conversation_messages.append(encouragement)
                        continue
                
                # Standard action encouragement for early iterations
                if (iteration < 2 and any(keyword in user_request 
                                        for keyword in ['create', 'build', 'make', 'install', 'run', 'setup', 'generate'])):
                    encouragement = {
                        "role": "system", 
                        "content": "The user is asking you to perform an action. You must use the available tools to complete their request. Execute the necessary steps."
                    }
                    conversation_messages.append(encouragement)
                    continue
                
                # Return final response
                consecutive_errors = 0
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
        "get_sandbox_url",
        "expose_endpoint"
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
        
        elif function_name == "expose_endpoint":
            service_id = arguments.get("service_id") or existing_service_id
            port = arguments.get("port")
            
            if not service_id:
                return {"error": "No service_id available. Create a sandbox first."}
            if not port:
                return {"error": "Port number is required to expose an endpoint."}
            
            result = execute_with_retry(
                expose_endpoint,
                service_id=service_id,
                port=port
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
    },
    {
        "type": "function",
        "function": {
            "name": "expose_endpoint",
            "description": "Expose a specific port on the sandbox to make it accessible via a public URL. The endpoint your expose depends on the port you choose (e.g., 3000 for React apps).",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox (required)"
                    },
                    "port": {
                        "type": "integer",
                        "description": "The port number to expose (e.g., 3000 for React apps). Choose the appropriate port based on the application type."
                    }
                },
                "required": ["service_id", "port"]
            }
        }
    }
]

def filter_assistant_response(content: str) -> str:
    """Filter out planning language from assistant responses"""
    if not content:
        return ""
    
    # Remove common planning phrases
    planning_phrases = [
        "I will call",
        "I'll use the",
        "Let me",
        "I need to",
        "First, I'll",
        "Then, I'll",
        "Next, I'll",
        "Please wait while I",
        "I'm going to"
    ]
    
    lines = content.split('\n')
    filtered_lines = []
    
    for line in lines:
        # Skip lines that start with planning language
        if not any(line.strip().startswith(phrase) for phrase in planning_phrases):
            filtered_lines.append(line)
    
    result = '\n'.join(filtered_lines).strip()
    
    # If we filtered everything out, return a simple acknowledgment
    if not result:
        return "Working on your request..."
    
    return result
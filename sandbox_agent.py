from typing import Optional, Union, List, Any
import time
import asyncio
import json

from koyeb import Sandbox
from create_sandbox import create_sandbox_client
from get_sandbox_url import get_sandbox_url
from generate_files import create_file_and_add_code
from run_command import run_command
from expose_endpoint import expose_endpoint

from websocket_utils import broadcast_log

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
                raise e
def set_up_environment(service_id, log_service_id=None):
    """Set up the sandbox environment with necessary installations"""
    setup_command = (
        "curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - && "
        "apt-get install -y nodejs && "
        "rm -rf /tmp/my-project && "
        "cd /tmp && "
        "echo y | npx create-vite my-project --template react-ts && "
        "cd my-project && "
        "npm install && "
        "npm install -D tailwindcss postcss autoprefixer && "
        "npx tailwindcss init -p"
    )
    
    print("Setting up sandbox environment...")
    
    result = execute_with_retry(
        run_command,
        service_id=service_id,
        command=setup_command,
        log_service_id=log_service_id  # Pass log routing through
    )
    
    print("Environment setup complete.")
    return result

def process_chat_with_tools(client, messages_dict, tools, service_id=None, max_iterations=10, log_service_id=None):
    """
    Process chat with tools, sending logs to log_service_id if provided
    """
    print(f"Starting chat processing with service_id: {service_id}")

    # If no service_id, create a sandbox first and get its ID
    if not service_id:
        print("No service_id provided, will create sandbox if needed.")
        service_id = create_sandbox_client()

    # Safe broadcast for agent start
    def safe_broadcast(service_id, log_type, message, data=None):
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(broadcast_log(service_id, log_type, message, data))
        except RuntimeError:
            # No running loop - we're in sync context, skip broadcasting
            print(f"[LOG] {log_type}: {message}")
    
    # Broadcast agent start
    if log_service_id:
        safe_broadcast(
            log_service_id,
            "agent_start", 
            "🚀 Starting agent workflow..."
        )
    
    all_tool_results = []
    current_service_id = service_id
    conversation_messages = messages_dict.copy()
    consecutive_errors = 0  # Track consecutive errors
    
    # Single system prompt - prepend service_id info if it exists
    system_prompt = f"""You are a helpful coding assistant that can create and manage sandboxes and their React applications running on Vite.

{f"IMPORTANT: You already have access to sandbox with service_id: {current_service_id}"}

CRITICAL BEHAVIOR RULES:
- Perform all steps required to complete the entire user request
- ALWAYS use tools to perform actions rather than just describing them
- Call tools immediately when the user requests an action
- Only provide a final summary AFTER all tools have been executed

TOOLS:
1. set_up_environment - Set up the sandbox environment with necessary installations
2. run_command - Execute shell commands in the sandbox
3. create_file_and_add_code - Create or modify files in the sandbox
4. get_sandbox_url - Get the sandbox URL
5. expose_endpoint - Expose a port on the sandbox to make it publicly accessible

The environment resets with every command you make. When running shell commands, you must combine and run all commands as a single command string.
Only create files or projects in the /tmp directory.

When the user asks you to create something:

1. !!Important Use the set_up_environment function COMPLETE setup command (wait for it to finish)

This above command already installs Node.js, verifies installation, creates the /tmp/my-project directory, and initializes a React app there with the following structure:
  README.md
  eslint.config.js
  node_modules/
  package.json
  package-lock.json
  public/
    vite.svg
  index.html
  src/
    App.css
    App.tsx
    index.css
    main.tsx
    assets/
      react.svg
  tsconfig.app.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
!! Important You should write in these existing files or create new ones only as needed.
!! Important Run this step only once.
2. Call get_sandbox_url to retrieve the URL of the sandbox.
3. Call create_file_and_add_code to modify files as needed !!Important: create files ONLY in /tmp/my-project for React apps and first run the setup command above. Use the file structure created by that command as your guide. Repeat this step as needed to add all necessary files.
4. Only after you have added any code to files that you needed, call create_file_and_add_code on /tmp/myproject/vite.config.js and add the sandbox as a server.allowedHosts entry, adding the sandbox url you just got:
  ```
  server.allowedHosts: ['sandbox.<your-koyeb-subdomain>.koyeb.app']
  ```
Do this step only once.
5. After you have made changes to all necessary files, call this command to start the React app:
cd /tmp/my-project && npm run dev -- --host 0.0.0.0 --port 80
6. Only THEN provide a brief summary with the URL

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
                    result = execute_tool_call(tool_call, current_service_id, log_service_id)
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
def execute_tool_call(tool_call, existing_service_id=None, log_service_id=None):
    """Execute a tool call and return the result"""
    function_name = tool_call.function.name
    arguments = tool_call.function.arguments
    
    # Parse arguments if they're a string
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON in tool arguments: {str(e)}"}
    
    # Safe broadcast for tool start
    def safe_broadcast(service_id, log_type, message, data=None):
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(broadcast_log(service_id, log_type, message, data))
        except RuntimeError:
            print(f"[LOG] {log_type}: {message}")
    
    # Broadcast tool start
    if log_service_id:
        safe_broadcast(
            log_service_id,
            "tool_start",
            f"🔧 Calling tool: {function_name}",
            {"tool": function_name, "arguments": arguments}
        )
    
    print(f"Executing tool: {function_name} with arguments: {arguments}")
    
    try:
        if function_name == "run_command":
            service_id = arguments.get("service_id") or existing_service_id
            command = arguments.get("command", "")
            
            print(f"Running command: {command} on service: {service_id}")
            
            if not service_id:
                return {"error": "No service_id available. Create a sandbox first."}
            
            result = execute_with_retry(
                run_command,
                service_id=service_id,
                command=command,
                log_service_id=log_service_id  # Pass log routing
            )
            return {"result": result}
        
        elif function_name == "set_up_environment":
            # FIXED: Pass log_service_id to set_up_environment
            service_id = arguments.get("service_id") or existing_service_id
            if not service_id:
                return {"error": "No service_id available. Create a sandbox first."}
            result = execute_with_retry(
                set_up_environment,
                service_id=service_id,
                log_service_id=log_service_id  # Pass log routing
            )
            return {"result": result}
        
        elif function_name == "create_file_and_add_code":
            # Broadcast file operation
            if log_service_id:
                file_path = arguments.get("file_path", "unknown")
                safe_broadcast(
                    log_service_id,
                    "file_operation",
                    f"📝 Creating/updating file: {file_path}",
                    {"file_path": file_path}
                )
            
            service_id = arguments.get("service_id") or existing_service_id
            if not service_id:
                return {"error": "No service_id available. Create a sandbox first."}
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
        print(f"Tool execution error: {error_msg}")
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
                        "description": "Path to the file. Refer to the structure created by the React setup command."
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
                        "description": "The shell command to execute (e.g., 'npm install')"
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
    },
    {
        "type": "function",
        "function": {
            "name": "set_up_environment",
            "description": "Set up the complete React development environment with Node.js, Vite, and Tailwind CSS. This should be called first when creating a new project.",
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
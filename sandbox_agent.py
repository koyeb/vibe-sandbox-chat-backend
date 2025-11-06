from typing import Optional, Union, List, Any

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

def process_chat_with_tools(client, messages_dict, tools, service_id=None, max_iterations=5):
    """
    Process a chat conversation with tool calling capabilities
    
    Args:
        client: HuggingFace InferenceClient
        messages_dict: List of message dictionaries
        tools: List of available tools
        service_id: Optional existing service ID
        max_iterations: Maximum number of tool call iterations
    
    Returns:
        Dictionary with conversation result
    """
    print(f"Starting chat processing with service_id: {service_id}")
    all_tool_results = []
    current_service_id = service_id
    conversation_messages = messages_dict.copy()
    conversation_messages.insert(0, {"role": "system", "content": f"Current service_id: {current_service_id} or None - you will need to create one first PROMPT"})

    current_service_id = service_id

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
            print(f"Assistant message: {message.content}")
            
            # Check if the model wants to use tools
            if hasattr(message, 'tool_calls') and message.tool_calls:
                print(f"Model requested {len(message.tool_calls)} tool calls")
                print(f"Tool calls: {[tool_call.function.name for tool_call in message.tool_calls]}")
                
                # Add assistant message with content explaining what it's doing
                assistant_message = {
                    "role": "assistant", 
                    "content": message.content or f"I'm going to call {len(message.tool_calls)} tool(s) to help you."
                }
                conversation_messages.append(assistant_message)
                
                # Execute each tool call and add results to conversation
                for tool_call in message.tool_calls:
                    result = execute_tool_call(tool_call)
                    print(f"Tool {tool_call.function.name} result: {result}")
                    
                    # Extract service_id if this was a create_sandbox_client call
                    if tool_call.function.name == "create_sandbox_client" and isinstance(result, dict) and "result" in result:
                        sandbox_result = result["result"]
                        if isinstance(sandbox_result, str):
                            current_service_id = sandbox_result
                            print(f"Created new sandbox with ID: {current_service_id}")
                            
                            # Update the system message with the new service_id
                            conversation_messages[0]["content"] = conversation_messages[0]["content"].replace(
                                f"Current service_id: {service_id or 'None - you will need to create one first'}", 
                                f"Current service_id: {current_service_id}"
                            )
                    
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
                
                # Continue to next iteration - don't return here!
                continue
            
            else:
                # Check if the task seems incomplete
                if iteration < 2 and current_service_id and not all_tool_results:
                    # If we have a service_id but haven't used any tools, encourage more action
                    encouragement = {
                        "role": "system", 
                        "content": "The user's request may require multiple steps. Consider what files need to be created or commands need to be run to fully complete their request."
                    }
                    conversation_messages.append(encouragement)
                    continue
                
                # No more tool calls - return final response
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
            "content": "I've completed as much as I could within the iteration limit. The sandbox is ready for further use.",
            "service_id": current_service_id,
            "tool_calls": all_tool_results if all_tool_results else None,
            "tool_results": all_tool_results,
            "iterations": max_iterations,
            "warning": "Stopped due to iteration limit",
            "success": True  # Changed to True since partial completion is still success
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
        service_id = arguments.get("service_id")
        
        # If service_id is missing, automatically create a sandbox first
        if not service_id:
            print("No service_id provided, creating sandbox automatically...")
            sandbox_result = create_sandbox_client(
                image="koyeb/sandbox",
                name="auto-created-sandbox"
            )
            
            if sandbox_result:
                service_id = sandbox_result
                print(f"Auto-created sandbox with ID: {service_id}")
            else:
                return {"error": "Failed to create sandbox automatically"}
        
        result = create_file_and_add_code(
            service_id=service_id,
            file_path=arguments.get("file_path"),
            code=arguments.get("code")
        )
        return {
            "result": result,
            "auto_created_sandbox": service_id if not arguments.get("service_id") else None
        }
    
    elif function_name == "get_sandbox_url":
        service_id = arguments.get("service_id")
        
        # If service_id is missing, automatically create a sandbox first
        if not service_id:
            print("No service_id provided, creating sandbox automatically...")
            sandbox_result = create_sandbox_client(
                image="koyeb/sandbox",
                name="auto-created-sandbox"
            )
            
            if sandbox_result:
                service_id = sandbox_result
                print(f"Auto-created sandbox with ID: {service_id}")
            else:
                return {"error": "Failed to create sandbox automatically"}
        
        result = get_sandbox_url(service_id=service_id)

        return {
            "result": result,
            "auto_created_sandbox": service_id if not arguments.get("service_id") else None
        }
    
    elif function_name == "run_command":
        service_id = arguments.get("service_id")
        command = arguments.get("command", "")
        
        # If service_id is missing, automatically create a sandbox first
        if not service_id:
            print("No service_id provided, creating sandbox automatically...")
            sandbox_result = create_sandbox_client(
                image="koyeb/sandbox",
                name="auto-created-sandbox"
            )
            
            if sandbox_result:
                service_id = sandbox_result
                print(f"Auto-created sandbox with ID: {service_id}")
            else:
                return {"error": "Failed to create sandbox automatically"}
        
        result = run_command(service_id=service_id, command=command)
        return {
            "result": result,
            "auto_created_sandbox": service_id if not arguments.get("service_id") else None
        }

    else:
        return {"error": f"Unknown function: {function_name}"}

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
            # "description": "Create a new file in the sandbox and add code to it. If you don't yet have a sandbox, first call create_sandbox_client to create one. Use this to create or modify files within the sandbox at the user's request. !!Important: This function requires a valid service_id. If no service_id exists yet, you must first call create_sandbox_client to create one.",
            "description": GENERATE_FILES_PROMPT,
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The ID of the service for the sandbox to use, as returned by create_sandbox_client or provided by the user. !!Important If you don't have this value, then call create_sandbox_client first to create a new sandbox, so you will need more than one tool call.",
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
    },
    {
        "type": "function",
        "function": {
            "name": "get_sandbox_url",
            "description": GET_SANDBOX_URL_PROMPT,
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The ID of the service for the sandbox to use, as returned by create_sandbox_client or provided by the user. !!Important If you don't have this value, then call create_sandbox_client first to create a new sandbox, so you will need more than one tool call.",
                    },
                },
                "required": ["service_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": RUN_COMMAND_PROMPT,
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The ID of the service for the sandbox to use, as returned by create_sandbox_client or provided by the user. !!Important If you don't have this value, then call create_sandbox_client first to create a new sandbox, so you will need more than one tool call.",
                    },
                },
                "required": ["service_id"],
            },
        },
    }
]
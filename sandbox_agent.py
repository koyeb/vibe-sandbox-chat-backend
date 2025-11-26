import asyncio
from utils.websocket_utils import broadcast_log
import json
from typing import AsyncGenerator, Dict, Any
from start_app import set_up_environment


def execute_tool_call(tool_call, service_id, log_service_id=None):
    """Execute a tool call and return the result"""
    
    function_name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments)
    
    print(f"Executing tool: {function_name} with arguments: {arguments}")
    
    # Import tool functions
    from run_command import run_command
    from generate_files import create_file_and_add_code, read_file
    from start_app import start_app
    from expose_endpoint import expose_endpoint
    
    # CRITICAL FIX: Always use the service_id passed to this function, not from arguments
    # The model might hallucinate names, so we override with the real UUID
    if 'service_id' in arguments:
        print(f"[DEBUG] Overriding service_id argument '{arguments['service_id']}' with actual service_id: {service_id}")
        arguments['service_id'] = service_id
    
    # Map function names to actual functions
    function_map = {
        "set_up_environment": set_up_environment,
        "run_command": run_command,
        "create_file_and_add_code": create_file_and_add_code,
        "read_file": read_file,
        "start_app": start_app,
        "expose_endpoint": expose_endpoint
    }
    
    if function_name not in function_map:
        return {"error": f"Unknown function: {function_name}"}
    
    try:
        # Add log_service_id to arguments if the function supports it
        func = function_map[function_name]
        func_params = func.__code__.co_varnames
        
        if 'log_service_id' in func_params and log_service_id:
            arguments['log_service_id'] = log_service_id
        
        # Call the function with the arguments
        result = func(**arguments)
        return {"result": result}
    except Exception as e:
        error_msg = f"Error executing {function_name}: {str(e)}"
        print(error_msg)
        import traceback
        traceback.print_exc()
        return {"error": error_msg}


async def process_chat_with_tools_streaming(
    client, 
    messages_dict, 
    tools, 
    service_id=None, 
    max_iterations=10, 
    log_service_id=None, 
    model=None
) -> AsyncGenerator[Dict[str, Any], None]:  # ADD THIS TYPE HINT
    """
    Streaming version of process_chat_with_tools that yields chunks as the agent works
    
    Yields:
        Dict[str, Any]: Event chunks with different types (status, tool_calls, content, etc.)
    """
    
    # CREATE SANDBOX IF NONE PROVIDED
    if not service_id:
        print("No service_id provided, creating new sandbox...")
        yield {
            "type": "status",
            "message": "📦 Creating new sandbox..."
        }
        
        from create_sandbox import create_sandbox_client
        try:
            service_id = create_sandbox_client()
            print(f"Created new sandbox with ID: {service_id}")
            
            yield {
                "type": "sandbox_created",
                "service_id": service_id,
                "message": f"✅ Sandbox created: {service_id}"
            }
        except Exception as e:
            error_msg = f"Failed to create sandbox: {str(e)}"
            print(error_msg)
            yield {
                "type": "error",
                "error": error_msg
            }
            return
    
    # Safe broadcast for agent start
    def safe_broadcast(service_id, log_type, message, data=None):
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(broadcast_log(service_id, log_type, message, data))
        except RuntimeError:
            # No running loop - we're in sync context, skip broadcasting
            print(f"[LOG] {log_type}: {message}")
    
    # Yield initial status
    yield {
        "type": "status",
        "message": "🚀 Starting agent workflow...",
        "service_id": service_id
    }
    
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
    
    # Single system prompt - prepend service_id info
    system_prompt = f"""You are a helpful coding assistant that can create and manage sandboxes and their React applications running on Vite and TypeScript (.tsx files).

IMPORTANT: The sandbox service_id is: {current_service_id}

CRITICAL RULES:
- ALWAYS use this exact service_id: {current_service_id}
- DO NOT make up or modify the service_id
- Perform all steps required to complete the user request
- ALWAYS use tools to perform actions rather than describing them
- Only provide a final summary AFTER all tools have been executed

TOOLS:
1. set_up_environment - Set up the sandbox environment with necessary installations
2. run_command - Execute shell commands in the sandbox
3. read_file - Read contents of files in the sandbox
4. create_file_and_add_code - Create or modify files in the sandbox
5. start_app - Start the React application in the sandbox and expose the endpoint

The environment resets with every command you make. When running shell commands, you must combine and run all commands as a single command string.
Only create files or projects in the /tmp directory.

When the user asks you to create something:

1. Use set_up_environment (ONLY ONCE at start)
2. Call read_file to get the current value of any files you need to modify. That way you're not just overriding files blindly.
3. Call create_file_and_add_code to modify files as needed (repeat as needed for all files). Only make the specific update requested, and leave the remaining code. If the file already has functionality, don't override it unless requested.
4. After all files are created, call start_app (ONLY ONCE). Do not try to run your own separate start commands.
5. Provide a brief summary with the URL

DO NOT describe your plan - execute it directly with tools."""
    
    conversation_messages.insert(0, {"role": "system", "content": system_prompt})
    
    try:
        for iteration in range(max_iterations):
            print(f"Iteration {iteration + 1}")
            
            # Yield iteration status
            yield {
                "type": "iteration",
                "iteration": iteration + 1,
                "max_iterations": max_iterations
            }
            
            # Stop if we have too many consecutive errors
            if consecutive_errors >= 2:
                error_msg = "I encountered repeated errors trying to call tools. I'll stop here to avoid further issues."
                yield {
                    "type": "error",
                    "message": error_msg,
                    "content": error_msg,
                    "service_id": current_service_id,
                    "tool_calls": all_tool_results if all_tool_results else None,
                    "tool_results": all_tool_results,
                    "iterations": iteration + 1,
                    "success": False
                }
                return
            
            response = client.chat_completion(
                model=model,
                messages=conversation_messages,
                tools=tools,
            )
            
            if not response.choices:
                yield {"type": "error", "error": "No response from model"}
                return
            
            message = response.choices[0].message
            print(f"Assistant message: {message.content}")
            
            # Check if the model wants to use tools
            if hasattr(message, 'tool_calls') and message.tool_calls:
                print(f"Model requested {len(message.tool_calls)} tool calls")
                print(f"Tool calls: {[tool_call.function.name for tool_call in message.tool_calls]}")
                
                # Yield tool call info
                yield {
                    "type": "tool_calls",
                    "count": len(message.tool_calls),
                    "tools": [tc.function.name for tc in message.tool_calls]
                }
                
                # Add assistant message with tool_calls
                assistant_message = {
                    "role": "assistant", 
                    "content": message.content or "Working on your request...",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in message.tool_calls
                    ]
                }
                conversation_messages.append(assistant_message)
                
                # Execute each tool call
                has_errors = False
                for tool_call in message.tool_calls:
                    # Yield tool execution start
                    yield {
                        "type": "tool_start",
                        "tool": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                    
                    result = execute_tool_call(tool_call, current_service_id, log_service_id)
                    print(f"Tool {tool_call.function.name} result: {result}")
                    
                    # Yield tool result
                    yield {
                        "type": "tool_result",
                        "tool": tool_call.function.name,
                        "result": result
                    }
                    
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
                            
                            # If we've read files but haven't created or modified them
                            elif 'read_file' in recent_tools and 'create_file_and_add_code' not in recent_tools:
                                needs_continuation = True

                            # If we've created files but haven't exposed/finished
                            elif 'create_file_and_add_code' in recent_tools and 'start_app' not in recent_tools:
                                needs_continuation = True
                    
                    if needs_continuation:
                        encouragement = {
                            "role": "system", 
                            "content": f"Continue with the next steps. You've completed {len(all_tool_results)} steps but the workflow isn't finished. Keep calling tools to complete the user's request."
                        }
                        conversation_messages.append(encouragement)
                        
                        # Yield continuation status
                        yield {
                            "type": "status",
                            "message": f"Continuing workflow... ({len(all_tool_results)} steps completed)"
                        }
                        continue
                
                # Standard action encouragement for early iterations
                if (iteration < 2 and any(keyword in user_request 
                                        for keyword in ['create', 'build', 'make', 'install', 'run', 'setup', 'generate'])):
                    encouragement = {
                        "role": "system", 
                        "content": "The user is asking you to perform an action. You must use the available tools to complete their request. Execute the necessary steps."
                    }
                    conversation_messages.append(encouragement)
                    
                    # Yield encouragement status
                    yield {
                        "type": "status",
                        "message": "Prompting model to use tools..."
                    }
                    continue
                
                # Stream the final content token by token
                if message.content:
                    words = message.content.split()
                    for i, word in enumerate(words):
                        yield {
                            "type": "content",
                            "content": word + (" " if i < len(words) - 1 else ""),
                            "delta": word + (" " if i < len(words) - 1 else "")
                        }
                        await asyncio.sleep(0.01)  # Small delay for streaming effect
                
                # Return final response
                consecutive_errors = 0
                yield {
                    "type": "complete",
                    "content": message.content,
                    "service_id": current_service_id,
                    "tool_calls": all_tool_results if all_tool_results else None,
                    "tool_results": all_tool_results,
                    "iterations": iteration + 1,
                    "success": True
                }
                return
        
        # If we hit max iterations
        yield {
            "type": "complete",
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
        import traceback
        traceback.print_exc()
        yield {
            "type": "error",
            "error": f"Error during tool execution: {str(e)}",
            "service_id": current_service_id,
            "tool_results": all_tool_results,
            "success": False
        }
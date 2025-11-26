# Find the tools array and add the read_file tool definition
# It should be added after the create_file_and_add_code tool

tools = [
    {
        "type": "function",
        "function": {
            "name": "set_up_environment",
            "description": "Set up the complete development environment with Node.js, npm, and create a React + Vite project with Tailwind CSS in /tmp/my-project. Run this ONLY ONCE at the start.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox"
                    }
                },
                "required": ["service_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command in the sandbox. The environment resets between commands, so combine related commands with && or ;",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox"
                    },
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    }
                },
                "required": ["service_id", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_file_and_add_code",
            "description": "Create or overwrite a file with the provided code content. Use ONLY for files in /tmp/my-project",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Full path to the file (must be in /tmp/my-project)"
                    },
                    "code": {
                        "type": "string",
                        "description": "The complete code content to write to the file"
                    }
                },
                "required": ["service_id", "file_path", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the sandbox. Use this before modifying files to understand their current content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Full path to the file (must be in /tmp/my-project)"
                    }
                },
                "required": ["service_id", "file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_app",
            "description": "Start the React application on port 80 and expose it externally. Run this ONLY ONCE after all files are created.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox"
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
            "description": "Expose a port on the sandbox to make it accessible from the internet. Required before starting web servers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": "The service ID of the sandbox"
                    },
                    "port": {
                        "type": "integer",
                        "description": "The port number to expose (usually 80 for web apps)"
                    }
                },
                "required": ["service_id", "port"]
            }
        }
    }
]
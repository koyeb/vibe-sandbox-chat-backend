"""
Model Configuration
Configure available models and their routing (local vs external endpoints)
"""
import os

# Available models that users can select
AVAILABLE_MODELS = {
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": "Qwen 3 Coder 30B A3B Instruct",
}

# Model routing configuration
# Models listed here will use external vLLM endpoints
# Models not listed will use Hugging Face Inference API
MODEL_ROUTING = {
    "Qwen/Qwen3-Coder-30B-A3B-Instruct": {
        "endpoint": os.getenv("Qwen3_Coder_30B_A3B_Instruct_Endpoint"),
        "model_name": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
    }
}

# Helper function to add a new model
def add_model(model_id: str, display_name: str, endpoint: str = None):
    """
    Add a new model to the configuration
    
    Args:
        model_id: The HuggingFace model ID (e.g., "Qwen/Qwen2.5-7B-Instruct")
        display_name: Human-readable name for the model
        endpoint: Optional external vLLM endpoint URL. If None, uses HF Inference API
    
    Example:
        add_model("mistralai/Mistral-7B-Instruct-v0.2", "Mistral 7B Instruct")
        add_model("Qwen/Qwen2.5-32B", "Qwen 32B", "https://my-endpoint.com")
    """
    AVAILABLE_MODELS[model_id] = display_name
    
    if endpoint:
        MODEL_ROUTING[model_id] = {
            "endpoint": endpoint,
            "model_name": model_id
        }

# Helper function to remove a model
def remove_model(model_id: str):
    """Remove a model from the configuration"""
    if model_id in AVAILABLE_MODELS:
        del AVAILABLE_MODELS[model_id]
    if model_id in MODEL_ROUTING:
        del MODEL_ROUTING[model_id]

# Helper function to update an endpoint
def update_endpoint(model_id: str, new_endpoint: str):
    """Update the endpoint for an external model"""
    if model_id in MODEL_ROUTING:
        MODEL_ROUTING[model_id]["endpoint"] = new_endpoint
    else:
        raise ValueError(f"Model {model_id} is not configured for external routing")
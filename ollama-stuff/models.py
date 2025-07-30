"""
Data models for Ollama Model Manager
"""

from typing import Optional
from pydantic import BaseModel

class ModelConfig(BaseModel):
    """Configuration parameters for a model"""
    num_ctx: Optional[int] = 4096
    num_gpu: Optional[int] = -1  # Default to -1 (all layers)
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    top_k: Optional[int] = 40
    repeat_penalty: Optional[float] = 1.1
    seed: Optional[int] = None
    num_thread: Optional[int] = None

class ChatMessage(BaseModel):
    """Chat message request"""
    model: str
    message: str
    config: Optional[ModelConfig] = None

class DownloadRequest(BaseModel):
    """Model download request"""
    model_name: str

class LoadedModelState:
    """Global state for the currently loaded model"""
    def __init__(self):
        self.name: Optional[str] = None
        self.config: Optional[dict] = None
    
    def set_model(self, name: str, config: dict = None):
        self.name = name
        self.config = config
    
    def clear(self):
        self.name = None
        self.config = None
    
    def is_loaded(self, model_name: str = None) -> bool:
        if model_name:
            return self.name == model_name
        return self.name is not None

# Global state instance
loaded_model = LoadedModelState() 
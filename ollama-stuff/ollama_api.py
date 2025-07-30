"""
Ollama API wrapper for model management
"""

import json
import requests
from typing import List, Dict, Any, Optional, AsyncGenerator
from config import OLLAMA_API_BASE

class OllamaAPI:
    """Wrapper class for Ollama API operations"""
    
    @staticmethod
    def list_models() -> List[Dict[str, Any]]:
        """Get list of available models from Ollama"""
        try:
            print(f"Fetching models from {OLLAMA_API_BASE}/api/tags")
            response = requests.get(f"{OLLAMA_API_BASE}/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()
            models = data.get('models', [])
            print(f"Found {len(models)} models")
            return models
        except requests.exceptions.ConnectionError:
            print(f"Error: Cannot connect to Ollama at {OLLAMA_API_BASE}")
            print("Make sure Ollama is running with: ollama serve")
            return []
        except Exception as e:
            print(f"Error listing models: {type(e).__name__}: {e}")
            return []
    
    @staticmethod
    def get_model_info(model_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific model"""
        try:
            response = requests.post(f"{OLLAMA_API_BASE}/api/show",
                                    json={"name": model_name})
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting model info: {e}")
            return None
    
    @staticmethod
    def load_model(model_name: str, config: dict = None) -> bool:
        """Load a model into memory"""
        try:
            payload = {
                "model": model_name,
                "options": config or {"num_gpu": -1}
            }
            response = requests.post(f"{OLLAMA_API_BASE}/api/generate",
                                    json={**payload, "prompt": "", "stream": False})
            return response.status_code == 200
        except Exception as e:
            print(f"Error loading model: {e}")
            return False
    
    @staticmethod
    def unload_model(model_name: str) -> bool:
        """Unload a model from memory"""
        try:
            # Unload by loading with keep_alive=0
            response = requests.post(f"{OLLAMA_API_BASE}/api/generate",
                                    json={"model": model_name, "prompt": "", "keep_alive": 0})
            return response.status_code == 200
        except Exception as e:
            print(f"Error unloading model: {e}")
            return False
    
    @staticmethod
    async def chat_stream(model: str, message: str, config: dict = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream chat responses from a model"""
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "stream": True
        }
        if config:
            payload["options"] = config
        
        response = requests.post(f"{OLLAMA_API_BASE}/api/chat",
                                json=payload, stream=True)
        
        for line in response.iter_lines():
            if line:
                yield json.loads(line)
    
    @staticmethod
    async def pull_model_stream(model_name: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Pull a model and stream progress updates"""
        try:
            response = requests.post(
                f"{OLLAMA_API_BASE}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True
            )
            
            for line in response.iter_lines():
                if line:
                    yield json.loads(line.decode('utf-8'))
        except Exception as e:
            print(f"Error pulling model: {e}")
            yield {"error": str(e)}
    
    @staticmethod
    def unload_all_models() -> None:
        """Unload all models for cleanup"""
        print("🧹 Performing startup cleanup...")
        try:
            models = OllamaAPI.list_models()
            if models:
                print(f"📋 Found {len(models)} models, checking if any are loaded...")
                
                for model in models:
                    model_name = model.get('name', '')
                    if model_name:
                        print(f"   Unloading {model_name}...")
                        try:
                            response = requests.post(
                                f"{OLLAMA_API_BASE}/api/generate",
                                json={"model": model_name, "prompt": "", "keep_alive": 0},
                                timeout=5
                            )
                            if response.status_code == 200:
                                print(f"   ✅ Successfully unloaded {model_name}")
                            else:
                                print(f"   ⚠️  Could not unload {model_name}")
                        except Exception as e:
                            print(f"   ❌ Error unloading {model_name}: {e}")
                
                print("✅ Startup cleanup complete")
            else:
                print("✅ No models found to cleanup")
        except Exception as e:
            print(f"⚠️  Error during startup cleanup: {e}")
            print("   Continuing anyway...")
    
    @staticmethod
    def test_connection() -> tuple[bool, str]:
        """Test connection to Ollama server"""
        try:
            response = requests.get(f"{OLLAMA_API_BASE}/api/tags", timeout=2)
            if response.ok:
                models = response.json().get('models', [])
                return True, f"✅ Ollama is running! Found {len(models)} models"
            else:
                return False, f"⚠️  Ollama responded with status {response.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "❌ Cannot connect to Ollama! Make sure it's running with: ollama serve"
        except Exception as e:
            return False, f"❌ Error checking Ollama: {e}" 
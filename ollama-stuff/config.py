"""
Configuration settings for Ollama Model Manager
"""

# API Configuration
OLLAMA_API_BASE = "http://localhost:11434"
CLINE_PROXY_PORT = 11435

# Database Configuration
DB_PATH = "ollama_models.db"

# Network Configuration
HOST = "0.0.0.0"
PORT = 8000
NETWORK_IP = "192.168.50.24"  # Update this to your actual network IP

# Required packages for auto-installation
REQUIRED_PACKAGES = [
    'fastapi', 
    'uvicorn', 
    'aiofiles', 
    'websockets', 
    'jinja2', 
    'python-multipart', 
    'requests'
] 
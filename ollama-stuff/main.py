#!/usr/bin/env python3
"""
Ollama Model Manager - Main Entry Point
Author: Assistant
License: MIT

A comprehensive web GUI for managing Ollama models with features including:
- Model management (list, load, unload, download)
- Interactive chat interface
- Configuration management
- OpenAI-compatible proxy server
- Model notes and ratings system
"""

import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager

# Install required packages
from config import REQUIRED_PACKAGES, HOST, PORT

for package in REQUIRED_PACKAGES:
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
    except subprocess.CalledProcessError:
        print(f"Failed to install {package}, continuing...")

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from database import init_db
from ollama_api import OllamaAPI
from proxy import cleanup_on_shutdown
from routes import *

# Application lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    print("🚀 Starting Ollama Model Manager...")
    
    # Initialize database
    init_db()
    
    # Test Ollama connection
    connected, status_msg = OllamaAPI.test_connection()
    print(f"   {status_msg}")
    
    if connected:
        # Clean up any loaded models on startup
        OllamaAPI.unload_all_models()
    
    print(f"   🌐 Web interface: http://{HOST}:{PORT}")
    print("   📋 Ready to manage your Ollama models!")
    
    yield
    
    # Shutdown
    print("\n🛑 Shutting down Ollama Model Manager...")
    cleanup_on_shutdown()
    print("   ✅ Shutdown complete")

# Create FastAPI application
app = FastAPI(
    title="Ollama Model Manager",
    description="A comprehensive web GUI for managing Ollama models",
    version="1.0.0",
    lifespan=lifespan
)

# Static files (for future CSS/JS separation if needed)
# app.mount("/static", StaticFiles(directory="static"), name="static")

# Main web interface
@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main web interface"""
    with open("templates/index.html", "r") as f:
        return HTMLResponse(content=f.read())

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    connected, _ = OllamaAPI.test_connection()
    return {
        "status": "healthy" if connected else "degraded",
        "ollama_connected": connected,
        "message": "Ollama Model Manager is running"
    }

# API Routes
@app.get("/api/test")
async def api_test():
    return await get_test()

@app.get("/api/models")
async def api_get_models():
    return await get_models()

@app.get("/api/model-info")
async def api_get_model_info(model: str):
    return await get_model_info(model)

@app.get("/api/model-usage")
async def api_get_model_usage(model: str):
    return await get_model_usage(model)

@app.post("/api/load-model")
async def api_load_model(data: dict):
    return await load_model(data)

@app.post("/api/unload-model")
async def api_unload_model(data: dict):
    return await unload_model(data)

@app.post("/api/update-usage")
async def api_update_usage(data: dict):
    return await update_usage(data)

@app.get("/api/model-config")
async def api_get_model_config(model: str):
    return await get_model_config(model)

@app.post("/api/save-config")
async def api_save_config(data: dict):
    return await save_config(data)

@app.get("/api/model-notes")
async def api_get_model_notes(model: str):
    return await get_model_notes(model)

@app.post("/api/save-notes")
async def api_save_notes(data: dict):
    return await save_notes(data)

@app.get("/api/export-notes")
async def api_export_notes():
    return await export_notes()

@app.post("/api/chat")
async def api_chat(chat_msg: ChatMessage):
    return await chat(chat_msg)

@app.get("/api/download-model")
async def api_download_model(model: str):
    return await download_model(model)

@app.post("/api/server/start")
async def api_start_server(data: dict):
    return await start_server(data)

@app.post("/api/server/stop")
async def api_stop_server():
    return await stop_server()

@app.get("/api/server/status")
async def api_get_server_status():
    return await get_server_status()

if __name__ == "__main__":
    import uvicorn
    
    print("Starting Ollama Model Manager...")
    print(f"Navigate to http://{HOST}:{PORT} to access the web interface")
    
    uvicorn.run(app, host=HOST, port=PORT) 
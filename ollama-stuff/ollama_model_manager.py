#!/usr/bin/env python3
"""
Ollama Model Manager - A comprehensive web GUI for managing Ollama models
Author: Assistant
License: MIT
"""

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

# Install required packages
required_packages = ['fastapi', 'uvicorn', 'aiofiles', 'websockets', 'jinja2', 'python-multipart', 'requests']
for package in required_packages:
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
    except subprocess.CalledProcessError:
        print(f"Failed to install {package}, continuing...")

import requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# Configuration
OLLAMA_API_BASE = "http://localhost:11434"
DB_PATH = "ollama_models.db"
CLINE_PROXY_PORT = 11435

# Database initialization
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Drop old table if exists to fix constraint issue
    c.execute('DROP TABLE IF EXISTS model_usage')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS model_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL UNIQUE,
            last_used TIMESTAMP,
            times_used INTEGER DEFAULT 0,
            notes TEXT,
            rating INTEGER,
            performance_notes TEXT,
            custom_params TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            user_message TEXT,
            assistant_message TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Pydantic models
class ModelConfig(BaseModel):
    num_ctx: Optional[int] = 4096
    num_gpu: Optional[int] = -1  # Default to -1 (all layers)
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9
    top_k: Optional[int] = 40
    repeat_penalty: Optional[float] = 1.1
    seed: Optional[int] = None
    num_thread: Optional[int] = None

class ChatMessage(BaseModel):
    model: str
    message: str
    config: Optional[ModelConfig] = None

class DownloadRequest(BaseModel):
    model_name: str

# Global state for loaded model
loaded_model = {"name": None, "config": None}

# Ollama API wrapper
class OllamaAPI:
    @staticmethod
    def list_models():
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
    def get_model_info(model_name: str):
        try:
            response = requests.post(f"{OLLAMA_API_BASE}/api/show",
                                    json={"name": model_name})
            return response.json()
        except Exception as e:
            print(f"Error getting model info: {e}")
            return None
    
    @staticmethod
    def load_model(model_name: str, config: dict = None):
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
    def unload_model(model_name: str):
        try:
            # Unload by loading with keep_alive=0
            response = requests.post(f"{OLLAMA_API_BASE}/api/generate",
                                    json={"model": model_name, "prompt": "", "keep_alive": 0})
            return response.status_code == 200
        except Exception as e:
            print(f"Error unloading model: {e}")
            return False
    
    @staticmethod
    async def chat_stream(model: str, message: str, config: dict = None):
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
    async def pull_model_stream(model_name: str):
        """Pull a model and stream progress"""
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

# Database operations
class ModelDB:
    @staticmethod
    def get_usage(model_name: str):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT * FROM model_usage WHERE model_name = ?
        ''', (model_name,))
        result = c.fetchone()
        conn.close()
        return result
    
    @staticmethod
    def update_usage(model_name: str):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check if record exists
        c.execute('SELECT id FROM model_usage WHERE model_name = ?', (model_name,))
        exists = c.fetchone()
        
        if exists:
            c.execute('''
                UPDATE model_usage 
                SET last_used = ?, times_used = times_used + 1
                WHERE model_name = ?
            ''', (datetime.now(), model_name))
        else:
            c.execute('''
                INSERT INTO model_usage (model_name, last_used, times_used)
                VALUES (?, ?, 1)
            ''', (model_name, datetime.now()))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def save_notes(model_name: str, notes: str = None, rating: int = None,
                   performance_notes: str = None, custom_params: str = None):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Check if record exists
        c.execute('SELECT id FROM model_usage WHERE model_name = ?', (model_name,))
        exists = c.fetchone()
        
        if exists:
            # Update only provided fields
            updates = []
            params = []
            
            if notes is not None:
                updates.append("notes = ?")
                params.append(notes)
            if rating is not None:
                updates.append("rating = ?")
                params.append(rating)
            if performance_notes is not None:
                updates.append("performance_notes = ?")
                params.append(performance_notes)
            if custom_params is not None:
                updates.append("custom_params = ?")
                params.append(custom_params)
            
            if updates:
                params.append(model_name)
                c.execute(f'''
                    UPDATE model_usage 
                    SET {", ".join(updates)}
                    WHERE model_name = ?
                ''', params)
        else:
            c.execute('''
                INSERT INTO model_usage 
                (model_name, notes, rating, performance_notes, custom_params, last_used)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (model_name, notes, rating, performance_notes, custom_params, datetime.now()))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def save_chat(model_name: str, user_message: str, assistant_message: str):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO chat_history (model_name, user_message, assistant_message)
            VALUES (?, ?, ?)
        ''', (model_name, user_message, assistant_message))
        conn.commit()
        conn.close()

# Initialize database
init_db()

# Startup cleanup function
def cleanup_on_startup():
    """Ensure all models are unloaded on startup"""
    print("🧹 Performing startup cleanup...")
    try:
        # Get list of all models
        models = OllamaAPI.list_models()
        if models:
            print(f"📋 Found {len(models)} models, checking if any are loaded...")
            
            # Try to unload each model
            for model in models:
                model_name = model.get('name', '')
                if model_name:
                    print(f"   Unloading {model_name}...")
                    try:
                        # Send unload request for each model
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

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting Ollama Model Manager...")
    cleanup_on_startup()
    yield
    # Shutdown
    print("Shutting down...")
    
    # Stop proxy server if running
    global proxy_process
    if proxy_process:
        print("🛑 Stopping proxy server...")
        proxy_process.terminate()
        try:
            proxy_process.wait(timeout=5)
        except:
            proxy_process.kill()
        proxy_process = None
    
    # Clean up proxy files
    cleanup_proxy_files()
    
    # Unload any loaded models
    if loaded_model["name"]:
        print(f"📦 Unloading model: {loaded_model['name']}")
        OllamaAPI.unload_model(loaded_model["name"])

app = FastAPI(lifespan=lifespan)

# HTML Template (keeping the same as original)
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ollama Model Manager</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            line-height: 1.6;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        header {
            background: #1a1a1a;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        h1 {
            color: #4a9eff;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        .subtitle {
            color: #888;
            font-size: 1.1em;
        }
        .main-grid {
            display: grid;
            grid-template-columns: 400px 1fr;
            gap: 20px;
            height: calc(100vh - 200px);
        }
        .models-panel {
            background: #1a1a1a;
            border-radius: 10px;
            padding: 20px;
            overflow-y: auto;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .models-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .header-buttons {
            display: flex;
            gap: 10px;
        }
        .header-button {
            padding: 6px 12px;
            background: #252525;
            border: 1px solid #333;
            border-radius: 5px;
            color: #e0e0e0;
            cursor: pointer;
            font-size: 0.9em;
            transition: all 0.3s;
        }
        .header-button:hover {
            background: #303030;
            border-color: #4a9eff;
        }
        .models-controls {
            margin-bottom: 20px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .search-box {
            padding: 10px;
            background: #252525;
            border: 1px solid #333;
            border-radius: 5px;
            color: #e0e0e0;
            font-size: 1em;
        }
        .sort-controls {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .sort-button {
            padding: 8px 15px;
            background: #252525;
            border: 1px solid #333;
            border-radius: 5px;
            color: #e0e0e0;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 0.9em;
        }
        .sort-button:hover {
            background: #303030;
            border-color: #4a9eff;
        }
        .sort-button.active {
            background: #4a9eff;
            border-color: #4a9eff;
            color: white;
        }
        .model-card {
            background: #252525;
            padding: 15px;
            margin-bottom: 15px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            border: 2px solid transparent;
            position: relative;
        }
        .model-card:hover {
            background: #303030;
            border-color: #4a9eff;
            transform: translateY(-2px);
        }
        .model-card.active {
            background: #2a3f5f;
            border-color: #4a9eff;
        }
        .model-card.loaded {
            border-color: #4ade80;
            box-shadow: 0 0 10px rgba(74, 222, 128, 0.3);
        }
        .model-name {
            font-weight: bold;
            color: #4a9eff;
            margin-bottom: 5px;
            font-size: 1.1em;
        }
        .model-info {
            font-size: 0.85em;
            color: #aaa;
            display: grid;
            gap: 3px;
        }
        .model-size {
            color: #ffa500;
        }
        .model-rating {
            color: #ffeb3b;
        }
        .model-usage {
            color: #4ade80;
        }
        .loaded-indicator {
            position: absolute;
            top: 10px;
            right: 10px;
            background: #4ade80;
            color: #0a0a0a;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.8em;
            font-weight: bold;
        }
        .workspace {
            display: grid;
            grid-template-rows: auto auto 1fr;
            gap: 20px;
        }
        .model-details {
            background: #1a1a1a;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            min-height: 100px;
        }
        .model-details h3 {
            color: #4a9eff;
            margin-bottom: 10px;
        }
        .model-details-content {
            color: #aaa;
            font-size: 0.95em;
            line-height: 1.8;
        }
        .tabs {
            background: #1a1a1a;
            border-radius: 10px;
            padding: 10px;
            display: flex;
            gap: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .tab {
            padding: 10px 20px;
            background: #252525;
            border: none;
            color: #e0e0e0;
            border-radius: 5px;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 1em;
        }
        .tab:hover {
            background: #303030;
        }
        .tab.active {
            background: #4a9eff;
            color: white;
        }
        .tab-content {
            background: #1a1a1a;
            border-radius: 10px;
            padding: 20px;
            overflow-y: auto;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .load-controls {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            padding: 15px;
            background: #252525;
            border-radius: 8px;
            align-items: center;
        }
        .load-button {
            padding: 10px 25px;
            background: #4ade80;
            color: #0a0a0a;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 1em;
            font-weight: bold;
            transition: all 0.3s;
        }
        .load-button:hover {
            background: #3ac870;
        }
        .load-button:disabled {
            background: #555;
            cursor: not-allowed;
        }
        .unload-button {
            padding: 10px 25px;
            background: #ef4444;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 1em;
            font-weight: bold;
            transition: all 0.3s;
        }
        .unload-button:hover {
            background: #dc2626;
        }
        .unload-button:disabled {
            background: #555;
            cursor: not-allowed;
        }
        .load-status {
            flex: 1;
            text-align: center;
            font-size: 0.95em;
        }
        .chat-container {
            display: grid;
            grid-template-rows: 1fr auto;
            height: calc(100% - 80px);
            gap: 20px;
        }
        .chat-messages {
            background: #0a0a0a;
            border-radius: 8px;
            padding: 20px;
            overflow-y: auto;
            border: 1px solid #333;
        }
        .message {
            margin-bottom: 15px;
            padding: 10px 15px;
            border-radius: 8px;
            max-width: 80%;
        }
        .user-message {
            background: #2a3f5f;
            margin-left: auto;
            text-align: right;
        }
        .assistant-message {
            background: #252525;
            margin-right: auto;
        }
        .chat-input-container {
            display: flex;
            gap: 10px;
        }
        .chat-input {
            flex: 1;
            padding: 15px;
            background: #252525;
            border: 1px solid #333;
            border-radius: 8px;
            color: #e0e0e0;
            font-size: 1em;
        }
        .send-button {
            padding: 15px 30px;
            background: #4a9eff;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1em;
            transition: all 0.3s;
        }
        .send-button:hover {
            background: #3a8eef;
        }
        .send-button:disabled {
            background: #555;
            cursor: not-allowed;
        }
        .config-form {
            display: grid;
            gap: 20px;
        }
        .form-group {
            display: grid;
            gap: 8px;
        }
        .form-group label {
            color: #4a9eff;
            font-weight: 500;
        }
        .form-group input, .form-group textarea, .form-group select {
            padding: 10px;
            background: #252525;
            border: 1px solid #333;
            border-radius: 5px;
            color: #e0e0e0;
            font-size: 0.95em;
        }
        .form-group input[type="range"] {
            width: 100%;
        }
        .range-value {
            text-align: center;
            color: #888;
            font-size: 0.9em;
        }
        .notes-section {
            margin-top: 30px;
            padding-top: 30px;
            border-top: 1px solid #333;
        }
        .button-group {
            display: flex;
            gap: 10px;
            margin-top: 20px;
        }
        .button {
            padding: 10px 20px;
            background: #4a9eff;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 1em;
            transition: all 0.3s;
        }
        .button:hover {
            background: #3a8eef;
        }
        .button.secondary {
            background: #555;
        }
        .button.secondary:hover {
            background: #666;
        }
        .server-status {
            padding: 15px;
            background: #252525;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 10px;
        }
        .status-indicator.running {
            background: #4ade80;
            box-shadow: 0 0 10px #4ade80;
        }
        .status-indicator.stopped {
            background: #ef4444;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #888;
        }
        .spinner {
            border: 3px solid #333;
            border-top: 3px solid #4a9eff;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .rating {
            display: flex;
            gap: 5px;
            margin: 10px 0;
        }
        .star {
            cursor: pointer;
            color: #555;
            font-size: 1.5em;
            transition: color 0.3s;
        }
        .star:hover, .star.active {
            color: #ffa500;
        }
        pre {
            background: #0a0a0a;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            margin: 10px 0;
            border: 1px solid #333;
        }
        code {
            color: #4ade80;
            font-family: 'Courier New', monospace;
        }
        
        /* Modal styles */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.7);
        }
        .modal-content {
            background-color: #1a1a1a;
            margin: 10% auto;
            padding: 30px;
            border: 1px solid #333;
            border-radius: 10px;
            width: 500px;
            max-width: 90%;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
        }
        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        .modal-header h2 {
            color: #4a9eff;
        }
        .close {
            color: #aaa;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
        }
        .close:hover {
            color: #fff;
        }
        .download-input {
            width: 100%;
            padding: 12px;
            background: #252525;
            border: 1px solid #333;
            border-radius: 5px;
            color: #e0e0e0;
            font-size: 1em;
            margin-bottom: 20px;
        }
        .download-button {
            width: 100%;
            padding: 12px;
            background: #4a9eff;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 1em;
            font-weight: bold;
            transition: all 0.3s;
        }
        .download-button:hover {
            background: #3a8eef;
        }
        .download-button:disabled {
            background: #555;
            cursor: not-allowed;
        }
        .download-progress {
            display: none;
            margin-top: 20px;
        }
        .progress-bar {
            width: 100%;
            height: 20px;
            background: #252525;
            border-radius: 10px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: #4a9eff;
            width: 0%;
            transition: width 0.3s;
        }
        .progress-text {
            margin-top: 10px;
            text-align: center;
            color: #aaa;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 Ollama Model Manager</h1>
            <div class="subtitle">Manage, configure, and chat with your local AI models</div>
        </header>
        
        <div class="main-grid">
            <div class="models-panel">
                <div class="models-header">
                    <h2 style="color: #4a9eff;">Available Models</h2>
                    <div class="header-buttons">
                        <button class="header-button" onclick="showDownloadModal()" title="Download new model">
                            ⬇️ Download
                        </button>
                        <button class="header-button" onclick="loadModels()" title="Refresh models">
                            🔄 Refresh
                        </button>
                    </div>
                </div>
                <div class="models-controls">
                    <input type="text" class="search-box" id="search-box" 
                           placeholder="Search models..." onkeyup="filterModels()">
                    <div class="sort-controls">
                        <button class="sort-button active" onclick="sortModels('name')">Name</button>
                        <button class="sort-button" onclick="sortModels('size')">Size</button>
                        <button class="sort-button" onclick="sortModels('rating')">Rating</button>
                        <button class="sort-button" onclick="sortModels('usage')">Usage</button>
                        <button class="sort-button" onclick="sortModels('modified')">Modified</button>
                    </div>
                </div>
                <div id="models-list">
                    <div class="loading">
                        <div class="spinner"></div>
                        <p>Loading models...</p>
                    </div>
                </div>
            </div>
            
            <div class="workspace">
                <div class="model-details" id="model-details">
                    <h3>Select a Model</h3>
                    <div class="model-details-content">
                        Choose a model from the list to view its details and manage it.
                    </div>
                </div>
                
                <div class="tabs">
                    <button class="tab active" onclick="switchTab('chat')">💬 Chat</button>
                    <button class="tab" onclick="switchTab('config')">⚙️ Configuration</button>
                    <button class="tab" onclick="switchTab('server')">🖥️ Server Mode</button>
                    <button class="tab" onclick="switchTab('notes')">📝 Notes & Rating</button>
                </div>
                
                <div class="tab-content">
                    <div id="chat-tab" class="tab-panel">
                        <div class="load-controls">
                            <button class="load-button" id="load-model-chat" 
                                    onclick="loadModel()" disabled>Load Model</button>
                            <button class="unload-button" id="unload-model-chat" 
                                    onclick="unloadModel()" disabled>Unload Model</button>
                            <div class="load-status" id="load-status-chat">No model selected</div>
                        </div>
                        <div class="chat-container">
                            <div class="chat-messages" id="chat-messages">
                                <div style="text-align: center; color: #888; padding: 40px;">
                                    Select and load a model to start chatting
                                </div>
                            </div>
                            <div class="chat-input-container">
                                <input type="text" class="chat-input" id="chat-input" 
                                       placeholder="Type your message..." 
                                       onkeypress="handleChatKeypress(event)" disabled>
                                <button class="send-button" id="send-button" 
                                        onclick="sendMessage()" disabled>Send</button>
                            </div>
                        </div>
                    </div>
                    
                    <div id="config-tab" class="tab-panel" style="display: none;">
                        <h3 style="margin-bottom: 20px; color: #4a9eff;">Model Configuration</h3>
                        <div class="config-form">
                            <div class="form-group">
                                <label>Context Length (num_ctx)</label>
                                <input type="range" id="num_ctx" min="512" max="131072" 
                                       value="4096" step="512" oninput="updateRangeValue(this)">
                                <div class="range-value" id="num_ctx_value">4096</div>
                            </div>
                            
                            <div class="form-group">
                                <label>Temperature</label>
                                <input type="range" id="temperature" min="0" max="2" 
                                       value="0.7" step="0.1" oninput="updateRangeValue(this)">
                                <div class="range-value" id="temperature_value">0.7</div>
                            </div>
                            
                            <div class="form-group">
                                <label>Top P</label>
                                <input type="range" id="top_p" min="0" max="1" 
                                       value="0.9" step="0.05" oninput="updateRangeValue(this)">
                                <div class="range-value" id="top_p_value">0.9</div>
                            </div>
                            
                            <div class="form-group">
                                <label>Top K</label>
                                <input type="range" id="top_k" min="1" max="100" 
                                       value="40" step="1" oninput="updateRangeValue(this)">
                                <div class="range-value" id="top_k_value">40</div>
                            </div>
                            
                            <div class="form-group">
                                <label>Repeat Penalty</label>
                                <input type="range" id="repeat_penalty" min="0.5" max="2" 
                                       value="1.1" step="0.1" oninput="updateRangeValue(this)">
                                <div class="range-value" id="repeat_penalty_value">1.1</div>
                            </div>
                            
                            <div class="form-group">
                                <label>GPU Layers (num_gpu) - Default: -1 (all layers)</label>
                                <input type="number" id="num_gpu" min="-1" max="999" value="-1">
                            </div>
                            
                            <div class="form-group">
                                <label>CPU Threads (num_thread)</label>
                                <input type="number" id="num_thread" min="1" max="128" 
                                       placeholder="Auto-detect">
                            </div>
                            
                            <div class="form-group">
                                <label>Seed (for reproducible outputs)</label>
                                <input type="number" id="seed" placeholder="Random">
                            </div>
                            
                            <div class="button-group">
                                <button class="button" onclick="saveConfig()">Save Configuration</button>
                                <button class="button secondary" onclick="resetConfig()">Reset to Defaults</button>
                            </div>
                        </div>
                    </div>
                    
                    <div id="server-tab" class="tab-panel" style="display: none;">
                        <h3 style="margin-bottom: 20px; color: #4a9eff;">OpenAI-Compatible Server Mode</h3>
                        <div class="load-controls">
                            <button class="load-button" id="load-model-server" 
                                    onclick="loadModel()" disabled>Load Model</button>
                            <button class="unload-button" id="unload-model-server" 
                                    onclick="unloadModel()" disabled>Unload Model</button>
                            <div class="load-status" id="load-status-server">No model selected</div>
                        </div>
                        
                        <div class="server-status">
                            <div>
                                <span class="status-indicator stopped" id="server-status"></span>
                                <span id="server-status-text">Server Stopped</span>
                            </div>
                            <button class="button" id="server-toggle" onclick="toggleServer()" disabled>
                                Start Server
                            </button>
                        </div>
                        
                        <div style="background: #252525; padding: 20px; border-radius: 8px;">
                            <h4 style="color: #4a9eff; margin-bottom: 15px;">Client Configuration</h4>
                            <p style="margin-bottom: 15px;">Configure your client (Ollamac, Cline, etc.) with these settings:</p>
                            <pre><code>API Provider: OpenAI Compatible
Base URL: http://192.168.50.24:11435/v1
API Key: ollama (or any text)
Model ID: <span id="cline-model-id">Select a model first</span></code></pre>
                            
                            <div style="margin-top: 20px; padding: 15px; background: #1a1a1a; 
                                        border-radius: 5px; border-left: 3px solid #4a9eff;">
                                <strong>Note:</strong> The server provides OpenAI-compatible endpoints and is accessible from other devices on your network. Make sure Ollama is running on port 11434.
                            </div>
                        </div>
                    </div>
                    
                    <div id="notes-tab" class="tab-panel" style="display: none;">
                        <h3 style="margin-bottom: 20px; color: #4a9eff;">Model Notes & Rating</h3>
                        <div class="config-form">
                            <div class="form-group">
                                <label>Overall Rating</label>
                                <div class="rating" id="rating">
                                    <span class="star" onclick="setRating(1)">★</span>
                                    <span class="star" onclick="setRating(2)">★</span>
                                    <span class="star" onclick="setRating(3)">★</span>
                                    <span class="star" onclick="setRating(4)">★</span>
                                    <span class="star" onclick="setRating(5)">★</span>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label>General Notes</label>
                                <textarea id="general-notes" rows="4" 
                                          placeholder="Add your notes about this model..."></textarea>
                            </div>
                            
                            <div class="form-group">
                                <label>Performance Notes</label>
                                <textarea id="performance-notes" rows="4" 
                                          placeholder="Speed, accuracy, memory usage observations..."></textarea>
                            </div>
                            
                            <div class="form-group">
                                <label>Best Use Cases</label>
                                <textarea id="use-cases" rows="3" 
                                          placeholder="What tasks is this model best suited for?"></textarea>
                            </div>
                            
                            <div class="button-group">
                                <button class="button" onclick="saveNotes()">Save Notes</button>
                                <button class="button secondary" onclick="exportNotes()">Export All Notes</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Download Modal -->
    <div id="downloadModal" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h2>Download New Model</h2>
                <span class="close" onclick="closeDownloadModal()">&times;</span>
            </div>
            <p style="color: #aaa; margin-bottom: 20px;">
                Enter the model name to download (e.g., "llama3.1:8b", "qwen2.5-coder:32b")
            </p>
            <input type="text" id="download-model-name" class="download-input" 
                   placeholder="Model name (e.g., llama3.1:8b)">
            <button class="download-button" id="download-button" onclick="startDownload()">
                Download Model
            </button>
            <div class="download-progress" id="download-progress">
                <div class="progress-bar">
                    <div class="progress-fill" id="progress-fill"></div>
                </div>
                <div class="progress-text" id="progress-text">Starting download...</div>
            </div>
        </div>
    </div>

    <script>
        let selectedModel = null;
        let loadedModelName = null;
        let ws = null;
        let serverRunning = false;
        let allModels = [];
        let currentSort = 'name';
        let downloadEventSource = null;
        
        // Load models on startup
        async function loadModels() {
            console.log('Loading models...');
            const modelsList = document.getElementById('models-list');
            
            try {
                console.log('Fetching from /api/models...');
                const response = await fetch('/api/models');
                console.log('Response status:', response.status);
                
                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`);
                }
                
                const models = await response.json();
                console.log('Loaded models:', models);
                
                // Validate models array
                if (!Array.isArray(models)) {
                    throw new Error('Invalid response: models is not an array');
                }
                
                allModels = models;
                
                if (models.length === 0) {
                    modelsList.innerHTML = '<div class="loading">No models found. Click "Download" to get started.</div>';
                    return;
                }
                
                displayModels();
                
                // Restore selection if model was previously selected
                if (selectedModel) {
                    // Find and reselect the model
                    const modelCard = document.getElementById(`model-${selectedModel.replace(/[^a-zA-Z0-9]/g, '-')}`);
                    if (modelCard) {
                        modelCard.classList.add('active');
                    }
                    updateLoadStatus();
                }
                
            } catch (error) {
                console.error('Error loading models:', error);
                modelsList.innerHTML = 
                    `<div class="loading">
                        <p style="color: #ef4444;">Error loading models!</p>
                        <p style="color: #ff6b6b; font-family: monospace; font-size: 0.9em;">${error.message}</p>
                        <p style="font-size: 0.9em; margin-top: 10px;">
                            Make sure Ollama is running: <code>ollama serve</code>
                        </p>
                        <button onclick="loadModels()" style="margin-top: 10px; padding: 8px 16px; background: #4a9eff; color: white; border: none; border-radius: 4px; cursor: pointer;">Retry</button>
                    </div>`;
            }
        }
        
        function filterModels() {
            const searchTerm = document.getElementById('search-box').value.toLowerCase();
            const filteredModels = allModels.filter(model => 
                model.name.toLowerCase().includes(searchTerm)
            );
            displayModels(filteredModels);
        }
        
        function sortModels(sortBy) {
            currentSort = sortBy;
            
            // Update button states
            document.querySelectorAll('.sort-button').forEach(btn => {
                btn.classList.remove('active');
            });
            event.target.classList.add('active');
            
            // Sort models
            const sortedModels = [...allModels].sort((a, b) => {
                switch(sortBy) {
                    case 'name':
                        return a.name.localeCompare(b.name);
                    case 'size':
                        return b.size - a.size;
                    case 'rating':
                        return (b.rating || 0) - (a.rating || 0);
                    case 'usage':
                        return (b.times_used || 0) - (a.times_used || 0);
                    case 'modified':
                        return new Date(b.modified_at) - new Date(a.modified_at);
                    default:
                        return 0;
                }
            });
            
            allModels = sortedModels;
            displayModels();
        }
        
        function displayModels(models = allModels) {
            const container = document.getElementById('models-list');
            
            console.log('displayModels called with:', models.length, 'models');
            
            if (!models || models.length === 0) {
                container.innerHTML = '<div class="loading">No models found. Click "Download" to get started.</div>';
                return;
            }
            
            try {
                const modelCards = models.map((model, index) => {
                    try {
                        // Validate model object
                        if (!model || typeof model !== 'object') {
                            console.warn(`Invalid model at index ${index}:`, model);
                            return '';
                        }
                        
                        // Safely access properties with fallbacks
                        const modelName = model.name || `Unknown Model ${index}`;
                        const size = formatSize(model.size || 0);
                        const isLoaded = loadedModelName === modelName;
                        const rating = model.rating || 0;
                        const timesUsed = model.times_used || 0;
                        const modifiedAt = model.modified_at || new Date().toISOString();
                        
                        // Create safe ID for the model card
                        const safeId = modelName.replace(/[^a-zA-Z0-9]/g, '-');
                        
                        return `
                            <div class="model-card ${selectedModel === modelName ? 'active' : ''} ${isLoaded ? 'loaded' : ''}" 
                                 onclick="selectModel('${modelName.replace(/'/g, "\\'")}');" 
                                 id="model-${safeId}">
                                ${isLoaded ? '<div class="loaded-indicator">LOADED</div>' : ''}
                                <div class="model-name">${modelName}</div>
                                <div class="model-info">
                                    <span class="model-size">Size: ${size}</span>
                                    <span class="model-rating">Rating: ${'★'.repeat(rating)}${'☆'.repeat(5-rating)}</span>
                                    <span>Modified: ${formatDate(modifiedAt)}</span>
                                    <span class="model-usage">
                                        ${timesUsed ? `Used ${timesUsed} times` : 'Never used'}
                                    </span>
                                </div>
                            </div>
                        `;
                    } catch (modelError) {
                        console.error(`Error rendering model at index ${index}:`, modelError, model);
                        return '';
                    }
                }).filter(card => card.length > 0); // Remove empty cards
                
                if (modelCards.length === 0) {
                    container.innerHTML = '<div class="loading">No valid models found. Check console for errors.</div>';
                    return;
                }
                
                container.innerHTML = modelCards.join('');
                console.log(`Successfully displayed ${modelCards.length} model cards`);
                
            } catch (error) {
                console.error('Error in displayModels:', error);
                container.innerHTML = `
                    <div class="loading">
                        <p style="color: #ef4444;">Error displaying models!</p>
                        <p style="color: #ff6b6b; font-size: 0.9em;">${error.message}</p>
                        <button onclick="loadModels()" style="margin-top: 10px; padding: 8px 16px; background: #4a9eff; color: white; border: none; border-radius: 4px; cursor: pointer;">Retry</button>
                    </div>
                `;
            }
        }
        
        async function selectModel(modelName) {
            selectedModel = modelName;
            
            // Update UI
            document.querySelectorAll('.model-card').forEach(card => {
                card.classList.remove('active');
            });
            document.getElementById(`model-${modelName.replace(/[^a-zA-Z0-9]/g, '-')}`).classList.add('active');
            
            // Update model details
            await updateModelDetails(modelName);
            
            // Enable load buttons
            document.getElementById('load-model-chat').disabled = false;
            document.getElementById('load-model-server').disabled = false;
            
            // Update server config
            document.getElementById('cline-model-id').textContent = modelName;
            
            // Load saved configuration and notes
            await loadModelConfig(modelName);
            await loadModelNotes(modelName);
            
            // Update status displays
            updateLoadStatus();
        }
        
        async function updateModelDetails(modelName) {
            const detailsDiv = document.getElementById('model-details');
            detailsDiv.innerHTML = '<h3>Loading model details...</h3>';
            
            try {
                const response = await fetch(`/api/model-info?model=${encodeURIComponent(modelName)}`);
                const info = await response.json();
                
                const model = allModels.find(m => m.name === modelName);
                const size = formatSize(model?.size || 0);
                const rating = model?.rating || 0;
                const usage = model?.times_used || 0;
                
                detailsDiv.innerHTML = `
                    <h3>${modelName}</h3>
                    <div class="model-details-content">
                        <strong>Size:</strong> ${size}<br>
                        <strong>Rating:</strong> ${'★'.repeat(rating)}${'☆'.repeat(5-rating)}<br>
                        <strong>Times Used:</strong> ${usage}<br>
                        <strong>Modified:</strong> ${formatDate(model?.modified_at)}<br>
                        ${info.details ? `<strong>Architecture:</strong> ${info.details.family || 'Unknown'}<br>` : ''}
                        ${info.details ? `<strong>Parameters:</strong> ${info.details.parameter_size || 'Unknown'}<br>` : ''}
                        ${info.details ? `<strong>Quantization:</strong> ${info.details.quantization_level || 'Unknown'}` : ''}
                    </div>
                `;
            } catch (error) {
                console.error('Error loading model details:', error);
                detailsDiv.innerHTML = `
                    <h3>${modelName}</h3>
                    <div class="model-details-content">
                        Error loading model details
                    </div>
                `;
            }
        }
        
        async function loadModel() {
            if (!selectedModel) return;
            
            const config = getConfig();
            
            // Update UI to show loading
            updateLoadStatus('Loading model...');
            document.getElementById('load-model-chat').disabled = true;
            document.getElementById('load-model-server').disabled = true;
            
            try {
                const response = await fetch('/api/load-model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        model: selectedModel,
                        config: config
                    })
                });
                
                if (response.ok) {
                    loadedModelName = selectedModel;
                    updateLoadStatus();
                    displayModels(); // Update display to show loaded indicator
                    
                    // Enable chat
                    document.getElementById('chat-input').disabled = false;
                    document.getElementById('send-button').disabled = false;
                    document.getElementById('chat-messages').innerHTML = 
                        '<div style="text-align: center; color: #4ade80; padding: 20px;">Model loaded! Ready to chat.</div>';
                    
                    // Enable server button
                    document.getElementById('server-toggle').disabled = false;
                    
                    // Update usage count
                    const model = allModels.find(m => m.name === selectedModel);
                    if (model) {
                        model.times_used = (model.times_used || 0) + 1;
                    }
                } else {
                    updateLoadStatus('Failed to load model');
                }
            } catch (error) {
                console.error('Error loading model:', error);
                updateLoadStatus('Error loading model');
            }
            
            // Re-enable buttons
            document.getElementById('load-model-chat').disabled = false;
            document.getElementById('load-model-server').disabled = false;
        }
        
        async function unloadModel() {
            if (!loadedModelName) return;
            
            updateLoadStatus('Unloading model...');
            document.getElementById('unload-model-chat').disabled = true;
            document.getElementById('unload-model-server').disabled = true;
            
            try {
                const response = await fetch('/api/unload-model', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model: loadedModelName })
                });
                
                if (response.ok) {
                    loadedModelName = null;
                    updateLoadStatus();
                    displayModels(); // Update display to remove loaded indicator
                    
                    // Disable chat
                    document.getElementById('chat-input').disabled = true;
                    document.getElementById('send-button').disabled = true;
                    document.getElementById('chat-messages').innerHTML = 
                        '<div style="text-align: center; color: #888; padding: 40px;">Select and load a model to start chatting</div>';
                    
                    // Stop server if running
                    if (serverRunning) {
                        await toggleServer();
                    }
                    
                    // Disable server button
                    document.getElementById('server-toggle').disabled = true;
                }
            } catch (error) {
                console.error('Error unloading model:', error);
                updateLoadStatus('Error unloading model');
            }
            
            // Re-enable buttons
            document.getElementById('unload-model-chat').disabled = false;
            document.getElementById('unload-model-server').disabled = false;
        }
        
        function updateLoadStatus(message = null) {
            const statusTexts = {
                chat: document.getElementById('load-status-chat'),
                server: document.getElementById('load-status-server')
            };
            
            const loadButtons = {
                chat: document.getElementById('load-model-chat'),
                server: document.getElementById('load-model-server')
            };
            
            const unloadButtons = {
                chat: document.getElementById('unload-model-chat'),
                server: document.getElementById('unload-model-server')
            };
            
            let statusText = message;
            if (!message) {
                if (!selectedModel) {
                    statusText = 'No model selected';
                } else if (loadedModelName === selectedModel) {
                    statusText = `Model loaded: ${loadedModelName}`;
                } else if (loadedModelName) {
                    statusText = `Different model loaded: ${loadedModelName}`;
                } else {
                    statusText = 'Model not loaded';
                }
            }
            
            Object.values(statusTexts).forEach(el => el.textContent = statusText);
            
            // Update button states
            const isCurrentModelLoaded = loadedModelName === selectedModel;
            Object.values(loadButtons).forEach(btn => {
                btn.disabled = !selectedModel || isCurrentModelLoaded;
            });
            Object.values(unloadButtons).forEach(btn => {
                btn.disabled = !isCurrentModelLoaded;
            });
        }
        
        function switchTab(tabName) {
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });
            event.target.classList.add('active');
            
            // Update tab content
            document.querySelectorAll('.tab-panel').forEach(panel => {
                panel.style.display = 'none';
            });
            document.getElementById(`${tabName}-tab`).style.display = 'block';
        }
        
        function getConfig() {
            return {
                num_ctx: parseInt(document.getElementById('num_ctx').value),
                temperature: parseFloat(document.getElementById('temperature').value),
                top_p: parseFloat(document.getElementById('top_p').value),
                top_k: parseInt(document.getElementById('top_k').value),
                repeat_penalty: parseFloat(document.getElementById('repeat_penalty').value),
                num_gpu: parseInt(document.getElementById('num_gpu').value) || -1,
                num_thread: parseInt(document.getElementById('num_thread').value) || null,
                seed: parseInt(document.getElementById('seed').value) || null
            };
        }
        
        async function sendMessage() {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message || !loadedModelName) return;
            
            // Add user message to chat
            addMessage(message, 'user');
            input.value = '';
            
            // Get current config
            const config = getConfig();
            
            // Send to backend
            try {
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        model: loadedModelName,
                        message: message,
                        config: config
                    })
                });
                
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let assistantMessage = '';
                const messageId = addMessage('', 'assistant');
                
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    
                    const chunk = decoder.decode(value);
                    const lines = chunk.split('\\n');
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.message?.content) {
                                    assistantMessage += data.message.content;
                                    updateMessage(messageId, assistantMessage);
                                }
                            } catch (e) {
                                console.error('Error parsing SSE:', e);
                            }
                        }
                    }
                }
            } catch (error) {
                console.error('Chat error:', error);
                addMessage('Error: Failed to get response. Make sure the model is loaded.', 'assistant');
            }
        }
        
        function addMessage(content, type) {
            const messagesDiv = document.getElementById('chat-messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${type}-message`;
            messageDiv.textContent = content;
            messageDiv.id = `msg-${Date.now()}`;
            messagesDiv.appendChild(messageDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            return messageDiv.id;
        }
        
        function updateMessage(messageId, content) {
            const messageDiv = document.getElementById(messageId);
            if (messageDiv) {
                messageDiv.textContent = content;
                messageDiv.parentElement.scrollTop = messageDiv.parentElement.scrollHeight;
            }
        }
        
        function handleChatKeypress(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        }
        
        function updateRangeValue(input) {
            const valueDiv = document.getElementById(`${input.id}_value`);
            if (valueDiv) {
                valueDiv.textContent = input.value;
            }
        }
        
        async function saveConfig() {
            if (!selectedModel) {
                alert('Please select a model first');
                return;
            }
            
            const config = getConfig();
            
            try {
                await fetch('/api/save-config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        model: selectedModel,
                        config: config
                    })
                });
                alert('Configuration saved!');
            } catch (error) {
                console.error('Error saving config:', error);
                alert('Failed to save configuration');
            }
        }
        
        function resetConfig() {
            document.getElementById('num_ctx').value = 4096;
            document.getElementById('temperature').value = 0.7;
            document.getElementById('top_p').value = 0.9;
            document.getElementById('top_k').value = 40;
            document.getElementById('repeat_penalty').value = 1.1;
            document.getElementById('num_gpu').value = -1;
            document.getElementById('num_thread').value = '';
            document.getElementById('seed').value = '';
            
            // Update displayed values
            document.querySelectorAll('input[type="range"]').forEach(input => {
                updateRangeValue(input);
            });
        }
        
        async function loadModelConfig(modelName) {
            try {
                const response = await fetch(`/api/model-config?model=${encodeURIComponent(modelName)}`);
                const data = await response.json();
                if (data.config) {
                    const config = JSON.parse(data.config);
                    Object.keys(config).forEach(key => {
                        const input = document.getElementById(key);
                        if (input && config[key] !== null) {
                            input.value = config[key];
                            if (input.type === 'range') {
                                updateRangeValue(input);
                            }
                        }
                    });
                } else {
                    resetConfig();
                }
            } catch (error) {
                console.error('Error loading config:', error);
            }
        }
        
        async function loadModelNotes(modelName) {
            try {
                const response = await fetch(`/api/model-notes?model=${encodeURIComponent(modelName)}`);
                const data = await response.json();
                
                document.getElementById('general-notes').value = data.notes || '';
                document.getElementById('performance-notes').value = data.performance_notes || '';
                
                // Set rating
                setRating(data.rating || 0, false);
            } catch (error) {
                console.error('Error loading notes:', error);
            }
        }
        
        function setRating(rating, save = true) {
            document.querySelectorAll('.star').forEach((star, index) => {
                star.classList.toggle('active', index < rating);
            });
            
            if (save && selectedModel) {
                saveNotes();
            }
        }
        
        async function saveNotes() {
            if (!selectedModel) {
                alert('Please select a model first');
                return;
            }
            
            const rating = document.querySelectorAll('.star.active').length;
            const notes = document.getElementById('general-notes').value;
            const performanceNotes = document.getElementById('performance-notes').value;
            
            try {
                await fetch('/api/save-notes', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        model: selectedModel,
                        notes: notes,
                        rating: rating,
                        performance_notes: performanceNotes
                    })
                });
                
                // Update the model's rating in the list
                const model = allModels.find(m => m.name === selectedModel);
                if (model) {
                    model.rating = rating;
                    displayModels();
                }
                
                alert('Notes saved!');
            } catch (error) {
                console.error('Error saving notes:', error);
                alert('Failed to save notes');
            }
        }
        
        async function exportNotes() {
            try {
                const response = await fetch('/api/export-notes');
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `ollama_models_notes_${new Date().toISOString().split('T')[0]}.json`;
                a.click();
                window.URL.revokeObjectURL(url);
            } catch (error) {
                console.error('Error exporting notes:', error);
                alert('Failed to export notes');
            }
        }
        
        async function toggleServer() {
            if (!loadedModelName) {
                alert('Please load a model first');
                return;
            }
            
            const button = document.getElementById('server-toggle');
            const statusIndicator = document.getElementById('server-status');
            const statusText = document.getElementById('server-status-text');
            
            try {
                if (!serverRunning) {
                    const response = await fetch('/api/server/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ model: loadedModelName })
                    });
                    
                    if (response.ok) {
                        serverRunning = true;
                        button.textContent = 'Stop Server';
                        statusIndicator.classList.remove('stopped');
                        statusIndicator.classList.add('running');
                        statusText.textContent = 'Server Running on port 11435';
                    }
                } else {
                    const response = await fetch('/api/server/stop', {
                        method: 'POST'
                    });
                    
                    if (response.ok) {
                        serverRunning = false;
                        button.textContent = 'Start Server';
                        statusIndicator.classList.remove('running');
                        statusIndicator.classList.add('stopped');
                        statusText.textContent = 'Server Stopped';
                    }
                }
            } catch (error) {
                console.error('Error toggling server:', error);
                alert('Failed to toggle server');
            }
        }
        
        // Download modal functions
        function showDownloadModal() {
            document.getElementById('downloadModal').style.display = 'block';
            document.getElementById('download-model-name').focus();
        }
        
        function closeDownloadModal() {
            document.getElementById('downloadModal').style.display = 'none';
            document.getElementById('download-model-name').value = '';
            document.getElementById('download-progress').style.display = 'none';
            document.getElementById('download-button').disabled = false;
            
            // Close EventSource if active
            if (downloadEventSource) {
                downloadEventSource.close();
                downloadEventSource = null;
            }
        }
        
        async function startDownload() {
            const modelName = document.getElementById('download-model-name').value.trim();
            if (!modelName) {
                alert('Please enter a model name');
                return;
            }
            
            const downloadButton = document.getElementById('download-button');
            const progressDiv = document.getElementById('download-progress');
            const progressFill = document.getElementById('progress-fill');
            const progressText = document.getElementById('progress-text');
            
            downloadButton.disabled = true;
            progressDiv.style.display = 'block';
            progressText.textContent = 'Starting download...';
            progressFill.style.width = '0%';
            
            try {
                // Create EventSource for streaming progress
                downloadEventSource = new EventSource(`/api/download-model?model=${encodeURIComponent(modelName)}`);
                
                downloadEventSource.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    
                    if (data.status === 'pulling manifest') {
                        progressText.textContent = 'Pulling manifest...';
                        progressFill.style.width = '5%';
                    } else if (data.status === 'downloading') {
                        const percent = Math.round((data.completed / data.total) * 100);
                        progressFill.style.width = `${percent}%`;
                        progressText.textContent = `Downloading: ${formatSize(data.completed)} / ${formatSize(data.total)} (${percent}%)`;
                    } else if (data.status === 'verifying') {
                        progressText.textContent = 'Verifying download...';
                        progressFill.style.width = '95%';
                    } else if (data.status === 'success') {
                        progressFill.style.width = '100%';
                        progressText.textContent = 'Download complete!';
                        setTimeout(() => {
                            closeDownloadModal();
                            loadModels(); // Refresh the model list
                        }, 2000);
                    }
                };
                
                downloadEventSource.onerror = (error) => {
                    console.error('Download error:', error);
                    progressText.textContent = 'Error downloading model. Check console for details.';
                    downloadButton.disabled = false;
                    downloadEventSource.close();
                    downloadEventSource = null;
                };
                
            } catch (error) {
                console.error('Error starting download:', error);
                progressText.textContent = 'Error: ' + error.message;
                downloadButton.disabled = false;
            }
        }
        
        // Utility functions
        function formatSize(bytes) {
            try {
                const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
                
                // Handle invalid input
                if (bytes === null || bytes === undefined || isNaN(bytes)) {
                    return 'Unknown';
                }
                
                const numBytes = Number(bytes);
                if (numBytes === 0) return '0 B';
                if (numBytes < 0) return 'Invalid size';
                
                const i = Math.floor(Math.log(numBytes) / Math.log(1024));
                if (i >= sizes.length) return Math.round(numBytes / Math.pow(1024, sizes.length - 1)) + ' ' + sizes[sizes.length - 1];
                
                const size = numBytes / Math.pow(1024, i);
                return Math.round(size * 100) / 100 + ' ' + sizes[i];
            } catch (error) {
                console.error('Error formatting size:', error, bytes);
                return 'Unknown';
            }
        }
        
        function formatDate(dateString) {
            try {
                // Handle invalid input
                if (!dateString) {
                    return 'Unknown';
                }
                
                const date = new Date(dateString);
                
                // Check if date is valid
                if (isNaN(date.getTime())) {
                    console.warn('Invalid date string:', dateString);
                    return 'Invalid date';
                }
                
                const now = new Date();
                const diff = now - date;
                
                // Handle future dates
                if (diff < 0) {
                    return date.toLocaleDateString();
                }
                
                if (diff < 60000) return 'Just now';
                if (diff < 3600000) return Math.floor(diff / 60000) + ' minutes ago';
                if (diff < 86400000) return Math.floor(diff / 3600000) + ' hours ago';
                if (diff < 604800000) return Math.floor(diff / 86400000) + ' days ago';
                
                return date.toLocaleDateString();
            } catch (error) {
                console.error('Error formatting date:', error, dateString);
                return 'Unknown';
            }
        }
        
        // Close modal when clicking outside
        window.onclick = function(event) {
            const modal = document.getElementById('downloadModal');
            if (event.target === modal) {
                closeDownloadModal();
            }
        }
        
        // Initialize
        console.log('Initializing Ollama Model Manager...');
        
        // Initialize models loading
        function initializeApp() {
            console.log('Initializing app...');
            try {
                // Check if required elements exist
                const requiredElements = ['models-list', 'model-details', 'chat-messages'];
                const missingElements = requiredElements.filter(id => !document.getElementById(id));
                
                if (missingElements.length > 0) {
                    console.error('Missing required elements:', missingElements);
                    return;
                }
                
                console.log('All required elements found, loading models...');
                loadModels();
                
            } catch (error) {
                console.error('Error initializing app:', error);
            }
        }
        
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            console.log('DOM loading, waiting for ready state...');
            document.addEventListener('DOMContentLoaded', () => {
                console.log('DOM ready, initializing app...');
                initializeApp();
            });
        } else {
            console.log('DOM already ready, initializing app...');
            initializeApp();
        }
    </script>
</body>
</html>'''

# Routes (keeping the same as original)
@app.get("/")
async def home():
    return HTMLResponse(content=HTML_TEMPLATE)

@app.get("/api/test")
async def test():
    return JSONResponse(content={"status": "ok", "message": "API is working"})

@app.get("/api/models")
async def get_models():
    try:
        print("API: Fetching models...")
        models = OllamaAPI.list_models()
        print(f"API: Got {len(models)} models")
        
        if not isinstance(models, list):
            print(f"API: Warning - models is not a list: {type(models)}")
            return JSONResponse(content=[], status_code=500)
        
        # Add usage data to each model and validate structure
        processed_models = []
        for i, model in enumerate(models):
            try:
                if not isinstance(model, dict):
                    print(f"API: Warning - model {i} is not a dict: {type(model)}")
                    continue
                
                if 'name' not in model:
                    print(f"API: Warning - model {i} has no name: {model}")
                    continue
                
                # Ensure required fields exist with defaults
                processed_model = {
                    'name': model.get('name', f'Unknown Model {i}'),
                    'size': model.get('size', 0),
                    'modified_at': model.get('modified_at', ''),
                    'digest': model.get('digest', ''),
                    'details': model.get('details', {}),
                    'times_used': 0,
                    'last_used': None,
                    'rating': 0
                }
                
                # Add usage data
                usage = ModelDB.get_usage(model['name'])
                if usage:
                    processed_model['times_used'] = usage[3] or 0
                    processed_model['last_used'] = usage[2]
                    processed_model['rating'] = usage[5] or 0
                
                processed_models.append(processed_model)
                print(f"API: Processed model {i}: {processed_model['name']} ({processed_model['size']} bytes)")
                
            except Exception as e:
                print(f"API: Error processing model {i}: {e}")
                continue
        
        print(f"API: Successfully processed {len(processed_models)} models")
        return JSONResponse(content=processed_models)
        
    except Exception as e:
        print(f"API Error in get_models: {type(e).__name__}: {e}")
        import traceback
        print(f"API Traceback: {traceback.format_exc()}")
        return JSONResponse(
            content={"error": f"Failed to fetch models: {str(e)}"}, 
            status_code=500
        )

@app.get("/api/model-info")
async def get_model_info(model: str = Query(...)):
    info = OllamaAPI.get_model_info(model)
    return JSONResponse(content=info or {})

@app.get("/api/model-usage")
async def get_model_usage(model: str = Query(...)):
    usage = ModelDB.get_usage(model)
    if usage:
        return JSONResponse(content={
            'model_name': usage[1],
            'last_used': usage[2],
            'times_used': usage[3],
            'notes': usage[4],
            'rating': usage[5],
            'performance_notes': usage[6]
        })
    return JSONResponse(content={'times_used': 0})

@app.post("/api/load-model")
async def load_model(data: dict):
    global loaded_model
    success = OllamaAPI.load_model(data['model'], data.get('config'))
    if success:
        loaded_model = {"name": data['model'], "config": data.get('config')}
        ModelDB.update_usage(data['model'])
    return JSONResponse(content={'status': 'loaded' if success else 'failed'})

@app.post("/api/unload-model")
async def unload_model(data: dict):
    global loaded_model
    success = OllamaAPI.unload_model(data['model'])
    if success:
        loaded_model = {"name": None, "config": None}
    return JSONResponse(content={'status': 'unloaded' if success else 'failed'})

@app.post("/api/update-usage")
async def update_usage(data: dict):
    ModelDB.update_usage(data['model'])
    return JSONResponse(content={'status': 'ok'})

@app.get("/api/model-config")
async def get_model_config(model: str = Query(...)):
    usage = ModelDB.get_usage(model)
    if usage and usage[7]:  # custom_params
        return JSONResponse(content={'config': usage[7]})
    return JSONResponse(content={'config': None})

@app.post("/api/save-config")
async def save_config(data: dict):
    ModelDB.save_notes(
        model_name=data['model'],
        custom_params=json.dumps(data['config'])
    )
    return JSONResponse(content={'status': 'ok'})

@app.get("/api/model-notes")
async def get_model_notes(model: str = Query(...)):
    usage = ModelDB.get_usage(model)
    if usage:
        return JSONResponse(content={
            'notes': usage[4],
            'rating': usage[5],
            'performance_notes': usage[6]
        })
    return JSONResponse(content={})

@app.post("/api/save-notes")
async def save_notes(data: dict):
    ModelDB.save_notes(
        model_name=data['model'],
        notes=data.get('notes'),
        rating=data.get('rating'),
        performance_notes=data.get('performance_notes')
    )
    return JSONResponse(content={'status': 'ok'})

@app.get("/api/export-notes")
async def export_notes():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT * FROM model_usage')
    rows = c.fetchall()
    conn.close()
    
    data = []
    for row in rows:
        data.append({
            'model_name': row[1],
            'last_used': row[2],
            'times_used': row[3],
            'notes': row[4],
            'rating': row[5],
            'performance_notes': row[6],
            'custom_params': row[7],
            'created_at': row[8]
        })
    
    return JSONResponse(
        content=data,
        headers={
            'Content-Disposition': f'attachment; filename=ollama_notes_{datetime.now().strftime("%Y%m%d")}.json'
        }
    )

@app.post("/api/chat")
async def chat(chat_msg: ChatMessage):
    ModelDB.update_usage(chat_msg.model)
    
    # Stream response
    async def generate():
        full_response = ""
        async for chunk in OllamaAPI.chat_stream(
            chat_msg.model, 
            chat_msg.message,
            chat_msg.config.dict() if chat_msg.config else None
        ):
            if 'message' in chunk and 'content' in chunk['message']:
                content = chunk['message']['content']
                full_response += content
                yield f"data: {json.dumps(chunk)}\n\n"
        
        # Save to history
        ModelDB.save_chat(chat_msg.model, chat_msg.message, full_response)
    
    return StreamingResponse(generate(), media_type="text/event-stream")

@app.get("/api/download-model")
async def download_model(model: str = Query(...)):
    """Download a model and stream progress updates"""
    async def generate():
        async for progress in OllamaAPI.pull_model_stream(model):
            if 'error' in progress:
                yield f"data: {json.dumps({'status': 'error', 'error': progress['error']})}\n\n"
            elif 'status' in progress:
                data = {
                    'status': progress['status']
                }
                if 'completed' in progress:
                    data['completed'] = progress['completed']
                if 'total' in progress:
                    data['total'] = progress['total']
                yield f"data: {json.dumps(data)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

# OpenAI-compatible proxy server
proxy_process = None

# Cleanup function for proxy files
def cleanup_proxy_files():
    """Remove any leftover proxy script files"""
    try:
        proxy_file = Path('ollama_openai_proxy.py')
        if proxy_file.exists():
            proxy_file.unlink()
            print("   🗑️  Removed leftover proxy script")
    except Exception as e:
        print(f"   ⚠️  Error cleaning up proxy files: {e}")

@app.post("/api/server/start")
async def start_server(data: dict):
    global proxy_process
    
    if proxy_process:
        return JSONResponse(content={'error': 'Server already running'}, status_code=400)
    
    # Create an OpenAI-compatible proxy server script
    proxy_script = f'''#!/usr/bin/env python3
import http.server
import socketserver
import requests
import json
import sys
import time
import uuid
from datetime import datetime

# The model to use for all requests
MODEL_NAME = "{data['model']}"

class OpenAICompatibleHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Custom logging
        sys.stderr.write(f"[{{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}] {{self.address_string()}} - {{format%args}}\\n")
    
    def do_HEAD(self):
        # Handle HEAD requests (same as GET but without body)
        if self.path in ['/v1/', '/v1', '/health', '/v1/health']:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
        elif self.path == '/v1/models':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
        else:
            self.send_error(404)
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, HEAD')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
    
    def do_GET(self):
        if self.path == '/v1' or self.path == '/v1/':
            # Root endpoint - return API info
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = {{
                "object": "api_info",
                "version": "v1",
                "endpoints": ["/v1/models", "/v1/chat/completions"]
            }}
            self.wfile.write(json.dumps(response).encode())
        elif self.path == '/v1/models':
            # List models endpoint
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = {{
                "object": "list",
                "data": [{{
                    "id": MODEL_NAME,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "ollama",
                    "permission": [{{
                        "id": "modelperm-" + MODEL_NAME,
                        "object": "model_permission",
                        "created": int(time.time()),
                        "allow_create_engine": False,
                        "allow_sampling": True,
                        "allow_logprobs": True,
                        "allow_search_indices": False,
                        "allow_view": True,
                        "allow_fine_tuning": False,
                        "organization": "*",
                        "group": None,
                        "is_blocking": False
                    }}],
                    "root": MODEL_NAME,
                    "parent": None
                }}]
            }}
            self.wfile.write(json.dumps(response).encode())
        elif self.path == '/health' or self.path == '/v1/health':
            # Health check endpoint
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            response = {{
                "status": "healthy",
                "model": MODEL_NAME,
                "timestamp": datetime.now().isoformat()
            }}
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_error(404)
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            request_data = json.loads(post_data)
        except:
            self.send_error(400, "Invalid JSON")
            return
        
        if self.path == '/v1/chat/completions':
            # Chat completions endpoint
            messages = request_data.get('messages', [])
            stream = request_data.get('stream', False)
            
            # Convert OpenAI format to Ollama format
            ollama_request = {{
                "model": MODEL_NAME,
                "messages": messages,
                "stream": stream
            }}
            
            # Add options if provided
            if 'temperature' in request_data:
                ollama_request.setdefault('options', {{}})['temperature'] = request_data['temperature']
            if 'max_tokens' in request_data:
                ollama_request.setdefault('options', {{}})['num_predict'] = request_data['max_tokens']
            
            # Forward to Ollama
            try:
                ollama_response = requests.post(
                    "http://localhost:11434/api/chat",
                    json=ollama_request,
                    stream=stream,
                    timeout=5 if not stream else None
                )
                
                # Check if request was successful
                if not stream and ollama_response.status_code != 200:
                    self.send_error(502, f"Ollama returned error: {{ollama_response.text}}")
                    return
                
                if stream:
                    # Streaming response
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    for line in ollama_response.iter_lines():
                        if line:
                            try:
                                ollama_data = json.loads(line)
                                
                                # Convert Ollama response to OpenAI format
                                openai_chunk = {{
                                    "id": f"chatcmpl-{{str(uuid.uuid4())[:8]}}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": MODEL_NAME,
                                    "choices": [{{
                                        "index": 0,
                                        "delta": {{
                                            "content": ollama_data.get('message', {{}}).get('content', '')
                                        }},
                                        "finish_reason": None
                                    }}]
                                }}
                                
                                if ollama_data.get('done', False):
                                    openai_chunk['choices'][0]['finish_reason'] = 'stop'
                                
                                self.wfile.write(f"data: {{json.dumps(openai_chunk)}}\\n\\n".encode())
                                self.wfile.flush()
                            except:
                                pass
                    
                    # Send final [DONE] message
                    self.wfile.write(b"data: [DONE]\\n\\n")
                else:
                    # Non-streaming response
                    full_response = ""
                    for line in ollama_response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                if 'message' in data and 'content' in data['message']:
                                    full_response += data['message']['content']
                            except:
                                pass
                    
                    # Send OpenAI-formatted response
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    response = {{
                        "id": f"chatcmpl-{{str(uuid.uuid4())[:8]}}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": MODEL_NAME,
                        "choices": [{{
                            "index": 0,
                            "message": {{
                                "role": "assistant",
                                "content": full_response
                            }},
                            "finish_reason": "stop"
                        }}],
                        "usage": {{
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0
                        }}
                    }}
                    
                    self.wfile.write(json.dumps(response).encode())
            
            except Exception as e:
                print(f"Error forwarding request: {{e}}", file=sys.stderr)
                self.send_error(500, f"Error communicating with Ollama: {{str(e)}}")
        
        elif self.path == '/v1/completions':
            # Legacy completions endpoint (convert to chat format)
            prompt = request_data.get('prompt', '')
            
            # Convert to chat format
            messages = [{{
                "role": "user",
                "content": prompt
            }}]
            
            # Forward as chat completion
            request_data['messages'] = messages
            self.path = '/v1/chat/completions'
            self.do_POST()
        
        else:
            self.send_error(404, f"Endpoint {{self.path}} not found")

# Allow binding to all interfaces for network access
httpd = socketserver.TCPServer(("0.0.0.0", {CLINE_PROXY_PORT}), OpenAICompatibleHandler)
httpd.allow_reuse_address = True

print(f"OpenAI-compatible proxy server running on 0.0.0.0:{CLINE_PROXY_PORT}")
print(f"Using model: {{MODEL_NAME}}")
print("Accessible from network at http://192.168.50.24:11435/v1")
print("Endpoints available:")
print("  - GET  /v1/models")
print("  - POST /v1/chat/completions")
print("  - HEAD /v1/")
sys.stdout.flush()

try:
    httpd.serve_forever()
except KeyboardInterrupt:
    print("\\nShutting down proxy server...")
    httpd.shutdown()
'''
    
    # Write and run the proxy script
    with open('ollama_openai_proxy.py', 'w') as f:
        f.write(proxy_script)
    
    proxy_process = subprocess.Popen([sys.executable, 'ollama_openai_proxy.py'])
    
    # Give it a moment to start
    time.sleep(1)
    
    return JSONResponse(content={'status': 'started', 'port': CLINE_PROXY_PORT})

@app.post("/api/server/stop")
async def stop_server():
    global proxy_process
    
    if proxy_process:
        proxy_process.terminate()
        proxy_process.wait(timeout=5)  # Wait for process to terminate
        proxy_process = None
        
        # Clean up proxy script
        cleanup_proxy_files()
        
        return JSONResponse(content={'status': 'stopped'})
    
    return JSONResponse(content={'error': 'Server not running'}, status_code=400)

if __name__ == "__main__":
    print("🚀 Starting Ollama Model Manager...")
    print("📍 Open http://localhost:8000 in your browser")
    print("⚡ Make sure Ollama is running on port 11434")
    print("🔍 Checking Ollama connection...")
    
    # Test Ollama connection
    try:
        response = requests.get(f"{OLLAMA_API_BASE}/api/tags", timeout=2)
        if response.ok:
            models = response.json().get('models', [])
            print(f"✅ Ollama is running! Found {len(models)} models")
        else:
            print(f"⚠️  Ollama responded with status {response.status_code}")
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to Ollama! Make sure it's running with: ollama serve")
    except Exception as e:
        print(f"❌ Error checking Ollama: {e}")
    
    # Handle graceful shutdown
    import signal
    
    def signal_handler(signum, frame):
        print("\n⏹️  Received interrupt signal, shutting down gracefully...")
        # The lifespan handler will take care of cleanup
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
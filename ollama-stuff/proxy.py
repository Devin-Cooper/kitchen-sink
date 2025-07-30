"""
OpenAI-compatible proxy server management
"""

import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from config import CLINE_PROXY_PORT, NETWORK_IP
from database import ServerStateDB

# Global proxy process
proxy_process: Optional[subprocess.Popen] = None

def cleanup_proxy_files():
    """Remove any leftover proxy script files"""
    try:
        proxy_file = Path('ollama_openai_proxy.py')
        if proxy_file.exists():
            proxy_file.unlink()
            print("   🗑️  Removed leftover proxy script")
    except Exception as e:
        print(f"   ⚠️  Error cleaning up proxy files: {e}")

def create_proxy_script(model_name: str) -> str:
    """Generate the proxy server script"""
    return f'''#!/usr/bin/env python3
import http.server
import socketserver
import requests
import json
import sys
import time
import uuid
from datetime import datetime

# The model to use for all requests
MODEL_NAME = "{model_name}"

class OpenAICompatibleHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Custom logging with timestamps
        sys.stderr.write(f"[{{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}] {{self.address_string()}} - {{format%args}}\\n")
    
    def do_HEAD(self):
        # Handle HEAD requests (same as GET but without body)
        if self.path in ['/v1/', '/v1', '/health', '/v1/health']:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
        elif self.path == '/v1/models' or self.path == '/v1/api/tags':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
        elif self.path.startswith('/v1/api/'):
            # Forward HEAD requests for Ollama API endpoints
            ollama_path = self.path[3:]  # Remove '/v1' prefix
            try:
                ollama_response = requests.head(f"http://localhost:11434{{ollama_path}}", timeout=5)
                self.send_response(ollama_response.status_code)
                for header, value in ollama_response.headers.items():
                    if header.lower() not in ['content-encoding', 'transfer-encoding', 'connection']:
                        self.send_header(header, value)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
            except Exception as e:
                self.send_error(500, f"Error forwarding HEAD request: {{str(e)}}")
        else:
            self.send_error(404)
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, HEAD')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With')
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
                "endpoints": ["/v1/models", "/v1/chat/completions", "/v1/api/tags"]
            }}
            self.wfile.write(json.dumps(response).encode())
        elif self.path == '/v1/models':
            # List models endpoint (OpenAI format)
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
        elif self.path == '/v1/api/tags':
            # Ollama-specific endpoint for listing models
            try:
                # Forward to actual Ollama API
                ollama_response = requests.get("http://localhost:11434/api/tags", timeout=5)
                
                if ollama_response.status_code == 200:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    
                    # Return only the currently loaded model in Ollama format
                    models_data = ollama_response.json()
                    filtered_models = []
                    
                    # Find the current model in the list
                    for model in models_data.get('models', []):
                        if model.get('name') == MODEL_NAME:
                            filtered_models.append(model)
                            break
                    
                    # If model not found in list, create a minimal entry
                    if not filtered_models:
                        filtered_models.append({{
                            "name": MODEL_NAME,
                            "modified_at": datetime.now().isoformat(),
                            "size": 0,
                            "digest": "unknown"
                        }})
                    
                    response = {{"models": filtered_models}}
                    self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_error(502, "Failed to fetch models from Ollama")
            except Exception as e:
                print(f"Error fetching models: {{e}}", file=sys.stderr)
                self.send_error(500, f"Error fetching models: {{str(e)}}")
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
        elif self.path.startswith('/v1/api/'):
            # Forward any other Ollama API calls
            ollama_path = self.path[3:]  # Remove '/v1' prefix
            try:
                ollama_response = requests.get(f"http://localhost:11434{{ollama_path}}", timeout=5)
                
                self.send_response(ollama_response.status_code)
                for header, value in ollama_response.headers.items():
                    if header.lower() not in ['content-encoding', 'transfer-encoding', 'connection']:
                        self.send_header(header, value)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                
                self.wfile.write(ollama_response.content)
            except Exception as e:
                print(f"Error forwarding request: {{e}}", file=sys.stderr)
                self.send_error(500, f"Error forwarding request: {{str(e)}}")
        else:
            self.send_error(404)
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        print(f"POST request to: {{self.path}}", file=sys.stderr)
        
        # Handle Ollama-specific API endpoints first (before JSON parsing)
        if self.path.startswith('/v1/api/'):
            ollama_path = self.path[3:]  # Remove '/v1' prefix
            
            try:
                # Prepare headers for forwarding
                headers = {{}}
                for k, v in self.headers.items():
                    if k.lower() not in ['host', 'content-length']:
                        headers[k] = v
                
                # Ensure Content-Type is set for JSON requests
                if ollama_path == '/api/chat':
                    headers['Content-Type'] = 'application/json'
                    
                    # Special handling for chat requests - modify to use current model
                    try:
                        request_data = json.loads(post_data)
                        # Override model with currently loaded model
                        request_data['model'] = MODEL_NAME
                        post_data = json.dumps(request_data).encode()
                        headers['Content-Length'] = str(len(post_data))
                        print(f"Modified chat request to use model: {{MODEL_NAME}}", file=sys.stderr)
                    except json.JSONDecodeError:
                        print(f"Failed to parse JSON for chat request", file=sys.stderr)
                        # Continue with original data
                elif post_data and not headers.get('Content-Type'):
                    headers['Content-Type'] = 'application/json'
                
                # Update Content-Length if we have data
                if post_data:
                    headers['Content-Length'] = str(len(post_data))
                
                # Forward to Ollama - adjust timeout based on endpoint
                timeout = None if ollama_path == '/api/chat' else 30
                ollama_response = requests.post(
                    f"http://localhost:11434{{ollama_path}}",
                    data=post_data,
                    headers=headers,
                    stream=True,
                    timeout=timeout
                )
                
                # Forward response
                self.send_response(ollama_response.status_code)
                for header, value in ollama_response.headers.items():
                    if header.lower() not in ['content-encoding', 'transfer-encoding', 'connection']:
                        self.send_header(header, value)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                
                # Stream response content
                for chunk in ollama_response.iter_content(chunk_size=8192):
                    if chunk:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                
                return
                
            except Exception as e:
                print(f"Error forwarding Ollama API request: {{e}}", file=sys.stderr)
                self.send_error(500, f"Error forwarding request: {{str(e)}}")
                return
        
        # Parse JSON for OpenAI-compatible endpoints
        try:
            request_data = json.loads(post_data)
        except json.JSONDecodeError:
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
                    timeout=None  # No timeout for chat requests
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
                    
                    # Convert to OpenAI format
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
print("Accessible from network at http://{NETWORK_IP}:{CLINE_PROXY_PORT}/v1")
print("Endpoints available:")
print("  - GET  /v1/models")
print("  - POST /v1/chat/completions")
print("  - POST /v1/api/chat (Ollama native)")
print("  - GET  /v1/api/tags (Ollama native)")
print("  - HEAD /v1/")
sys.stdout.flush()

try:
    httpd.serve_forever()
except KeyboardInterrupt:
    print("\\nShutting down proxy server...")
    httpd.shutdown()
'''

def start_proxy_server(model_name: str) -> bool:
    """Start the proxy server"""
    global proxy_process
    
    if proxy_process:
        return False
    
    try:
        # Create proxy script
        proxy_script = create_proxy_script(model_name)
        
        # Write proxy script to file
        with open('ollama_openai_proxy.py', 'w') as f:
            f.write(proxy_script)
        
        # Start proxy process
        proxy_process = subprocess.Popen([sys.executable, 'ollama_openai_proxy.py'])
        
        # Give it a moment to start
        time.sleep(1)
        
        # Update database state
        ServerStateDB.set_server_state(True, model_name, CLINE_PROXY_PORT)
        
        return True
    except Exception as e:
        print(f"Error starting proxy server: {e}")
        return False

def stop_proxy_server() -> bool:
    """Stop the proxy server"""
    global proxy_process
    
    if proxy_process:
        try:
            proxy_process.terminate()
            proxy_process.wait(timeout=5)
        except:
            proxy_process.kill()
        finally:
            proxy_process = None
        
        # Clean up proxy script
        cleanup_proxy_files()
        
        # Update database state
        ServerStateDB.clear_server_state()
        
        return True
    
    return False

def is_proxy_running() -> bool:
    """Check if proxy server is running"""
    global proxy_process
    
    # Check process status
    if proxy_process and proxy_process.poll() is None:
        return True
    
    # Check database state
    state = ServerStateDB.get_server_state()
    return state['is_running']

def get_proxy_status() -> dict:
    """Get current proxy server status"""
    return ServerStateDB.get_server_state()

def cleanup_on_shutdown():
    """Clean up proxy server on application shutdown"""
    global proxy_process
    
    if proxy_process:
        print("🛑 Stopping proxy server...")
        stop_proxy_server()
    
    cleanup_proxy_files() 
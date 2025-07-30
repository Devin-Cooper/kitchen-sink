"""
FastAPI route handlers for Ollama Model Manager
"""

import json
from datetime import datetime
from fastapi import Query
from fastapi.responses import JSONResponse, StreamingResponse

from models import ChatMessage, loaded_model
from database import ModelDB
from ollama_api import OllamaAPI
from proxy import start_proxy_server, stop_proxy_server, get_proxy_status

async def get_test():
    """Test endpoint"""
    return JSONResponse(content={"status": "ok", "message": "API is working"})

async def get_models():
    """Get list of available models with usage data"""
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

async def get_model_info(model: str = Query(...)):
    """Get detailed information about a specific model"""
    info = OllamaAPI.get_model_info(model)
    return JSONResponse(content=info or {})

async def get_model_usage(model: str = Query(...)):
    """Get usage statistics for a model"""
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

async def load_model(data: dict):
    """Load a model into memory"""
    success = OllamaAPI.load_model(data['model'], data.get('config'))
    if success:
        loaded_model.set_model(data['model'], data.get('config'))
        ModelDB.update_usage(data['model'])
    return JSONResponse(content={'status': 'loaded' if success else 'failed'})

async def unload_model(data: dict):
    """Unload a model from memory"""
    success = OllamaAPI.unload_model(data['model'])
    if success:
        loaded_model.clear()
    return JSONResponse(content={'status': 'unloaded' if success else 'failed'})

async def update_usage(data: dict):
    """Update usage statistics for a model"""
    ModelDB.update_usage(data['model'])
    return JSONResponse(content={'status': 'ok'})

async def get_model_config(model: str = Query(...)):
    """Get saved configuration for a model"""
    usage = ModelDB.get_usage(model)
    if usage and usage[7]:  # custom_params
        return JSONResponse(content={'config': usage[7]})
    return JSONResponse(content={'config': None})

async def save_config(data: dict):
    """Save configuration for a model"""
    ModelDB.save_notes(
        model_name=data['model'],
        custom_params=json.dumps(data['config'])
    )
    return JSONResponse(content={'status': 'ok'})

async def get_model_notes(model: str = Query(...)):
    """Get saved notes for a model"""
    usage = ModelDB.get_usage(model)
    if usage:
        return JSONResponse(content={
            'notes': usage[4],
            'rating': usage[5],
            'performance_notes': usage[6]
        })
    return JSONResponse(content={})

async def save_notes(data: dict):
    """Save notes and rating for a model"""
    ModelDB.save_notes(
        model_name=data['model'],
        notes=data.get('notes'),
        rating=data.get('rating'),
        performance_notes=data.get('performance_notes')
    )
    return JSONResponse(content={'status': 'ok'})

async def export_notes():
    """Export all model notes and usage data"""
    data = ModelDB.get_all_usage()
    
    return JSONResponse(
        content=data,
        headers={
            'Content-Disposition': f'attachment; filename=ollama_notes_{datetime.now().strftime("%Y%m%d")}.json'
        }
    )

async def chat(chat_msg: ChatMessage):
    """Stream chat responses"""
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

async def start_server(data: dict):
    """Start the OpenAI-compatible proxy server"""
    success = start_proxy_server(data['model'])
    if success:
        return JSONResponse(content={'status': 'started', 'port': 11435})
    else:
        return JSONResponse(content={'error': 'Server already running'}, status_code=400)

async def stop_server():
    """Stop the OpenAI-compatible proxy server"""
    success = stop_proxy_server()
    if success:
        return JSONResponse(content={'status': 'stopped'})
    else:
        return JSONResponse(content={'error': 'Server not running'}, status_code=400)

async def get_server_status():
    """Get current proxy server status"""
    status = get_proxy_status()
    return JSONResponse(content=status) 
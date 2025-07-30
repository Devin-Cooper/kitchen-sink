# Ollama Model Manager

A comprehensive web-based GUI for managing, configuring, and chatting with your local AI models via Ollama. Features an integrated OpenAI-compatible proxy server for seamless integration with AI clients like Ollamac and Cline.

![Ollama Model Manager](https://via.placeholder.com/800x400/0a0a0a/4a9eff?text=Ollama+Model+Manager)

## ✨ Features

### 🤖 Model Management
- **List & Browse**: View all available models with detailed information
- **Load/Unload**: Efficient model memory management
- **Download**: Pull new models directly from Ollama Hub
- **Smart Filtering**: Search and sort models by name, size, rating, usage, or date
- **Usage Tracking**: Monitor how often each model is used

### 💬 Interactive Chat
- **Real-time Chat**: Stream responses from loaded models
- **Configuration Control**: Adjust temperature, context length, and other parameters
- **Chat History**: Automatically saved conversations
- **Model Switching**: Easy switching between different models

### ⚙️ Advanced Configuration
- **Per-model Settings**: Save custom configurations for each model
- **GPU Control**: Manage GPU layer allocation
- **Context Management**: Control context window sizes up to 131K tokens
- **Parameter Tuning**: Fine-tune temperature, top-p, top-k, and more

### 🖥️ OpenAI-Compatible Proxy Server
- **Dual API Support**: Handles both OpenAI and Ollama native APIs
- **Client Integration**: Works seamlessly with Ollamac, Cline, and other AI tools
- **Request Interception**: Ensures all requests use the currently loaded model
- **Network Access**: Accessible from other devices on your network

### 📝 Model Notes & Ratings
- **Rating System**: 5-star rating system for models
- **Detailed Notes**: General notes, performance observations, and use cases
- **Export/Import**: Save and share your model evaluations

### 🔄 State Management
- **Persistent State**: Server and model status persists across page refreshes
- **Database Storage**: SQLite database for reliable data storage
- **Session Continuity**: Maintains loaded model and server state

## 🏗️ Architecture

The application is now properly modularized for maintainability and extensibility:

```
ollama-model-manager/
├── main.py              # Application entry point and FastAPI setup
├── config.py            # Configuration constants and settings
├── models.py            # Pydantic models and data structures
├── database.py          # Database operations and state management
├── ollama_api.py        # Ollama API wrapper and operations
├── proxy.py             # OpenAI-compatible proxy server management
├── routes.py            # FastAPI route handlers
├── templates/
│   └── index.html       # Main web interface template
└── README.md           # This file
```

### Component Details

#### `main.py`
- **FastAPI Application**: Main entry point with application lifespan management
- **Route Registration**: Maps all API endpoints to handler functions
- **Startup/Shutdown**: Handles database initialization and cleanup

#### `config.py`
- **Centralized Configuration**: All constants and settings in one place
- **Environment Settings**: Easy modification of ports, URLs, and other settings
- **Package Management**: Required package definitions

#### `models.py`
- **Pydantic Models**: Type-safe data structures for API requests/responses
- **State Management**: Global model state tracking
- **Data Validation**: Automatic validation of model configurations

#### `database.py`
- **SQLite Operations**: All database interactions and schema management
- **Model Usage Tracking**: Statistics and usage history
- **Server State Persistence**: Maintains proxy server state across restarts

#### `ollama_api.py`
- **API Wrapper**: Clean interface to Ollama's REST API
- **Error Handling**: Robust error handling and connection management
- **Streaming Support**: Async generators for real-time responses

#### `proxy.py`
- **Proxy Server Management**: Creates and manages the OpenAI-compatible proxy
- **Request Interception**: Modifies requests to use the currently loaded model
- **Dual Protocol Support**: Handles both OpenAI and Ollama API formats

#### `routes.py`
- **API Handlers**: All FastAPI route handler functions
- **Business Logic**: Core application logic separated from web framework
- **Response Formatting**: Consistent API response formatting

#### `templates/index.html`
- **Single Page Application**: Complete web interface with embedded CSS and JavaScript
- **Responsive Design**: Modern, dark-themed UI that works on all devices
- **Real-time Updates**: WebSocket-style streaming for chat and downloads

## 🚀 Getting Started

### Prerequisites

- **Python 3.8+**: Required for FastAPI and async features
- **Ollama**: Must be installed and running (`ollama serve`)
- **Models**: At least one model downloaded in Ollama

### Installation & Running

1. **Clone or download** the project files to a directory
2. **Navigate** to the project directory
3. **Run the application**:
   ```bash
   python main.py
   ```

The application will:
- Automatically install required Python packages
- Initialize the database
- Test the connection to Ollama
- Start the web server on `http://localhost:8000`

### First Time Setup

1. **Ensure Ollama is running**: `ollama serve`
2. **Download a model** (if you haven't already): `ollama pull llama3.1:8b`
3. **Open your browser** to `http://localhost:8000`
4. **Select and load a model** from the list
5. **Start chatting** or configure the proxy server!

## 🔧 Configuration

### Network Settings

Edit `config.py` to customize:

```python
HOST = "0.0.0.0"           # Bind to all interfaces
PORT = 8000                # Web interface port
CLINE_PROXY_PORT = 11435   # Proxy server port
NETWORK_IP = "192.168.50.24"  # Your network IP for client config
```

### Database

The SQLite database (`ollama_models.db`) stores:
- Model usage statistics and ratings
- Custom configurations per model
- Chat history
- Server state for persistence

## 🖥️ Using the Proxy Server

### For Ollamac (Ollama macOS client)

1. **Load a model** in the Model Manager
2. **Start the proxy server** in the "Server Mode" tab
3. **Configure Ollamac**:
   - API Provider: `OpenAI Compatible`
   - Base URL: `http://YOUR_IP:11435/v1`
   - API Key: `ollama` (or any text)
   - Model: (will be automatically overridden)

### For Cline (VS Code Extension)

1. **Load a model** in the Model Manager
2. **Start the proxy server**
3. **Configure Cline**:
   - Provider: `OpenAI Compatible`
   - Base URL: `http://YOUR_IP:11435/v1`
   - API Key: `ollama`
   - Model: Copy from the server config display

### Proxy Features

- **Model Override**: All requests automatically use your loaded model
- **Dual API Support**: Handles both OpenAI and Ollama-specific endpoints
- **Request Logging**: Debug output for troubleshooting
- **Network Access**: Available to other devices on your network
- **No Timeout on Chat**: Long responses won't time out

## 🐛 Troubleshooting

### Common Issues

**"Cannot connect to Ollama"**
- Ensure Ollama is running: `ollama serve`
- Check if port 11434 is accessible
- Verify no firewall is blocking connections

**"No models found"**
- Download a model: `ollama pull llama3.1:8b`
- Refresh the models list in the interface
- Check Ollama logs for errors

**"Proxy server not starting"**
- Ensure a model is loaded first
- Check if port 11435 is available
- Look for error messages in the console

**"Chat requests timing out"**
- This should be fixed in the current version
- Try unloading and reloading the model
- Check available system memory

### Network Access Issues

If clients can't connect to the proxy:
1. **Update your network IP** in `config.py`
2. **Check firewall settings** for port 11435
3. **Ensure the host is set to** `"0.0.0.0"` in config
4. **Test connectivity**: `curl http://YOUR_IP:11435/v1/models`

### State Management Issues

If the interface shows incorrect state after refresh:
- The new version includes persistent state management
- Server and model status are now saved to the database
- The interface will correctly restore state on page load

## 🚧 Development

### Adding New Features

The modular architecture makes it easy to extend:

1. **New API endpoints**: Add handlers to `routes.py` and register in `main.py`
2. **Database changes**: Modify schema in `database.py`
3. **UI enhancements**: Edit `templates/index.html`
4. **Ollama integration**: Extend `ollama_api.py`

### Testing

```bash
# Test the API
curl http://localhost:8000/health

# Test model listing
curl http://localhost:8000/api/models

# Test proxy endpoints
curl http://localhost:11435/v1/models
```

## 📝 License

MIT License - Feel free to use, modify, and distribute!

## 🙏 Acknowledgments

- **Ollama**: For providing the excellent local AI model platform
- **FastAPI**: For the robust web framework
- **SQLite**: For reliable local data storage

---

**Enjoy managing your AI models!** 🤖✨ 
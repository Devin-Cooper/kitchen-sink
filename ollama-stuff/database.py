"""
Database operations for Ollama Model Manager
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any
from config import DB_PATH

def init_db():
    """Initialize the database with required tables"""
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
    
    # Add table for tracking proxy server state
    c.execute('''
        CREATE TABLE IF NOT EXISTS server_state (
            id INTEGER PRIMARY KEY,
            is_running BOOLEAN DEFAULT 0,
            model_name TEXT,
            port INTEGER,
            started_at TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

class ModelDB:
    """Database operations for model management"""
    
    @staticmethod
    def get_usage(model_name: str):
        """Get usage statistics for a model"""
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
        """Update usage count and last used timestamp for a model"""
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
        """Save notes and configuration for a model"""
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
        """Save chat history"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO chat_history (model_name, user_message, assistant_message)
            VALUES (?, ?, ?)
        ''', (model_name, user_message, assistant_message))
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_all_usage() -> list:
        """Get all model usage data for export"""
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
        return data

class ServerStateDB:
    """Database operations for server state management"""
    
    @staticmethod
    def set_server_state(is_running: bool, model_name: str = None, port: int = None):
        """Update server running state"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Clear existing state and insert new
        c.execute('DELETE FROM server_state')
        if is_running:
            c.execute('''
                INSERT INTO server_state (id, is_running, model_name, port, started_at)
                VALUES (1, ?, ?, ?, ?)
            ''', (is_running, model_name, port, datetime.now()))
        
        conn.commit()
        conn.close()
    
    @staticmethod
    def get_server_state() -> Dict[str, Any]:
        """Get current server state"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT * FROM server_state WHERE id = 1')
        result = c.fetchone()
        conn.close()
        
        if result:
            return {
                'is_running': bool(result[1]),
                'model_name': result[2],
                'port': result[3],
                'started_at': result[4]
            }
        return {'is_running': False, 'model_name': None, 'port': None, 'started_at': None}
    
    @staticmethod
    def clear_server_state():
        """Clear server state (called when server stops)"""
        ServerStateDB.set_server_state(False) 
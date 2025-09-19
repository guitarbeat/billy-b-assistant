"""
OpenAI API configuration and connection management.
Centralizes OpenAI API settings, connection logic, and common patterns.
"""
import asyncio
import json
from typing import Any, Dict, List, Optional

from .config import OPENAI_API_KEY, OPENAI_MODEL, VOICE, INSTRUCTIONS
from .constants import (
    OPENAI_REALTIME_URI,
    OPENAI_DEFAULT_MODEL,
    OPENAI_DEFAULT_VOICE,
    WS_SESSION_UPDATE,
    WS_CONVERSATION_ITEM_CREATE,
    WS_RESPONSE_CREATE,
    WS_SESSION_END,
    WS_INPUT_AUDIO_BUFFER_APPEND,
    WS_INPUT_AUDIO_BUFFER_COMMIT,
)
from .error_handling import handle_openai_error, retry_on_failure


class OpenAIConfig:
    """OpenAI API configuration and connection settings."""
    
    def __init__(
        self,
        api_key: str = OPENAI_API_KEY,
        model: str = OPENAI_MODEL,
        voice: str = VOICE,
        base_uri: str = OPENAI_REALTIME_URI
    ):
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.base_uri = base_uri
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "openai-beta": "realtime=v1",
        }

    def get_connection_uri(self) -> str:
        """Get the full WebSocket connection URI."""
        return f"{self.base_uri}?model={self.model}"

    def get_headers(self) -> Dict[str, str]:
        """Get connection headers."""
        return self.headers.copy()

    def validate_config(self) -> bool:
        """Validate that the configuration is complete."""
        return bool(self.api_key and self.model and self.voice)

    def create_session_config(
        self,
        modalities: List[str] = None,
        instructions: str = "",
        tools: List[Dict] = None,
        turn_detection: Dict = None,
        input_audio_format: str = "pcm16",
        output_audio_format: str = "pcm16"
    ) -> Dict[str, Any]:
        """Create a session configuration dictionary."""
        return {
            "type": WS_SESSION_UPDATE,
            "session": {
                "voice": self.voice,
                "modalities": modalities or ["audio", "text"],
                "input_audio_format": input_audio_format,
                "output_audio_format": output_audio_format,
                "turn_detection": turn_detection or {"type": "server_vad"},
                "instructions": instructions or INSTRUCTIONS,
                "tools": tools or [],
            },
        }

    def create_message_config(
        self,
        text: str,
        role: str = "user"
    ) -> Dict[str, Any]:
        """Create a message configuration dictionary."""
        return {
            "type": WS_CONVERSATION_ITEM_CREATE,
            "item": {
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            },
        }

    def create_response_config(
        self,
        modalities: List[str] = None
    ) -> Dict[str, Any]:
        """Create a response configuration dictionary."""
        return {
            "type": WS_RESPONSE_CREATE,
            "response": {"modalities": modalities or ["audio", "text"]},
        }

    def create_audio_append_config(
        self,
        audio_data: bytes
    ) -> Dict[str, Any]:
        """Create an audio append configuration dictionary."""
        import base64
        return {
            "type": WS_INPUT_AUDIO_BUFFER_APPEND,
            "audio": base64.b64encode(audio_data).decode("utf-8"),
        }

    def create_audio_commit_config(self) -> Dict[str, Any]:
        """Create an audio commit configuration dictionary."""
        return {
            "type": WS_INPUT_AUDIO_BUFFER_COMMIT,
        }

    def create_session_end_config(self) -> Dict[str, Any]:
        """Create a session end configuration dictionary."""
        return {
            "type": WS_SESSION_END,
        }


class OpenAIConnectionManager:
    """Manages OpenAI API connections and common operations."""
    
    def __init__(self, config: OpenAIConfig):
        self.config = config
        self.active_connections = set()

    @retry_on_failure(max_retries=3, delay=1.0, exceptions=(Exception,))
    async def create_connection(self, websocket_client_class):
        """Create a new WebSocket connection with retry logic."""
        try:
            uri = self.config.get_connection_uri()
            headers = self.config.get_headers()
            
            connection = await websocket_client_class.connect(
                uri, additional_headers=headers
            )
            self.active_connections.add(connection)
            return connection
        except Exception as e:
            handle_openai_error(e, "creating connection")
            raise

    async def close_connection(self, connection):
        """Close a WebSocket connection."""
        try:
            if connection in self.active_connections:
                self.active_connections.remove(connection)
            await connection.close()
            await connection.wait_closed()
        except Exception as e:
            handle_openai_error(e, "closing connection")

    async def close_all_connections(self):
        """Close all active connections."""
        for connection in list(self.active_connections):
            await self.close_connection(connection)

    async def send_message(self, connection, message: Dict[str, Any]):
        """Send a message through the connection."""
        try:
            await connection.send(json.dumps(message))
        except Exception as e:
            handle_openai_error(e, "sending message")
            raise

    async def send_audio_chunk(self, connection, audio_data: bytes):
        """Send audio data through the connection."""
        message = self.config.create_audio_append_config(audio_data)
        await self.send_message(connection, message)

    async def commit_audio_buffer(self, connection):
        """Commit the audio buffer."""
        message = self.config.create_audio_commit_config()
        await self.send_message(connection, message)

    async def start_session(
        self,
        connection,
        modalities: List[str] = None,
        instructions: str = "",
        tools: List[Dict] = None
    ):
        """Start a new session."""
        config = self.config.create_session_config(
            modalities=modalities,
            instructions=instructions,
            tools=tools
        )
        await self.send_message(connection, config)

    async def send_text_message(self, connection, text: str, role: str = "user"):
        """Send a text message."""
        config = self.config.create_message_config(text, role)
        await self.send_message(connection, config)

    async def request_response(self, connection, modalities: List[str] = None):
        """Request a response from the assistant."""
        config = self.config.create_response_config(modalities)
        await self.send_message(connection, config)

    async def end_session(self, connection):
        """End the current session."""
        config = self.config.create_session_end_config()
        await self.send_message(connection, config)


# Global configuration and connection manager
openai_config = OpenAIConfig()
connection_manager = OpenAIConnectionManager(openai_config)


def get_openai_config() -> OpenAIConfig:
    """Get the global OpenAI configuration."""
    return openai_config


def get_connection_manager() -> OpenAIConnectionManager:
    """Get the global connection manager."""
    return connection_manager


def validate_openai_setup() -> bool:
    """Validate that OpenAI is properly configured."""
    if not openai_config.validate_config():
        print("❌ OpenAI configuration is incomplete. Please check your API key and settings.")
        return False
    return True
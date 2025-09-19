"""
Shared WebSocket client utilities for OpenAI Realtime API connections.
Consolidates common connection logic used across audio.py, say.py, and wakeup.py.
"""
import asyncio
import base64
import json
from typing import Any, AsyncGenerator, Dict, Optional

import websockets.asyncio.client
import websockets.legacy.client

from .openai_config import get_openai_config, get_connection_manager


class OpenAIConnectionConfig:
    """Configuration for OpenAI Realtime API connections."""
    
    def __init__(
        self,
        voice: str = VOICE,
        modalities: list[str] = None,
        output_audio_format: str = "pcm16",
        turn_detection: dict = None,
        instructions: str = "",
        tools: list = None
    ):
        self.voice = voice
        self.modalities = modalities or ["audio", "text"]
        self.output_audio_format = output_audio_format
        self.turn_detection = turn_detection or {"type": "server_vad"}
        self.instructions = instructions
        self.tools = tools or []


class AudioChunk:
    """Represents an audio chunk with metadata."""
    
    def __init__(self, data: bytes, chunk_type: str = "audio"):
        self.data = data
        self.chunk_type = chunk_type


class OpenAIWebSocketClient:
    """Shared WebSocket client for OpenAI Realtime API."""
    
    def __init__(self, config: OpenAIConnectionConfig):
        self.config = config
        self.ws = None
        self.openai_config = get_openai_config()
        self.connection_manager = get_connection_manager()
        self.uri = self.openai_config.get_connection_uri()
        self.headers = self.openai_config.get_headers()

    async def connect(self) -> None:
        """Establish WebSocket connection and configure session."""
        self.ws = await websockets.asyncio.client.connect(
            self.uri, additional_headers=self.headers
        )
        
        session_config = {
            "voice": self.config.voice,
            "modalities": self.config.modalities,
            "output_audio_format": self.config.output_audio_format,
            "turn_detection": self.config.turn_detection,
            "instructions": self.config.instructions,
        }
        
        if self.config.tools:
            session_config["tools"] = self.config.tools
            
        await self.ws.send(json.dumps({
            "type": "session.update",
            "session": session_config,
        }))

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self.ws:
            try:
                await self.ws.close()
                await self.ws.wait_closed()
            except Exception as e:
                print(f"⚠️ Error closing websocket: {e}")
            finally:
                self.ws = None

    async def send_message(self, text: str, role: str = "user") -> None:
        """Send a text message to the conversation."""
        await self.ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            },
        }))

    async def create_response(self, modalities: list[str] = None) -> None:
        """Request a response from the assistant."""
        response_config = {"modalities": modalities or self.config.modalities}
        await self.ws.send(json.dumps({
            "type": "response.create",
            "response": response_config,
        }))

    async def commit_audio_buffer(self) -> None:
        """Commit the current audio buffer."""
        await self.ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def send_audio_chunk(self, audio_data: bytes) -> None:
        """Send audio data to the input buffer."""
        pcm_b64 = base64.b64encode(audio_data).decode("utf-8")
        await self.ws.send(json.dumps({
            "type": "input_audio_buffer.append",
            "audio": pcm_b64,
        }))

    async def listen_for_response(self) -> AsyncGenerator[Dict[str, Any], None]:
        """Listen for response messages from the WebSocket."""
        async for message in self.ws:
            data = json.loads(message)
            yield data

    async def extract_audio_chunks(self) -> AsyncGenerator[AudioChunk, None]:
        """Extract audio chunks from response messages."""
        async for data in self.listen_for_response():
            if data["type"] in ("response.audio", "response.audio.delta"):
                audio_b64 = data.get("audio") or data.get("delta")
                if audio_b64:
                    audio_data = base64.b64decode(audio_b64)
                    yield AudioChunk(audio_data, "audio")
            elif data["type"] == "response.done":
                break

    async def extract_text_deltas(self) -> AsyncGenerator[str, None]:
        """Extract text deltas from response messages."""
        async for data in self.listen_for_response():
            if data["type"] in ("response.text.delta", "response.audio_transcript.delta"):
                delta = data.get("delta")
                if delta:
                    yield delta
            elif data["type"] == "response.done":
                break


async def create_websocket_connection(config: OpenAIConnectionConfig) -> OpenAIWebSocketClient:
    """Create and connect a new WebSocket client."""
    client = OpenAIWebSocketClient(config)
    await client.connect()
    return client


def create_legacy_websocket_connection(config: OpenAIConnectionConfig):
    """Create a legacy WebSocket connection (for compatibility)."""
    uri = f"wss://api.openai.com/v1/realtime?model={OPENAI_MODEL}"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "openai-beta": "realtime=v1",
    }
    
    return websockets.legacy.client.connect(uri, extra_headers=headers)
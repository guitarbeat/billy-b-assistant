"""
Shared audio processing utilities.
Consolidates common audio handling logic used across multiple modules.
"""
import asyncio
import base64
import os
import wave
from typing import AsyncGenerator, Optional

import numpy as np
from scipy.signal import resample

from .audio import playback_queue, rotate_and_save_response_audio
from .config import CHUNK_MS, PLAYBACK_VOLUME
from .movements import move_head


class AudioProcessor:
    """Handles audio processing and playback operations."""
    
    def __init__(self, sample_rate: int = 24000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels

    def process_audio_chunk(self, audio_data: bytes) -> bytes:
        """Process audio chunk for playback (resample, convert to stereo, apply volume)."""
        mono = np.frombuffer(audio_data, dtype=np.int16)
        chunk_len = int(self.sample_rate * CHUNK_MS / 1000)
        
        processed_chunks = []
        for i in range(0, len(mono), chunk_len):
            sub = mono[i:i + chunk_len]
            if len(sub) == 0:
                continue
                
            # Resample from 24kHz to 48kHz
            resampled = resample(
                sub, int(len(sub) * 48000 / self.sample_rate)
            ).astype(np.int16)
            
            # Convert to stereo
            stereo = np.repeat(resampled[:, np.newaxis], 2, axis=1)
            
            # Apply volume and clip
            stereo = np.clip(
                stereo * PLAYBACK_VOLUME, -32768, 32767
            ).astype(np.int16)
            
            processed_chunks.append(stereo.tobytes())
            
        return b''.join(processed_chunks)

    def enqueue_audio_chunk(self, audio_data: bytes) -> None:
        """Enqueue processed audio chunk for playback."""
        processed = self.process_audio_chunk(audio_data)
        playback_queue.put(processed)

    async def play_audio_with_head_movement(
        self, 
        audio_data: bytes, 
        save_audio: bool = True
    ) -> None:
        """Play audio with head movement and optional saving."""
        if save_audio:
            rotate_and_save_response_audio(audio_data)
        
        move_head("on")
        
        try:
            self.enqueue_audio_chunk(audio_data)
            # Signal end of playback
            playback_queue.put(None)
            # Wait for playback to complete
            await asyncio.to_thread(playback_queue.join)
        finally:
            move_head("off")

    def save_audio_to_wav(self, audio_data: bytes, filepath: str) -> None:
        """Save audio data to WAV file."""
        with wave.open(filepath, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_data)

    def load_wav_file(self, filepath: str) -> bytes:
        """Load audio data from WAV file."""
        with wave.open(filepath, 'rb') as wf:
            if (wf.getframerate() != self.sample_rate or 
                wf.getnchannels() != self.channels or 
                wf.getsampwidth() != 2):
                raise ValueError(f"WAV file must be {self.sample_rate} Hz, mono, 16-bit")
            return wf.readframes(wf.getnframes())


class AudioStreamProcessor:
    """Handles streaming audio processing from WebSocket responses."""
    
    def __init__(self, processor: AudioProcessor):
        self.processor = processor
        self.audio_buffer = bytearray()
        self.full_text = ""

    def process_audio_delta(self, audio_b64: str) -> None:
        """Process audio delta from WebSocket response."""
        audio_chunk = base64.b64decode(audio_b64)
        self.audio_buffer.extend(audio_chunk)
        self.processor.enqueue_audio_chunk(audio_chunk)

    def process_text_delta(self, delta: str) -> None:
        """Process text delta from WebSocket response."""
        self.full_text += delta

    def get_audio_buffer(self) -> bytes:
        """Get the complete audio buffer."""
        return bytes(self.audio_buffer)

    def get_full_text(self) -> str:
        """Get the complete text response."""
        return self.full_text.strip()

    def clear_buffers(self) -> None:
        """Clear audio and text buffers."""
        self.audio_buffer.clear()
        self.full_text = ""


def create_audio_processor(sample_rate: int = 24000, channels: int = 1) -> AudioProcessor:
    """Create a new audio processor instance."""
    return AudioProcessor(sample_rate, channels)


def create_stream_processor(processor: AudioProcessor) -> AudioStreamProcessor:
    """Create a new audio stream processor instance."""
    return AudioStreamProcessor(processor)
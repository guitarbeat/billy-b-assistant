"""
Main audio module - provides simplified interface to audio functionality.
This module consolidates audio device management and playback operations.
"""
import asyncio
import base64
import json
import os
import time
import wave

import numpy as np
from scipy.signal import resample

from .audio_device_manager import device_manager
from .audio_playback import playback_manager
from .config import CHUNK_MS, MIC_TIMEOUT_SECONDS, SILENCE_THRESHOLD, TEXT_ONLY_MODE
from .constants import DEFAULT_SAMPLE_RATE, DEFAULT_CHANNELS, SONGS_DIR
from .movements import move_tail_async, stop_all_motors


# Expose the main interfaces for backward compatibility
playback_queue = playback_manager.playback_queue
head_move_queue = playback_manager.head_move_queue
playback_done_event = playback_manager.playback_done_event
last_played_time = playback_manager.last_played_time
song_mode = playback_manager.song_mode
beat_length = playback_manager.beat_length
compensate_tail_beats = playback_manager.compensate_tail_beats

# Device configuration
MIC_DEVICE_INDEX = device_manager.mic_device_index
MIC_RATE = device_manager.mic_rate
MIC_CHANNELS = device_manager.mic_channels
OUTPUT_DEVICE_INDEX = device_manager.output_device_index
OUTPUT_CHANNELS = device_manager.output_channels
OUTPUT_RATE = device_manager.output_rate
CHUNK_SIZE = device_manager.chunk_size


def detect_devices(debug=False):
    """Detect and configure audio devices."""
    device_manager.detect_devices(debug)
    
    # Update global variables for backward compatibility
    global MIC_DEVICE_INDEX, MIC_RATE, MIC_CHANNELS, CHUNK_SIZE
    global OUTPUT_DEVICE_INDEX, OUTPUT_RATE, OUTPUT_CHANNELS
    
    MIC_DEVICE_INDEX = device_manager.mic_device_index
    MIC_RATE = device_manager.mic_rate
    MIC_CHANNELS = device_manager.mic_channels
    CHUNK_SIZE = device_manager.chunk_size
    OUTPUT_DEVICE_INDEX = device_manager.output_device_index
    OUTPUT_RATE = device_manager.output_rate
    OUTPUT_CHANNELS = device_manager.output_channels


def ensure_playback_worker_started(chunk_ms):
    """Ensure the playback worker thread is running."""
    playback_manager.ensure_playback_worker_started(chunk_ms)


def save_audio_to_wav(audio_bytes, filename):
    """Save audio data to WAV file."""
    playback_manager.save_audio_to_wav(audio_bytes, filename)


def rotate_and_save_response_audio(audio_bytes):
    """Rotate old response files and save new audio."""
    playback_manager.rotate_and_save_response_audio(audio_bytes)


def handle_incoming_audio_chunk(audio_b64, buffer):
    """Handle incoming audio chunk from WebSocket."""
    audio_chunk = base64.b64decode(audio_b64)
    buffer.extend(audio_chunk)
    playback_queue.put(audio_chunk)
    return len(audio_chunk)


def send_mic_audio(ws, samples, loop):
    """Send microphone audio to WebSocket."""
    pcm = (
        resample(samples, int(len(samples) * 24000 / MIC_RATE))
        .astype(np.int16)
        .tobytes()
    )
    try:
        future = asyncio.run_coroutine_threadsafe(
            ws.send(
                json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm).decode("utf-8"),
                })
            ),
            loop,
        )

        # Await the result; avoid race conditions.
        future.result()
    except Exception as e:
        print(f"❌ Failed to send audio chunk: {e}")


def enqueue_wav_to_playback(filepath):
    """Read a WAV file and enqueue its PCM audio data to the playback queue."""
    playback_manager.enqueue_wav_to_playback(filepath)


def play_random_wake_up_clip():
    """Select and enqueue a random wake-up WAV file with mouth movement."""
    return playback_manager.play_random_wake_up_clip()


def stop_playback():
    """Immediately stop playback and flush queue."""
    playback_manager.stop_playback()


def is_billy_speaking():
    """Return True if Billy is still playing audio."""
    return playback_manager.is_billy_speaking()


def reset_for_new_song():
    """Reset playback state for a new song."""
    playback_manager.reset_for_new_song()


async def play_song(song_name):
    """Play a full Billy song: main audio, vocals for mouth, drums for tail."""
    import contextlib

    from core import audio
    from core.movements import stop_all_motors
    from core.mqtt import mqtt_publish

    reset_for_new_song()

    SONG_DIR = os.path.join(SONGS_DIR, song_name)
    MAIN_AUDIO = os.path.join(SONG_DIR, "full.wav")
    VOCALS_AUDIO = os.path.join(SONG_DIR, "vocals.wav")
    DRUMS_AUDIO = os.path.join(SONG_DIR, "drums.wav")
    METADATA_FILE = os.path.join(SONG_DIR, "metadata.txt")

    def load_metadata(path):
        metadata = {
            "bpm": None,
            "head_moves": [],
            "tail_threshold": 1500,
            "gain": 1.0,
            "compensate_tail": 0.0,
            "half_tempo_tail_flap": False,
        }
        if not os.path.exists(path):
            print(f"⚠️ No metadata.txt found at {path}")
            return metadata

        with open(path) as f:
            for line in f:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    if key == "head_moves":
                        metadata[key] = [
                            (float(v.split(':')[0]), float(v.split(':')[1]))
                            for v in value.split(',')
                        ]
                    elif key in ("bpm", "tail_threshold", "gain", "compensate_tail"):
                        metadata[key] = float(value.strip())
                    elif key == "half_tempo_tail_flap":
                        metadata[key] = value.strip().lower() == "true"
        return metadata

    # --- Load metadata ---
    metadata = load_metadata(METADATA_FILE)
    GAIN = metadata.get("gain", 1.0)
    BPM = metadata.get("bpm", 120)
    tail_threshold = metadata.get("tail_threshold", 1500)
    global compensate_tail_beats
    compensate_tail_beats = metadata.get("compensate_tail", 0.0)
    head_move_schedule = metadata.get("head_moves", [])
    for move in head_move_schedule:
        audio.head_move_queue.put(move)
    half_tempo_tail_flap = metadata.get("half_tempo_tail_flap", False)

    audio.beat_length = 60.0 / BPM
    if metadata.get("half_tempo_tail_flap"):
        audio.beat_length *= 2

    # Start the playback worker, passing the schedule
    audio.song_mode = True
    ensure_playback_worker_started(CHUNK_MS)

    mqtt_publish("billy/state", STATE_PLAYING_SONG)
    print(f"\n🎧 Playing {song_name} with mouth (vocals) and tail (drums) flaps")

    try:
        with contextlib.ExitStack() as stack:
            wf_main = stack.enter_context(wave.open(MAIN_AUDIO, 'rb'))
            wf_vocals = stack.enter_context(wave.open(VOCALS_AUDIO, 'rb'))
            wf_drums = stack.enter_context(wave.open(DRUMS_AUDIO, 'rb'))

            rate_main = wf_main.getframerate()
            rate_vocals = wf_vocals.getframerate()
            rate_drums = wf_drums.getframerate()

            chunk_size_main = int(rate_main * CHUNK_MS / 1000)
            chunk_size_vocals = int(rate_vocals * CHUNK_MS / 1000)
            chunk_size_drums = int(rate_drums * CHUNK_MS / 1000)

            while True:
                frames_main = wf_main.readframes(chunk_size_main)
                frames_vocals = wf_vocals.readframes(chunk_size_vocals)
                frames_drums = wf_drums.readframes(chunk_size_drums)

                if not frames_main:
                    break

                # --- Main audio (24kHz mono)
                samples_main = np.frombuffer(frames_main, dtype=np.int16)
                samples_main = samples_main.reshape((-1, 2)).mean(axis=1)
                if rate_main == 48000:
                    samples_main = resample(
                        samples_main, len(samples_main) // 2
                    ).astype(np.int16)
                samples_main = np.clip(samples_main * GAIN, -32768, 32767).astype(
                    np.int16
                )

                # --- Vocals (for mouth flap)
                samples_vocals = np.frombuffer(frames_vocals, dtype=np.int16)
                samples_vocals = samples_vocals.reshape((-1, 2)).mean(axis=1)
                if rate_vocals == 48000:
                    samples_vocals = resample(
                        samples_vocals, len(samples_vocals) // 2
                    ).astype(np.int16)
                samples_vocals = np.clip(samples_vocals * GAIN, -32768, 32767).astype(
                    np.int16
                )

                # --- Drums (for tail flap)
                samples_drums = np.frombuffer(frames_drums, dtype=np.int16)
                samples_drums = samples_drums.reshape((-1, 2)).mean(axis=1)
                if rate_drums == 48000:
                    samples_drums = resample(
                        samples_drums, len(samples_drums) // 2
                    ).astype(np.int16)
                samples_drums = np.clip(samples_drums * GAIN, -32768, 32767).astype(
                    np.int16
                )
                rms_drums = np.sqrt(np.mean(samples_drums.astype(np.float32) ** 2))

                # --- Enqueue combined chunk
                audio.playback_queue.put((
                    "song",
                    samples_main.tobytes(),
                    samples_vocals.tobytes(),
                    rms_drums,
                ))

        print("⌛ Waiting for song playback to complete...")
        await asyncio.to_thread(audio.playback_queue.join())

    except Exception as e:
        print(f"❌ Playback failed: {e}")

    finally:
        audio.song_mode = False
        stop_all_motors()
        mqtt_publish("billy/state", STATE_IDLE)
        print("🎶 Song finished, waiting for button press.")

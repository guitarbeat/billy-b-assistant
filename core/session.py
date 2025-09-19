import asyncio
import base64
import json
import os
import re
import socket
import time
from typing import Any

import numpy as np
import websockets.asyncio.client
import websockets.exceptions

from . import audio
from .audio_utils import create_audio_processor, create_stream_processor
from .config import (
    CHUNK_MS,
    DEBUG_MODE,
    DEBUG_MODE_INCLUDE_DELTA,
    INSTRUCTIONS,
    MIC_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    PERSONALITY,
    RUN_MODE,
    SILENCE_THRESHOLD,
    TEXT_ONLY_MODE,
    VOICE,
)
from .constants import (
    SUCCESS_SESSION_STARTED,
    WS_SESSION_UPDATED,
    WS_RESPONSE_DONE,
    WS_RESPONSE_AUDIO,
    WS_RESPONSE_AUDIO_DELTA,
    WS_RESPONSE_TEXT_DELTA,
    WS_RESPONSE_AUDIO_TRANSCRIPT_DELTA,
    WS_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE,
    WS_INPUT_AUDIO_BUFFER_COMMIT,
    WS_ERROR,
    STATE_LISTENING,
    STATE_SPEAKING,
    STATE_IDLE,
    ERROR_NETWORK_UNREACHABLE,
    ERROR_INVALID_API_KEY,
    NO_API_KEY_WAV,
    NO_WIFI_WAV,
)
from .ha import send_conversation_prompt
from .mic import MicManager
from .movements import move_tail_async, stop_all_motors
from .mqtt import mqtt_publish
from .personality import update_persona_ini
from .websocket_client import OpenAIConnectionConfig, OpenAIWebSocketClient


TOOLS = [
    {
        "name": "update_personality",
        "type": "function",
        "description": "Adjusts Billy's personality traits",
        "parameters": {
            "type": "object",
            "properties": {
                trait: {"type": "integer", "minimum": 0, "maximum": 100}
                for trait in vars(PERSONALITY)
            },
        },
    },
    {
        "name": "play_song",
        "type": "function",
        "description": "Plays a special Billy song based on a given name.",
        "parameters": {
            "type": "object",
            "properties": {"song": {"type": "string"}},
            "required": ["song"],
        },
    },
    {
        "name": "smart_home_command",
        "type": "function",
        "description": "Send a natural language prompt to the Home Assistant conversation API and read back the response.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The command to send to Home Assistant",
                }
            },
            "required": ["prompt"],
        },
    },
]


class BillySession:
    def __init__(self, interrupt_event=None):
        self.ws_client: OpenAIWebSocketClient | None = None
        self.ws_lock: asyncio.Lock = asyncio.Lock()
        self.loop = None
        self.audio_processor = create_audio_processor()
        self.stream_processor = create_stream_processor(self.audio_processor)
        self.committed = False
        self.first_text = True
        self.full_response_text = ""
        self.last_rms = 0.0
        self.last_activity = [time.time()]
        self.session_active = asyncio.Event()
        self.user_spoke_after_assistant = False
        self.allow_mic_input = True
        self.interrupt_event = interrupt_event or asyncio.Event()
        self.mic = MicManager()
        self.mic_timeout_task: asyncio.Task | None = None

        # Track whenever a session is updated after creation, and OpenAI is ready to
        # receive voice.
        self.session_initialized = False
        self.run_mode = RUN_MODE

    async def start(self):
        self.loop = asyncio.get_running_loop()
        print("\n⏱️ Session starting...")

        self.stream_processor.clear_buffers()
        self.committed = False
        self.first_text = True
        self.full_response_text = ""
        self.last_activity[0] = time.time()
        self.session_active.set()
        self.user_spoke_after_assistant = False
        self.allow_mic_input = True

        async with self.ws_lock:
            if self.ws_client is None:
                # Configure WebSocket connection
                config = OpenAIConnectionConfig(
                    modalities=["text"] if TEXT_ONLY_MODE else ["audio", "text"],
                    instructions=INSTRUCTIONS,
                    tools=TOOLS
                )

                try:
                    self.ws_client = OpenAIWebSocketClient(config)
                    await self.ws_client.connect()

                except socket.gaierror:
                    print(f"📡 {ERROR_NETWORK_UNREACHABLE} Playing nowifi.wav...")
                    path = NO_WIFI_WAV
                    if os.path.exists(path):
                        await asyncio.to_thread(audio.enqueue_wav_to_playback, path)
                        await asyncio.to_thread(audio.playback_queue.join)
                    else:
                        print("⚠️ nowifi.wav not found, skipping.")
                    return

                except Exception as e:
                    print(f"❌ Unexpected error during WebSocket setup: {e}")
                    raise

        if not TEXT_ONLY_MODE:
            audio.playback_done_event.clear()
            audio.ensure_playback_worker_started(CHUNK_MS)

        await self.run_stream()

    def mic_callback(self, indata, *_):
        if not self.allow_mic_input or not self.session_active.is_set():
            return
        samples = indata[:, 0]
        rms = np.sqrt(np.mean(np.square(samples.astype(np.float32))))
        self.last_rms = rms

        if DEBUG_MODE:
            print(f"\r🎙 Mic Volume: {rms:.1f}     ", end='', flush=True)

        if rms > SILENCE_THRESHOLD:
            self.last_activity[0] = time.time()
            self.user_spoke_after_assistant = True

        if self.ws_client:
            audio.send_mic_audio(self.ws_client.ws, samples, self.loop)

    async def run_stream(self):
        if not TEXT_ONLY_MODE and audio.playback_done_event.is_set():
            await asyncio.to_thread(audio.playback_done_event.wait)

        print("🎙️ Mic stream active. Say something...")
        mqtt_publish("billy/state", STATE_LISTENING)

        # Ensure we hold a reference to the mic checker task, or it may be destroyed.
        self.mic_timeout_task: asyncio.Task = asyncio.create_task(
            self.mic_timeout_checker()
        )

        try:
            self.mic.start(self.mic_callback)

            async for data in self.ws_client.listen_for_response():
                if not self.session_active.is_set():
                    print("🚪 Session marked as inactive, stopping stream loop.")
                    break
                    
                if DEBUG_MODE and (
                    DEBUG_MODE_INCLUDE_DELTA
                    or not data.get('type', "").endswith('delta')
                ):
                    print(f"\n🔁 Raw message: {data} ")

                # If the session has been updated properly, flag it as so. We can't
                # send audio until the session is fully initialized.
                if data.get('type', "") == WS_SESSION_UPDATED:
                    self.session_initialized = True

                await self.handle_message(data)

        except Exception as e:
            print(f"❌ Error opening mic input: {e}")
            self.session_active.clear()

        finally:
            try:
                self.mic.stop()
                print("🎙️ Mic stream closed.")
            except Exception as e:
                print(f"⚠️ Error while stopping mic: {e}")

            try:
                await self.post_response_handling()
            except Exception as e:
                print(f"⚠️ Error in post_response_handling: {e}")

    async def handle_message(self, data):
        # If this speech segment is done, add some newlines to the full response text,
        # so it's clearer in logging.
        if data['type'] == 'response.audio_transcript.done':
            self.full_response_text += "\n\n"

        if not TEXT_ONLY_MODE and data["type"] in (WS_RESPONSE_AUDIO, WS_RESPONSE_AUDIO_DELTA):
            if not self.committed and self.session_initialized:
                async with self.ws_lock:
                    await self.ws_client.commit_audio_buffer()
                self.committed = True
            audio_b64 = data.get("audio") or data.get("delta")
            if audio_b64:
                self.stream_processor.process_audio_delta(audio_b64)
                self.last_activity[0] = time.time()

                if self.interrupt_event.is_set():
                    print("⛔ Assistant turn interrupted. Stopping response playback.")
                    while not audio.playback_queue.empty():
                        try:
                            audio.playback_queue.get_nowait()
                            audio.playback_queue.task_done()
                        except Exception:
                            break

                    self.session_active.clear()
                    self.interrupt_event.clear()
                    return

        if (
            data["type"] in (WS_RESPONSE_AUDIO_TRANSCRIPT_DELTA, WS_RESPONSE_TEXT_DELTA)
            and "delta" in data
        ):
            self.allow_mic_input = False
            if self.first_text:
                mqtt_publish("billy/state", STATE_SPEAKING)
                print("\n🐟 Billy: ", end='', flush=True)
                self.first_text = False
                self.user_spoke_after_assistant = False
            print(data["delta"], end='', flush=True)
            self.full_response_text += data["delta"]

        if data["type"] == WS_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            if data.get("name") == "update_personality":
                args = json.loads(data["arguments"])
                changes = []
                for trait, val in args.items():
                    if hasattr(PERSONALITY, trait) and isinstance(val, int):
                        setattr(PERSONALITY, trait, val)
                        update_persona_ini(trait, val)
                        changes.append((trait, val))
                if changes:
                    print("\n🎛️ Personality updated via function_call:")
                    for trait, val in changes:
                        print(f"  - {trait.capitalize()}: {val}%")
                    print("\n🧠 New Instructions:\n")
                    print(PERSONALITY.generate_prompt())

                    self.user_spoke_after_assistant = True
                    self.full_response_text = ""
                    self.last_activity[0] = time.time()

                    confirmation_text = " ".join([
                        f"Okay, {trait} is now set to {val}%." for trait, val in changes
                    ])
                    async with self.ws_lock:
                        await self.ws_client.send_message(confirmation_text)
                        await self.ws_client.create_response()

            elif data.get("name") == "play_song":
                args = json.loads(data["arguments"])
                song_name = args.get("song")
                if song_name:
                    print(f"\n🎵 Assistant requested to play song: {song_name} ")
                    await self.stop_session()
                    await asyncio.sleep(1.0)
                    await audio.play_song(song_name)
                    return

            elif data.get("name") == "smart_home_command":
                args = json.loads(data["arguments"])
                prompt = args.get("prompt")

                if prompt:
                    print(f"\n🏠 Sending to Home Assistant Conversation API: {prompt} ")

                    ha_response = await send_conversation_prompt(prompt)
                    # Try to extract plain speech text
                    speech_text = None
                    if isinstance(ha_response, dict):
                        speech_text = (
                            ha_response.get("speech", {}).get("plain", {}).get("speech")
                        )

                    if speech_text:
                        print(f"🔍 HA debug: {ha_response.get('data')}")
                        ha_message = f"Home Assistant says: {speech_text}"
                        print(f"\n📣 {ha_message}")

                        async with self.ws_lock:
                            await self.ws_client.send_message(ha_message)
                            await self.ws_client.create_response()
                    else:
                        print(f"⚠️ Failed to parse HA response: {ha_response}")
                        async with self.ws_lock:
                            await self.ws_client.send_message("Home Assistant didn't understand the request.")
                            await self.ws_client.create_response()

        elif data["type"] == WS_RESPONSE_DONE:
            error = data.get("status_details", {}).get("error")
            if error:
                error_type = error.get("type")
                error_message = error.get("message", "Unknown error")
                print(f"\n❌ OpenAI API Error [{error_type}]: {error_message}")
            else:
                print("\n✿ Assistant response complete.")

            if not TEXT_ONLY_MODE:
                await asyncio.to_thread(audio.playback_queue.join)

                # Let the last audio chunk finish playing
                await asyncio.sleep(1)

                audio_buffer = self.stream_processor.get_audio_buffer()
                if len(audio_buffer) > 0:
                    print(f"💾 Saving audio buffer ({len(audio_buffer)} bytes)")
                    audio.rotate_and_save_response_audio(audio_buffer)
                else:
                    print("⚠️ Audio buffer was empty, skipping save.")

                self.stream_processor.clear_buffers()
                audio.playback_done_event.set()
                self.last_activity[0] = time.time()

                # Allow mic input only after a short delay
                self.allow_mic_input = True

            if self.run_mode == "dory":
                print("🎣 Dory mode active. Ending session after single response.")
                await self.stop_session()
                return

        elif data["type"] == WS_ERROR:
            error: dict[str, Any] = data.get('error') or {}
            stop_all_motors()
            print(
                f"\n🛑 Error response (code='{error.get('code') or '<unknown>'}'): "
                f"{error.get('message') or '<unknown>'}"
            )

            if error.get("code") == "invalid_api_key":
                path = NO_API_KEY_WAV
                if os.path.exists(path):
                    print(f"🔐 {ERROR_INVALID_API_KEY} Playing noapikey.wav...")
                    await asyncio.to_thread(audio.enqueue_wav_to_playback, path)
                    await asyncio.to_thread(audio.playback_queue.join)
                else:
                    print("⚠️ noapikey.wav not found, skipping audio.")
                await self.stop_session()
                return

    async def mic_timeout_checker(self):
        print("🛡️ Mic timeout checker active")
        last_tail_move = 0

        while self.session_active.is_set():
            now = time.time()
            idle_seconds = now - max(self.last_activity[0], audio.last_played_time)
            timeout_offset = 2

            if idle_seconds - timeout_offset > 0.5:
                elapsed = idle_seconds - timeout_offset
                progress = min(elapsed / MIC_TIMEOUT_SECONDS, 1.0)
                bar_len = 20
                filled = int(bar_len * progress)
                bar = '█' * filled + '-' * (bar_len - filled)
                print(
                    f"\r👂 {MIC_TIMEOUT_SECONDS}s timeout: [{bar}] {elapsed:.1f}s "
                    f"| Mic Volume:: {self.last_rms:.4f} / Threshold: {SILENCE_THRESHOLD:.4f}",
                    end='',
                    flush=True,
                )

                if now - last_tail_move > 1.0:
                    move_tail_async(duration=0.2)
                    last_tail_move = now

                if elapsed > MIC_TIMEOUT_SECONDS:
                    print(
                        f"\n⏱️ No mic activity for {MIC_TIMEOUT_SECONDS}s. Ending input..."
                    )
                    await self.stop_session()
                    break

            await asyncio.sleep(0.5)

    async def post_response_handling(self):
        print(f"\n🧠 Full response: {self.full_response_text.strip()} ")

        if not self.session_active.is_set():
            print("🚪 Session inactive after timeout or interruption. Not restarting.")
            mqtt_publish("billy/state", STATE_IDLE)
            stop_all_motors()
            async with self.ws_lock:
                if self.ws_client:
                    await self.ws_client.disconnect()
                    self.ws_client = None
            return

        if not self.run_mode and (
            re.search(r"[a-zA-Z]\?\s*$", self.full_response_text.strip())
            and self.user_spoke_after_assistant
        ):
            print("🔁 Follow-up detected. Restarting...\n")
            await self.start()
        else:
            print("🛑 No follow-up. Ending session.")
            mqtt_publish("billy/state", STATE_IDLE)
            stop_all_motors()
            async with self.ws_lock:
                if self.ws_client:
                    await self.ws_client.disconnect()
                    self.ws_client = None

    async def stop_session(self):
        print("🛑 Stopping session...")
        self.session_active.clear()
        self.mic.stop()

        async with self.ws_lock:
            if self.ws_client:
                try:
                    await self.ws_client.disconnect()
                except Exception as e:
                    print(f"⚠️ Error closing websocket: {e}")
                finally:
                    self.ws_client = None

    async def request_stop(self):
        print("🛑 Stop requested via external signal.")
        self.session_active.clear()

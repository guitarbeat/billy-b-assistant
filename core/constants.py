"""
Centralized constants and configuration values.
Consolidates magic numbers and repeated strings used across the codebase.
"""

# Audio Configuration
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_OUTPUT_RATE = 48000
DEFAULT_CHANNELS = 1
DEFAULT_OUTPUT_CHANNELS = 2
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit
DEFAULT_CHUNK_MS = 50

# Audio Thresholds
DEFAULT_SILENCE_THRESHOLD = 2000
DEFAULT_MIC_TIMEOUT_SECONDS = 5
DEFAULT_TAIL_THRESHOLD = 1500

# Motor Configuration
DEFAULT_MOTOR_FREQ = 10000
DEFAULT_HEAD_SPEED = 80
DEFAULT_TAIL_SPEED = 80
DEFAULT_HEAD_DURATION = 0.5
DEFAULT_TAIL_DURATION = 0.2

# Timing Configuration
DEFAULT_BUTTON_DEBOUNCE_DELAY = 0.5
DEFAULT_MOTOR_WATCHDOG_INTERVAL = 1
DEFAULT_MOTOR_IDLE_TIMEOUT = 60
DEFAULT_INTERLUDE_DELAY_MIN = 0.2
DEFAULT_INTERLUDE_DELAY_MAX = 2
DEFAULT_TAIL_MOVE_INTERVAL = 1.0

# File Paths
SOUNDS_DIR = "sounds"
WAKE_UP_DIR = "sounds/wake-up"
WAKE_UP_CUSTOM_DIR = "sounds/wake-up/custom"
WAKE_UP_DEFAULT_DIR = "sounds/wake-up/default"
RESPONSE_HISTORY_DIR = "sounds/response-history"
SONGS_DIR = "sounds/songs"

# Audio Files
NO_API_KEY_WAV = "sounds/noapikey.wav"
NO_WIFI_WAV = "sounds/nowifi.wav"
SPEAKER_TEST_WAV = "sounds/speakertest.wav"

# MQTT Topics
MQTT_TOPIC_STATE = "billy/state"
MQTT_TOPIC_COMMAND = "billy/command"
MQTT_TOPIC_SAY = "billy/say"

# MQTT States
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_SPEAKING = "speaking"
STATE_PLAYING_SONG = "playing_song"

# MQTT Commands
COMMAND_SHUTDOWN = "shutdown"

# Home Assistant Configuration
HA_DISCOVERY_PREFIX = "homeassistant"
HA_DEVICE_IDENTIFIER = "billy_bass"
HA_DEVICE_NAME = "Big Mouth Billy Bass"
HA_DEVICE_MODEL = "Billy Bassistant"
HA_DEVICE_MANUFACTURER = "Thom Koopman"

# OpenAI Configuration
OPENAI_REALTIME_URI = "wss://api.openai.com/v1/realtime"
OPENAI_DEFAULT_MODEL = "gpt-4o-mini-realtime-preview"
OPENAI_DEFAULT_VOICE = "ash"

# WebSocket Message Types
WS_SESSION_UPDATE = "session.update"
WS_SESSION_UPDATED = "session_updated"
WS_SESSION_END = "session.end"
WS_CONVERSATION_ITEM_CREATE = "conversation.item.create"
WS_RESPONSE_CREATE = "response.create"
WS_RESPONSE_DONE = "response.done"
WS_RESPONSE_AUDIO = "response.audio"
WS_RESPONSE_AUDIO_DELTA = "response.audio.delta"
WS_RESPONSE_TEXT_DELTA = "response.text.delta"
WS_RESPONSE_AUDIO_TRANSCRIPT_DELTA = "response.audio_transcript.delta"
WS_RESPONSE_AUDIO_TRANSCRIPT_DONE = "response.audio_transcript.done"
WS_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE = "response.function_call_arguments.done"
WS_INPUT_AUDIO_BUFFER_APPEND = "input_audio_buffer.append"
WS_INPUT_AUDIO_BUFFER_COMMIT = "input_audio_buffer.commit"
WS_ERROR = "error"

# Personality Traits
PERSONALITY_TRAITS = [
    "humor", "sarcasm", "honesty", "respectfulness", "optimism",
    "confidence", "warmth", "curiosity", "verbosity", "formality"
]

# Personality Buckets
PERSONALITY_BUCKETS = {
    "min": (0, 9),
    "low": (10, 29),
    "med": (30, 69),
    "high": (70, 89),
    "max": (90, 100)
}

# Billy Models
BILLY_MODEL_CLASSIC = "classic"
BILLY_MODEL_MODERN = "modern"

# Run Modes
RUN_MODE_NORMAL = "normal"
RUN_MODE_DORY = "dory"

# Debug Configuration
DEBUG_PROGRESS_BAR_LENGTH = 20
DEBUG_MIC_VOLUME_UPDATE_INTERVAL = 0.5

# Error Messages
ERROR_NO_DEVICES = "No suitable input/output devices found."
ERROR_NETWORK_UNREACHABLE = "Network unreachable or DNS failed."
ERROR_INVALID_API_KEY = "Invalid API key detected."
ERROR_WEBSOCKET_CONNECTION = "WebSocket connection failed."
ERROR_AUDIO_PROCESSING = "Audio processing failed."

# Success Messages
SUCCESS_DEVICE_SELECTED = "✔ Input/Output device index {index} selected."
SUCCESS_MQTT_CONNECTED = "🔌 MQTT connected successfully!"
SUCCESS_SESSION_STARTED = "🛰️ Session started"
SUCCESS_AUDIO_SAVED = "🎨 Saved response audio to {path}"

# Warning Messages
WARNING_MQTT_NOT_CONFIGURED = "⚠️ MQTT not configured, skipping."
WARNING_HA_NOT_CONFIGURED = "⚠️ Home Assistant not configured."
WARNING_NO_CUSTOM_CLIPS = "🔁 No custom clips found, falling back to default."
WARNING_NO_WAKEUP_CLIPS = "⚠️ No wake-up clips found in either custom or default."
WARNING_EMPTY_AUDIO_BUFFER = "⚠️ Audio buffer was empty, skipping save."
WARNING_EMPTY_SAY_COMMAND = "⚠️ SAY command received, but text was empty."

# Info Messages
INFO_READY = "🎦 Ready. Press button to start a voice session. Press Ctrl+C to quit."
INFO_WAITING_FOR_BUTTON = "🕐 Waiting for button press..."
INFO_LISTENING = "🎙️ Mic stream active. Say something..."
INFO_BUTTON_PRESSED = "🎤 Button pressed. Listening..."
INFO_SESSION_STARTING = "⏱️ Session starting..."
INFO_MIC_STREAM_CLOSED = "🎙️ Mic stream closed."
INFO_RESPONSE_COMPLETE = "✿ Assistant response complete."
INFO_SONG_FINISHED = "🎶 Song finished, waiting for button press."
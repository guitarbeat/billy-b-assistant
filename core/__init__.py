"""
Billy Bass Assistant Core Module

This module provides the core functionality for the Billy Bass Assistant,
including audio processing, movement control, personality management,
and communication interfaces.

Main Components:
- audio: Audio processing and playback
- movements: Motor control and physical movements
- personality: Personality trait management
- session: Voice session management
- mqtt: MQTT communication
- ha: Home Assistant integration
- config: Configuration management
- error_handling: Error handling utilities
"""

# Core functionality exports
from .audio import (
    detect_devices,
    ensure_playback_worker_started,
    play_random_wake_up_clip,
    stop_playback,
    is_billy_speaking,
    play_song,
)

from .movements import (
    move_head,
    move_tail,
    move_tail_async,
    stop_all_motors,
    start_motor_watchdog,
)

from .personality import (
    PersonalityProfile,
    load_traits_from_ini,
    update_persona_ini,
)

from .session import BillySession

from .mqtt import (
    start_mqtt,
    stop_mqtt,
    mqtt_publish,
    mqtt_available,
)

from .ha import (
    ha_available,
    send_conversation_prompt,
)

from .config import (
    PERSONALITY,
    INSTRUCTIONS,
    DEBUG_MODE,
    TEXT_ONLY_MODE,
)

from .error_handling import (
    setup_logging,
    log_error,
    handle_openai_error,
    handle_network_error,
    handle_audio_error,
    handle_hardware_error,
)

from .openai_config import (
    get_openai_config,
    get_connection_manager,
    validate_openai_setup,
)

# Version information
__version__ = "1.0.0"
__author__ = "Billy Bass Assistant Team"
__description__ = "AI-powered Billy Bass Assistant with voice interaction and physical movements"
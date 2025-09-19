"""
Shared error handling utilities.
Provides consistent error handling, logging, and recovery mechanisms across the codebase.
"""
import asyncio
import logging
import os
import sys
import traceback
from typing import Any, Callable, Optional, Type, Union

from .constants import (
    ERROR_NO_DEVICES,
    ERROR_NETWORK_UNREACHABLE,
    ERROR_INVALID_API_KEY,
    ERROR_WEBSOCKET_CONNECTION,
    ERROR_AUDIO_PROCESSING,
    NO_API_KEY_WAV,
    NO_WIFI_WAV,
)


class BillyError(Exception):
    """Base exception class for Billy-specific errors."""
    pass


class AudioError(BillyError):
    """Audio processing related errors."""
    pass


class NetworkError(BillyError):
    """Network connectivity related errors."""
    pass


class ConfigurationError(BillyError):
    """Configuration related errors."""
    pass


class HardwareError(BillyError):
    """Hardware related errors."""
    pass


def setup_logging(debug_mode: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def log_error(error: Exception, context: str = "", level: int = logging.ERROR) -> None:
    """Log an error with context information."""
    logger = logging.getLogger(__name__)
    message = f"{context}: {str(error)}" if context else str(error)
    logger.log(level, message)
    if level >= logging.ERROR:
        logger.debug(traceback.format_exc())


def handle_audio_error(error: Exception, context: str = "") -> None:
    """Handle audio processing errors."""
    log_error(error, f"Audio error {context}", logging.ERROR)
    # Could add audio-specific recovery logic here


def handle_network_error(error: Exception, context: str = "") -> None:
    """Handle network connectivity errors."""
    log_error(error, f"Network error {context}", logging.ERROR)
    # Could add network retry logic here


def handle_hardware_error(error: Exception, context: str = "") -> None:
    """Handle hardware related errors."""
    log_error(error, f"Hardware error {context}", logging.ERROR)
    # Could add hardware reset logic here


def safe_execute(
    func: Callable,
    *args,
    error_handler: Optional[Callable[[Exception], None]] = None,
    default_return: Any = None,
    context: str = "",
    **kwargs
) -> Any:
    """Safely execute a function with error handling."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if error_handler:
            error_handler(e)
        else:
            log_error(e, context)
        return default_return


async def safe_async_execute(
    coro: Callable,
    *args,
    error_handler: Optional[Callable[[Exception], None]] = None,
    default_return: Any = None,
    context: str = "",
    **kwargs
) -> Any:
    """Safely execute an async function with error handling."""
    try:
        return await coro(*args, **kwargs)
    except Exception as e:
        if error_handler:
            error_handler(e)
        else:
            log_error(e, context)
        return default_return


def handle_openai_error(error: Exception, context: str = "") -> None:
    """Handle OpenAI API specific errors."""
    error_str = str(error).lower()
    
    if "invalid_api_key" in error_str or "unauthorized" in error_str:
        log_error(error, f"OpenAI API key error {context}", logging.CRITICAL)
        # Play no API key sound
        try:
            from .audio import enqueue_wav_to_playback
            if os.path.exists(NO_API_KEY_WAV):
                enqueue_wav_to_playback(NO_API_KEY_WAV)
        except Exception as e:
            log_error(e, "Failed to play no API key sound")
    elif "network" in error_str or "connection" in error_str:
        log_error(error, f"OpenAI network error {context}", logging.ERROR)
        # Play no wifi sound
        try:
            from .audio import enqueue_wav_to_playback
            if os.path.exists(NO_WIFI_WAV):
                enqueue_wav_to_playback(NO_WIFI_WAV)
        except Exception as e:
            log_error(e, "Failed to play no wifi sound")
    else:
        log_error(error, f"OpenAI API error {context}", logging.ERROR)


def handle_websocket_error(error: Exception, context: str = "") -> None:
    """Handle WebSocket specific errors."""
    error_str = str(error).lower()
    
    if "connection" in error_str or "network" in error_str:
        handle_network_error(error, f"WebSocket {context}")
    else:
        log_error(error, f"WebSocket error {context}", logging.ERROR)


def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """Decorator to retry a function on failure."""
    def decorator(func: Callable) -> Callable:
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        log_error(e, f"Attempt {attempt + 1} failed, retrying in {current_delay}s")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        log_error(e, f"All {max_retries + 1} attempts failed")
            
            raise last_exception
        
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        log_error(e, f"Attempt {attempt + 1} failed, retrying in {current_delay}s")
                        import time
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        log_error(e, f"All {max_retries + 1} attempts failed")
            
            raise last_exception
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def validate_configuration(config: dict, required_keys: list) -> None:
    """Validate that required configuration keys are present."""
    missing_keys = [key for key in required_keys if key not in config or not config[key]]
    if missing_keys:
        raise ConfigurationError(f"Missing required configuration: {missing_keys}")


def cleanup_on_exit() -> None:
    """Cleanup resources on exit."""
    try:
        from .movements import stop_all_motors
        from .mqtt import stop_mqtt
        stop_all_motors()
        stop_mqtt()
    except Exception as e:
        log_error(e, "Error during cleanup")


def setup_signal_handlers() -> None:
    """Setup signal handlers for graceful shutdown."""
    import signal
    
    def signal_handler(sig, frame):
        print("\n👋 Exiting cleanly (signal received).")
        cleanup_on_exit()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
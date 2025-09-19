import shutil
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv

from core.audio import playback_queue
from core.button import start_loop
from core.error_handling import (
    setup_logging,
    setup_signal_handlers,
    safe_execute,
    log_error,
    cleanup_on_exit,
)
from core.movements import start_motor_watchdog
from core.mqtt import start_mqtt
from core.config import DEBUG_MODE


def ensure_env_file():
    """Ensure .env file exists, create from example if needed."""
    env_path = Path(".env")
    env_example_path = Path(".env.example")

    if not env_path.exists():
        if env_example_path.exists():
            shutil.copy(env_example_path, env_path)
            print("✅ .env file created from .env.example")
            print(
                "⚠️  Please review the .env file and update your API key and other settings."
            )
        else:
            print("❌ Neither .env nor .env.example found. Exiting.")
            sys.exit(1)


def main():
    """Main application entry point."""
    # Setup logging
    setup_logging(DEBUG_MODE)
    
    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()
    
    # Ensure environment file exists
    ensure_env_file()
    load_dotenv()

    # Start background services
    threading.Thread(target=start_mqtt, daemon=True).start()
    start_motor_watchdog()
    
    # Start main button loop
    start_loop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_error(e, "Unhandled exception in main")
        cleanup_on_exit()
        sys.exit(1)

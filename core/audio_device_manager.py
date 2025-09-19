"""
Audio device detection and management.
Handles device enumeration, selection, and configuration.
"""
import sys

import sounddevice as sd

from .config import MIC_PREFERENCE, SPEAKER_PREFERENCE, TEXT_ONLY_MODE
from .constants import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_CHANNELS,
    DEFAULT_OUTPUT_CHANNELS,
    DEFAULT_CHUNK_MS,
    ERROR_NO_DEVICES,
    SUCCESS_DEVICE_SELECTED,
)


class AudioDeviceManager:
    """Manages audio device detection and configuration."""
    
    def __init__(self):
        self.mic_device_index = None
        self.mic_rate = None
        self.mic_channels = DEFAULT_CHANNELS
        self.output_device_index = None
        self.output_channels = DEFAULT_OUTPUT_CHANNELS
        self.output_rate = None
        self.chunk_size = None

    def detect_devices(self, debug=False):
        """Detect and configure audio devices."""
        devices = sd.query_devices()

        print("🔢 Enumerating audio devices...")
        for i, d in enumerate(devices):
            if debug:
                print(
                    f"  {i}: {d['name']} (inputs: {d['max_input_channels']}, outputs: {d['max_output_channels']})"
                )

            if self.mic_device_index is None and d['max_input_channels'] > 0:
                if (
                    MIC_PREFERENCE
                    and MIC_PREFERENCE.lower() in d['name'].lower()
                    or not MIC_PREFERENCE
                ):
                    self.mic_device_index = i
                    print(SUCCESS_DEVICE_SELECTED.format(index=i))

                self.mic_rate = int(d['default_samplerate'])
                self.mic_channels = d['max_input_channels']
                self.chunk_size = int(self.mic_rate * DEFAULT_CHUNK_MS / 1000)

            if self.output_device_index is None and d['max_output_channels'] > 0:
                if (
                    SPEAKER_PREFERENCE
                    and SPEAKER_PREFERENCE.lower() in d['name'].lower()
                    or not SPEAKER_PREFERENCE
                ):
                    self.output_device_index = i
                    print(SUCCESS_DEVICE_SELECTED.format(index=i))

                self.output_rate = int(d['default_samplerate'])
                self.output_channels = d['max_output_channels']

        if self.mic_device_index is None or (self.output_device_index is None and not TEXT_ONLY_MODE):
            print(ERROR_NO_DEVICES)
            sys.exit(1)

    def get_mic_config(self):
        """Get microphone configuration."""
        return {
            'device': self.mic_device_index,
            'samplerate': self.mic_rate,
            'channels': self.mic_channels,
            'blocksize': self.chunk_size,
        }

    def get_output_config(self):
        """Get output device configuration."""
        return {
            'device': self.output_device_index,
            'samplerate': 48000,  # Always 48kHz for output
            'channels': self.output_channels,
        }


# Global device manager instance
device_manager = AudioDeviceManager()
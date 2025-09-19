"""
Audio playback management.
Handles audio queue, playback worker, and audio file operations.
"""
import asyncio
import glob
import os
import random
import threading
import time
import wave
from queue import Queue

import numpy as np
import sounddevice as sd
from scipy.signal import resample

from .audio_device_manager import device_manager
from .config import CHUNK_MS, PLAYBACK_VOLUME, TEXT_ONLY_MODE
from .constants import (
    WAKE_UP_CUSTOM_DIR,
    WAKE_UP_DEFAULT_DIR,
    RESPONSE_HISTORY_DIR,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_CHANNELS,
    WARNING_NO_CUSTOM_CLIPS,
    WARNING_NO_WAKEUP_CLIPS,
)
from .movements import flap_from_pcm_chunk, interlude, move_head, move_tail_async, stop_all_motors


class AudioPlaybackManager:
    """Manages audio playback operations."""
    
    def __init__(self):
        self.playback_queue = Queue()
        self.head_move_queue = Queue()
        self.playback_done_event = threading.Event()
        self._playback_thread = None
        self.last_played_time = time.time()
        self.song_mode = False
        self.beat_length = 0.5
        self.compensate_tail_beats = 0.0
        
        # Ensure response history directory exists
        os.makedirs(RESPONSE_HISTORY_DIR, exist_ok=True)

    def ensure_playback_worker_started(self, chunk_ms):
        """Ensure the playback worker thread is running."""
        if TEXT_ONLY_MODE:
            return
        if not self._playback_thread or not self._playback_thread.is_alive():
            self._playback_thread = threading.Thread(
                target=self._playback_worker, args=(chunk_ms,), daemon=True
            )
            self._playback_thread.start()

    def _playback_worker(self, chunk_ms):
        """Background worker that processes the playback queue."""
        global head_out
        global song_start_time

        interlude_counter = 0
        interlude_target = random.randint(150000, 300000)
        head_move_active = False
        head_move_end_time = 0
        next_head_move = None
        drums_peak = 0
        drums_peak_time = 0
        next_beat_time = 0

        try:
            with sd.OutputStream(
                samplerate=48000, channels=2, dtype='int16', 
                device=device_manager.output_device_index
            ) as stream:
                print("🔈 Output stream opened")
                while True:
                    item = self.playback_queue.get()
                    now = time.time()

                    if head_move_active and now >= head_move_end_time:
                        move_head("off")
                        head_out = False
                        head_move_active = False
                        print("🛑 Head move ended")

                    if not head_move_active and not self.head_move_queue.empty():
                        move_time, move_duration = self.head_move_queue.queue[0]  # peek
                        if now - song_start_time >= move_time:
                            self.head_move_queue.get()
                            move_head("on")
                            head_out = True
                            head_move_active = True
                            head_move_end_time = now + move_duration
                            print(f"🐟 Head move started for {move_duration:.2f} seconds")

                    if item is None:
                        print("🧵 Received stop signal, cleaning up.")
                        self.playback_queue.task_done()
                        break

                    if isinstance(item, tuple):
                        mode = item[0]
                        if mode == "song":
                            audio_chunk, flap_chunk, rms_drums = item[1], item[2], item[3]

                            flap_from_pcm_chunk(
                                np.frombuffer(flap_chunk, dtype=np.int16), chunk_ms=chunk_ms
                            )

                            if rms_drums > drums_peak:
                                drums_peak = rms_drums
                                drums_peak_time = now

                            adjusted_now = (now - song_start_time) + (
                                self.compensate_tail_beats * self.beat_length
                            )
                            elapsed_song_time = now - song_start_time

                            if adjusted_now >= next_beat_time:
                                if drums_peak > 1500 and not head_out:
                                    move_tail_async(duration=0.2)
                                drums_peak = 0
                                drums_peak_time = 0
                                next_beat_time += self.beat_length

                            mono = np.frombuffer(audio_chunk, dtype=np.int16)
                            resampled = resample(
                                mono, int(len(mono) * 48000 / 24000)
                            ).astype(np.int16)
                            stereo = np.repeat(resampled[:, np.newaxis], 2, axis=1)
                            stereo = np.clip(
                                stereo * PLAYBACK_VOLUME, -32768, 32767
                            ).astype(np.int16)
                            stream.write(stereo)

                        elif mode == "tts":
                            chunk = item[1]
                            mono = np.frombuffer(chunk, dtype=np.int16)
                            chunk_len = int(24000 * chunk_ms / 1000)
                            for i in range(0, len(mono), chunk_len):
                                sub = mono[i : i + chunk_len]
                                if len(sub) == 0:
                                    continue
                                flap_from_pcm_chunk(sub, chunk_ms=chunk_ms)
                                resampled = resample(
                                    sub, int(len(sub) * 48000 / 24000)
                                ).astype(np.int16)
                                stereo = np.repeat(resampled[:, np.newaxis], 2, axis=1)
                                stereo = np.clip(
                                    stereo * PLAYBACK_VOLUME, -32768, 32767
                                ).astype(np.int16)
                                stream.write(stereo)

                                interlude_counter += len(sub)
                                if interlude_counter >= interlude_target:
                                    interlude()
                                    interlude_counter = 0
                                    interlude_target = random.randint(80000, 160000)

                    else:
                        chunk = item
                        mono = np.frombuffer(chunk, dtype=np.int16)
                        chunk_len = int(24000 * chunk_ms / 1000)
                        for i in range(0, len(mono), chunk_len):
                            sub = mono[i : i + chunk_len]
                            if len(sub) == 0:
                                continue
                            flap_from_pcm_chunk(sub, chunk_ms=chunk_ms)
                            resampled = resample(sub, int(len(sub) * 48000 / 24000)).astype(
                                np.int16
                            )
                            stereo = np.repeat(resampled[:, np.newaxis], 2, axis=1)
                            stereo = np.clip(
                                stereo * PLAYBACK_VOLUME, -32768, 32767
                            ).astype(np.int16)
                            stream.write(stereo)

                            interlude_counter += len(sub)
                            if interlude_counter >= interlude_target:
                                interlude()
                                interlude_counter = 0
                                interlude_target = random.randint(80000, 160000)

                    self.playback_queue.task_done()
                    self.last_played_time = time.time()

        except Exception as e:
            print(f"❌ Playback stream failed: {e}")
        finally:
            self.playback_done_event.set()
            stop_all_motors()

    def save_audio_to_wav(self, audio_bytes, filename):
        """Save audio data to WAV file."""
        full_path = os.path.join(RESPONSE_HISTORY_DIR, filename)
        with wave.open(full_path, 'wb') as wf:
            wf.setnchannels(DEFAULT_CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(DEFAULT_SAMPLE_RATE)
            wf.writeframes(audio_bytes)
        print(f"🎨 Saved response audio to {full_path}")

    def rotate_and_save_response_audio(self, audio_bytes):
        """Rotate old response files and save new audio."""
        # Rotate old files first (2 -> 3, 1 -> 2)
        for i in range(2, 0, -1):
            src = os.path.join(RESPONSE_HISTORY_DIR, f"response-{i}.wav")
            dst = os.path.join(RESPONSE_HISTORY_DIR, f"response-{i + 1}.wav")
            if os.path.exists(src):
                os.replace(src, dst)

        self.save_audio_to_wav(audio_bytes, "response-1.wav")

    def enqueue_wav_to_playback(self, filepath):
        """Read a WAV file and enqueue its PCM audio data to the playback queue."""
        with wave.open(filepath, 'rb') as wf:
            if (
                wf.getframerate() != DEFAULT_SAMPLE_RATE
                or wf.getnchannels() != DEFAULT_CHANNELS
                or wf.getsampwidth() != 2
            ):
                raise ValueError("WAV file must be 24000 Hz, mono, 16-bit")

            chunk_size = int(DEFAULT_SAMPLE_RATE * CHUNK_MS / 1000)
            while True:
                frames = wf.readframes(chunk_size)
                if not frames:
                    break
                self.playback_queue.put(frames)

    def play_random_wake_up_clip(self):
        """Select and enqueue a random wake-up WAV file with mouth movement."""
        # Check custom folder first
        clips = glob.glob(os.path.join(WAKE_UP_CUSTOM_DIR, "*.wav"))

        if not clips:
            print(WARNING_NO_CUSTOM_CLIPS)
            clips = glob.glob(os.path.join(WAKE_UP_DEFAULT_DIR, "*.wav"))

        if not clips:
            print(WARNING_NO_WAKEUP_CLIPS)
            return None

        clip = random.choice(clips)

        # Track how many tasks were pending before enqueue
        already_pending = self.playback_queue.unfinished_tasks

        # Enqueue the WAV file
        self.enqueue_wav_to_playback(clip)

        # Wait for exactly those new chunks to finish
        while self.playback_queue.unfinished_tasks > already_pending:
            time.sleep(0.01)

        # Once done, set the event
        self.playback_done_event.set()

        return clip

    def stop_playback(self):
        """Immediately stop playback and flush queue."""
        while not self.playback_queue.empty():
            try:
                self.playback_queue.get_nowait()
                self.playback_queue.task_done()
            except Exception:
                break
        self.playback_done_event.set()

    def is_billy_speaking(self):
        """Return True if Billy is still playing audio."""
        if not self.playback_done_event.is_set():
            return True
        return bool(not self.playback_queue.empty())

    def reset_for_new_song(self):
        """Reset playback state for a new song."""
        global song_start_time
        
        self.playback_queue.queue.clear()
        self.head_move_queue.queue.clear()
        self.playback_done_event.clear()
        self.last_played_time = time.time()
        song_start_time = time.time()


# Global playback manager instance
playback_manager = AudioPlaybackManager()
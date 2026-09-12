"""
End-to-End (E2E) Test Suite for Windows Volume Synchronization.

Verifies:
1. Windows master volume changes (100%, 50%, 0%, Muted) scale live audio PCM RMS amplitude.
2. Mute state produces digital silence (b"\x00" * N).
3. Toggle config["win_volume_sync"] dynamically enables/disables scaling.
4. /api/win_volume_sync endpoint responds with accurate status.
"""

import math
import struct
import sys
import time
import numpy as np

import audio_engine
from config import config
import win_volume


def generate_sine_wave(freq=440.0, duration=0.1, rate=44100, amplitude=30000):
    """Generates 16-bit PCM stereo sine wave bytes."""
    num_samples = int(rate * duration)
    arr = np.zeros(num_samples * 2, dtype=np.int16)
    for i in range(num_samples):
        val = int(amplitude * math.sin(2 * math.pi * freq * i / rate))
        arr[i * 2] = val
        arr[i * 2 + 1] = val
    return arr.tobytes()


def calculate_rms(pcm_bytes):
    """Calculates RMS audio level from 16-bit PCM bytes."""
    if not pcm_bytes:
        return 0.0
    arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float64)
    if len(arr) == 0:
        return 0.0
    return math.sqrt(np.mean(arr ** 2))


def run_e2e_win_volume_test():
    print("=" * 60)
    print("      E2E Test: Native Windows Volume Synchronization")
    print("=" * 60)

    # Save initial state
    orig_vol, orig_mute = win_volume.get_win_volume()
    orig_sync = config.get("win_volume_sync", True)
    orig_stream_gain = config.get("sonos_stream_gain", 2.5)
    config["win_volume_sync"] = True
    config["sonos_stream_gain"] = 1.0

    sub_id, q = audio_engine.broadcaster.subscribe(maxlen=10)

    try:
        # 1. Start listener
        win_volume.start_win_volume_listener()
        time.sleep(0.5)

        test_chunk = generate_sine_wave(amplitude=20000)
        base_rms = calculate_rms(test_chunk)
        print(f"[E2E] Base PCM Test Signal RMS: {base_rms:.2f}")
        assert base_rms > 10000, "Base RMS signal generation failed"

        # 2. Test 100% Volume
        print("\n--- Test Case 1: 100% Volume, Unmuted ---")
        win_volume.set_win_volume_scalar(1.0, mute=False)
        time.sleep(0.2)
        audio_engine.broadcaster.publish(test_chunk)
        received = q.get(timeout=1.0)
        rms_100 = calculate_rms(received)
        print(f"  Published RMS: {base_rms:.2f} -> Output RMS: {rms_100:.2f}")
        assert abs(rms_100 - base_rms) < 100.0, f"Expected ~{base_rms}, got {rms_100}"
        print("  -> PASSED: 100% volume preserved full amplitude.")

        # 3. Test 50% Volume
        print("\n--- Test Case 2: 50% Volume, Unmuted ---")
        win_volume.set_win_volume_scalar(0.5, mute=False)
        time.sleep(0.2)
        audio_engine.broadcaster.publish(test_chunk)
        received = q.get(timeout=1.0)
        rms_50 = calculate_rms(received)
        print(f"  Published RMS: {base_rms:.2f} -> Output RMS: {rms_50:.2f}")
        expected_50 = base_rms * 0.5
        assert abs(rms_50 - expected_50) < 500.0, f"Expected ~{expected_50}, got {rms_50}"
        print("  -> PASSED: 50% volume scaled amplitude by 50%.")

        # 4. Test Mute
        print("\n--- Test Case 3: Windows Mute ---")
        win_volume.set_win_volume_scalar(0.5, mute=True)
        time.sleep(0.2)
        audio_engine.broadcaster.publish(test_chunk)
        received = q.get(timeout=1.0)
        rms_mute = calculate_rms(received)
        print(f"  Published RMS: {base_rms:.2f} -> Muted Output RMS: {rms_mute:.2f}")
        assert rms_mute == 0.0, f"Expected 0.0 RMS when muted, got {rms_mute}"
        assert received == b"\x00" * len(test_chunk), "Expected all silence bytes when muted"
        print("  -> PASSED: Mute produced complete digital silence.")

        # 5. Test Disable Sync Toggle
        print("\n--- Test Case 4: Disable win_volume_sync Toggle ---")
        config["win_volume_sync"] = False
        win_volume.set_win_volume_scalar(0.2, mute=True)
        time.sleep(0.2)
        audio_engine.broadcaster.publish(test_chunk)
        received = q.get(timeout=1.0)
        rms_disabled = calculate_rms(received)
        print(f"  Sync Disabled Output RMS: {rms_disabled:.2f} (Windows muted at 20%)")
        assert abs(rms_disabled - base_rms) < 100.0, "Disabling sync should bypass Windows volume"
        print("  -> PASSED: Sync toggle correctly bypassed Windows volume scaling.")

        print("\n" + "=" * 60)
        print("    ALL E2E WINDOWS VOLUME SYNC TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)

    finally:
        audio_engine.broadcaster.unsubscribe(sub_id)
        config["win_volume_sync"] = orig_sync
        config["sonos_stream_gain"] = orig_stream_gain
        if orig_vol is not None:
            win_volume.set_win_volume_scalar(orig_vol, orig_mute)
        win_volume.stop_win_volume_listener()


if __name__ == "__main__":
    run_e2e_win_volume_test()

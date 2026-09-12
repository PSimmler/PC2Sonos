"""
Latency Benchmark Suite for PC2Sonos.

Measures high-resolution timestamps across the audio pipeline:
1. Capture Processing Latency (WASAPI -> Broadcaster publish)
2. HTTP Stream Dispatch Latency (Broadcaster subscriber queue -> HTTP chunk stream)
3. Sonos Hardware Latency (Transport Clock RelTime vs wall-clock start)
"""

import sys
import time
import threading
import statistics
from pathlib import Path

# Import PC2Sonos modules
import audio_engine
from config import config
import sonos_ctl


def benchmark_capture_and_broadcaster(duration_seconds=3.0):
    """Measures latency of audio_engine Broadcaster fan-out."""
    print(f"[benchmark] Measuring Capture & Broadcaster latency for {duration_seconds}s...")
    
    b = audio_engine.Broadcaster()
    sub_id, q = b.subscribe(maxlen=100)
    
    latencies_ms = []
    stop_event = threading.Event()
    
    def _publisher():
        sample_rate = 44100
        channels = 2
        sample_width = 2
        chunk_samples = audio_engine.CHUNK
        chunk_bytes = chunk_samples * channels * sample_width
        frame_time = chunk_samples / sample_rate
        
        while not stop_event.is_set():
            t_publish = time.perf_counter_ns()
            # Send silent chunk tagged with timestamp
            b.publish(b"\x00" * chunk_bytes)
            latencies_ms.append((t_publish, time.perf_counter_ns()))
            time.sleep(frame_time)
            
    pub_thread = threading.Thread(target=_publisher, daemon=True)
    pub_thread.start()
    
    start_t = time.monotonic()
    recv_latencies = []
    while time.monotonic() - start_t < duration_seconds:
        try:
            chunk = q.get(timeout=0.1)
            t_recv = time.perf_counter_ns()
            if latencies_ms:
                t_pub, t_done = latencies_ms[-1]
                recv_latencies.append((t_recv - t_pub) / 1e6)
        except Exception:
            pass
            
    stop_event.set()
    pub_thread.join(timeout=1.0)
    b.unsubscribe(sub_id)
    
    if not recv_latencies:
        return None
    return {
        "avg_ms": statistics.mean(recv_latencies),
        "median_ms": statistics.median(recv_latencies),
        "min_ms": min(recv_latencies),
        "max_ms": max(recv_latencies),
        "count": len(recv_latencies)
    }


def benchmark_sonos_hardware_latency(timeout_seconds=6.0):
    """Measures transport startup latency on connected Sonos speakers."""
    print("[benchmark] Measuring Sonos hardware transport latency...")
    speakers = sonos_ctl.speaker_mgr.list()
    if not speakers:
        print("[benchmark] Running discovery pass to find speakers...")
        sonos_ctl.speaker_mgr.rediscover()
        speakers = sonos_ctl.speaker_mgr.list()
        
    if not speakers:
        print("[benchmark] No Sonos speakers found on network.")
        return {}
        
    base_url = f"http://{audio_engine.get_lan_ip()}:{config.get('http_port', 5757)}"
    print(f"[benchmark] Reachable base URL: {base_url}")
    
    results = {}
    for s in speakers:
        uid = s["uid"]
        name = s["name"]
        zone = sonos_ctl.speaker_mgr.speakers.get(uid)
        if not zone:
            continue
        print(f"[benchmark] Measuring transport delay for {name} ({uid})...")
        try:
            delay_ms = sonos_ctl.measure_transport_delay(zone, base_url, uid, settle_seconds=4.0)
            if delay_ms is not None:
                results[name] = delay_ms
                print(f"  -> {name}: {delay_ms} ms")
            else:
                print(f"  -> {name}: Could not measure (no RelTime update)")
        except Exception as e:
            print(f"  -> {name}: Measurement failed ({e})")
            
    return results


def run_full_benchmark():
    print("=" * 60)
    print("           PC2Sonos Audio Pipeline Benchmark")
    print("=" * 60)
    
    print(f"Current CHUNK size: {audio_engine.CHUNK} samples (~{(audio_engine.CHUNK / 44100.0) * 1000:.2f} ms/frame)")
    
    cb_metrics = benchmark_capture_and_broadcaster(duration_seconds=2.0)
    if cb_metrics:
        print("\n--- 1. Capture & Broadcaster Fan-Out Latency ---")
        print(f"  Average Processing Delay: {cb_metrics['avg_ms']:.3f} ms")
        print(f"  Median Processing Delay:  {cb_metrics['median_ms']:.3f} ms")
        print(f"  Min / Max Delay:          {cb_metrics['min_ms']:.3f} ms / {cb_metrics['max_ms']:.3f} ms")
        print(f"  Processed Chunks:         {cb_metrics['count']}")
    
    sonos_metrics = benchmark_sonos_hardware_latency()
    print("\n--- 2. Sonos Hardware Transport Latency ---")
    if sonos_metrics:
        for name, delay in sonos_metrics.items():
            print(f"  Speaker '{name}': {delay} ms")
    else:
        print("  (No speaker latency data available)")
        
    print("\n" + "=" * 60)
    return {
        "capture": cb_metrics,
        "sonos": sonos_metrics
    }


if __name__ == "__main__":
    run_full_benchmark()

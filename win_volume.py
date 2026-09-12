"""
Windows CoreAudio Endpoint Volume Listener for PC2Sonos.

Tracks native Windows volume slider adjustments and keyboard volume/mute keys
(Volume Up, Volume Down, Volume Mute) in real time using Windows CoreAudio COM interfaces.
"""

import threading
import time

_volume_scalar = 1.0
_is_muted = False
_lock = threading.Lock()
_listener_thread = None
_stop_event = threading.Event()
_pycaw_available = False

try:
    from comtypes import COMObject, CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolumeCallback
    _pycaw_available = True
except Exception:
    _pycaw_available = False


class _VolumeCallback(COMObject):
    _com_interfaces_ = [IAudioEndpointVolumeCallback] if _pycaw_available else []

    def OnNotify(self, pNotify):
        global _volume_scalar, _is_muted
        try:
            data = pNotify.contents
            with _lock:
                _volume_scalar = float(data.fMasterVolume)
                _is_muted = bool(data.bMuted)
        except Exception:
            pass
        return 0


def get_win_volume():
    """Returns (volume_scalar: float 0.0-1.0, is_muted: bool) thread-safely."""
    with _lock:
        return _volume_scalar, _is_muted


def set_win_volume_scalar(scalar, mute=None):
    """Sets Windows endpoint volume programmatically."""
    if not _pycaw_available:
        return False
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    try:
        device = AudioUtilities.GetSpeakers()
        if device and hasattr(device, "EndpointVolume"):
            vol = device.EndpointVolume
            vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(scalar))), None)
            if mute is not None:
                vol.SetMute(bool(mute), None)
            with _lock:
                global _volume_scalar, _is_muted
                _volume_scalar = vol.GetMasterVolumeLevelScalar()
                _is_muted = bool(vol.GetMute())
            return True
    except Exception as e:
        print(f"[win_volume] failed to set volume: {e}")
    finally:
        try:
            import comtypes
            comtypes.CoUninitialize()
        except Exception:
            pass
    return False


def _listener_loop():
    global _volume_scalar, _is_muted
    if not _pycaw_available:
        print("[win_volume] pycaw/comtypes not available; Windows volume sync disabled")
        return

    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass

    cb = None
    vol = None
    try:
        device = AudioUtilities.GetSpeakers()
        if device and hasattr(device, "EndpointVolume"):
            vol = device.EndpointVolume
            cb = _VolumeCallback()
            try:
                vol.RegisterControlChangeNotify(cb)
            except Exception:
                cb = None

            # Initialize initial volume
            try:
                with _lock:
                    _volume_scalar = vol.GetMasterVolumeLevelScalar()
                    _is_muted = bool(vol.GetMute())
            except Exception:
                pass

        print(f"[win_volume] Windows volume listener active (initial: {_volume_scalar * 100:.0f}%, muted={_is_muted})")

        while not _stop_event.is_set():
            # Periodic refresh to catch volume changes if COM callback misses an event
            if vol:
                try:
                    s = vol.GetMasterVolumeLevelScalar()
                    m = bool(vol.GetMute())
                    with _lock:
                        _volume_scalar = s
                        _is_muted = m
                except Exception:
                    pass
            _stop_event.wait(0.5)

    except Exception as e:
        print(f"[win_volume] listener error: {e}")
    finally:
        if vol and cb:
            try:
                vol.UnregisterControlChangeNotify(cb)
            except Exception:
                pass
        try:
            import comtypes
            comtypes.CoUninitialize()
        except Exception:
            pass


def start_win_volume_listener():
    global _listener_thread, _stop_event
    if _listener_thread and _listener_thread.is_alive():
        return
    _stop_event.clear()
    _listener_thread = threading.Thread(target=_listener_loop, daemon=True)
    _listener_thread.start()


def stop_win_volume_listener():
    global _stop_event
    _stop_event.set()

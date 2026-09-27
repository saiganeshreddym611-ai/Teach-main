"""TTS plumbing. Engine tests skip when model files are absent (CI without voices)."""
import wave
import io

import numpy as np
import pytest

from tutor.config import settings
from tutor.tts import PiperEngine, wav_bytes


def test_wav_bytes_is_valid_16bit_mono():
    samples = (np.sin(np.linspace(0, 200, 2205)) * 10000).astype(np.int16)
    data = wav_bytes(samples, 22050)
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 22050
        assert w.getnframes() == 2205


@pytest.mark.skipif(not (settings.tts_models_dir / "en_GB-jenny_dioco-medium.onnx").exists(), reason="piper voice not downloaded")
def test_piper_engine_synthesises_and_switches_voice():
    eng = PiperEngine(settings.tts_models_dir, "en_GB-jenny_dioco-medium")
    a = eng.synth("Revenue is recognised when control transfers.")
    assert a.dtype == np.int16 and len(a) > eng.sample_rate * 0.5  # > half a second of audio
    assert "en_GB-jenny_dioco-medium" in eng.voices()
    other = next((v for v in eng.voices() if v != eng.voice and v.endswith("medium")), None)
    if other:
        b = eng.synth("Revenue is recognised when control transfers.", voice=other)
        assert len(b) > 0
    with pytest.raises(FileNotFoundError):
        eng.synth("x", voice="en_XX-nope-medium")


def test_prepare_tts_downloads_missing_piper_voice_once(tmp_path, monkeypatch):
    from tutor import tts

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        (tmp_path / "v.onnx").write_bytes(b"x")

    monkeypatch.setattr(tts.subprocess, "run", fake_run)
    assert tts.ensure_piper_voice(tmp_path, "v") is True
    assert tts.ensure_piper_voice(tmp_path, "v") is True  # present now: no second download
    assert len(calls) == 1 and calls[0][1:4] == ["-m", "piper.download_voices", "--download-dir"]


def test_prepare_tts_respects_opt_out(tmp_path, monkeypatch):
    from tutor import tts

    monkeypatch.setattr(settings, "tts_engine", "piper")
    monkeypatch.setattr(settings, "tts_auto_download", False)
    monkeypatch.setattr(tts, "ensure_piper_voice", lambda *a: (_ for _ in ()).throw(AssertionError("downloaded")))
    monkeypatch.setattr(tts, "get_tts", lambda: None)
    tts.prepare_tts()  # no download, no crash

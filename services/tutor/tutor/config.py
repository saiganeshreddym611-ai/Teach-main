"""Environment-driven settings."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass
class Settings:
    content_pack: str = os.getenv("CONTENT_PACK", "ind_as_115")
    # Placeholder until H5 signs off a calibrated value (scripts/calibrate_retrieval.py).
    retrieval_min_confidence: float = float(os.getenv("RETRIEVAL_MIN_CONFIDENCE", "0.5"))
    require_reviewed_content: bool = os.getenv("REQUIRE_REVIEWED_CONTENT", "0") in {"1", "true", "yes"}
    model: str = os.getenv("TUTOR_MODEL", "claude-opus-5")
    mock_llm: bool = os.getenv("MOCK_LLM", "0") in {"1", "true", "yes"}
    # Backends: "claude" (default) or "ollama", per role. MOCK_LLM=1 overrides both.
    grader_provider: str = os.getenv("GRADER_PROVIDER", "claude").lower()
    tutor_provider: str = os.getenv("TUTOR_PROVIDER", "claude").lower()
    ollama_model: str = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
    # Per-role overrides (default to OLLAMA_MODEL) so grader and tutor can differ.
    ollama_grader_model: str = os.getenv("OLLAMA_GRADER_MODEL") or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
    ollama_tutor_model: str = os.getenv("OLLAMA_TUTOR_MODEL") or os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud")
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    # Grader "thinking": unset -> model default (nemotron thinks, gemma does not).
    # Measured: nemotron needs it (22 s/grade, 28/28); with it off it becomes
    # unreliable (5 s, 23/28). gemma passes 28/28 without it at 0.8 s.
    ollama_grader_think: bool | None = (
        None if os.getenv("OLLAMA_GRADER_THINK", "") == "" else os.getenv("OLLAMA_GRADER_THINK") in {"1", "true", "yes"}
    )
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
    )
    speaker_verifier: str = os.getenv("SPEAKER_VERIFIER", "stub").lower()
    # Server-side TTS: piper (default) | kokoro | browser (client Web Speech API)
    tts_engine: str = os.getenv("TTS_ENGINE", "piper").lower()
    # Download the default Piper voice on first start, so a fresh clone speaks with Piper.
    tts_auto_download: bool = os.getenv("TTS_AUTO_DOWNLOAD", "1") in {"1", "true", "yes"}
    tts_models_dir: Path = Path(os.getenv("TTS_MODELS_DIR", str(Path(__file__).resolve().parents[1] / "models")))
    piper_voice: str = os.getenv("PIPER_VOICE", "en_GB-jenny_dioco-medium")
    kokoro_voice: str = os.getenv("KOKORO_VOICE", "af_heart")
    kokoro_model_file: str = os.getenv("KOKORO_MODEL_FILE", "kokoro-v1.0.onnx")
    tts_speed: float = float(os.getenv("TTS_SPEED", "1.0"))
    # Tutor pacing knobs (code-enforced, not prompt-enforced)
    max_instruct_turns_per_node: int = int(os.getenv("MAX_INSTRUCT_TURNS", "3"))
    max_teach_back_attempts: int = int(os.getenv("MAX_TEACH_BACK_ATTEMPTS", "2"))
    # Study mode after the diagnostic: revision when at most this many main headings (level-1
    # nodes) got no evidence at all, otherwise learning, one heading at a time in depth.
    revision_max_missing_heads: int = int(os.getenv("REVISION_MAX_MISSING_HEADS", "0"))
    # Content review (T23): "session" (the Claude Code session answers packets) or "claude-api".
    # Ollama models are refused (D6).
    reviewer: str = os.getenv("REVIEWER", "session").lower()
    reviewer_model: str = os.getenv("REVIEWER_MODEL") or os.getenv("TUTOR_MODEL", "claude-opus-5")
    review_dir: Path = Path(os.getenv("REVIEW_DIR", str(Path(__file__).resolve().parents[1] / "data" / "reviews")))
    # Grader audit settings
    grader_capture_dir: Path = Path(os.getenv("GRADER_CAPTURE_DIR", str(Path(__file__).resolve().parents[1] / "data" / "captures")))
    capture_grader_calls: bool = os.getenv("CAPTURE_GRADER_CALLS", "1") in {"1", "true", "yes"}
    grade_memo: bool = os.getenv("GRADE_MEMO", "1") in {"1", "true", "yes"}


settings = Settings()

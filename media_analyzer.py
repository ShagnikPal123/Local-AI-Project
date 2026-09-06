"""Media analysis engine for pictures, images, diagrams, and video files."""

from __future__ import annotations

import base64
import os
from pathlib import Path
import struct
from typing import Any, Dict, List, Optional


class MediaAnalyzer:
    """Analyze picture and video media files locally with multimodal adapter hooks."""

    @staticmethod
    def analyze_picture(file_path: str | Path) -> Dict[str, Any]:
        """Inspect image file headers, dimensions, format, and prepare vision payloads."""
        path = Path(file_path).resolve()
        if not path.exists() or not path.is_file():
            return {"success": False, "error": f"Image file not found: {file_path}"}

        size_bytes = path.stat().st_size
        ext = path.suffix.lower()

        width, height, img_type = None, None, ext.replace(".", "").upper()

        # Parse basic dimensions from binary headers without external dependencies
        try:
            with path.open("rb") as f:
                header = f.read(64)

                # PNG
                if header.startswith(b"\x89PNG\r\n\x1a\n"):
                    img_type = "PNG"
                    f.seek(16)
                    width, height = struct.unpack(">II", f.read(8))

                # GIF
                elif header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
                    img_type = "GIF"
                    width, height = struct.unpack("<HH", header[6:10])

                # JPEG / JFIF
                elif header.startswith(b"\xff\xd8"):
                    img_type = "JPEG"
                    f.seek(2)
                    byte = f.read(1)
                    while byte:
                        while byte != b"\xff":
                            byte = f.read(1)
                        while byte == b"\xff":
                            byte = f.read(1)
                        if byte in (b"\xc0", b"\xc1", b"\xc2", b"\xc3"):
                            f.read(3)
                            h, w = struct.unpack(">HH", f.read(4))
                            width, height = w, h
                            break
                        else:
                            len_bytes = f.read(2)
                            if len(len_bytes) < 2:
                                break
                            block_len = struct.unpack(">H", len_bytes)[0]
                            f.seek(block_len - 2, os.SEEK_CUR)
                        byte = f.read(1)

        except Exception:
            pass

        return {
            "success": True,
            "filename": path.name,
            "path": str(path),
            "format": img_type,
            "size_bytes": size_bytes,
            "width": width,
            "height": height,
            "aspect_ratio": f"{round(width / height, 2)}:1" if width and height else None,
            "multimodal_ready": True,
        }

    @staticmethod
    def encode_image_base64(file_path: str | Path, max_bytes: int = 5_000_000) -> Optional[str]:
        """Safely encode an image file to a base64 data string for multimodal LLMs."""
        path = Path(file_path).resolve()
        if not path.exists() or path.stat().st_size > max_bytes:
            return None
        try:
            with path.open("rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return None

    @staticmethod
    def analyze_video(file_path: str | Path) -> Dict[str, Any]:
        """Inspect video file metadata, duration estimation, and frame sampling plan."""
        path = Path(file_path).resolve()
        if not path.exists() or not path.is_file():
            return {"success": False, "error": f"Video file not found: {file_path}"}

        size_bytes = path.stat().st_size
        ext = path.suffix.lower()

        # Generate a structured video breakdown plan
        sampling_fps = 1  # 1 frame per second standard for LLM vision analysis
        estimated_duration_sec = max(1, int(size_bytes / 250_000))  # rough heuristic if unparsed

        return {
            "success": True,
            "filename": path.name,
            "path": str(path),
            "format": ext.replace(".", "").upper(),
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "analysis_strategy": {
                "sampling_rate_fps": sampling_fps,
                "keyframes_recommended": min(30, max(5, estimated_duration_sec // 10)),
                "audio_track_transcription": True,
                "scene_change_detection": True,
            },
        }

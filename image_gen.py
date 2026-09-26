"""Pictures from a description, on the model the owner chose.

Generation runs through the ``image_gen`` role (``model_roles``), so "use NVIDIA
FLUX for pictures" is a setting, not code. The picture is saved as an upload —
it survives a restart and appears in the chat like any image the user sent —
and shown in the turn's timeline as it arrives.

The previous version guessed endpoints that do not exist
(``integrate.api.nvidia.com/v1/images/generations``) and swallowed every error,
so a failed generation read as "no provider supports image generation". The
real endpoints and their errors now live in ``model_hub.generate_image``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ImageGenResult:
    ok: bool
    prompt: str
    provider: str
    model: str = ""
    label: str = ""
    image_id: str = ""
    file_path: str = ""
    url: str = ""
    revised_prompt: str = ""
    error: str = ""
    note: str = ""
    ms: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "prompt": self.prompt, "provider": self.provider, "model": self.model,
            "label": self.label, "image_id": self.image_id, "url": self.url,
            "revised_prompt": self.revised_prompt, "error": self.error, "note": self.note, "ms": self.ms,
            "width": self.width, "height": self.height,
        }


def generate_image(prompt: str, size: str = "1024x1024", provider: str = "", model: str = "") -> ImageGenResult:
    """Generate, save, and show one picture. Never raises."""
    from model_hub import ModelCallError, generate_image as hub_generate
    from model_roles import MODEL_ROLES, RoleRun, _emit_run, _label_for

    clean = (prompt or "").strip()
    if not clean:
        return ImageGenResult(ok=False, prompt="", provider="", error="Describe the picture to generate.")

    try:
        import content_mode

        refusal = content_mode.check_image_prompt(clean)
    except Exception:  # pragma: no cover - the check must never break picture-making
        refusal = ""
    if refusal:
        return ImageGenResult(ok=False, prompt=clean, provider=provider or "", error=refusal)

    try:
        if provider:
            # An explicit provider for this one picture: exactly that, no fallback.
            image = hub_generate(provider, model, clean, size)
            run = RoleRun(role="image_gen", title="Image generation", job="image", provider=image.provider,
                          model=image.model, label=_label_for(image.provider, image.model), ms=image.ms)
            _emit_run(run)
        else:
            image, run = MODEL_ROLES.generate(clean, size=size)
    except ModelCallError as error:
        return ImageGenResult(ok=False, prompt=clean, provider=provider or "", error=str(error))

    import uploads

    extension = "jpg" if image.mime == "image/jpeg" else "png"
    safe = "".join(ch for ch in clean[:40] if ch.isalnum() or ch in " -_").strip().replace(" ", "-") or "image"
    record = uploads.save_upload(image.data, f"generated-{safe}.{extension}", image.mime)

    try:
        from tool_context import current

        ctx = current()
        if ctx is not None:
            from tool_context import _thumbnail_data_url

            data_url, width, height = _thumbnail_data_url(image.data, image.mime)
            ctx.emit("tool.image", call_id=ctx.call_id, name=record.get("name", ""), note=f"Made by {run.label}",
                     data_url=data_url, width=width, height=height, upload_id=record.get("id", ""),
                     generated=True)
    except Exception:
        pass

    return ImageGenResult(
        ok=True, prompt=clean, provider=run.provider, model=run.model, label=run.label,
        image_id=record.get("id", ""), file_path=record.get("path", ""),
        url=f"/api/uploads/{record.get('id', '')}", revised_prompt=getattr(image, "revised_prompt", ""),
        note=run.note, ms=run.ms, width=int(record.get("width") or 0), height=int(record.get("height") or 0),
    )

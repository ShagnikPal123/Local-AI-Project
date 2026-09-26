"""Tools that look at pictures, read documents and make images — on assigned models.

Each tool runs through ``model_roles``, so the model doing the job is whatever
the owner (or Nyx, when asked) assigned: "NVIDIA Llama Vision for image checks",
"AWS Nova for reading text". Every result starts with a line naming the model,
so the reply can say which model did what, and a ``model.role`` event puts the
same fact in the chat's step timeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

#: Characters of a document handed to the reading model in one request. Long
#: files are read in parts and the notes combined.
_READ_CHUNK_CHARS = 60_000
_MAX_CHUNKS = 6


def _load_source(source: str) -> Tuple[bytes, str, str]:
    """Bytes, mime and a display name for an upload id or a local path."""
    import uploads
    from permissions import is_protected_path

    ref = (source or "").strip().strip('"')
    record = uploads.get_upload(ref) if ref else None
    if record is not None:
        return Path(record["path"]).read_bytes(), record.get("mime", ""), record.get("name", ref)
    path = Path(ref).expanduser()
    if not ref or not path.is_file():
        raise FileNotFoundError(f"No upload or file called {source!r}.")
    if is_protected_path(str(path)):
        raise PermissionError(f"{path.name} is on the protected list (credentials), so it is not read.")
    mime = uploads._guess_mime(path.name, "")
    data = path.read_bytes()
    # A file picked up from the disk gets the same check as one dropped into the
    # chat: it may have come from an email or a download five minutes ago.
    try:
        import file_guard

        verdict = file_guard.check_bytes(data, path.name, mime)
        file_guard.record(verdict, "read by a tool")
    except Exception:  # noqa: BLE001 - a broken checker must not block reading
        verdict = None
    if verdict is not None and verdict.blocked:
        raise PermissionError(verdict.message)
    return data, mime, path.name


def _document_text(data: bytes, mime: str, name: str) -> str:
    import uploads

    kind = uploads.kind_for(name, mime)
    if kind == "pdf":
        return uploads.extract_pdf_text(data)
    if kind == "document":
        return uploads.extract_document_text(data, name)
    return uploads._decode_text(data)


def tool_analyze_image(source: str, question: str = "") -> str:
    """Look at an image (upload id or file path) with the image-check model."""
    from model_hub import ModelCallError
    from model_roles import MODEL_ROLES

    try:
        data, mime, name = _load_source(source)
    except (FileNotFoundError, PermissionError, OSError) as error:
        return f"Error: {error}"
    if not (mime or "").startswith("image/"):
        return f"Error: {name} is not an image ({mime or 'unknown type'}). Use read_document for files."
    import uploads

    prepared, prepared_mime = uploads.prepare_image(data, mime)
    prompt = (question or "Describe this image in detail: what it shows, any text in it, and anything notable.").strip()
    try:
        run = MODEL_ROLES.run("image_check", prompt, images=[(prepared, prepared_mime)])
    except ModelCallError as error:
        return f"Error: {error}"
    return f"{run.announcement()}\n{name}: {run.text}"


def tool_read_document(source: str, question: str = "") -> str:
    """Read a document (upload id or file path) with the reading-text model."""
    from model_hub import ModelCallError
    from model_roles import MODEL_ROLES

    try:
        data, mime, name = _load_source(source)
    except (FileNotFoundError, PermissionError, OSError) as error:
        return f"Error: {error}"
    text = _document_text(data, mime, name).strip()
    if not text:
        return f"Error: no readable text in {name} (a scanned PDF needs analyze_image on its pages)."

    ask = (question or "Summarise this document: its purpose, key points, and anything that needs action.").strip()
    chunks = [text[i:i + _READ_CHUNK_CHARS] for i in range(0, len(text), _READ_CHUNK_CHARS)][:_MAX_CHUNKS]
    notes: List[str] = []
    announcement = ""
    try:
        for index, chunk in enumerate(chunks, 1):
            if len(chunks) > 1:
                try:
                    from tool_context import progress

                    progress(f"Reading part {index} of {len(chunks)} of {name}")
                except Exception:
                    pass
            part = f" (part {index} of {len(chunks)})" if len(chunks) > 1 else ""
            run = MODEL_ROLES.run(
                "reading_text",
                f"Document: {name}{part}\n\n{chunk}\n\n---\nTask: {ask}",
                system="You read documents carefully and answer only from their content. Quote exact figures.",
                max_tokens=1500,
            )
            announcement = announcement or run.announcement()
            notes.append(run.text)
    except ModelCallError as error:
        return f"Error: {error}"

    truncated = len(text) > _READ_CHUNK_CHARS * _MAX_CHUNKS
    body = "\n\n".join(notes)
    if truncated:
        body += f"\n\n(Read the first {_READ_CHUNK_CHARS * _MAX_CHUNKS:,} of {len(text):,} characters.)"
    return f"{announcement}\n{name}:\n{body}"


def tool_generate_image(prompt: str, size: str = "1024x1024", provider: str = "", model: str = "") -> str:
    """Make a picture with the image-generation model and show it in the chat."""
    from image_gen import generate_image

    result = generate_image(prompt, size=size, provider=provider, model=model)
    if not result.ok:
        return f"Error: {result.error}"
    lines = [f"[{result.label} · image generation]" + (f" ({result.note})" if result.note else ""),
             f"Made the picture in {result.ms / 1000:.1f}s and showed it in the chat.",
             f"Upload id: {result.image_id}", f"![{prompt[:80]}]({result.url})"]
    if result.revised_prompt:
        lines.insert(2, f"The model rewrote the prompt as: {result.revised_prompt}")
    return "\n".join(lines)


def tool_set_model_purpose(purpose: str, provider: str, model: str = "", label: str = "", job: str = "") -> str:
    """Assign a provider and model to a job, as the user asked."""
    from model_roles import MODEL_ROLES, RoleError

    try:
        entry = MODEL_ROLES.assign_role(purpose, provider, model=model, announced_label=label, job=job,
                                        assigned_by="assistant")
    except RoleError as error:
        return f"Error: {error}"
    from model_hub import SIGNUP_URLS, is_configured

    ready = is_configured(entry["provider"])
    tail = "" if ready else (
        f" It has no key yet — add one in Keys"
        + (f" (get one at {SIGNUP_URLS[entry['provider']]})." if entry["provider"] in SIGNUP_URLS else ".")
    )
    return (f"Done: {entry['title']} now uses {entry['label']} ({entry['provider']}/{entry['model']}).{tail} "
            "Tell the user this assignment in your reply.")


def tool_list_model_roles() -> str:
    from model_roles import MODEL_ROLES

    return MODEL_ROLES.summary_for_prompt()


def register_media_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        "analyze_image",
        "Look at an image with the model assigned to image checks (upload id from the chat, or a file path). "
        "The result names the model used — tell the user which model looked at it.",
        [ToolParam("source", "string", "Upload id or full path of the image"),
         ToolParam("question", "string", "What to look for (optional)", required=False)],
        tool_analyze_image,
        category="files.read",
        label=lambda a: f"Checking image {str(a.get('source', ''))[:40]}",
    )
    registry.register(
        "read_document",
        "Read a PDF, Word, Excel, PowerPoint or text file with the model assigned to reading text "
        "(upload id or file path) and answer a question about it. The result names the model used.",
        [ToolParam("source", "string", "Upload id or full path of the document"),
         ToolParam("question", "string", "What you need from it (optional)", required=False)],
        tool_read_document,
        category="files.read",
        label=lambda a: f"Reading {str(a.get('source', ''))[:40]}",
    )
    registry.register(
        "generate_image",
        "Create a picture from a description with the model assigned to image generation; it appears in the chat. "
        "Write a vivid, specific prompt. The result names the model used.",
        [ToolParam("prompt", "string", "Detailed description of the picture"),
         ToolParam("size", "string", "WIDTHxHEIGHT, e.g. 1024x1024 or 1344x768", required=False),
         ToolParam("provider", "string", "Only when the user names a provider for this one picture", required=False),
         ToolParam("model", "string", "Only when the user names a model for this one picture", required=False)],
        tool_generate_image,
        category="network",
        label=lambda a: f"Drawing: {str(a.get('prompt', ''))[:60]}",
    )
    registry.register(
        "set_model_purpose",
        "Assign a provider and model to a job when the user asks (e.g. image_check -> nvidia "
        "meta/llama-3.2-11b-vision-instruct; reading_text -> aws amazon.nova-lite-v1:0; image_gen -> nvidia "
        "black-forest-labs/flux.1-schnell). New job names create a new role.",
        [ToolParam("purpose", "string", "Job name: image_check, reading_text, image_gen, ui_pointing, code_generation, fast_chat, or a new one"),
         ToolParam("provider", "string", "gemini, nvidia, groq, openai, claude, aws, deepseek, kimi, ollama, pollinations, or an added provider"),
         ToolParam("model", "string", "Exact model id (optional: a sensible default is used)", required=False),
         ToolParam("label", "string", "How to announce it, e.g. 'NVIDIA Vision' (optional)", required=False),
         ToolParam("job", "string", "text, vision or image (only for a new role)", required=False)],
        tool_set_model_purpose,
        category="general",
        label=lambda a: f"Assigning {a.get('provider', '')} to {a.get('purpose', '')}",
    )
    registry.register(
        "list_model_roles",
        "Which model is assigned to each job (image check, reading text, image generation, …) and whether it has a key.",
        [],
        tool_list_model_roles,
        category="general",
        label="Checking model assignments",
    )

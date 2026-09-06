"""Tests for the generic folder reader."""

import pytest

from folder_reader import FolderReader, FolderReaderError


@pytest.fixture
def folder(tmp_path):
    """Create a sample folder with text, media, and binary files."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("python is fun", encoding="utf-8")
    (docs / "data.txt").write_text("hello world", encoding="utf-8")
    (docs / "image.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (docs / "archive.zip").write_bytes(b"PK\x03\x04fake")
    (docs / "sub").mkdir()
    (docs / "sub" / "deep.py").write_text("def python_helper(): pass", encoding="utf-8")
    return docs


@pytest.fixture
def registry(tmp_path):
    # Registry lives outside the registered folder so it does not count as a file.""
    return tmp_path / "registry.json"


def test_add_folder_resolves_path(folder, registry):
    reader = FolderReader(registry_path=registry)
    resolved = reader.add_folder("docs", str(folder))
    assert resolved == str(folder.resolve())
    assert reader.folders["docs"] == resolved


def test_add_folder_missing_path_raises(registry):
    reader = FolderReader(registry_path=registry)
    with pytest.raises(FolderReaderError):
        reader.add_folder("nope", "C:/does/not/exist")


def test_remove_folder(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    removed = reader.remove_folder("docs")
    assert removed == str(folder.resolve())
    assert reader.list_folders() == []


def test_remove_missing_folder_raises(registry):
    reader = FolderReader(registry_path=registry)
    with pytest.raises(FolderReaderError):
        reader.remove_folder("missing")


def test_list_folders_reports_file_count(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    folders = reader.list_folders()
    assert len(folders) == 1
    assert folders[0]["name"] == "docs"
    assert folders[0]["exists"] is True
    assert folders[0]["file_count"] == 5


def test_registry_persists_across_instances(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    reloaded = FolderReader(registry_path=registry)
    assert reloaded.folders == {"docs": str(folder.resolve())}


def test_list_files_any_format(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    files = reader.list_files("docs")
    kinds = {f["name"]: f["kind"] for f in files}
    assert kinds["notes.md"] == "text"
    assert kinds["image.png"] == "media"
    assert kinds["archive.zip"] == "media"
    assert kinds["deep.py"] == "text"


def test_read_text_file(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    result = reader.read_file("docs", "notes.md")
    assert result["kind"] == "text"
    assert "python is fun" in result["content"]


def test_read_media_file_returns_placeholder(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    result = reader.read_file("docs", "image.png")
    assert result["kind"] == "media"
    assert "future feature" in result["content"]


def test_read_missing_file_raises(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    with pytest.raises(FolderReaderError):
        reader.read_file("docs", "missing.txt")


def test_read_path_escape_raises(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    with pytest.raises(FolderReaderError):
        reader.read_file("docs", "../secret.txt")


def test_search_files(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    results = reader.search_files("docs", "python")
    paths = {r["path"] for r in results}
    assert "notes.md" in paths
    assert "sub/deep.py" in paths


def test_search_no_match(registry, folder):
    reader = FolderReader(registry_path=registry)
    reader.add_folder("docs", str(folder))
    assert reader.search_files("docs", "zzz") == []


def test_unregistered_folder_raises(registry):
    reader = FolderReader(registry_path=registry)
    with pytest.raises(FolderReaderError):
        reader.list_files("unknown")

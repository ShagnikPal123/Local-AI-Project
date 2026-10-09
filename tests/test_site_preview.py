"""Trying what Nyx built (U11/U12): a preview that stays up, a zip to download, and only the owner's folders."""

from __future__ import annotations

import urllib.request
import zipfile

import pytest

import site_preview


@pytest.fixture
def site(tmp_path, monkeypatch):
    folder = tmp_path / "my-site"
    (folder / "node_modules" / "big").mkdir(parents=True)
    (folder / "index.html").write_text("<h1>Hello from the preview</h1>", encoding="utf-8")
    (folder / "style.css").write_text("h1{color:red}", encoding="utf-8")
    (folder / "node_modules" / "big" / "x.js").write_text("// not shipped", encoding="utf-8")
    import code_workspace

    monkeypatch.setattr(code_workspace, "resolve", lambda path: folder if str(folder) in str(path) else (_ for _ in ()).throw(
        code_workspace.CodeError("Open the folder (or file) in the Code tab first")))
    monkeypatch.setattr(site_preview, "data_path", lambda name: (tmp_path / "data" / name).parent.mkdir(parents=True, exist_ok=True) or tmp_path / "data" / name)
    yield folder
    site_preview.stop_all()


def test_a_folder_is_served_until_it_is_stopped_and_twice_gives_the_same_preview(site):
    preview = site_preview.start(str(site))
    assert preview["mode"] == "static" and preview["url"].startswith("http://127.0.0.1:")
    with urllib.request.urlopen(preview["url"], timeout=5) as response:
        assert "Hello from the preview" in response.read().decode()
    assert site_preview.start(str(site / "index.html"))["id"] == preview["id"]
    site_preview.stop(preview["id"])
    assert site_preview.running() == []
    with pytest.raises(Exception):
        urllib.request.urlopen(preview["url"], timeout=2)


def test_built_output_is_served_when_the_folder_itself_has_no_page(site, tmp_path):
    (site / "index.html").unlink()
    (site / "dist").mkdir()
    (site / "dist" / "index.html").write_text("built", encoding="utf-8")
    assert site_preview.site_root(site) == site / "dist"
    preview = site_preview.start(str(site))
    assert "dist" in preview["note"]


def test_only_folders_the_owner_opened_are_served(site, tmp_path):
    other = tmp_path / "private"
    other.mkdir()
    with pytest.raises(site_preview.PreviewError, match="Open that folder"):
        site_preview.start(str(other))


def test_the_download_leaves_out_packages(site):
    archive = site_preview.zip_folder(str(site))
    names = zipfile.ZipFile(archive).namelist()
    assert "my-site/index.html" in names and "my-site/style.css" in names
    assert not any("node_modules" in n for n in names)


def test_a_dev_script_is_used_only_when_its_packages_are_installed(site):
    (site / "package.json").write_text('{"scripts": {"dev": "vite"}}', encoding="utf-8")
    assert site_preview.dev_script(site) == "dev"
    (site / "node_modules" / "big" / "x.js").unlink()
    (site / "node_modules" / "big").rmdir()
    (site / "node_modules").rmdir()
    assert site_preview.dev_script(site) == ""


def test_preview_routes_are_owner_only():
    from fastapi.testclient import TestClient

    import server

    local = TestClient(server.app, client=("127.0.0.1", 50041))
    assert local.get("/api/code/previews").status_code == 200
    remote = TestClient(server.app, client=("203.0.113.9", 50042))
    assert remote.get("/api/code/previews").status_code in (401, 403)
    assert remote.post("/api/code/previews", json={"path": "C:/"}).status_code in (401, 403)
    assert remote.get("/api/code/download", params={"path": "C:/"}).status_code in (401, 403)
    assert remote.delete("/api/code/previews/pv-x").status_code in (401, 403)


def test_a_page_an_office_wrote_can_be_tried(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server
    from office import library

    library.use_root(tmp_path / "offices")
    try:
        office, _ = library.create_office("Site shop")
        work = library.work_dir(office.id)
        (work / "site").mkdir()
        (work / "site" / "index.html").write_text("<h1>Built by the office</h1>", encoding="utf-8")
        local = TestClient(server.app, client=("127.0.0.1", 50071))
        response = local.post(f"/api/office/offices/{office.id}/try", json={"path": "site/index.html"})
        assert response.status_code == 200, response.text
        url = response.json()["preview"]["url"]
        with urllib.request.urlopen(url, timeout=5) as page:
            assert "Built by the office" in page.read().decode()
        assert local.post(f"/api/office/offices/{office.id}/try", json={"path": "../../etc"}).status_code in (404, 409)
        remote = TestClient(server.app, client=("203.0.113.9", 50072))
        assert remote.post(f"/api/office/offices/{office.id}/try", json={"path": "site/index.html"}).status_code in (401, 403)
    finally:
        site_preview.stop_all()
        library.use_root(None)

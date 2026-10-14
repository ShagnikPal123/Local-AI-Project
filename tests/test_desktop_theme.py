"""Desktop colour sync (S4): the Windows accent, dark mode and wallpaper colour, read without Windows in the test."""

from desktop_theme import accent_from_dword, read_desktop_theme, solid_background


def test_the_accent_dword_is_read_as_abgr():
    # 0xFF D77800 in BGR is the classic Windows blue #0078d7.
    assert accent_from_dword(0xFFD77800) == "#0078d7"


def test_a_solid_background_is_read_from_decimal_triplets():
    assert solid_background("0 120 215") == "#0078d7"
    assert solid_background("nonsense") is None


def test_everything_is_read_when_it_is_there(tmp_path):
    wallpaper = tmp_path / "wall.png"
    wallpaper.write_bytes(b"x")
    values = {
        "AccentColor": 0xFFD77800,
        "AppsUseLightTheme": 0,
        "WallPaper": str(wallpaper),
    }
    theme = read_desktop_theme(reader=lambda path, name: values.get(name), average=lambda p: "#223344", is_windows=True)
    assert theme == {"available": True, "accent": "#0078d7", "dark": True, "wallpaper_color": "#223344"}


def test_no_picture_falls_back_to_the_solid_colour():
    values = {"WallPaper": "", "Background": "10 20 30"}
    theme = read_desktop_theme(reader=lambda path, name: values.get(name), average=lambda p: None, is_windows=True)
    assert theme["wallpaper_color"] == "#0a141e"
    assert theme["accent"] is None and theme["dark"] is None


def test_off_windows_nothing_is_read_and_nothing_raises():
    def boom(path, name):
        raise AssertionError("must not read the registry off Windows")

    theme = read_desktop_theme(reader=boom, is_windows=False)
    assert theme == {"available": False, "accent": None, "dark": None, "wallpaper_color": None}


def test_the_route_answers_on_any_system():
    import server
    from fastapi.testclient import TestClient

    reply = TestClient(server.app, client=("127.0.0.1", 50094)).get("/api/desktop-theme")
    assert reply.status_code == 200
    assert set(reply.json()) == {"available", "accent", "dark", "wallpaper_color"}

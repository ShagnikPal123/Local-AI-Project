"""The notch's controls and home (notch_controls.py): closed-set system controls, the owner's launchers, the default
view and its switching, and the small data each home view shows. Nothing here opens a real app or reaches the web."""

import types

import pytest

import notch_controls as nc


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(nc, "STORE", tmp_path / "notch_controls.json")
    monkeypatch.setattr(nc, "_cache", {})
    opened, started = [], []
    monkeypatch.setattr(nc, "_start", lambda target: opened.append(target))
    monkeypatch.setattr(nc, "_popen", lambda args, cwd=None, console=False: started.append((args, cwd, console)))
    monkeypatch.setattr(nc.sys, "platform", "win32")
    return types.SimpleNamespace(opened=opened, started=started)


def test_defaults_and_unknown_values_are_dropped():
    state = nc.update({"system": ["theme", "format_c_drive", "theme"], "home": {"default": "space", "views": ["weather", "x"]},
                       "launchers": [{"name": "Bad site", "kind": "site", "target": "javascript:alert(1)"},
                                     {"name": "", "kind": "app", "target": "x"},
                                     {"name": "GitHub", "kind": "site", "target": "https://github.com"}]})
    assert state["system"] == ["theme"]
    assert state["home"] == {"default": "weather", "views": ["weather"], "city": "", "triple_click": True}
    assert [l["name"] for l in state["launchers"]] == ["GitHub"] and state["launchers"][0]["color"]


def test_only_known_system_controls_run(isolated):
    assert nc.run_system("rm -rf")["ok"] is False
    assert nc.run_system("settings")["ok"] and isolated.opened == ["ms-settings:"]
    assert nc.run_system("explorer")["ok"] and isolated.started[-1] == (["explorer.exe"], None, False)
    assert nc.run_system("cmd")["ok"] and isolated.started[-1][2] is True  # its own console window


def test_volume_and_media_go_through_ultra_fast(monkeypatch):
    import ultrafast

    seen = []
    monkeypatch.setattr(ultrafast, "execute", lambda plan, dry_run=False: seen.append(plan) or {"ok": True, "said": "Louder."})
    assert nc.run_system("volume_up")["said"] == "Louder."
    nc.run_system("next")
    assert [(p["action"], p["args"]["op"]) for p in seen] == [("volume", "up"), ("media", "next")]


def test_theme_toggle_flips_apps_and_taskbar_together():
    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    values = {"AppsUseLightTheme": 1, "SystemUsesLightTheme": 1}
    registry = types.SimpleNamespace(
        HKEY_CURRENT_USER=1, KEY_READ=1, KEY_SET_VALUE=2, REG_DWORD=4, OpenKey=lambda *a: FakeKey(),
        QueryValueEx=lambda key, name: (values[name], 4), SetValueEx=lambda key, name, _r, _t, v: values.__setitem__(name, v))
    told = []
    assert nc.toggle_theme(registry, broadcast=lambda: told.append(1)) == "dark"
    assert values == {"AppsUseLightTheme": 0, "SystemUsesLightTheme": 0} and told == [1]
    assert nc.toggle_theme(registry, broadcast=lambda: None) == "light"


def test_a_command_launcher_opens_cmd_in_its_folder(isolated, tmp_path):
    state = nc.add_launcher({"name": "Claude Code", "kind": "command", "command": "claude", "folder": str(tmp_path)})
    launcher = state["launchers"][0]
    assert nc.run_launcher(launcher["id"])["ok"]
    assert isolated.started[-1] == (["cmd.exe", "/k", "claude"], str(tmp_path), True)
    nc.update({"launchers": [{**launcher, "folder": str(tmp_path / "gone")}]})
    assert nc.run_launcher(launcher["id"])["ok"] is False


def test_site_and_app_launchers_open_their_target(isolated, monkeypatch):
    import ultrafast

    monkeypatch.setattr(ultrafast, "installed_apps", lambda: {"spotify": r"C:\Start\Spotify.lnk"})
    state = nc.add_launcher({"name": "Spotify", "kind": "app", "target": "spotify"})
    state = nc.add_launcher({"name": "Vercel", "kind": "site", "target": "https://vercel.com"})
    for item in state["launchers"]:
        assert nc.run_launcher(item["id"])["ok"]
    assert isolated.opened == [r"C:\Start\Spotify.lnk", "https://vercel.com"]
    nc.remove_launcher(state["launchers"][0]["id"])
    assert [l["name"] for l in nc.settings()["launchers"]] == ["Vercel"]


def test_launchers_are_capped():
    for i in range(nc.MAX_LAUNCHERS):
        nc.add_launcher({"name": f"Site {i}", "kind": "site", "target": f"https://example{i}.com"})
    with pytest.raises(ValueError):
        nc.add_launcher({"name": "One more", "kind": "site", "target": "https://more.example"})


def test_suggest_finds_an_app_a_site_a_domain_or_a_search():
    apps = {"visual studio code": "code.lnk", "google chrome": "chrome.lnk"}
    assert nc.suggest("vs code", apps)["kind"] == "app"
    assert nc.suggest("google", apps)["target"] == "https://www.google.com"  # a site beats a loose app match
    assert nc.suggest("you tube", apps)["target"] == "https://www.youtube.com"
    assert nc.suggest("n8n.io", apps)["target"] == "https://n8n.io"
    guess = nc.suggest("my bank", apps)
    assert guess["kind"] == "site" and "q=my+bank" in guess["target"] and "check" in guess["how"]
    with pytest.raises(ValueError):
        nc.suggest("  ", apps)


def test_triple_click_walks_the_views_and_h_sets_the_default():
    nc.update({"home": {"views": ["apps", "weather", "calendar"]}})
    assert nc.cycle("apps") == "weather" and nc.cycle("calendar") == "apps" and nc.cycle("nope") == "apps"
    home = nc.set_default("now_playing")["home"]
    assert home["default"] == "now_playing" and home["views"][-1] == "now_playing"
    with pytest.raises(ValueError):
        nc.set_default("moon")


def test_weather_is_cached_and_kept_when_offline():
    calls = []

    def fetch(url, params):
        calls.append(url)
        if "geocoding" in url:
            return {"results": [{"name": "Austin", "latitude": 30.3, "longitude": -97.7}]}
        return {"current": {"temperature_2m": 21.5, "weather_code": 61},
                "daily": {"temperature_2m_max": [25], "temperature_2m_min": [14]}}

    first = nc.weather("Austin", fetch=fetch, now=1000)
    assert first == {"ok": True, "city": "Austin", "now": 21.5, "code": 61, "high": 25, "low": 14, "sky": "rain"}
    assert nc.weather("austin", fetch=fetch, now=1100) == first and len(calls) == 2  # cached

    def offline(url, params):
        raise OSError("no network")

    assert nc.weather("Austin", fetch=offline, now=1000 + nc.WEATHER_TTL + 1)["stale"] is True
    assert nc.weather("Nowhere", fetch=offline)["ok"] is False


def test_weather_needs_a_city(monkeypatch):
    import morning_digest

    monkeypatch.setattr(morning_digest, "settings", lambda: {"city": ""})
    assert nc.weather()["ok"] is False


def test_calendar_lists_today(monkeypatch):
    from datetime import datetime, timezone

    def call(connector, action, params):
        assert connector == "google_calendar" and params["timeMin"].startswith("2026-10-11T00:00")
        return {"data": {"items": [
            {"summary": "Design review", "start": {"dateTime": "2026-10-11T15:00:00Z"}, "end": {"dateTime": "2026-10-11T15:30:00Z"}},
            {"summary": "Holiday", "start": {"date": "2026-10-11"}}]}}

    day = nc.calendar(call=call, today=datetime(2026, 10, 11, 9, 30, tzinfo=timezone.utc))
    assert day["day"] == "Sun" and day["date"] == 11
    assert day["events"][0] == {"title": "Design review", "start": "15:00", "end": "15:30", "all_day": False}
    assert day["events"][1]["all_day"] is True


def test_now_playing_without_the_windows_package_says_what_to_install():
    result = nc.now_playing()
    assert result["ok"] is False and "winrt" in result["why"]


def test_now_playing_reads_the_current_media_session():
    class Session:
        source_app_user_model_id = "Spotify.exe"

        async def try_get_media_properties_async(self):
            return types.SimpleNamespace(title="Low Tide", artist="Nova Lane")

        def get_playback_info(self):
            return types.SimpleNamespace(playback_status=4)

    class Manager:
        @staticmethod
        async def request_async():
            return types.SimpleNamespace(get_current_session=lambda: Session())

    assert nc.now_playing(Manager) == {"ok": True, "playing": True, "title": "Low Tide", "artist": "Nova Lane",
                                       "app": "Spotify.exe"}


def test_places_are_clamped_and_a_locked_window_stays_put():
    state = nc.update({"place": {"sidebar": {"edge": "top", "y": -50, "x": "12.7", "bogus": 1}, "notch": {"x": 99999}}})
    assert state["place"]["sidebar"]["edge"] == "right" and state["place"]["sidebar"]["y"] == 0
    assert state["place"]["sidebar"]["x"] == 12 and "bogus" not in state["place"]["sidebar"]
    assert state["place"]["notch"]["x"] == 4000
    assert nc.move("notch", {"x": -120, "locked": True}) == {"x": -120, "locked": True}
    assert nc.move("notch", {"x": 300})["x"] == -120  # locked: the drag does not move it
    assert nc.move("notch", {"locked": False, "x": 300}) == {"x": 300, "locked": False}
    with pytest.raises(ValueError):
        nc.move("taskbar", {"x": 1})


def test_home_is_the_io_view_and_an_untouched_old_home_moves_to_it():
    assert nc.settings()["home"]["default"] == "agents"
    nc.STORE.write_text('{"home": {"default": "apps", "views": ["apps", "now_playing", "weather", "calendar"]}}', encoding="utf-8")
    home = nc.settings()["home"]
    assert home["default"] == "agents" and home["views"][0] == "agents"
    nc.STORE.write_text('{"home": {"default": "weather", "views": ["apps", "weather"]}}', encoding="utf-8")
    assert nc.settings()["home"] == {"default": "weather", "views": ["apps", "weather"], "city": "", "triple_click": True}


def test_the_timer_screen_is_no_longer_a_home_view_and_its_owners_land_on_agents():
    # Drive doc 2, item 2.6: "the screen below is unneeded, but the time aspect can stay".
    assert "timer" not in nc.VIEWS
    nc.STORE.write_text('{"home": {"default": "timer", "views": ["apps", "timer", "weather"]}}', encoding="utf-8")
    home = nc.settings()["home"]
    assert home["default"] == "agents" and home["views"] == ["agents", "apps", "weather"]

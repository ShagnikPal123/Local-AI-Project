"""Style from an image: only safe CSS values survive, and the route explains when no model can see."""

import base64

import style_from_image as sfi


def test_clean_look_keeps_safe_values():
    look = sfi.clean_look({
        "background": "#0D1117", "sidebar": "#010409", "panel": "#161b22", "text": "#e6edf3", "muted": "#7d8590",
        "accent": "#2f81f7", "radius": 9.6, "density": "Compact", "nav": "LEFT", "dark": True,
        "name": "GitHub <dark>", "notes": "Sidebar on the left, cards in a grid.",
    })
    assert look["background"] == "#0d1117" and look["accent"] == "#2f81f7"
    assert look["radius"] == 10 and look["density"] == "compact" and look["nav"] == "left" and look["dark"] is True
    assert look["name"] == "GitHub dark"


def test_clean_look_drops_anything_unsafe():
    look = sfi.clean_look({"background": "red; background:url(x)", "accent": "#12345", "radius": 400,
                           "density": "huge", "nav": "middle", "dark": "yes"})
    assert "background" not in look and "accent" not in look and "density" not in look and "nav" not in look
    assert "dark" not in look and look["radius"] == 24


def test_json_is_found_inside_prose():
    assert sfi._json_from('Sure! {"accent": "#ff0000"} hope that helps')["accent"] == "#ff0000"
    assert sfi._json_from("no json here") == {}


def test_read_style_uses_vision(monkeypatch):
    import vision

    monkeypatch.setattr(vision, "_ask", lambda image, mime, prompt, role="": '{"accent": "#D97757", "nav": "top"}')
    assert sfi.read_style(b"png", "image/png") == {"accent": "#d97757", "nav": "top"}


def test_route_says_when_no_model_can_see(monkeypatch):
    import pytest
    from fastapi import HTTPException

    import routes_style
    import vision

    def blind(*_args, **_kwargs):
        raise vision.VisionUnavailable("Seeing images needs a vision-capable model.")

    monkeypatch.setattr(sfi, "read_style", blind)
    body = routes_style.StyleImage(image=base64.b64encode(b"\x89PNG").decode(), mime="image/png")
    with pytest.raises(HTTPException) as caught:
        routes_style.style_from_image(body, _user=None)
    assert caught.value.status_code == 503


def test_route_refuses_non_images():
    import pytest
    from fastapi import HTTPException

    import routes_style

    with pytest.raises(HTTPException) as caught:
        routes_style.style_from_image(routes_style.StyleImage(image="aGVsbG8=", mime="text/plain"), _user=None)
    assert caught.value.status_code == 400

from __future__ import annotations


class _FakeImage:
    def __init__(self, label: str):
        self.label = label
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def convert(self, _mode: str):
        return _FakeImage(f"{self.label}-converted")

    def close(self):
        self.closed = True


def test_analyze_image_bytes_closes_converted_images(monkeypatch):
    from app import vision_client

    opened = _FakeImage("opened")
    created: list[_FakeImage] = [opened]

    def _fake_open(_src):
        return opened

    def _fake_convert(mode: str):
        converted = _FakeImage(f"opened-{mode}")
        created.append(converted)
        return converted

    opened.convert = _fake_convert  # type: ignore[assignment]
    monkeypatch.setattr(vision_client.Image, "open", _fake_open)
    monkeypatch.setattr(vision_client, "_preprocess_image", lambda img, mode="text": img)
    monkeypatch.setattr(vision_client.pytesseract, "image_to_string", lambda *a, **k: "hello")

    out = vision_client.analyze_image_bytes(b"img", lang="en", mode="text")
    assert "I extracted the following text" in out
    assert created[-1].closed is True


def test_ocr_image_bytes_closes_converted_image(monkeypatch):
    from app.services import ocr_service

    opened = _FakeImage("opened")
    created: list[_FakeImage] = [opened]

    def _fake_open(_src):
        return opened

    def _fake_convert(_mode: str):
        converted = _FakeImage("converted")
        created.append(converted)
        return converted

    opened.convert = _fake_convert  # type: ignore[assignment]
    monkeypatch.setattr(ocr_service.Image, "open", _fake_open)
    monkeypatch.setattr(ocr_service.pytesseract, "image_to_string", lambda *a, **k: "ocr")

    out = ocr_service.ocr_image_bytes(b"img")
    assert out == "ocr"
    assert created[-1].closed is True

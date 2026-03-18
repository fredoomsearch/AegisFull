from __future__ import annotations

from app.scripts import image_backend_probe as probe


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = b"{}"

    def json(self):
        return self._payload


def test_extract_checkpoint_choices_handles_nested_shape():
    payload = {
        "CheckpointLoaderSimple": {
            "input": {
                "required": {
                    "ckpt_name": [["DreamShaper_8_pruned.safetensors", "sd_turbo.safetensors"]],
                }
            }
        }
    }
    out = probe._extract_checkpoint_choices(payload)  # noqa: SLF001
    assert out == ["DreamShaper_8_pruned.safetensors", "sd_turbo.safetensors"]


def test_probe_backend_success(monkeypatch):
    monkeypatch.setattr(probe, "_tcp_reachable", lambda *_a, **_k: (True, "ok"))

    def _fake_get(url: str, timeout: float = 0):  # noqa: ARG001
        if url.endswith("/object_info/CheckpointLoaderSimple"):
            return _Resp(
                200,
                {
                    "CheckpointLoaderSimple": {
                        "required": {
                            "ckpt_name": [["DreamShaper_8_pruned.safetensors"]],
                        }
                    }
                },
            )
        return _Resp(200, {})

    monkeypatch.setattr(probe.requests, "get", _fake_get)

    out = probe.probe_backend(endpoint="http://127.0.0.1:8188/prompt", require_checkpoint=True)
    assert out.ok is True
    assert out.object_info_status == 200
    assert out.checkpoints == ["DreamShaper_8_pruned.safetensors"]


def test_probe_backend_fails_when_no_checkpoints_required(monkeypatch):
    monkeypatch.setattr(probe, "_tcp_reachable", lambda *_a, **_k: (True, "ok"))

    def _fake_get(url: str, timeout: float = 0):  # noqa: ARG001
        if url.endswith("/object_info/CheckpointLoaderSimple"):
            return _Resp(200, {"CheckpointLoaderSimple": {}})
        return _Resp(200, {})

    monkeypatch.setattr(probe.requests, "get", _fake_get)

    out = probe.probe_backend(endpoint="http://127.0.0.1:8188/prompt", require_checkpoint=True)
    assert out.ok is False
    assert out.error == "no-checkpoints-found"


def test_probe_backend_requires_nvidia_smi_pass(monkeypatch):
    monkeypatch.setattr(probe, "_tcp_reachable", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(probe, "_probe_nvidia_smi", lambda *_a, **_k: (True, 1, "gpu_count=1"))

    def _fake_get(url: str, timeout: float = 0):  # noqa: ARG001
        if url.endswith("/object_info/CheckpointLoaderSimple"):
            return _Resp(200, {"CheckpointLoaderSimple": {"required": {"ckpt_name": [["a.safetensors"]]}}})
        return _Resp(200, {})

    monkeypatch.setattr(probe.requests, "get", _fake_get)

    out = probe.probe_backend(
        endpoint="http://127.0.0.1:8188/prompt",
        require_checkpoint=True,
        require_nvidia_smi=True,
    )
    assert out.ok is True
    assert out.nvidia_probe_attempted is True
    assert out.nvidia_probe_ok is True
    assert out.nvidia_gpu_count == 1


def test_probe_backend_requires_nvidia_smi_fail(monkeypatch):
    monkeypatch.setattr(probe, "_tcp_reachable", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(probe, "_probe_nvidia_smi", lambda *_a, **_k: (False, 0, "not-found"))

    def _fake_get(url: str, timeout: float = 0):  # noqa: ARG001
        if url.endswith("/object_info/CheckpointLoaderSimple"):
            return _Resp(200, {"CheckpointLoaderSimple": {"required": {"ckpt_name": [["a.safetensors"]]}}})
        return _Resp(200, {})

    monkeypatch.setattr(probe.requests, "get", _fake_get)

    out = probe.probe_backend(
        endpoint="http://127.0.0.1:8188/prompt",
        require_checkpoint=True,
        require_nvidia_smi=True,
    )
    assert out.ok is False
    assert "nvidia-smi-required" in out.error


def test_probe_backend_torch_cuda_required_pass(monkeypatch):
    monkeypatch.setattr(probe, "_tcp_reachable", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(
        probe,
        "_probe_torch_runtime",
        lambda *_a, **_k: (True, True, "cuda_available=True device_count=1"),
    )

    def _fake_get(url: str, timeout: float = 0):  # noqa: ARG001
        if url.endswith("/object_info/CheckpointLoaderSimple"):
            return _Resp(200, {"CheckpointLoaderSimple": {"required": {"ckpt_name": [["a.safetensors"]]}}})
        return _Resp(200, {})

    monkeypatch.setattr(probe.requests, "get", _fake_get)

    out = probe.probe_backend(
        endpoint="http://127.0.0.1:8188/prompt",
        require_checkpoint=True,
        python_bin="/tmp/fake-python",
        require_torch_cuda=True,
    )
    assert out.ok is True
    assert out.torch_probe_attempted is True
    assert out.torch_probe_ok is True
    assert out.torch_cuda_available is True


def test_probe_backend_torch_cuda_required_without_python_bin_fails(monkeypatch):
    monkeypatch.setattr(probe, "_tcp_reachable", lambda *_a, **_k: (True, "ok"))

    def _fake_get(url: str, timeout: float = 0):  # noqa: ARG001
        if url.endswith("/object_info/CheckpointLoaderSimple"):
            return _Resp(200, {"CheckpointLoaderSimple": {"required": {"ckpt_name": [["a.safetensors"]]}}})
        return _Resp(200, {})

    monkeypatch.setattr(probe.requests, "get", _fake_get)

    out = probe.probe_backend(
        endpoint="http://127.0.0.1:8188/prompt",
        require_checkpoint=True,
        python_bin="",
        require_torch_cuda=True,
    )
    assert out.ok is False
    assert "torch-cuda-required" in out.error

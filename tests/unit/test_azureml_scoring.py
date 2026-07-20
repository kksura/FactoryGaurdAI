"""The AML scoring entries (deployment/azureml/scoring/) are thin adapters over
PredictionService; these tests pin the adapter contract itself — bundle
discovery under AZUREML_MODEL_DIR, env-driven serving mode, JSON in/out —
without retraining a model (the full service path is covered end-to-end in
tests/end_to_end/test_api_flow.py)."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCORING_DIR = Path(__file__).resolve().parents[2] / "deployment" / "azureml" / "scoring"


def _load(name: str) -> ModuleType:
    if str(SCORING_DIR) not in sys.path:
        sys.path.insert(0, str(SCORING_DIR))
    spec = importlib.util.spec_from_file_location(name, SCORING_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _FakeService:
    def __init__(self, bundle, serving_mode):  # type: ignore[no-untyped-def]
        self.bundle = bundle
        self.mode = serving_mode

    def predict(self, request):  # type: ignore[no-untyped-def]
        class _Resp:
            @staticmethod
            def model_dump_json() -> str:
                return json.dumps({"echo": request["x"], "mode": str(self.mode)})

        return _Resp()


def test_locate_bundle_finds_nested_manifest(tmp_path: Path) -> None:
    score = _load("score")
    nested = tmp_path / "model" / "artifacts" / "small"
    nested.mkdir(parents=True)
    (nested / "manifest.json").write_text("{}")
    assert score._locate_bundle(tmp_path) == nested


def test_locate_bundle_fails_loudly_without_manifest(tmp_path: Path) -> None:
    score = _load("score")
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        score._locate_bundle(tmp_path)


def test_run_before_init_raises() -> None:
    score = _load("score")
    score._service = None
    with pytest.raises(RuntimeError, match="init"):
        score.run("{}")


def test_init_and_run_plumbing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    score = _load("score")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "manifest.json").write_text("{}")

    loaded: dict[str, object] = {}

    def fake_load(path: Path, verify_checksums: bool = True) -> str:
        loaded["path"], loaded["verify"] = path, verify_checksums
        return "fake-bundle"

    monkeypatch.setenv("AZUREML_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("FG_SERVING_MODE", "anomaly-only")
    monkeypatch.setattr(score.ArtifactBundle, "load", staticmethod(fake_load))
    monkeypatch.setattr(score, "PredictionService", _FakeService)
    monkeypatch.setattr(
        score, "PredictionRequest", type("R", (), {"model_validate": staticmethod(lambda d: d)})
    )

    score.init()
    assert loaded == {"path": bundle_dir, "verify": True}
    out = score.run(json.dumps({"x": 42}))
    assert out["echo"] == 42
    assert "anomaly" in out["mode"]


def test_batch_run_scores_jsonl_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _load("score")  # score_batch imports _locate_bundle from score
    batch = _load("score_batch")

    class _Svc:
        @staticmethod
        def predict(request):  # type: ignore[no-untyped-def]
            class _Resp:
                @staticmethod
                def model_dump_json() -> str:
                    return json.dumps({"unit": request["unit"]})

            return _Resp()

    monkeypatch.setattr(batch, "_service", _Svc())
    monkeypatch.setattr(
        batch, "PredictionRequest", type("R", (), {"model_validate": staticmethod(lambda d: d)})
    )
    f = tmp_path / "requests.jsonl"
    f.write_text('{"unit": "U1"}\n\n{"unit": "U2"}\n')
    rows = batch.run([str(f)])
    assert [json.loads(r)["unit"] for r in rows] == ["U1", "U2"]

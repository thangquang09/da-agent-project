from __future__ import annotations

from e2b_code_interpreter.exceptions import TimeoutException as SandboxException

from app.graph.standalone_visualization import _normalize_raw_data, inline_data_worker
from app.tools.visualization import E2BVisualizationService


def test_normalize_raw_numeric_series_to_rows():
    rows = _normalize_raw_data([10, 30, 60])

    assert rows == [
        {"Category": "Category 1", "Value": 10},
        {"Category": "Category 2", "Value": 30},
        {"Category": "Category 3", "Value": 60},
    ]


def test_standalone_visualization_handles_numeric_raw_data(monkeypatch):
    class DummyFiles:
        def write(self, path, content):
            return None

    class DummyExecution:
        error = None
        results = []

    class DummySandbox:
        files = DummyFiles()

        def run_code(self, code):
            return DummyExecution()

    class DummyService:
        def __init__(self):
            self._sandbox = DummySandbox()

        def _get_sandbox(self):
            return self._sandbox

        def _sandbox_is_stale(self, exc):
            return False

        def _reset_sandbox(self):
            self._sandbox = DummySandbox()

    monkeypatch.setattr(
        "app.graph.standalone_visualization.is_visualization_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.graph.standalone_visualization.get_visualization_service",
        lambda: DummyService(),
    )
    monkeypatch.setattr(
        "app.graph.standalone_visualization._generate_standalone_visualization_code",
        lambda query, raw_data: "import matplotlib.pyplot as plt\nplt.show()",
    )
    monkeypatch.setattr(
        "app.graph.standalone_visualization._extract_image",
        lambda execution: (b"img", "png"),
    )

    result = inline_data_worker(
        {
            "query": "Vẽ biểu đồ tròn cho 10, 30, 60",
            "raw_data": [10, 30, 60],
        }
    )

    assert result["status"] == "success"
    assert result["visualization"]["success"] is True


def test_visualization_service_recreates_stale_sandbox(monkeypatch):
    class DummyFiles:
        def __init__(self, fail_first_write: bool = False):
            self.write_calls = 0
            self.fail_first_write = fail_first_write

        def write(self, path, content):
            self.write_calls += 1
            if self.fail_first_write and self.write_calls == 1:
                raise SandboxException("The sandbox was not found")
            return None

    class DummyExecution:
        def __init__(self):
            self.error = None
            self.results = []

    class DummySandbox:
        def __init__(self, fail_first_write: bool = False):
            self.files = DummyFiles(fail_first_write=fail_first_write)

        def run_code(self, code):
            return DummyExecution()

        def close(self):
            return None

    service = E2BVisualizationService(api_key="test")

    sandboxes = [DummySandbox(fail_first_write=True), DummySandbox()]

    def fake_get_sandbox(*args, **kwargs):
        if service._sandbox is None:
            service._sandbox = sandboxes.pop(0)
        return service._sandbox

    monkeypatch.setattr(service, "_get_sandbox", fake_get_sandbox)
    monkeypatch.setattr(service, "_extract_image", lambda execution: (b"img", "png"))

    result = service.generate_visualization(
        data_rows=[{"Category": "A", "Value": 10}],
        user_query="draw chart",
        python_code="import matplotlib.pyplot as plt\nplt.show()",
    )

    assert result.success is True

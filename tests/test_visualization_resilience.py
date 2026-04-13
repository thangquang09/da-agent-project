from __future__ import annotations

import base64

from e2b_code_interpreter.exceptions import TimeoutException as SandboxException

from app.graph.standalone_visualization import _normalize_raw_data, inline_data_worker
from app.tools.visualization import (
    DockerVisualizationService,
    E2BVisualizationService,
    NullVisualizationService,
    get_visualization_service,
    is_visualization_available,
)


def test_normalize_raw_numeric_series_to_rows():
    rows = _normalize_raw_data([10, 30, 60])

    assert rows == [
        {"Category": "Category 1", "Value": 10},
        {"Category": "Category 2", "Value": 30},
        {"Category": "Category 3", "Value": 60},
    ]


def test_standalone_visualization_handles_numeric_raw_data(monkeypatch):
    class DummyService:
        def generate_visualization(self, *, data_rows, user_query, python_code):
            return type(
                "Result",
                (),
                {
                    "success": True,
                    "image_data": b"img",
                    "image_format": "png",
                    "error": None,
                    "code_executed": python_code,
                    "execution_time_ms": 12.0,
                },
            )()

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


def test_docker_visualization_service_extracts_chart_and_report_artifacts(monkeypatch):
    service = DockerVisualizationService(
        image="python:3.11-slim",
        bootstrap_command="",
        timeout_seconds=30,
    )
    png = base64.b64encode(b"fake-png").decode("utf-8")

    def fake_run_container(*, files, command, timeout_seconds=None):  # noqa: ANN001
        assert "query_data.csv" in files or "report_section_data.csv" in files
        return type(
            "ExecResult",
            (),
            {
                "success": True,
                "stdout": (
                    '__REPORT_ANALYSIS_JSON__:{"row_count": 2}\n'
                    '__REPORT_CHART_MANIFEST__:{"chart_type":"bar"}\n'
                    '__REPORT_HTML__:<div data-report-analysis="true"></div>\n'
                    f"__CHART_PNG_BASE64__:{png}\n"
                ),
                "stderr": "",
                "exit_code": 0,
            },
        )()

    monkeypatch.setattr(service, "_run_container", fake_run_container)

    report = service.generate_grounded_report_analysis(
        data_rows=[{"gender": "female", "count": 518}],
        user_query="report",
        section_title="Gender",
    )

    assert report.success is True
    assert report.computed_stats == {"row_count": 2}
    assert report.chart_manifest == {"chart_type": "bar"}
    assert report.chart_html == '<div data-report-analysis="true"></div>'
    assert report.image_data == b"fake-png"


def test_docker_visualization_wrapper_creates_home_user_query_data_alias():
    service = DockerVisualizationService(
        image="python:3.11-slim",
        bootstrap_command="",
        timeout_seconds=30,
    )

    wrapped = service._wrap_visualization_code("print('ok')")

    assert 'os.makedirs("/home/user", exist_ok=True)' in wrapped
    assert 'shutil.copyfile("query_data.csv", "/home/user/query_data.csv")' in wrapped


def test_visualization_factory_defaults_to_docker(monkeypatch):
    from app import config as config_module
    from app.tools import visualization as visualization_module

    config_module.load_settings.cache_clear()
    monkeypatch.setenv("TYPE_OF_SANDBOX", "docker")
    monkeypatch.setenv("APP_MODE", "full")
    monkeypatch.setenv("ENABLE_VISUALIZATION", "true")
    monkeypatch.setattr(
        "app.tools.visualization.shutil.which", lambda name: "/usr/bin/docker"
    )
    visualization_module._visualization_service = None
    visualization_module._visualization_service_key = None

    service = get_visualization_service()

    assert isinstance(service, DockerVisualizationService)
    assert is_visualization_available() is True
    config_module.load_settings.cache_clear()
    visualization_module._visualization_service = None
    visualization_module._visualization_service_key = None


def test_visualization_factory_none_disables_sandbox(monkeypatch):
    from app import config as config_module
    from app.tools import visualization as visualization_module

    config_module.load_settings.cache_clear()
    monkeypatch.setenv("TYPE_OF_SANDBOX", "none")
    visualization_module._visualization_service = None
    visualization_module._visualization_service_key = None

    service = get_visualization_service()

    assert (
        service.generate_visualization(
            data_rows=[{"x": 1, "y": 2}],
            user_query="chart",
        ).success
        is False
    )
    assert is_visualization_available() is False
    config_module.load_settings.cache_clear()
    visualization_module._visualization_service = None
    visualization_module._visualization_service_key = None


def test_visualization_flag_disables_service_even_with_docker(monkeypatch):
    from app import config as config_module
    from app.tools import visualization as visualization_module

    config_module.load_settings.cache_clear()
    monkeypatch.setenv("TYPE_OF_SANDBOX", "docker")
    monkeypatch.setenv("ENABLE_VISUALIZATION", "false")
    visualization_module._visualization_service = None
    visualization_module._visualization_service_key = None

    service = get_visualization_service()

    assert isinstance(service, NullVisualizationService)
    assert is_visualization_available() is False
    config_module.load_settings.cache_clear()
    visualization_module._visualization_service = None
    visualization_module._visualization_service_key = None

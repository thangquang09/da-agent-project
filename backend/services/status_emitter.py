from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable

from backend.models.events import StatusEvent

NODE_LABELS: dict[str, tuple[str, str]] = {
    "process_uploaded_files": ("started", "Đang xử lý file upload..."),
    "inject_session_context": ("started", "Đang tải lịch sử hội thoại..."),
    "task_grounder": ("started", "Đang phân tích câu hỏi..."),
    "leader_agent": ("started", "Đang suy luận..."),
    "chitchat_response_node": ("started", "Đang trả lời..."),
    "artifact_evaluator": ("started", "Đang đánh giá kết quả..."),
    "clarify_question_node": ("started", "Đang làm rõ câu hỏi..."),
    "capture_action_node": ("started", "Đang lưu trạng thái..."),
    "compact_and_save_memory": ("started", "Đang lưu hội thoại..."),
    "profiler_sampler": ("started", "Đang lấy mẫu dữ liệu..."),
    "profiler_analyzer": ("started", "Đang phân tích profile dữ liệu..."),
    "report_planner": ("started", "Đang lên kế hoạch báo cáo..."),
    "section_pipeline": ("started", "Đang viết mục báo cáo..."),
    "sections_sort": ("started", "Đang sắp xếp nội dung..."),
    "report_writer": ("started", "Đang tổng hợp báo cáo..."),
    "report_critic": ("started", "Đang kiểm chứng báo cáo..."),
    "report_finalize": ("started", "Đang hoàn thiện báo cáo..."),
    "create_visualization": ("started", "Đang tạo biểu đồ..."),
}

NODE_COMPLETED_LABELS: dict[str, str] = {
    "task_grounder": "Đã phân tích câu hỏi",
    "leader_agent": "Đã suy luận xong",
    "profiler_sampler": "Đã lấy mẫu dữ liệu",
    "profiler_analyzer": "Đã phân tích profile",
    "report_planner": "Đã lên kế hoạch báo cáo",
    "section_pipeline": "Đã viết mục báo cáo",
    "report_writer": "Đã tổng hợp báo cáo",
    "report_critic": "Đã kiểm chứng báo cáo",
    "report_finalize": "Đã hoàn thiện báo cáo",
}


class StatusEmitter:
    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[StatusEvent] = asyncio.Queue()
        self._done = threading.Event()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def queue(self) -> asyncio.Queue[StatusEvent]:
        return self._queue

    def mark_done(self) -> None:
        self._done.set()

    @property
    def is_done(self) -> bool:
        return self._done.is_set()

    def on_node_status(
        self,
        node_name: str,
        phase: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        from app.observability.schemas import utc_now_iso

        label = ""
        if phase == "started":
            entry = NODE_LABELS.get(node_name)
            if entry:
                label = entry[1]
            else:
                label = f"Đang chạy {node_name}..."
        elif phase == "completed":
            label = NODE_COMPLETED_LABELS.get(node_name, f"Đã hoàn thành {node_name}")
        elif phase == "error":
            label = f"Lỗi ở {node_name}"

        event = StatusEvent(
            event="status",
            node=node_name,
            phase=phase,
            label=label,
            detail=detail or {},
            timestamp=utc_now_iso(),
        )

        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        elif not self._done.is_set():
            try:
                self._queue.put_nowait(event)
            except Exception:
                pass

    def make_tracer_callback(self) -> Callable[[str, str, dict[str, Any] | None], None]:
        return self.on_node_status

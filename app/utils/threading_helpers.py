from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Generic, Optional, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class TimedCallResult(Generic[T]):
    completed: bool
    value: Optional[T] = None
    error: Optional[BaseException] = None


def call_with_timeout(
    fn: Callable[[], T],
    *,
    timeout_s: float,
    thread_name: str,
    daemon: bool = True,
) -> TimedCallResult[T]:
    result: dict[str, object] = {"value": None, "error": None}
    done = threading.Event()

    def _worker() -> None:
        try:
            result["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_worker, name=thread_name, daemon=daemon)
    thread.start()
    done.wait(timeout_s)
    if not done.is_set():
        return TimedCallResult(completed=False)
    return TimedCallResult(
        completed=True,
        value=result["value"],  # type: ignore[arg-type]
        error=result["error"],  # type: ignore[arg-type]
    )

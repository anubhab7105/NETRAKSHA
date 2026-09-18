"""Pipeline adapter interfaces and Netraksha-specific implementations.

Abstract base classes define the adapter contract.
Concrete adapters wrap real Netraksha pipeline functions.
Every adapter gracefully returns NOT_AVAILABLE if the import fails.
"""

from __future__ import annotations

import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .models import MetricSource, TestStatus


# ---------------------------------------------------------------------------
# Shared result type for adapters
# ---------------------------------------------------------------------------

class AdapterResult:
    """Result from an adapter call."""

    def __init__(
        self,
        available: bool,
        success: bool,
        duration_ms: float,
        score: Optional[float],
        status: str,
        raw_output: Dict[str, Any],
        error: Optional[str] = None,
        source: MetricSource = MetricSource.MEASURED,
    ):
        self.available = available
        self.success = success
        self.duration_ms = duration_ms
        self.score = score
        self.status = status  # "ok" | "inconclusive" | "error" | "unavailable"
        self.raw_output = raw_output
        self.error = error
        self.source = source

    @classmethod
    def unavailable(cls, reason: str) -> "AdapterResult":
        return cls(
            available=False,
            success=False,
            duration_ms=0.0,
            score=None,
            status="unavailable",
            raw_output={"reason": reason},
            error=reason,
            source=MetricSource.NOT_AVAILABLE,
        )

    @classmethod
    def error_result(cls, error: str, duration_ms: float = 0.0) -> "AdapterResult":
        return cls(
            available=True,
            success=False,
            duration_ms=duration_ms,
            score=None,
            status="error",
            raw_output={"error": error},
            error=error,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
            "score": self.score,
            "status": self.status,
            "raw_output": self.raw_output,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Abstract adapter base classes
# ---------------------------------------------------------------------------

class BaseAdapter(ABC):
    """Abstract base for all pipeline adapters."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...


class OCRAdapter(BaseAdapter):
    """Abstract OCR adapter."""

    @abstractmethod
    def run(self, image_path: Union[str, Path]) -> AdapterResult: ...


class TamperDetectionAdapter(BaseAdapter):
    """Abstract tamper detection adapter."""

    @abstractmethod
    def run(self, image_path: Union[str, Path]) -> AdapterResult: ...


class FaceVerificationAdapter(BaseAdapter):
    """Abstract face verification adapter."""

    @abstractmethod
    def run(
        self,
        document_photo: Union[str, Path],
        live_capture: Union[str, Path],
    ) -> AdapterResult: ...


class LivenessAdapter(BaseAdapter):
    """Abstract liveness detection adapter."""

    @abstractmethod
    def run(
        self,
        frame_burst: list,
        challenge_type: str = "blink",
    ) -> AdapterResult: ...


class DeepfakeAdapter(BaseAdapter):
    """Abstract deepfake detection adapter."""

    @abstractmethod
    def run(self, image_path: Union[str, Path]) -> AdapterResult: ...


class PhysicalForgeryAdapter(BaseAdapter):
    """Abstract physical forgery detection adapter."""

    @abstractmethod
    def run(self, image_path: Union[str, Path]) -> AdapterResult: ...


class DocumentQualityAdapter(BaseAdapter):
    """Abstract document quality adapter."""

    @abstractmethod
    def run(self, image_path: Union[str, Path]) -> AdapterResult: ...


class RiskEngineAdapter(BaseAdapter):
    """Abstract risk engine adapter."""

    @abstractmethod
    def run(self, module_results: Dict[str, Any]) -> AdapterResult: ...


# ---------------------------------------------------------------------------
# Netraksha concrete adapters
# ---------------------------------------------------------------------------

def _add_project_root_to_path(cfg_or_root: Any) -> None:
    """Ensure the Netraksha project root is on sys.path."""
    if hasattr(cfg_or_root, "project_root"):
        root = str(cfg_or_root.project_root)
    else:
        root = str(cfg_or_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def _module_result_to_adapter(mr: Any, duration_ms: float) -> AdapterResult:
    """Convert a Netraksha ModuleResult to AdapterResult."""
    return AdapterResult(
        available=True,
        success=mr.status == "ok",
        duration_ms=duration_ms,
        score=mr.score,
        status=mr.status,
        raw_output=mr.raw_output if isinstance(mr.raw_output, dict) else {},
        error=mr.raw_output.get("reason") if mr.status == "inconclusive" else None,
    )


class NetrakshaOCRAdapter(OCRAdapter):
    """Wraps pipeline.ocr_mrz.run_ocr_mrz()."""

    name = "NetrakshaOCR"

    def __init__(self, project_root: Optional[Path] = None):
        self._root = project_root
        self._fn = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                if self._root:
                    _add_project_root_to_path(self._root)
                from pipeline.ocr_mrz import run_ocr_mrz  # type: ignore
                self._fn = run_ocr_mrz
                self._available = True
            except Exception:
                self._available = False
        return self._available

    def run(self, image_path: Union[str, Path]) -> AdapterResult:
        if not self.is_available():
            return AdapterResult.unavailable("pipeline.ocr_mrz not importable")
        t0 = time.perf_counter()
        try:
            result = self._fn(str(image_path))
            elapsed = (time.perf_counter() - t0) * 1000
            return _module_result_to_adapter(result, elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AdapterResult.error_result(str(e), elapsed)


class NetrakshaTamperAdapter(TamperDetectionAdapter):
    """Wraps pipeline.tamper.run_tamper()."""

    name = "NetrakshaTamper"

    def __init__(self, project_root: Optional[Path] = None):
        self._root = project_root
        self._fn = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                if self._root:
                    _add_project_root_to_path(self._root)
                from pipeline.tamper import run_tamper  # type: ignore
                self._fn = run_tamper
                self._available = True
            except Exception:
                self._available = False
        return self._available

    def run(self, image_path: Union[str, Path]) -> AdapterResult:
        if not self.is_available():
            return AdapterResult.unavailable("pipeline.tamper not importable")
        t0 = time.perf_counter()
        try:
            result = self._fn(str(image_path), save_evidence=False)
            elapsed = (time.perf_counter() - t0) * 1000
            return _module_result_to_adapter(result, elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AdapterResult.error_result(str(e), elapsed)


class NetrakshaDeepfakeAdapter(DeepfakeAdapter):
    """Wraps pipeline.deepfake.run_deepfake()."""

    name = "NetrakshaDeepfake"

    def __init__(self, project_root: Optional[Path] = None):
        self._root = project_root
        self._fn = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                if self._root:
                    _add_project_root_to_path(self._root)
                from pipeline.deepfake import run_deepfake  # type: ignore
                self._fn = run_deepfake
                self._available = True
            except Exception:
                self._available = False
        return self._available

    def run(self, image_path: Union[str, Path]) -> AdapterResult:
        if not self.is_available():
            return AdapterResult.unavailable("pipeline.deepfake not importable")
        t0 = time.perf_counter()
        try:
            result = self._fn(str(image_path))
            elapsed = (time.perf_counter() - t0) * 1000
            return _module_result_to_adapter(result, elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AdapterResult.error_result(str(e), elapsed)


class NetrakshaFaceAdapter(FaceVerificationAdapter):
    """Wraps pipeline.face_match.run_face_match()."""

    name = "NetrakshaFaceMatch"

    def __init__(self, project_root: Optional[Path] = None):
        self._root = project_root
        self._fn = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                if self._root:
                    _add_project_root_to_path(self._root)
                from pipeline.face_match import run_face_match  # type: ignore
                self._fn = run_face_match
                self._available = True
            except Exception:
                self._available = False
        return self._available

    def run(
        self,
        document_photo: Union[str, Path],
        live_capture: Union[str, Path],
    ) -> AdapterResult:
        if not self.is_available():
            return AdapterResult.unavailable("pipeline.face_match not importable")
        t0 = time.perf_counter()
        try:
            result = self._fn(str(document_photo), str(live_capture), save_evidence=False)
            elapsed = (time.perf_counter() - t0) * 1000
            return _module_result_to_adapter(result, elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AdapterResult.error_result(str(e), elapsed)


class NetrakshaLivenessAdapter(LivenessAdapter):
    """Wraps pipeline.liveness.run_liveness()."""

    name = "NetrakshaLiveness"

    def __init__(self, project_root: Optional[Path] = None):
        self._root = project_root
        self._fn = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                if self._root:
                    _add_project_root_to_path(self._root)
                from pipeline.liveness import run_liveness  # type: ignore
                self._fn = run_liveness
                self._available = True
            except Exception:
                self._available = False
        return self._available

    def run(
        self,
        frame_burst: list,
        challenge_type: str = "blink",
    ) -> AdapterResult:
        if not self.is_available():
            return AdapterResult.unavailable("pipeline.liveness not importable")
        t0 = time.perf_counter()
        try:
            result = self._fn(frame_burst, challenge_type=challenge_type)
            elapsed = (time.perf_counter() - t0) * 1000
            return _module_result_to_adapter(result, elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AdapterResult.error_result(str(e), elapsed)


class NetrakshaPhysicalForgeryAdapter(PhysicalForgeryAdapter):
    """Wraps pipeline.physical_forgery.run_physical_forgery()."""

    name = "NetrakshaPhysicalForgery"

    def __init__(self, project_root: Optional[Path] = None):
        self._root = project_root
        self._fn = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                if self._root:
                    _add_project_root_to_path(self._root)
                from pipeline.physical_forgery import run_physical_forgery  # type: ignore
                self._fn = run_physical_forgery
                self._available = True
            except Exception:
                self._available = False
        return self._available

    def run(self, image_path: Union[str, Path]) -> AdapterResult:
        if not self.is_available():
            return AdapterResult.unavailable("pipeline.physical_forgery not importable")
        t0 = time.perf_counter()
        try:
            result = self._fn(str(image_path))
            elapsed = (time.perf_counter() - t0) * 1000
            return _module_result_to_adapter(result, elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AdapterResult.error_result(str(e), elapsed)


class NetrakshaDocQualityAdapter(DocumentQualityAdapter):
    """Wraps pipeline.document_quality.run_document_quality()."""

    name = "NetrakshaDocQuality"

    def __init__(self, project_root: Optional[Path] = None):
        self._root = project_root
        self._fn = None
        self._available = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                if self._root:
                    _add_project_root_to_path(self._root)
                from pipeline.document_quality import run_document_quality  # type: ignore
                self._fn = run_document_quality
                self._available = True
            except Exception:
                self._available = False
        return self._available

    def run(self, image_path: Union[str, Path]) -> AdapterResult:
        if not self.is_available():
            return AdapterResult.unavailable("pipeline.document_quality not importable")
        t0 = time.perf_counter()
        try:
            result = self._fn(str(image_path), save_evidence=False)
            elapsed = (time.perf_counter() - t0) * 1000
            return _module_result_to_adapter(result, elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return AdapterResult.error_result(str(e), elapsed)


# ---------------------------------------------------------------------------
# Adapter factory
# ---------------------------------------------------------------------------

def build_adapters(cfg: Any) -> Dict[str, BaseAdapter]:
    """Build all adapters from config."""
    root = cfg.project_root if hasattr(cfg, "project_root") else None
    return {
        "ocr": NetrakshaOCRAdapter(project_root=root),
        "tamper": NetrakshaTamperAdapter(project_root=root),
        "deepfake": NetrakshaDeepfakeAdapter(project_root=root),
        "face_match": NetrakshaFaceAdapter(project_root=root),
        "liveness": NetrakshaLivenessAdapter(project_root=root),
        "physical_forgery": NetrakshaPhysicalForgeryAdapter(project_root=root),
        "document_quality": NetrakshaDocQualityAdapter(project_root=root),
    }

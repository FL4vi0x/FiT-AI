"""Typed, READ-only tool layer. Independent of FastAPI, OCTAVE and Ollama."""
from fit_ai.tools.contracts import (
    EXECUTABLE_PERMISSIONS,
    Permission,
    Tool,
    ToolInput,
    ToolOutcome,
    ToolOutput,
    ToolRegistrationError,
    ToolSpec,
)
from fit_ai.tools.registry import ToolRegistry
from fit_ai.tools.vehicle import (
    GetMemoryFacts,
    GetVehicleStatus,
    GetVehicleTelemetry,
    build_vehicle_registry,
)

__all__ = [
    "EXECUTABLE_PERMISSIONS", "GetMemoryFacts", "GetVehicleStatus", "GetVehicleTelemetry", "Permission", "Tool",
    "ToolInput", "ToolOutcome", "ToolOutput", "ToolRegistrationError", "ToolRegistry", "ToolSpec",
    "build_vehicle_registry",
]

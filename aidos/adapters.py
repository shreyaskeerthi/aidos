"""Execution adapters for Nemosys governed runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aidos.execution import BaseAdapter, ExecutionResult, ExecutionTask
from aidos.schemas import Evidence


class _DeterministicAdapter(BaseAdapter):
    """Shared deterministic adapter behavior for MVP."""

    adapter_name = "unknown"

    def execute(self, task: ExecutionTask) -> ExecutionResult:
        return ExecutionResult(
            task_id=task.task_id,
            status="completed",
            output={
                "adapter": self.adapter_name,
                "action": task.action,
                "target": task.payload.get("target"),
                "normalized": True,
            },
            evidence=[
                Evidence(
                    source=f"adapter.{self.adapter_name}",
                    source_type="adapter",
                    source_system="nemosys",
                    parser_or_adapter=self.adapter_name,
                    raw_value=task.model_dump(mode="python"),
                    timestamp=datetime.now(timezone.utc),
                    context={"approval_required": task.approval_required},
                )
            ],
        )


class ApiAdapter(_DeterministicAdapter):
    adapter_name = "api"


class CliAdapter(_DeterministicAdapter):
    adapter_name = "cli"


class AnsibleAdapter(_DeterministicAdapter):
    adapter_name = "ansible"


class McpAdapter(_DeterministicAdapter):
    adapter_name = "mcp"


class PlaywrightAdapter(_DeterministicAdapter):
    adapter_name = "playwright"


class PyatsAdapter(BaseAdapter):
    """pyATS-backed adapter for post-deploy network health checks."""

    adapter_name = "pyats"

    def execute(self, task: ExecutionTask) -> ExecutionResult:
        testbed_path = task.payload.get("pyats_testbed_path")
        commands = task.payload.get("commands") or ["show version"]
        devices = task.payload.get("devices")

        if not testbed_path:
            return self._failed(
                task,
                "pyATS testbed path is required for pyATS execution.",
                {"commands": commands},
            )

        path = Path(str(testbed_path))
        if not path.exists():
            return self._failed(
                task,
                f"pyATS testbed file not found: {path}",
                {"commands": commands},
            )

        try:
            from pyats.topology import loader as pyats_loader
        except ImportError as exc:
            return self._failed(
                task,
                "pyATS is not installed. Install pyats and genie to enable this executor.",
                {"import_error": str(exc), "commands": commands, "testbed_path": str(path)},
            )

        try:
            testbed = pyats_loader.load(str(path))
        except Exception as exc:
            return self._failed(
                task,
                f"Failed to load pyATS testbed: {exc}",
                {"testbed_path": str(path)},
            )

        selected_devices = list(testbed.devices.keys())
        if isinstance(devices, list) and devices:
            selected_devices = [name for name in devices if name in testbed.devices]

        results: dict[str, Any] = {}
        failures: list[dict[str, str]] = []
        successes = 0

        for device_name in selected_devices:
            device = testbed.devices[device_name]
            device_results: dict[str, Any] = {}
            try:
                device.connect(log_stdout=False)
                for command in commands:
                    command_text = str(command)
                    try:
                        parsed = device.parse(command_text)
                        device_results[command_text] = {"mode": "parsed", "result": parsed}
                        successes += 1
                    except Exception as parse_exc:
                        try:
                            raw = device.execute(command_text)
                            device_results[command_text] = {"mode": "raw", "result": raw}
                            successes += 1
                        except Exception as exec_exc:
                            failures.append({"device": device_name, "command": command_text, "error": str(exec_exc)})
                            device_results[command_text] = {
                                "mode": "error",
                                "parse_error": str(parse_exc),
                                "error": str(exec_exc),
                            }
            except Exception as exc:
                failures.append({"device": device_name, "command": "connect", "error": str(exc)})
                device_results["connect"] = {"mode": "error", "error": str(exc)}
            finally:
                try:
                    if getattr(device, "connected", False):
                        device.disconnect()
                except Exception:
                    pass
            results[device_name] = device_results

        status = "completed" if successes > 0 and not failures else "failed"
        if successes > 0 and failures:
            status = "completed_with_warnings"

        return ExecutionResult(
            task_id=task.task_id,
            status=status,
            output={
                "adapter": self.adapter_name,
                "action": task.action,
                "target": task.payload.get("target"),
                "testbed_path": str(path),
                "devices": results,
                "failure_count": len(failures),
                "success_count": successes,
            },
            evidence=[
                Evidence(
                    source="adapter.pyats",
                    source_type="adapter",
                    source_system="nemosys",
                    parser_or_adapter=self.adapter_name,
                    raw_value={
                        "testbed_path": str(path),
                        "devices": selected_devices,
                        "commands": commands,
                        "failures": failures,
                    },
                    timestamp=datetime.now(timezone.utc),
                    context={"approval_required": task.approval_required},
                )
            ],
        )

    def _failed(self, task: ExecutionTask, message: str, detail: dict[str, Any]) -> ExecutionResult:
        return ExecutionResult(
            task_id=task.task_id,
            status="failed",
            output={"adapter": self.adapter_name, "error": message, **detail},
            evidence=[
                Evidence(
                    source="adapter.pyats",
                    source_type="adapter",
                    source_system="nemosys",
                    parser_or_adapter=self.adapter_name,
                    raw_value={"message": message, **detail},
                    timestamp=datetime.now(timezone.utc),
                    context={"task_id": task.task_id},
                )
            ],
        )

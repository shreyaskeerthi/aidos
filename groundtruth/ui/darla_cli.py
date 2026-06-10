"""CLI entrypoint for Darla."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from groundtruth.agents.darla import run_darla, write_outputs
from groundtruth.config.settings import load_settings


def _read_customer_ask(args: argparse.Namespace) -> str:
    if args.ask:
        return args.ask.strip()
    if args.ask_file:
        return Path(args.ask_file).read_text(encoding="utf-8").strip()
    raise ValueError("Provide either --ask or --ask-file.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Darla against the local GroundTruth knowledge base."
    )
    parser.add_argument("--ask", help="Customer ask text to analyze.")
    parser.add_argument(
        "--ask-file",
        help="Path to a text file containing the customer ask.",
    )
    parser.add_argument(
        "--mode",
        choices=["practice", "provisioned"],
        help="Override runtime mode for this invocation.",
    )
    parser.add_argument(
        "--demo-toggle",
        action="store_true",
        help="Run one practice flow and one provisioned flow to show mode switching.",
    )
    return parser


def _print_result_summary(result, outputs: dict[str, Path]) -> None:
    print("DARLA COMMAND CENTER")
    print(f"Objective: {result.objective}")
    print(
        f"Overall readiness: {sum(result.readiness.values()) // len(result.readiness)}/100"
    )
    print(f"Confidence: {result.confidence}/100")
    print(f"Backend mode: {result.backend_mode}")
    print(f"Backend model: {result.backend_model}")
    print(f"Verified: {'yes' if result.verified else 'no'}")
    print("Top evidence sources:")
    for match in result.evidence:
        print(f"  - {match.source} (score {match.score})")
    print("Outputs:")
    print(f"  - JSON: {outputs['json']}")
    print(f"  - Markdown: {outputs['markdown']}")
    print(f"  - HTML: {outputs['html']}")


def _run_single(customer_ask: str, groundtruth_root: Path) -> int:
    result = run_darla(customer_ask, groundtruth_root)
    outputs = write_outputs(result, groundtruth_root / "outputs")
    _print_result_summary(result, outputs)
    return 0


def _run_toggle_demo(customer_ask: str, groundtruth_root: Path) -> int:
    old_mode = os.environ.get("PROVISIONED_MODE")
    old_url = os.environ.get("NIM_BASE_URL")
    old_key = os.environ.get("NIM_API_KEY")

    try:
        print("[1/2] Practice mode demo")
        os.environ["PROVISIONED_MODE"] = "false"
        practice_result = run_darla(customer_ask, groundtruth_root)
        practice_outputs = write_outputs(practice_result, groundtruth_root / "outputs")
        _print_result_summary(practice_result, practice_outputs)

        print("\n[2/2] Provisioned mode demo (expected graceful error if not configured)")
        os.environ["PROVISIONED_MODE"] = "true"
        os.environ.pop("NIM_BASE_URL", None)
        os.environ.pop("NIM_API_KEY", None)
        try:
            run_darla(customer_ask, groundtruth_root)
        except RuntimeError as exc:
            print(f"Provisioned-mode guardrail: {exc}")
        return 0
    finally:
        if old_mode is None:
            os.environ.pop("PROVISIONED_MODE", None)
        else:
            os.environ["PROVISIONED_MODE"] = old_mode

        if old_url is None:
            os.environ.pop("NIM_BASE_URL", None)
        else:
            os.environ["NIM_BASE_URL"] = old_url

        if old_key is None:
            os.environ.pop("NIM_API_KEY", None)
        else:
            os.environ["NIM_API_KEY"] = old_key


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    customer_ask = _read_customer_ask(args)

    if args.mode == "practice":
        os.environ["PROVISIONED_MODE"] = "false"
    elif args.mode == "provisioned":
        os.environ["PROVISIONED_MODE"] = "true"

    settings = load_settings()

    groundtruth_root = REPO_ROOT / "groundtruth"
    if args.demo_toggle:
        return _run_toggle_demo(customer_ask, groundtruth_root)

    if settings.provisioned_mode:
        print("Running in provisioned mode")
    else:
        print("Running in practice mode")

    return _run_single(customer_ask, groundtruth_root)


if __name__ == "__main__":
    raise SystemExit(main())
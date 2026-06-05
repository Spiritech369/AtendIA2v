from __future__ import annotations

import argparse
import asyncio
import json

from atendia.eval_lab.fixtures import FixtureAgentProvider, all_fixture_scenarios
from atendia.eval_lab.scenario_runner import ScenarioRunner


async def _run(args: argparse.Namespace) -> int:
    scenarios = all_fixture_scenarios(include_blueprints=args.include_blueprints)
    runner = ScenarioRunner(provider=FixtureAgentProvider())
    result = await runner.run(scenarios)
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(
            f"Eval Lab v1: {result.passed_count}/{result.total} passed "
            f"({result.failed_count} failed)"
        )
        for scenario_result in result.results:
            marker = "PASS" if scenario_result.passed else "FAIL"
            print(f"{marker} {scenario_result.scenario_id}: {scenario_result.name}")
            for score in scenario_result.scores:
                if not score.passed:
                    print(f"  - {score.scorer}: {score.message}")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as file:
            json.dump(result.model_dump(mode="json"), file, ensure_ascii=False, indent=2)
    return 0 if result.passed or args.allow_failures else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AgentRuntime v2 eval scenarios.")
    parser.add_argument("--include-blueprints", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()

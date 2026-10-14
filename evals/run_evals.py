"""Run the multi-agent investigator against 20 injected incidents and score it.

Scores per case: root-cause service, fault category, remediation action (all
exact-match against ground truth), plus latency, tokens and cost. Writes
evals/results/<timestamp>.json and prints a markdown table.

    python evals/run_evals.py                 # all 20 cases
    python evals/run_evals.py --limit 5 --concurrency 3
    python evals/run_evals.py --no-critic     # ablation: skip reflection
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

from voxa.agents.orchestrator import Orchestrator
from voxa.llm import ClaudeLLM
from voxa.memory import IncidentMemory
from voxa.observability import Tracer
from voxa.rag import KnowledgeBase
from voxa.sim import SCENARIOS, Scenario

RESULTS = Path(__file__).resolve().parent / "results"
ACTION_OF_TOOL = {"rollback_deploy": "rollback", "restart_service": "restart",
                  "scale_service": "scale", "set_config": "set_config", "escalate": "escalate"}

# Each fault type moved across services so the agent can't memorise one answer.
VARIANTS = {
    "bad_deploy_checkout": ["checkout", "payments", "inventory", "recommendations"],
    "memory_leak_payments": ["payments", "inventory", "recommendations", "checkout"],
    "config_error_recommendations": ["recommendations", "checkout", "inventory", "payments"],
    "traffic_spike_checkout": ["checkout", "inventory", "payments", "recommendations"],
    "dependency_outage_payments": ["payments", "inventory", "recommendations", "checkout"],
}


def cases() -> list[Scenario]:
    out = []
    for name, services in VARIANTS.items():
        base = SCENARIOS[name]
        for svc in services:
            alert = dict(base.alert)
            # Keep the alert on the original symptom service unless it was the root itself.
            if alert["service"] == base.root_service:
                alert["service"] = svc
                alert["summary"] = alert["summary"].replace(base.root_service, svc)
            out.append(replace(base, name=f"{base.category}:{svc}", root_service=svc,
                               alert=alert))
    return out


async def run_case(scenario: Scenario, kb: KnowledgeBase, critic: bool, sem) -> dict:
    async with sem:
        tracer = Tracer()
        orch = Orchestrator(ClaudeLLM(tracer), scenario.build(), kb, IncidentMemory(), tracer,
                            max_revisions=1 if critic else 0)
        start = time.perf_counter()
        try:
            inv = await orch.investigate(scenario.alert)
        except Exception as exc:  # noqa: BLE001 - record and keep going
            return {"case": scenario.name, "error": f"{type(exc).__name__}: {exc}"}
        d = inv.diagnosis
        return {
            "case": scenario.name,
            "service_ok": d.root_cause_service == scenario.root_service,
            "category_ok": d.category == scenario.category,
            "action_ok": ACTION_OF_TOOL[d.action.tool] == scenario.action,
            "predicted": f"{d.root_cause_service}/{d.category}/{d.action.tool}",
            "expected": f"{scenario.root_service}/{scenario.category}/{scenario.action}",
            "confidence": d.confidence,
            "critic_rejections": sum(not c.approved for c in inv.critiques),
            "seconds": round(time.perf_counter() - start, 1),
            **tracer.summary(),
        }


def report(rows: list[dict]) -> str:
    ok = [r for r in rows if "error" not in r]
    n = len(rows)

    def pct(key):
        return f"{100 * sum(r[key] for r in ok) / n:.0f}%"

    full = sum(r["service_ok"] and r["category_ok"] and r["action_ok"] for r in ok)
    lines = [
        "| cases | root cause | category | action | all three | avg s | avg $ |",
        "|---|---|---|---|---|---|---|",
        (f"| {n} | {pct('service_ok')} | {pct('category_ok')} | {pct('action_ok')} | "
        f"{100 * full / n:.0f}% | {sum(r['seconds'] for r in ok) / max(len(ok), 1):.1f} | "
        f"{sum(r['cost_usd'] for r in ok) / max(len(ok), 1):.3f} |"),
        "",
        "| case | expected | predicted | ok |",
        "|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['case']} | | ERROR {r['error'][:60]} | ✗ |")
        else:
            good = r["service_ok"] and r["category_ok"] and r["action_ok"]
            lines.append(f"| {r['case']} | {r['expected']} | {r['predicted']} | "
                         f"{'✓' if good else '✗'} |")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-critic", action="store_true")
    args = parser.parse_args()

    selected = cases()[: args.limit]
    kb, sem = KnowledgeBase.from_dir(), asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(*(run_case(c, kb, not args.no_critic, sem) for c in selected))

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}{'-nocritic' if args.no_critic else ''}.json"
    out.write_text(json.dumps(rows, indent=2))
    print(report(rows))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    asyncio.run(main())

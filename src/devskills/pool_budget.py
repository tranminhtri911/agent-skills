"""Database connection budget at deployment peak (POOL-003, plan §14.4).

Total connections = sum over every process of (pool_size + max_overflow)
                    + admin/migration/batch connections + operational reserve,
computed for the peak replica count during rolling deploys, not the steady state.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import asdict, dataclass

from devskills.fsutil import resolve_repo_root, utc_now_iso
from devskills.models import EXEC_COMPLETED, GATE_FAIL, GATE_PASS, GATE_WARN, CheckResult, Finding, UsageError
from devskills.output import emit_result, format_findings

HEADROOM_WARNING_RATIO = 0.8


@dataclass
class ProcessGroup:
    name: str
    replicas: int
    processes_per_replica: int
    pool_size: int
    max_overflow: int
    peak_replicas: int = 0

    @property
    def connections_per_process(self) -> int:
        return self.pool_size + self.max_overflow

    @property
    def steady_connections(self) -> int:
        return self.replicas * self.processes_per_replica * self.connections_per_process

    @property
    def peak_connections(self) -> int:
        return self.peak_replicas * self.processes_per_replica * self.connections_per_process


def parse_group(spec: str) -> ProcessGroup:
    """Parse NAME:REPLICAS:PROCS:POOL:OVERFLOW, e.g. web:3:2:5:1."""
    parts = spec.split(":")
    if len(parts) != 5:
        raise UsageError(f"--group {spec!r}: expected NAME:REPLICAS:PROCS:POOL:OVERFLOW")
    name, *numbers = parts
    try:
        replicas, processes, pool_size, overflow = (int(value) for value in numbers)
    except ValueError as error:
        raise UsageError(f"--group {spec!r}: numbers expected") from error
    if min(replicas, processes, pool_size, overflow) < 0 or not name:
        raise UsageError(f"--group {spec!r}: values must be non-negative and the name non-empty")
    return ProcessGroup(name, replicas, processes, pool_size, overflow)


def compute_budget(groups: list[ProcessGroup], surge_percent: float, explicit_peaks: dict[str, int],
                   other_connections: int, reserve: int, database_max: int) -> dict:
    """Steady and peak connection totals per process group, plus other tools and the reserve."""
    for group in groups:
        surge_replicas = math.ceil(group.replicas * (1 + surge_percent / 100.0))
        group.peak_replicas = explicit_peaks.get(group.name, surge_replicas)
    steady_total = sum(group.steady_connections for group in groups) + other_connections + reserve
    peak_total = sum(group.peak_connections for group in groups) + other_connections + reserve
    return {
        "groups": [asdict(group) | {"steady_connections": group.steady_connections, "peak_connections": group.peak_connections}
                   for group in groups],
        "other_connections": other_connections,
        "reserve": reserve,
        "steady_total": steady_total,
        "peak_total": peak_total,
        "database_max": database_max,
        "headroom_at_peak": database_max - peak_total,
    }


def run(args: argparse.Namespace) -> int:
    """CLI handler for `pool-budget`: fail when the peak exceeds the database budget, warn above 80%."""
    repo_root = resolve_repo_root(args.repo)
    started_at = utc_now_iso()
    groups = [parse_group(spec) for spec in args.group]
    explicit_peaks: dict[str, int] = {}
    for item in args.peak:
        name, _, value = item.partition("=")
        if not value.isdigit():
            raise UsageError(f"--peak {item!r}: expected NAME=REPLICAS")
        explicit_peaks[name] = int(value)
    budget = compute_budget(groups, args.surge_percent, explicit_peaks, args.other, args.reserve, args.db_max)

    findings: list[Finding] = []
    if budget["peak_total"] > args.db_max:
        findings.append(Finding("POOL-003-OVER-BUDGET", "high",
                                f"peak {budget['peak_total']} connections exceed the database budget {args.db_max}",
                                hint="Lower pool/overflow, limit rollout surge or worker count, or add a pooler (PgBouncer/RDS Proxy)."))
        gate = GATE_FAIL
    elif budget["peak_total"] > args.db_max * HEADROOM_WARNING_RATIO:
        findings.append(Finding("POOL-003-LOW-HEADROOM", "medium",
                                f"peak {budget['peak_total']} uses over {int(HEADROOM_WARNING_RATIO * 100)}% of {args.db_max}",
                                hint="Keep room for incident response and migrations."))
        gate = GATE_WARN
    else:
        gate = GATE_PASS
    result = CheckResult(
        check_id=getattr(args, "check_id", "perf.pool_budget"),
        tool="devskills.pool-budget",
        execution_status=EXEC_COMPLETED,
        gate_result=gate,
        domain_result="over_budget" if gate == GATE_FAIL else "within_budget",
        summary=f"steady {budget['steady_total']}, peak {budget['peak_total']} of {args.db_max} connections",
        findings=findings,
        details=budget,
        started_at=started_at,
    )
    lines = ["pool-budget:"]
    for group in budget["groups"]:
        lines.append(
            f"  {group['name']}: {group['replicas']}→{group['peak_replicas']} replicas × {group['processes_per_replica']} proc × "
            f"({group['pool_size']}+{group['max_overflow']}) = {group['steady_connections']} steady / {group['peak_connections']} peak"
        )
    lines.append(f"  other {args.other} + reserve {args.reserve}; peak total {budget['peak_total']} vs max {args.db_max}")
    lines.extend(format_findings(findings))
    return emit_result(args, repo_root, result, lines)

from dataclasses import dataclass
from typing import Callable

from app.models import Activity, ActivityRole, Process, Role


@dataclass
class DefectResult:
    rule_id: str
    severity: str
    message: str
    process_id: int | None = None
    activity_id: int | None = None
    role_id: int | None = None
    dimension_id: int | None = None
    suggested_fix: str | None = None


def _letters(cell: str) -> set[str]:
    return {c.upper() for c in cell if c.upper() in {"R", "A", "C", "I"}}


def _assignments_for(
    activity: Activity, dimension_id: int, by_activity: dict[int, list[ActivityRole]]
) -> list[ActivityRole]:
    return [a for a in by_activity.get(activity.id, []) if a.dimension_id == dimension_id]


def rule_d001(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    out = []
    for act in activities:
        for dim in dimensions:
            assigns = _assignments_for(act, dim.id, by_activity)
            if not any("A" in _letters(a.raci_letters) for a in assigns):
                out.append(
                    DefectResult(
                        "D-001",
                        "Critical",
                        f"No Accountable for '{act.name}' ({dim.name})",
                        process.id,
                        act.id,
                        dimension_id=dim.id,
                        suggested_fix="Assign exactly one Accountable (A).",
                    )
                )
    return out


def rule_d002(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    out = []
    for act in activities:
        for dim in dimensions:
            count = sum(1 for a in _assignments_for(act, dim.id, by_activity) if "A" in _letters(a.raci_letters))
            if count > 1:
                out.append(
                    DefectResult(
                        "D-002",
                        "High",
                        f"Multiple Accountables ({count}) for '{act.name}' ({dim.name})",
                        process.id,
                        act.id,
                        dimension_id=dim.id,
                    )
                )
    return out


def rule_d003(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    out = []
    for act in activities:
        for dim in dimensions:
            assigns = _assignments_for(act, dim.id, by_activity)
            if not any("R" in _letters(a.raci_letters) for a in assigns):
                out.append(
                    DefectResult(
                        "D-003",
                        "Critical",
                        f"No Responsible for '{act.name}' ({dim.name})",
                        process.id,
                        act.id,
                        dimension_id=dim.id,
                    )
                )
    return out


def rule_d004(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    threshold: float = 0.30,
    **kwargs,
) -> list[DefectResult]:
    if not activities:
        return []
    total = len(activities) * max(len(dimensions), 1)
    out = []
    for role in roles:
        r_count = 0
        for act in activities:
            for dim in dimensions:
                for a in _assignments_for(act, dim.id, by_activity):
                    if a.role_id == role.id and "R" in _letters(a.raci_letters):
                        r_count += 1
        if total and r_count / total > threshold:
            out.append(
                DefectResult(
                    "D-004",
                    "High",
                    f"Role overload: '{role.name}' is Responsible on {r_count} assignments (>{threshold:.0%})",
                    process.id,
                    role_id=role.id,
                )
            )
    return out


def rule_d005(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    used = {a.role_id for acts in by_activity.values() for a in acts if a.raci_letters.strip()}
    out = []
    for role in roles:
        if role.id not in used:
            out.append(
                DefectResult(
                    "D-005",
                    "Low",
                    f"Role idle: '{role.name}' not used in this process",
                    process.id,
                    role_id=role.id,
                )
            )
    return out


def rule_d006(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    outputs = {act.outputs.strip().lower() for act in activities if act.outputs}
    consumed = set()
    for act in activities:
        if act.inputs:
            for part in act.inputs.split(","):
                consumed.add(part.strip().lower())
    out = []
    for act in activities:
        if act.outputs and act.outputs.strip().lower() not in consumed:
            out.append(
                DefectResult(
                    "D-006",
                    "High",
                    f"Missing hand-off: output of '{act.name}' not consumed by a successor",
                    process.id,
                    act.id,
                )
            )
    return out


def rule_d007(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    out = []
    for act in activities:
        if not act.is_start and not act.predecessors:
            out.append(
                DefectResult(
                    "D-007",
                    "Medium",
                    f"Orphan activity: '{act.name}' has no predecessor",
                    process.id,
                    act.id,
                )
            )
    return out


def rule_d008(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    graph: dict[int, list[int]] = {a.id: [] for a in activities}
    id_set = {a.id for a in activities}
    for act in activities:
        if act.predecessors:
            for pid in act.predecessors.split(","):
                pid = pid.strip()
                if pid.isdigit() and int(pid) in id_set:
                    graph[act.id].append(int(pid))

    visited: set[int] = set()
    stack: set[int] = set()
    cycles: list[list[int]] = []

    def dfs(node: int, path: list[int]) -> None:
        visited.add(node)
        stack.add(node)
        path.append(node)
        for nbr in graph.get(node, []):
            if nbr not in visited:
                dfs(nbr, path.copy())
            elif nbr in stack:
                cycles.append(path + [nbr])
        stack.remove(node)

    for act in activities:
        if act.id not in visited:
            dfs(act.id, [])

    out = []
    for cycle in cycles:
        names = ", ".join(str(n) for n in cycle)
        out.append(
            DefectResult(
                "D-008",
                "Critical",
                f"Circular dependency detected: {names}",
                process.id,
            )
        )
    return out


def rule_d009(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    out = []
    for role in roles:
        c_only = 0
        total = 0
        for act in activities:
            for dim in dimensions:
                for a in _assignments_for(act, dim.id, by_activity):
                    if a.role_id != role.id:
                        continue
                    letters = _letters(a.raci_letters)
                    if not letters:
                        continue
                    total += 1
                    if letters == {"C"}:
                        c_only += 1
        if total and c_only / total > 0.5:
            out.append(
                DefectResult(
                    "D-009",
                    "Medium",
                    f"'{role.name}' is Consulted-only on >50% of assignments — may need Accountable",
                    process.id,
                    role_id=role.id,
                )
            )
    return out


def rule_d010(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    hris_role_ids: set[int] | None = None,
    **kwargs,
) -> list[DefectResult]:
    hris = hris_role_ids or {r.id for r in roles if r.hris_external_id}
    out = []
    seen_roles: set[int] = set()
    for acts in by_activity.values():
        for a in acts:
            if a.role_id in seen_roles:
                continue
            seen_roles.add(a.role_id)
            if a.raci_letters.strip() and a.role_id not in hris:
                role = next((r for r in roles if r.id == a.role_id), None)
                if role:
                    out.append(
                        DefectResult(
                            "D-010",
                            "High",
                            f"RACI/Org mismatch: '{role.name}' not registered in HRIS",
                            process.id,
                            role_id=role.id,
                        )
                    )
    return out


def rule_d011(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    allow_r_equals_a: bool = True,
    **kwargs,
) -> list[DefectResult]:
    if allow_r_equals_a:
        return []
    out = []
    for act in activities:
        for dim in dimensions:
            for a in _assignments_for(act, dim.id, by_activity):
                letters = _letters(a.raci_letters)
                if "R" in letters and "A" in letters:
                    out.append(
                        DefectResult(
                            "D-011",
                            "Low",
                            f"Same role R and A on '{act.name}' ({dim.name})",
                            process.id,
                            act.id,
                            a.role_id,
                            dim.id,
                        )
                    )
    return out


def rule_d012(
    process: Process,
    activities: list[Activity],
    roles: list[Role],
    dimensions: list,
    by_activity: dict[int, list[ActivityRole]],
    **kwargs,
) -> list[DefectResult]:
    out = []
    for act in activities:
        if not act.sla or not act.frequency:
            out.append(
                DefectResult(
                    "D-012",
                    "Medium",
                    f"SLA gap: '{act.name}' missing SLA or frequency",
                    process.id,
                    act.id,
                )
            )
    return out


RULES: list[tuple[str, Callable[..., list[DefectResult]]]] = [
    ("D-001", rule_d001),
    ("D-002", rule_d002),
    ("D-003", rule_d003),
    ("D-004", rule_d004),
    ("D-005", rule_d005),
    ("D-006", rule_d006),
    ("D-007", rule_d007),
    ("D-008", rule_d008),
    ("D-009", rule_d009),
    ("D-010", rule_d010),
    ("D-011", rule_d011),
    ("D-012", rule_d012),
]

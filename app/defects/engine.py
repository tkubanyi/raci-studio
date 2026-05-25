from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Activity, Process, Role


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


RULE_SEVERITY = {
    "D-001": Severity.CRITICAL,
    "D-002": Severity.HIGH,
    "D-003": Severity.CRITICAL,
    "D-004": Severity.HIGH,
    "D-005": Severity.LOW,
    "D-006": Severity.HIGH,
    "D-007": Severity.MEDIUM,
    "D-008": Severity.CRITICAL,
    "D-009": Severity.MEDIUM,
    "D-010": Severity.HIGH,
    "D-011": Severity.LOW,
    "D-012": Severity.MEDIUM,
}


@dataclass
class Defect:
    rule_id: str
    severity: Severity
    message: str
    process_id: int | None = None
    process_name: str | None = None
    activity_id: int | None = None
    activity_name: str | None = None
    role_id: int | None = None
    role_name: str | None = None
    dimension_slug: str | None = None


def _letters_for_activity(activity: Activity, dimension_id: int) -> dict[int, str]:
    result: dict[int, str] = {}
    for ar in activity.assignments:
        if ar.dimension_id == dimension_id:
            result[ar.role_id] = (ar.letters or "").upper()
    return result


def _has_letter(letters: str, letter: str) -> bool:
    return letter in letters.replace("/", "").replace(" ", "")


class DefectEngine:
    def __init__(self, role_overload_threshold: float = 0.30, allow_r_equals_a: bool = True):
        self.role_overload_threshold = role_overload_threshold
        self.allow_r_equals_a = allow_r_equals_a

    def scan_process(
        self,
        process: Process,
        roles: list[Role],
        dimension_id: int,
        dimension_slug: str,
    ) -> list[Defect]:
        defects: list[Defect] = []
        activities = sorted(process.activities, key=lambda a: a.sequence)
        n_activities = max(len(activities), 1)
        role_r_counts: dict[int, int] = {r.id: 0 for r in roles}
        roles_in_matrix: set[int] = set()

        for activity in activities:
            by_role = _letters_for_activity(activity, dimension_id)
            accountable = [rid for rid, L in by_role.items() if _has_letter(L, "A")]
            responsible = [rid for rid, L in by_role.items() if _has_letter(L, "R")]

            for rid in by_role:
                roles_in_matrix.add(rid)
                if _has_letter(by_role[rid], "R"):
                    role_r_counts[rid] = role_r_counts.get(rid, 0) + 1

            if not accountable:
                defects.append(
                    Defect(
                        "D-001",
                        RULE_SEVERITY["D-001"],
                        f"No Accountable (A) assigned for activity '{activity.name}'.",
                        process.id,
                        process.name,
                        activity.id,
                        activity.name,
                        dimension_slug=dimension_slug,
                    )
                )
            if len(accountable) > 1:
                names = ", ".join(self._role_name(roles, rid) for rid in accountable)
                defects.append(
                    Defect(
                        "D-002",
                        RULE_SEVERITY["D-002"],
                        f"Multiple Accountables on '{activity.name}': {names}.",
                        process.id,
                        process.name,
                        activity.id,
                        activity.name,
                        dimension_slug=dimension_slug,
                    )
                )
            if not responsible:
                defects.append(
                    Defect(
                        "D-003",
                        RULE_SEVERITY["D-003"],
                        f"No Responsible (R) assigned for activity '{activity.name}'.",
                        process.id,
                        process.name,
                        activity.id,
                        activity.name,
                        dimension_slug=dimension_slug,
                    )
                )

            if not self.allow_r_equals_a:
                for rid, letters in by_role.items():
                    if _has_letter(letters, "R") and _has_letter(letters, "A"):
                        defects.append(
                            Defect(
                                "D-011",
                                RULE_SEVERITY["D-011"],
                                f"Role '{self._role_name(roles, rid)}' is both R and A on '{activity.name}'.",
                                process.id,
                                process.name,
                                activity.id,
                                activity.name,
                                rid,
                                self._role_name(roles, rid),
                                dimension_slug,
                            )
                        )

            if not activity.sla or not activity.frequency:
                defects.append(
                    Defect(
                        "D-012",
                        RULE_SEVERITY["D-012"],
                        f"Activity '{activity.name}' is missing SLA or frequency metadata.",
                        process.id,
                        process.name,
                        activity.id,
                        activity.name,
                        dimension_slug=dimension_slug,
                    )
                )

            if not activity.is_start and not activity.predecessor_ids:
                defects.append(
                    Defect(
                        "D-007",
                        RULE_SEVERITY["D-007"],
                        f"Orphan activity '{activity.name}' has no predecessor and is not marked as start.",
                        process.id,
                        process.name,
                        activity.id,
                        activity.name,
                        dimension_slug=dimension_slug,
                    )
                )

            if activity.outputs:
                consumed = False
                for other in activities:
                    if other.id != activity.id and other.inputs and activity.outputs in (other.inputs or ""):
                        consumed = True
                        break
                if not consumed and activity.sequence < max(a.sequence for a in activities):
                    defects.append(
                        Defect(
                            "D-006",
                            RULE_SEVERITY["D-006"],
                            f"Output of '{activity.name}' may not be consumed by a successor hand-off.",
                            process.id,
                            process.name,
                            activity.id,
                            activity.name,
                            dimension_slug=dimension_slug,
                        )
                    )

            consulted_heavy = sum(1 for L in by_role.values() if _has_letter(L, "C") and not _has_letter(L, "A"))
            if consulted_heavy > 0 and not accountable:
                pass
            for rid, letters in by_role.items():
                if not self._role_in_hris(roles, rid):
                    defects.append(
                        Defect(
                            "D-010",
                            RULE_SEVERITY["D-010"],
                            f"Role '{self._role_name(roles, rid)}' in RACI is not registered in HRIS.",
                            process.id,
                            process.name,
                            activity.id,
                            activity.name,
                            rid,
                            self._role_name(roles, rid),
                            dimension_slug,
                        )
                    )

        cycle = self._detect_cycle(activities)
        if cycle:
            defects.append(
                Defect(
                    "D-008",
                    RULE_SEVERITY["D-008"],
                    f"Circular dependency detected in process '{process.name}': {' → '.join(cycle)}.",
                    process.id,
                    process.name,
                    dimension_slug=dimension_slug,
                )
            )

        for role in roles:
            if role.id not in roles_in_matrix:
                defects.append(
                    Defect(
                        "D-005",
                        RULE_SEVERITY["D-005"],
                        f"Role '{role.name}' is defined but not used in this process RACI.",
                        process.id,
                        process.name,
                        role_id=role.id,
                        role_name=role.name,
                        dimension_slug=dimension_slug,
                    )
                )

        consulted_only_reported: set[int] = set()
        for role in roles:
            c_count = sum(
                1
                for a in activities
                for L in _letters_for_activity(a, dimension_id).get(role.id, "")
                if _has_letter(L, "C")
            )
            a_count = sum(
                1
                for a in activities
                for L in _letters_for_activity(a, dimension_id).get(role.id, "")
                if _has_letter(L, "A")
            )
            if c_count >= max(3, int(n_activities * 0.5)) and a_count == 0 and role.id not in consulted_only_reported:
                consulted_only_reported.add(role.id)
                defects.append(
                    Defect(
                        "D-009",
                        RULE_SEVERITY["D-009"],
                        f"Role '{role.name}' is Consulted on {c_count} activities but never Accountable.",
                        process.id,
                        process.name,
                        role_id=role.id,
                        role_name=role.name,
                        dimension_slug=dimension_slug,
                    )
                )

        for role in roles:
            count = role_r_counts.get(role.id, 0)
            if count / n_activities > self.role_overload_threshold:
                defects.append(
                    Defect(
                        "D-004",
                        RULE_SEVERITY["D-004"],
                        f"Role '{role.name}' is Responsible on {count}/{n_activities} activities (>{int(self.role_overload_threshold*100)}% threshold).",
                        process.id,
                        process.name,
                        role_id=role.id,
                        role_name=role.name,
                        dimension_slug=dimension_slug,
                    )
                )

        return defects

    def scan_workspace(
        self,
        processes: list[Process],
        roles: list[Role],
        dimensions: list,
    ) -> list[Defect]:
        all_defects: list[Defect] = []
        for process in processes:
            for dim in dimensions:
                all_defects.extend(self.scan_process(process, roles, dim.id, dim.slug))
        return all_defects

    @staticmethod
    def _role_name(roles: list[Role], role_id: int) -> str:
        for r in roles:
            if r.id == role_id:
                return r.name
        return f"Role#{role_id}"

    @staticmethod
    def _role_in_hris(roles: list[Role], role_id: int) -> bool:
        for r in roles:
            if r.id == role_id:
                return r.in_hris
        return True

    @staticmethod
    def _detect_cycle(activities: list[Activity]) -> list[str] | None:
        id_to_name = {a.id: a.name for a in activities}
        graph: dict[int, list[int]] = {a.id: [] for a in activities}
        for a in activities:
            if a.predecessor_ids:
                for pred in a.predecessor_ids.split(","):
                    pred = pred.strip()
                    if pred.isdigit():
                        graph[int(pred)].append(a.id)

        visited: set[int] = set()
        stack: set[int] = set()
        path: list[int] = []

        def dfs(node: int) -> list[str] | None:
            visited.add(node)
            stack.add(node)
            path.append(node)
            for nei in graph.get(node, []):
                if nei not in visited:
                    result = dfs(nei)
                    if result:
                        return result
                elif nei in stack:
                    idx = path.index(nei)
                    return [id_to_name[i] for i in path[idx:]] + [id_to_name[nei]]
            path.pop()
            stack.remove(node)
            return None

        for a in activities:
            if a.id not in visited:
                cycle = dfs(a.id)
                if cycle:
                    return cycle
        return None

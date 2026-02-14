"""Status report generator for goal-oriented task management.

Generates structured status reports from the goal/plan/todo hierarchy,
suitable for transformation into prose reports for stakeholders.

Usage:
    from core.status_report import StatusReportGenerator
    from config import get_config_async

    config = await get_config_async()
    generator = StatusReportGenerator()

    # Generate structured data
    report_data = await generator.generate()

    # Generate executive summary using LLM
    report_data = await generator.generate_summary(report_data, runner)

    # Write to file
    output_path = await generator.write_report(report_data, config)
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Protocol

import aiofiles

from core.async_storage import GoalStorage, get_goal_storage
from core.debug_log import debug_log
from core.stream_state import get_stream_state, StreamType
from storage_schema import GoalData, PlanData, TodoData

if TYPE_CHECKING:
    from config import Config
    from models import Message


# Load reporting role prompt from file
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts" / "shared" / "roles"
_REPORTING_PROMPT_PATH = _PROMPTS_DIR / "reporting.md"


def _load_reporting_prompt() -> str:
    """Load the reporting role prompt from file."""
    try:
        return _REPORTING_PROMPT_PATH.read_text()
    except Exception:
        return ""


_REPORTING_PROMPT = _load_reporting_prompt()


class StreamingRunner(Protocol):
    """Protocol for runners that can stream responses."""

    async def stream_response(
        self,
        messages: list["Message"],
        prompt: str,
        disable_tools: bool = False,
    ):
        """Stream a response from the LLM."""
        ...


@dataclass
class TodoStatus:
    """Status information for a single todo."""
    id: str
    title: str
    status: str  # "pending", "in_progress", "completed", "blocked", "abandoned"
    is_spike: bool
    plan_titles: list[str]  # Parent plan titles
    blocker_titles: list[str]  # Titles of todos this is blocked by
    completed_at: Optional[str] = None


@dataclass
class PlanStatus:
    """Status information for a single plan."""
    id: str
    title: str
    status: str  # "draft", "active", "completed", "abandoned"
    goal_title: str
    todo_count: int
    completed_count: int
    in_progress_count: int
    blocked_count: int
    pending_count: int
    completion_pct: float


@dataclass
class GoalStatus:
    """Status information for a single goal."""
    id: str
    title: str
    weight: int
    status: str  # "active", "completed", "superseded", "abandoned"
    plan_count: int
    active_plan_count: int
    total_todos: int
    completed_todos: int
    in_progress_todos: int
    blocked_todos: int
    completion_pct: float
    acceptance_criteria: list[str]


@dataclass
class StatusReportData:
    """Structured status report data.

    Contains all information needed to generate a human-readable
    status report. Designed to be transformed into prose by the
    reporting role.
    """
    generated_at: str  # ISO 8601 timestamp

    # Summary statistics
    total_goals: int
    active_goals: int
    completed_goals: int

    total_plans: int
    active_plans: int
    completed_plans: int

    total_todos: int
    completed_todos: int
    in_progress_todos: int
    blocked_todos: int
    pending_todos: int

    # Overall completion percentage
    overall_completion_pct: float

    # LLM-generated executive summary (prose description for stakeholders)
    summary: Optional[str] = None

    # Detailed breakdowns
    goals: list[GoalStatus] = field(default_factory=list)
    plans: list[PlanStatus] = field(default_factory=list)

    # Highlighted items for executive summary
    in_progress_items: list[TodoStatus] = field(default_factory=list)
    blocked_items: list[TodoStatus] = field(default_factory=list)
    recently_completed: list[TodoStatus] = field(default_factory=list)

    # Spikes (timeboxed exploration) listed separately
    active_spikes: list[TodoStatus] = field(default_factory=list)


class StatusReportGenerator:
    """Generates status reports from the goal/plan/todo hierarchy.

    Traverses the goal storage to collect status information and
    returns structured data suitable for transformation into prose.
    """

    def __init__(self, storage: Optional[GoalStorage] = None):
        """Initialize the generator.

        Args:
            storage: GoalStorage instance. If not provided, uses the
                     default singleton from get_goal_storage().
        """
        self._storage = storage

    async def _get_storage(self) -> GoalStorage:
        """Get the storage instance, initializing if needed."""
        if self._storage is None:
            self._storage = await get_goal_storage()
        return self._storage

    async def generate(
        self,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> StatusReportData:
        """Generate a status report from current goal/plan/todo state.

        Args:
            scope_type: Optional scope filter - "goal" or "plan".
                        If None, generates report for all goals/plans.
            scope_id: ID of the goal or plan to scope the report to.
                      Required if scope_type is set.

        Returns:
            StatusReportData with all status information.
        """
        storage = await self._get_storage()

        # Load all data (we'll filter below if scoped)
        all_goals = await storage.list_goals()
        all_plans = await storage.list_plans()
        all_todos = await storage.list_todos(include_spikes=True)

        # Apply scope filtering
        if scope_type == "goal" and scope_id:
            # Find the matching goal (support prefix match)
            target_goal = None
            for g in all_goals:
                if g.id == scope_id or g.id.startswith(scope_id):
                    target_goal = g
                    break

            if target_goal:
                goals = [target_goal]
                plans = [p for p in all_plans if p.goal_id == target_goal.id]
                plan_ids = {p.id for p in plans}
                # Get todos for these plans
                todos = []
                for todo in all_todos:
                    todo_plan_ids = await storage.get_plans_for_todo(todo.id)
                    if any(pid in plan_ids for pid in todo_plan_ids):
                        todos.append(todo)
            else:
                # Goal not found - generate empty report
                goals, plans, todos = [], [], []

        elif scope_type == "plan" and scope_id:
            # Find the matching plan (support prefix match)
            target_plan = None
            for p in all_plans:
                if p.id == scope_id or p.id.startswith(scope_id):
                    target_plan = p
                    break

            if target_plan:
                plans = [target_plan]
                # Include the parent goal for context
                goals = [g for g in all_goals if g.id == target_plan.goal_id]
                # Get todos for this plan
                todos = []
                for todo in all_todos:
                    todo_plan_ids = await storage.get_plans_for_todo(todo.id)
                    if target_plan.id in todo_plan_ids:
                        todos.append(todo)
            else:
                # Plan not found - generate empty report
                goals, plans, todos = [], [], []
        else:
            # No scope - use all data
            goals = all_goals
            plans = all_plans
            todos = all_todos

        # Build lookup maps
        goal_map: dict[str, GoalData] = {g.id: g for g in goals}
        plan_map: dict[str, PlanData] = {p.id: p for p in plans}
        todo_map: dict[str, TodoData] = {t.id: t for t in todos}

        # Build plan -> todos mapping
        plan_todos: dict[str, list[str]] = {p.id: [] for p in plans}
        todo_plans: dict[str, list[str]] = {t.id: [] for t in todos}

        for todo in todos:
            plan_ids = await storage.get_plans_for_todo(todo.id)
            todo_plans[todo.id] = plan_ids
            for plan_id in plan_ids:
                if plan_id in plan_todos:
                    plan_todos[plan_id].append(todo.id)

        # Build dependency map for blockers
        todo_blockers: dict[str, list[str]] = {}
        for todo in todos:
            deps = await storage.get_dependencies(todo.id)
            # A todo is blocked if it depends on incomplete todos
            blockers = [
                dep_id for dep_id in deps
                if dep_id in todo_map and todo_map[dep_id].status not in ("completed", "abandoned")
            ]
            todo_blockers[todo.id] = blockers

        # Compute statistics
        total_goals = len(goals)
        active_goals = sum(1 for g in goals if g.status == "active")
        completed_goals = sum(1 for g in goals if g.status == "completed")

        total_plans = len(plans)
        active_plans = sum(1 for p in plans if p.status == "active")
        completed_plans = sum(1 for p in plans if p.status == "completed")

        # Filter out spikes for main todo counts
        non_spike_todos = [t for t in todos if not t.is_spike]
        total_todos = len(non_spike_todos)
        completed_todos = sum(1 for t in non_spike_todos if t.status == "completed")
        in_progress_todos = sum(1 for t in non_spike_todos if t.status == "in_progress")
        blocked_todos = sum(1 for t in non_spike_todos if t.status == "blocked")
        pending_todos = sum(1 for t in non_spike_todos if t.status == "pending")

        # Overall completion percentage
        overall_completion_pct = (completed_todos / total_todos * 100) if total_todos > 0 else 0.0

        # Build goal statuses
        goal_statuses: list[GoalStatus] = []
        for goal in goals:
            goal_plans = [p for p in plans if p.goal_id == goal.id]
            goal_todo_ids: set[str] = set()
            for plan in goal_plans:
                goal_todo_ids.update(plan_todos.get(plan.id, []))

            goal_todos = [todo_map[tid] for tid in goal_todo_ids if tid in todo_map and not todo_map[tid].is_spike]

            g_total = len(goal_todos)
            g_completed = sum(1 for t in goal_todos if t.status == "completed")
            g_in_progress = sum(1 for t in goal_todos if t.status == "in_progress")
            g_blocked = sum(1 for t in goal_todos if t.status == "blocked")

            goal_statuses.append(GoalStatus(
                id=goal.id,
                title=goal.title,
                weight=goal.weight,
                status=goal.status,
                plan_count=len(goal_plans),
                active_plan_count=sum(1 for p in goal_plans if p.status == "active"),
                total_todos=g_total,
                completed_todos=g_completed,
                in_progress_todos=g_in_progress,
                blocked_todos=g_blocked,
                completion_pct=(g_completed / g_total * 100) if g_total > 0 else 0.0,
                acceptance_criteria=goal.acceptance_criteria,
            ))

        # Sort goals by weight (highest first)
        goal_statuses.sort(key=lambda g: -g.weight)

        # Build plan statuses
        plan_statuses: list[PlanStatus] = []
        for plan in plans:
            goal = goal_map.get(plan.goal_id)
            plan_todo_ids = plan_todos.get(plan.id, [])
            plan_todo_list = [todo_map[tid] for tid in plan_todo_ids if tid in todo_map and not todo_map[tid].is_spike]

            p_total = len(plan_todo_list)
            p_completed = sum(1 for t in plan_todo_list if t.status == "completed")
            p_in_progress = sum(1 for t in plan_todo_list if t.status == "in_progress")
            p_blocked = sum(1 for t in plan_todo_list if t.status == "blocked")
            p_pending = sum(1 for t in plan_todo_list if t.status == "pending")

            plan_statuses.append(PlanStatus(
                id=plan.id,
                title=plan.title,
                status=plan.status,
                goal_title=goal.title if goal else "Unknown Goal",
                todo_count=p_total,
                completed_count=p_completed,
                in_progress_count=p_in_progress,
                blocked_count=p_blocked,
                pending_count=p_pending,
                completion_pct=(p_completed / p_total * 100) if p_total > 0 else 0.0,
            ))

        # Build todo status items for highlighted sections
        def make_todo_status(todo: TodoData) -> TodoStatus:
            plan_ids = todo_plans.get(todo.id, [])
            plan_titles = [plan_map[pid].title for pid in plan_ids if pid in plan_map]
            blocker_ids = todo_blockers.get(todo.id, [])
            blocker_titles = [todo_map[bid].title for bid in blocker_ids if bid in todo_map]

            return TodoStatus(
                id=todo.id,
                title=todo.title,
                status=todo.status,
                is_spike=todo.is_spike,
                plan_titles=plan_titles,
                blocker_titles=blocker_titles,
                completed_at=todo.completed_at,
            )

        # In-progress items
        in_progress_items = [
            make_todo_status(t) for t in todos
            if t.status == "in_progress" and not t.is_spike
        ]

        # Blocked items
        blocked_items = [
            make_todo_status(t) for t in todos
            if t.status == "blocked" and not t.is_spike
        ]

        # Recently completed (last 7 days or last 10, whichever is smaller)
        completed = [t for t in todos if t.status == "completed" and t.completed_at and not t.is_spike]
        completed.sort(key=lambda t: t.completed_at or "", reverse=True)
        recently_completed = [make_todo_status(t) for t in completed[:10]]

        # Active spikes
        active_spikes = [
            make_todo_status(t) for t in todos
            if t.is_spike and t.status in ("pending", "in_progress")
        ]

        return StatusReportData(
            generated_at=datetime.now().isoformat(),
            total_goals=total_goals,
            active_goals=active_goals,
            completed_goals=completed_goals,
            total_plans=total_plans,
            active_plans=active_plans,
            completed_plans=completed_plans,
            total_todos=total_todos,
            completed_todos=completed_todos,
            in_progress_todos=in_progress_todos,
            blocked_todos=blocked_todos,
            pending_todos=pending_todos,
            overall_completion_pct=overall_completion_pct,
            goals=goal_statuses,
            plans=plan_statuses,
            in_progress_items=in_progress_items,
            blocked_items=blocked_items,
            recently_completed=recently_completed,
            active_spikes=active_spikes,
        )

    async def write_report(
        self,
        report_data: StatusReportData,
        output_dir: Optional[Path] = None,
        config: Optional["Config"] = None,
    ) -> Path:
        """Write a status report to a markdown file.

        Args:
            report_data: The structured report data to write.
            output_dir: Directory to write the report to. If not provided,
                        uses the reports.output_path from config.
            config: Config instance. If not provided and output_dir is None,
                    loads the config using get_config_async().

        Returns:
            Path to the written report file.
        """
        from config import get_config_async

        # Determine output directory
        if output_dir is None:
            if config is None:
                config = await get_config_async()
            output_dir = config.reports.ensure_output_dir()
        else:
            output_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with date stamp
        date_stamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"status-report-{date_stamp}.md"
        output_path = output_dir / filename

        # Generate markdown content
        content = self._render_markdown(report_data)

        # Write to file
        async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
            await f.write(content)

        return output_path

    def _render_markdown(self, data: StatusReportData) -> str:
        """Render report data as markdown.

        This is a basic rendering. The reporting role may transform
        this into more polished prose.
        """
        lines: list[str] = []

        # Header
        generated_date = datetime.fromisoformat(data.generated_at).strftime("%B %d, %Y")
        lines.append(f"# Status Report - {generated_date}")
        lines.append("")

        # Executive Summary
        lines.append("## Executive Summary")
        lines.append("")

        # Include LLM-generated summary if available
        if data.summary:
            lines.append(data.summary)
            lines.append("")

        lines.append(f"**Overall Progress:** {data.overall_completion_pct:.1f}% complete")
        lines.append("")
        lines.append("| Category | Total | Completed | In Progress | Blocked |")
        lines.append("|----------|-------|-----------|-------------|---------|")
        lines.append(f"| Goals | {data.total_goals} | {data.completed_goals} | {data.active_goals} | - |")
        lines.append(f"| Plans | {data.total_plans} | {data.completed_plans} | {data.active_plans} | - |")
        lines.append(f"| Todos | {data.total_todos} | {data.completed_todos} | {data.in_progress_todos} | {data.blocked_todos} |")
        lines.append("")

        # In Progress
        if data.in_progress_items:
            lines.append("## Currently In Progress")
            lines.append("")
            for item in data.in_progress_items:
                plan_info = f" ({', '.join(item.plan_titles)})" if item.plan_titles else ""
                lines.append(f"- {item.title}{plan_info}")
            lines.append("")

        # Blocked Items
        if data.blocked_items:
            lines.append("## Blocked Items")
            lines.append("")
            for item in data.blocked_items:
                blocker_info = f" - blocked by: {', '.join(item.blocker_titles)}" if item.blocker_titles else ""
                lines.append(f"- {item.title}{blocker_info}")
            lines.append("")

        # Recently Completed
        if data.recently_completed:
            lines.append("## Recently Completed")
            lines.append("")
            for item in data.recently_completed:
                completed_date = ""
                if item.completed_at:
                    try:
                        completed_date = f" ({datetime.fromisoformat(item.completed_at).strftime('%b %d')})"
                    except ValueError:
                        pass
                lines.append(f"- {item.title}{completed_date}")
            lines.append("")

        # Active Spikes
        if data.active_spikes:
            lines.append("## Active Explorations (Spikes)")
            lines.append("")
            for item in data.active_spikes:
                lines.append(f"- {item.title} [{item.status}]")
            lines.append("")

        # Goals Detail
        lines.append("## Goals Overview")
        lines.append("")
        for goal in data.goals:
            status_emoji = {
                "active": "",
                "completed": "",
                "superseded": "",
                "abandoned": "",
            }.get(goal.status, "")

            lines.append(f"### {status_emoji} {goal.title} (Weight: {goal.weight})")
            lines.append("")
            lines.append(f"**Status:** {goal.status.title()} | **Progress:** {goal.completion_pct:.0f}% ({goal.completed_todos}/{goal.total_todos} todos)")
            lines.append("")

            if goal.acceptance_criteria:
                lines.append("**Acceptance Criteria:**")
                for criterion in goal.acceptance_criteria:
                    lines.append(f"- {criterion}")
                lines.append("")

        # Plans Detail
        if data.plans:
            lines.append("## Plans Overview")
            lines.append("")
            lines.append("| Plan | Goal | Status | Progress |")
            lines.append("|------|------|--------|----------|")
            for plan in data.plans:
                progress = f"{plan.completion_pct:.0f}% ({plan.completed_count}/{plan.todo_count})"
                lines.append(f"| {plan.title} | {plan.goal_title} | {plan.status} | {progress} |")
            lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"*Report generated at {data.generated_at}*")

        return "\n".join(lines)

    def _build_summary_prompt(self, data: StatusReportData) -> str:
        """Build the prompt for executive summary generation.

        Formats the StatusReportData into a structured prompt that the LLM
        can use to generate a stakeholder-friendly executive summary.

        Args:
            data: The structured report data.

        Returns:
            The formatted prompt string.
        """
        lines: list[str] = []

        # Overall statistics
        lines.append("## Current Status")
        lines.append(f"Overall Progress: {data.overall_completion_pct:.1f}% complete")
        lines.append(f"Goals: {data.active_goals} active, {data.completed_goals} completed (of {data.total_goals})")
        lines.append(f"Todos: {data.completed_todos} done, {data.in_progress_todos} in progress, {data.blocked_todos} blocked")
        lines.append("")

        # Recently completed (wins)
        if data.recently_completed:
            lines.append("## Recently Completed")
            for item in data.recently_completed[:5]:  # Top 5 recent completions
                lines.append(f"- {item.title}")
            lines.append("")

        # In progress
        if data.in_progress_items:
            lines.append("## Currently In Progress")
            for item in data.in_progress_items:
                plan_info = f" ({', '.join(item.plan_titles)})" if item.plan_titles else ""
                lines.append(f"- {item.title}{plan_info}")
            lines.append("")

        # Blocked items (potential decisions needed)
        if data.blocked_items:
            lines.append("## Blocked Items (May Need Decisions)")
            for item in data.blocked_items:
                blocker_info = f" - blocked by: {', '.join(item.blocker_titles)}" if item.blocker_titles else ""
                lines.append(f"- {item.title}{blocker_info}")
            lines.append("")

        # Goal progress for context
        if data.goals:
            lines.append("## Goal Progress")
            for goal in data.goals[:5]:  # Top 5 goals by weight
                lines.append(f"- {goal.title}: {goal.completion_pct:.0f}% ({goal.completed_todos}/{goal.total_todos})")
            lines.append("")

        # Final instruction
        lines.append("---")
        lines.append("Based on the above status data, write a 2-3 sentence executive summary for non-technical stakeholders.")
        lines.append("Cover: major wins (what was accomplished), current blockers (if any), and decisions needed (if any).")
        lines.append("Use outcome-focused language, avoid jargon, and quantify impact where possible.")
        lines.append("")
        lines.append("Executive Summary:")

        return "\n".join(lines)

    async def generate_summary(
        self,
        data: StatusReportData,
        runner: StreamingRunner,
        session_id: Optional[str] = None,
        backend_name: str = "",
    ) -> StatusReportData:
        """Generate an LLM-powered executive summary for the report.

        Calls the LLM with the reporting.md role prompt and the structured
        StatusReportData to produce a 2-3 sentence executive summary covering
        major wins, current blockers, and decisions needed.

        Args:
            data: The structured report data (from generate()).
            runner: A streaming runner for LLM calls.
            session_id: Optional session ID for task tracking.
            backend_name: Name of backend for task tracking display.

        Returns:
            A new StatusReportData with the summary field populated.
        """
        # Build the prompt with role context and data
        status_prompt = self._build_summary_prompt(data)

        # Combine role prompt with status data
        if _REPORTING_PROMPT:
            full_prompt = f"{_REPORTING_PROMPT}\n\n---\n\n{status_prompt}"
        else:
            full_prompt = status_prompt

        # Register stream for tracking
        stream_id = str(uuid.uuid4())
        get_stream_state().register_helper_stream(
            stream_id=stream_id,
            stream_type=StreamType.REPORT_SUMMARY,
            prompt="Generating executive summary",
            session_id=session_id,
            backend_name=backend_name,
        )

        summary_parts: list[str] = []
        try:
            async for event in runner.stream_response(
                [], full_prompt, disable_tools=True
            ):
                # Use duck typing: accept any event with a text attribute
                if hasattr(event, "text"):
                    summary_parts.append(event.text)
            get_stream_state().complete_stream(stream_id)
        except Exception as e:
            get_stream_state().fail_stream(stream_id, str(e))
            debug_log.error(
                f"Executive summary generation failed: {e}",
                category="report",
            )
            # Return data without summary on error
            return data

        summary = "".join(summary_parts).strip()

        # Return a new dataclass with the summary populated
        # Use dataclasses.replace if available, otherwise construct manually
        return StatusReportData(
            generated_at=data.generated_at,
            total_goals=data.total_goals,
            active_goals=data.active_goals,
            completed_goals=data.completed_goals,
            total_plans=data.total_plans,
            active_plans=data.active_plans,
            completed_plans=data.completed_plans,
            total_todos=data.total_todos,
            completed_todos=data.completed_todos,
            in_progress_todos=data.in_progress_todos,
            blocked_todos=data.blocked_todos,
            pending_todos=data.pending_todos,
            overall_completion_pct=data.overall_completion_pct,
            summary=summary if summary else None,
            goals=data.goals,
            plans=data.plans,
            in_progress_items=data.in_progress_items,
            blocked_items=data.blocked_items,
            recently_completed=data.recently_completed,
            active_spikes=data.active_spikes,
        )

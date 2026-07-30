"""Sales pipeline order, transition rules and presentation metadata."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ValidationError

from .models import DealStage


OPEN_STAGE_ORDER = (
    DealStage.NEW,
    DealStage.FIRST_CONTACT,
    DealStage.QUALIFICATION,
    DealStage.PROPOSAL,
    DealStage.NEGOTIATION,
)

TERMINAL_STAGE_ORDER = (DealStage.WON, DealStage.LOST)

ALLOWED_STAGE_TRANSITIONS = {
    DealStage.NEW: (DealStage.FIRST_CONTACT, DealStage.LOST),
    DealStage.FIRST_CONTACT: (DealStage.QUALIFICATION, DealStage.LOST),
    DealStage.QUALIFICATION: (DealStage.PROPOSAL, DealStage.LOST),
    DealStage.PROPOSAL: (DealStage.NEGOTIATION, DealStage.LOST),
    DealStage.NEGOTIATION: (DealStage.WON, DealStage.LOST),
    DealStage.WON: (),
    DealStage.LOST: (),
}

STAGE_CSS_CLASSES = {
    DealStage.NEW: "stage-new",
    DealStage.FIRST_CONTACT: "stage-first-contact",
    DealStage.QUALIFICATION: "stage-qualification",
    DealStage.PROPOSAL: "stage-proposal",
    DealStage.NEGOTIATION: "stage-negotiation",
    DealStage.WON: "stage-won",
    DealStage.LOST: "stage-lost",
}


@dataclass(frozen=True)
class PipelineStep:
    """One UI step derived from the same rules used by the backend."""

    code: str
    label: str
    css_class: str
    state: str
    can_transition: bool
    title: str
    number: int


def allowed_stage_transitions(current_stage: str) -> tuple[str, ...]:
    """Return the only stages reachable from the current stage."""

    try:
        stage = DealStage(current_stage)
    except ValueError:
        return ()
    return tuple(ALLOWED_STAGE_TRANSITIONS[stage])


def validate_stage_transition(*, current_stage: str, new_stage: str) -> None:
    """Raise a user-facing validation error for skips, backwards moves and closed deals."""

    try:
        current = DealStage(current_stage)
        target = DealStage(new_stage)
    except ValueError as exc:
        raise ValidationError("Указан неизвестный этап сделки.", code="invalid_stage") from exc

    if current in TERMINAL_STAGE_ORDER:
        raise ValidationError(
            f"Сделка закрыта на этапе «{current.label}». Смена этапа недоступна.",
            code="closed_deal",
        )
    if current == target:
        raise ValidationError(
            f"Сделка уже находится на этапе «{current.label}».",
            code="same_stage",
        )

    allowed = allowed_stage_transitions(current)
    if target not in allowed:
        allowed_labels = " или ".join(f"«{DealStage(value).label}»" for value in allowed)
        raise ValidationError(
            f"Нельзя перейти с этапа «{current.label}» на «{target.label}». Доступно: {allowed_labels}.",
            code="invalid_transition",
        )


def stage_css_class(stage: str) -> str:
    """Return the shared stage color class for lists and the deal pipeline."""

    try:
        return STAGE_CSS_CLASSES[DealStage(stage)]
    except (KeyError, ValueError):
        return "stage-unknown"


def build_pipeline_steps(*, current_stage: str, terminal_from_stage: str = "") -> tuple[list[PipelineStep], list[PipelineStep]]:
    """Build open and terminal step states for the deal detail UI."""

    current = DealStage(current_stage)
    allowed = set(allowed_stage_transitions(current))
    completed_open_count = 0
    if current in OPEN_STAGE_ORDER:
        completed_open_count = OPEN_STAGE_ORDER.index(current)
    elif current == DealStage.WON:
        completed_open_count = len(OPEN_STAGE_ORDER)
    elif current == DealStage.LOST and terminal_from_stage in OPEN_STAGE_ORDER:
        completed_open_count = OPEN_STAGE_ORDER.index(DealStage(terminal_from_stage)) + 1

    open_steps = [
        _build_step(
            stage=stage,
            number=index + 1,
            current=current,
            allowed=allowed,
            completed=index < completed_open_count,
        )
        for index, stage in enumerate(OPEN_STAGE_ORDER)
    ]
    terminal_steps = [
        _build_step(
            stage=stage,
            number=len(OPEN_STAGE_ORDER) + index + 1,
            current=current,
            allowed=allowed,
            completed=False,
        )
        for index, stage in enumerate(TERMINAL_STAGE_ORDER)
    ]
    return open_steps, terminal_steps


def _build_step(*, stage: DealStage, number: int, current: DealStage, allowed: set[str], completed: bool) -> PipelineStep:
    if stage == current:
        state = "active"
        title = "Текущий этап"
    elif completed:
        state = "completed"
        title = "Этап пройден"
    elif stage in allowed:
        state = "available"
        title = f"Перейти на этап «{stage.label}»"
    else:
        state = "future"
        title = "Сначала завершите предыдущий этап" if current not in TERMINAL_STAGE_ORDER else "Сделка закрыта"

    return PipelineStep(
        code=stage.value,
        label=stage.label,
        css_class=stage_css_class(stage),
        state=state,
        can_transition=stage in allowed,
        title=title,
        number=number,
    )

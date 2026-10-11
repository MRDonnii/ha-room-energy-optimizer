"""Built-in Better Thermostat learning guard.

Pauses Better Thermostat's thermal learning (heating power and heat loss) while
an external heat source warms a room, without changing any Better Thermostat
file. A room takes part when the Better Thermostat extension is enabled for it;
its "External heat active" sensor drives the pause: ``on``, ``unknown`` and
``unavailable`` pause learning, ``off`` resumes it.

Regulation, setpoints, HVAC action and values Better Thermostat has already
learned are never touched. The learning methods always run; only the cycle in
progress is dropped while paused, so a period with external heat is never
learned.

The guard relies on these Better Thermostat internals: the coroutine methods
``calculate_heating_power`` and ``calculate_heat_loss``, the trackers
``_heating_tracker`` and ``_loss_tracker`` with their cycle fields
(``start_temp``/``end_temp`` in 1.x, ``start_temperature``/``end_temperature``
in 2.x, plus ``start_ts``/``end_ts``) and the ``extra_state_attributes``
property. If an update changes them, the guard does not attach and logs a
warning; the climate then lacks ``thermal_learning_paused`` and the Data
problem sensor reports it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
import functools
import inspect
import logging
from typing import Any

from homeassistant.const import STATE_OFF
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers.entity_platform import async_get_platforms
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

BT_DOMAIN = "better_thermostat"
RESCAN_INTERVAL = timedelta(seconds=60)

# Published on each guarded Better Thermostat climate entity.
ATTR_PAUSED = "thermal_learning_paused"
ATTR_GUARD = "external_heat_entity_id"

# Cycle-in-progress fields. Better Thermostat 1.x: start_temp/end_temp;
# 2.x: start_temperature/end_temperature.
_TRACKER_FIELD_SETS = (
    ("start_temp", "start_ts", "end_temp", "end_ts"),
    ("start_temperature", "start_ts", "end_temperature", "end_ts"),
)
_LEARNING_METHODS = {
    "calculate_heating_power": "_heating_tracker",
    "calculate_heat_loss": "_loss_tracker",
}
# Per-entity guard state. The name is shared with the stand-alone
# "bt_learning_guard" integration, so whichever guard attaches first owns the
# entity and the other one leaves it alone.
_ENTITY_ATTR = "_bt_learning_guard"
# Class-level wrapper bookkeeping (shared name, reference counted).
_CLASS_ATTR = "_bt_learning_guard_original_attrs"
_CLASS_REFS = "_bt_learning_guard_refs"


@dataclass
class _Guard:
    guard_entity_id: str
    paused: bool


@dataclass
class _Attachment:
    entity: Any
    guard: _Guard
    unsub: CALLBACK_TYPE | None = None
    methods: list[str] = field(default_factory=list)


def _tracker_fields(tracker: Any) -> tuple[str, ...] | None:
    for fields in _TRACKER_FIELD_SETS:
        if all(hasattr(tracker, f) for f in fields):
            return fields
    return None


def _discard(tracker: Any) -> None:
    """Drop the tracker's cycle in progress; learned values stay as they are."""
    for name in _tracker_fields(tracker) or ():
        setattr(tracker, name, None)


def compatible(entity: Any) -> bool:
    """Return True when the Better Thermostat internals the guard needs exist."""
    for method, tracker_name in _LEARNING_METHODS.items():
        if not inspect.iscoroutinefunction(getattr(entity, method, None)):
            return False
        tracker = getattr(entity, tracker_name, None)
        if tracker is None or _tracker_fields(tracker) is None:
            return False
    prop = inspect.getattr_static(type(entity), "extra_state_attributes", None)
    return isinstance(prop, property) and prop.fget is not None


def _wrap_attributes(cls: type) -> None:
    """Add the guard attributes to a Better Thermostat class's state attributes."""
    if _CLASS_ATTR not in cls.__dict__:
        original = inspect.getattr_static(cls, "extra_state_attributes")
        fget = original.fget

        @functools.wraps(fget)
        def extra_state_attributes(self: Any) -> Any:
            attrs = fget(self)
            guard = getattr(self, _ENTITY_ATTR, None)
            if guard is None:
                return attrs
            attrs = dict(attrs or {})
            attrs[ATTR_PAUSED] = guard.paused
            attrs[ATTR_GUARD] = guard.guard_entity_id
            return attrs

        setattr(cls, _CLASS_ATTR, original)
        setattr(cls, "extra_state_attributes", property(extra_state_attributes))
    setattr(cls, _CLASS_REFS, cls.__dict__.get(_CLASS_REFS, 0) + 1)


def _unwrap_attributes(cls: type) -> None:
    refs = cls.__dict__.get(_CLASS_REFS, 0) - 1
    if refs > 0:
        setattr(cls, _CLASS_REFS, refs)
        return
    original = cls.__dict__.get(_CLASS_ATTR)
    if original is not None:
        setattr(cls, "extra_state_attributes", original)
        delattr(cls, _CLASS_ATTR)
    if _CLASS_REFS in cls.__dict__:
        delattr(cls, _CLASS_REFS)


class LearningGuard:
    """Attach the learning guard to the configured Better Thermostat climates."""

    def __init__(
        self, hass: HomeAssistant, guards: Callable[[], dict[str, str | None]]
    ) -> None:
        # ``guards`` maps a Better Thermostat climate entity id to the entity id
        # of its "External heat active" sensor (None while it does not exist yet).
        self.hass = hass
        self._guards = guards
        self._attached: dict[str, _Attachment] = {}
        self._classes: list[type] = []
        self._reported: set[str] = set()

    def _report_once(self, key: str, message: str, *args: Any) -> None:
        if key not in self._reported:
            self._reported.add(key)
            _LOGGER.warning(message, *args)

    @callback
    def async_scan(self, *_: Any) -> None:
        """Attach to new or replaced entities and detach from removed ones."""
        wanted = {k: v for k, v in self._guards().items() if v}
        live: dict[str, Any] = {}
        for platform in async_get_platforms(self.hass, BT_DOMAIN):
            if platform.domain != "climate":
                continue
            for entity in list(platform.entities.values()):
                if entity.entity_id in wanted:
                    live[entity.entity_id] = entity
        for entity_id, attachment in list(self._attached.items()):
            if live.get(entity_id) is not attachment.entity or (
                wanted.get(entity_id) != attachment.guard.guard_entity_id
            ):
                self._detach(entity_id)
        for entity_id, entity in live.items():
            if entity_id not in self._attached:
                self._attach(entity, wanted[entity_id])

    def _attach(self, entity: Any, guard_id: str) -> None:
        entity_id: str = entity.entity_id
        if getattr(entity, _ENTITY_ATTR, None) is not None:
            return  # already guarded (e.g. by the stand-alone bt_learning_guard)
        if hasattr(entity, "_thermal_learning_paused"):
            self._report_once(
                f"native:{entity_id}",
                "%s already has a learning guard patched into Better Thermostat; "
                "remove that local patch so Room Energy Optimizer can take over",
                entity_id,
            )
            return
        if not compatible(entity):
            self._report_once(
                f"incompatible:{entity_id}",
                "Cannot guard %s: this Better Thermostat version lacks the "
                "learning internals the guard relies on",
                entity_id,
            )
            return
        self._reported.discard(f"incompatible:{entity_id}")
        self._reported.discard(f"native:{entity_id}")

        cls = type(entity)
        _wrap_attributes(cls)
        self._classes.append(cls)

        initial = self.hass.states.get(guard_id)
        guard = _Guard(guard_id, paused=initial is None or initial.state != STATE_OFF)
        if guard.paused:
            for tracker_name in _LEARNING_METHODS.values():
                _discard(getattr(entity, tracker_name))
        attachment = _Attachment(entity, guard)
        for method, tracker_name in _LEARNING_METHODS.items():
            original = getattr(entity, method)
            setattr(entity, method, self._guarded(entity, original, tracker_name, guard))
            attachment.methods.append(method)
        setattr(entity, _ENTITY_ATTR, guard)
        attachment.unsub = async_track_state_change_event(
            self.hass, [guard_id], functools.partial(self._async_guard_changed, entity_id)
        )
        self._attached[entity_id] = attachment
        _LOGGER.debug("Guarding %s with %s", entity_id, guard_id)
        self._write_state(entity)

    @staticmethod
    def _guarded(entity: Any, original: Any, tracker_name: str, guard: _Guard) -> Any:
        @functools.wraps(original)
        async def guarded(*args: Any, **kwargs: Any) -> Any:
            if guard.paused:
                _discard(getattr(entity, tracker_name))
            try:
                return await original(*args, **kwargs)
            finally:
                if guard.paused:
                    _discard(getattr(entity, tracker_name))

        return guarded

    def _apply(self, attachment: _Attachment, state: State | None) -> None:
        paused = state is None or state.state != STATE_OFF
        guard = attachment.guard
        if paused != guard.paused:
            for tracker_name in _LEARNING_METHODS.values():
                _discard(getattr(attachment.entity, tracker_name))
            _LOGGER.info(
                "%s: thermal learning %s (%s=%s)",
                attachment.entity.entity_id,
                "paused" if paused else "resumed",
                guard.guard_entity_id,
                None if state is None else state.state,
            )
        guard.paused = paused

    @callback
    def _async_guard_changed(self, entity_id: str, event: Event) -> None:
        attachment = self._attached.get(entity_id)
        if attachment is None:
            return
        self._apply(attachment, event.data.get("new_state"))
        self._write_state(attachment.entity)

    @staticmethod
    def _write_state(entity: Any) -> None:
        if entity.hass is not None and entity.entity_id:
            entity.async_write_ha_state()

    def _detach(self, entity_id: str) -> None:
        attachment = self._attached.pop(entity_id, None)
        if attachment is None:
            return
        if attachment.unsub is not None:
            attachment.unsub()
        entity = attachment.entity
        for method in attachment.methods:
            entity.__dict__.pop(method, None)
        entity.__dict__.pop(_ENTITY_ATTR, None)
        cls = type(entity)
        if cls in self._classes:
            self._classes.remove(cls)
            _unwrap_attributes(cls)
        if entity.hass is not None and entity.platform is not None:
            self._write_state(entity)

    @callback
    def async_stop(self) -> None:
        for entity_id in list(self._attached):
            self._detach(entity_id)
        for cls in self._classes:
            _unwrap_attributes(cls)
        self._classes.clear()

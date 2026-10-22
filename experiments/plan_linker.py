"""Offline feature-aware linking; keep the originally registered compiler intact."""
from copy import deepcopy

from gui_dna.followup.domain import EVENTS, HANDLERS, VIEW_STEPS, compile_plan


def link_plan(plan, features, library):
    """Remove only known disabled routes/stages, then run all original checks.

    The public renderer sends only enabled events. This does not infer missing
    bindings, reorder stages, replace a wrong handler, or construct a new plan.
    """
    if not isinstance(plan, dict):
        raise ValueError('plan must be an object')
    if set(features) - EVENTS.keys():
        raise ValueError('Unknown feature')
    routes = plan.get('handlers')
    view = plan.get('view')
    if not isinstance(routes, dict) or not isinstance(view, list):
        raise ValueError('handlers must be an object and view must be a list')
    all_routes = {event: HANDLERS[f] for f in EVENTS for event in EVENTS[f]}
    if any(event not in all_routes or name != all_routes[event] for event, name in routes.items()):
        raise ValueError('Unknown event or incorrect handler binding')
    all_stages = set(VIEW_STEPS.values()) | {'pageRows'}
    if any(not isinstance(name, str) or name not in all_stages for name in view):
        raise ValueError('Unknown row stage')
    enabled_events = {event for f in features for event in EVENTS[f]}
    enabled_stages = {VIEW_STEPS[f] for f in features if f in VIEW_STEPS} | {'pageRows'}
    normalized = deepcopy(plan)
    normalized['handlers'] = {event: name for event, name in routes.items() if event in enabled_events}
    normalized['view'] = [name for name in view if name in enabled_stages]
    code = compile_plan(normalized, features, library)
    changes = {'removed_events': [e for e in routes if e not in enabled_events],
               'removed_stages': [s for s in view if s not in enabled_stages]}
    return normalized, code, changes

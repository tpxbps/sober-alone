"""Game API exports, loaded lazily so pure clue policies do not import agents."""

from importlib import import_module

__all__ = ["GameFlowController", "StageTransition", "SpeechScheduler", "SpeechTendency"]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(name)
    module = (
        "flow_controller"
        if name in {"GameFlowController", "StageTransition"}
        else "speech_scheduler"
    )
    value = getattr(import_module(f"app.game.{module}"), name)
    globals()[name] = value
    return value

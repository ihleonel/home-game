"""Production composition root for the games module.

This module is the **single** place where the implemented game definitions are
wired into the production :class:`GameRegistry`. To add a game, add its
definition here; nothing else should construct a registry. The interface layer
imports this registry instead of building its own, so a definition added here
is immediately visible to the resolver and to any other catalog reader (for
example the FRG-07 catalog work).

The registry owns catalog discovery only and holds no runtime state.
"""

from .duelo.game import DueloDefinition
from .registry import GameRegistry

GAME_REGISTRY = GameRegistry((DueloDefinition(),))

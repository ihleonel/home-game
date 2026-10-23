"""In-memory registry of game definitions.

The registry owns catalog discovery only. It has no runtime state and may
import neither Django, DRF, nor Channels.
"""

from typing import Iterable

from .contracts import GameDefinition


class GameRegistry:
    """Ordered registry that rejects duplicate ``game_id`` values."""

    def __init__(self, definitions: Iterable[GameDefinition]):
        self._definitions: dict[str, GameDefinition] = {}
        for definition in definitions:
            if definition.game_id in self._definitions:
                raise ValueError(
                    f'duplicate game_id {definition.game_id!r} is already registered'
                )
            self._definitions[definition.game_id] = definition

    def get(self, game_id: str) -> GameDefinition | None:
        return self._definitions.get(game_id)

    def is_known_game(self, game_id: str) -> bool:
        return game_id in self._definitions

    def contains_seat_option(self, game_id: str, option_id: str) -> bool:
        definition = self._definitions.get(game_id)
        return definition is not None and option_id in {
            option.id for option in definition.seat_options
        }

    def list_games(self) -> tuple[dict, ...]:
        """Return the catalog DTO consumed by the frontend.

        ``markers`` is the compatibility name for the definition's
        ``seat_options``; the DTO shape must not drift from the static catalog.

        The DTOs come back **in registration order**, and that order is served to
        the frontend unchanged: the lobby renders the array as it arrives and
        never sorts it. Which game is offered first is therefore decided by the
        order of the tuple in the composition root, not here.
        """
        return tuple(
            {
                'id': definition.game_id,
                'label': definition.label,
                'description': definition.description,
                'markers': tuple(
                    {'id': option.id, 'label': option.label}
                    for option in definition.seat_options
                ),
            }
            for definition in self._definitions.values()
        )

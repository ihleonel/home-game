"""Production ``RandomSource`` adapter backed by ``random.SystemRandom``.

``random.SystemRandom`` draws from ``os.urandom`` and ignores ``random.seed``,
so the opening seat of a match cannot be predicted or replayed by anyone who
can influence the process-global PRNG. It is the production counterpart of the
framework-free :class:`~modules.games.contracts.RandomSource` protocol.
"""

import random


class SystemRandomSource:
    """``RandomSource`` implemented on top of ``random.SystemRandom``."""

    def __init__(self, source=None):
        self._source = source if source is not None else random.SystemRandom()

    def shuffle(self, items):
        """Return a randomly shuffled copy of ``items`` as a list."""
        shuffled = list(items)
        self._source.shuffle(shuffled)
        return shuffled

    def roll(self, sides):
        """Return an integer in ``1..sides`` inclusive.

        Raises ``ValueError`` for a non-positive ``sides``, where no valid
        roll exists and a silent ``randint`` error would be less clear.
        """
        if sides < 1:
            raise ValueError(f'sides must be positive, got {sides!r}')
        return self._source.randint(1, sides)

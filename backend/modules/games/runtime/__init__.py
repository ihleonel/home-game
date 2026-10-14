"""Framework-free match runtime.

The runtime executes any game through the ``GameDefinition`` contract and the
``MatchStore``/``MatchProjector`` ports. Nothing in this package may import
Django, DRF, Channels or ``modules.rooms``.
"""

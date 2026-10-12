"""Application layer of the framework-free match runtime.

The use cases depend only on the ports and the game contracts; nothing here
imports Django, DRF, Channels or ``modules.rooms``. The layer holds no logic
of its own: each use case lives in its own module and shared helpers live in
their own modules (for example ``views.seat_views``), so importing this
package has no side effects.
"""

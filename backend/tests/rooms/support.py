"""Shared fakes for the rooms use-case tests."""

from collections import deque
from contextlib import contextmanager
from unittest.mock import Mock

_UNSET = object()


def declared_ports(*protocols):
    """Port names declared by the given protocols."""
    return {
        name
        for protocol in protocols
        for name, member in vars(protocol).items()
        if not name.startswith('_') and callable(member)
    }


def ports_fake(*protocols, **results):
    """A Mock stand-in for the given ports protocols.

    `ports.timeline` records every declared port call in order, so a sequence
    assertion cannot silently omit a step: recording only the names configured
    below would let an unconfigured port be called without leaving a trace.
    Configured names return the configured result, and a `deque` result is
    consumed one item per call; names left unconfigured return an inert
    sentinel instead of a fabricated value. Every configured name must be
    declared by the given protocols: an undeclared one would be ignored
    silently, so it raises instead. `atomic` keeps its own context-manager side
    effect and contributes the `begin`/`commit`/`rollback` markers rather than a
    port entry.
    """
    ports = Mock()
    ports.timeline = []

    @contextmanager
    def atomic():
        ports.timeline.append('begin')
        try:
            yield
        except Exception:
            ports.timeline.append('rollback')
            raise
        else:
            ports.timeline.append('commit')

    ports.atomic.side_effect = atomic

    declared = declared_ports(*protocols)
    undeclared = sorted(set(results) - declared)
    if undeclared:
        names = ', '.join(protocol.__name__ for protocol in protocols)
        raise ValueError(
            f'ports_fake received undeclared ports {undeclared} for {names}; '
            'they would be ignored silently, so declare them in the protocol or '
            'remove the configuration'
        )

    for name in sorted(declared - {'atomic'}):
        result = results.get(name, _UNSET)

        def operation(*args, _name=name, _result=result, **kwargs):
            ports.timeline.append(_name)
            if isinstance(_result, deque):
                return _result.popleft()
            return _result

        getattr(ports, name).side_effect = operation

    return ports

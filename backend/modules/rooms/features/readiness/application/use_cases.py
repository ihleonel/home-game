from .ports import ReadinessGateway


def set_ready_state(gateway: ReadinessGateway, data):
    return gateway.set_ready(data)

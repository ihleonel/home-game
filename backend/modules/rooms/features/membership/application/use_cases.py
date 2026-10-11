from .ports import RoomMembershipGateway


def create_or_discover_room(gateway: RoomMembershipGateway, data):
    return gateway.create_or_discover(data)


def join_room(gateway: RoomMembershipGateway, data):
    return gateway.join(data)


def leave_room(gateway: RoomMembershipGateway, data):
    return gateway.leave(data)


def get_active_room(gateway: RoomMembershipGateway):
    return gateway.get_active_room()

GAMES = (
    {
        'id': 'starlight-garden',
        'label': 'Starlight Garden',
        'description': 'Tend a quiet garden beneath a glowing night sky.',
        'markers': (
            {'id': 'silver-leaf', 'label': 'Silver Leaf'},
            {'id': 'moonstone', 'label': 'Moonstone'},
            {'id': 'night-bloom', 'label': 'Night Bloom'},
        ),
    },
    {
        'id': 'cloud-couriers',
        'label': 'Cloud Couriers',
        'description': 'Carry tiny parcels across a sky of drifting clouds.',
        'markers': (
            {'id': 'wind-kite', 'label': 'Wind Kite'},
            {'id': 'cloud-bell', 'label': 'Cloud Bell'},
            {'id': 'sunbeam', 'label': 'Sunbeam'},
        ),
    },
    {
        'id': 'amber-islands',
        'label': 'Amber Islands',
        'description': 'Explore a chain of warm, faraway islands.',
        'markers': (
            {'id': 'amber-shell', 'label': 'Amber Shell'},
            {'id': 'coral-star', 'label': 'Coral Star'},
            {'id': 'tide-glass', 'label': 'Tide Glass'},
        ),
    },
)

GAMES_BY_ID = {game['id']: game for game in GAMES}

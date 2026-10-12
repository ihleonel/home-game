GAMES = (
    {
        'id': 'starlight-garden',
        'label': 'Jardín estrellado',
        'description': 'Cuida un jardín tranquilo bajo un cielo nocturno lleno de estrellas.',
        'markers': (
            {'id': 'silver-leaf', 'label': 'Hoja plateada'},
            {'id': 'moonstone', 'label': 'Piedra lunar'},
            {'id': 'night-bloom', 'label': 'Flor nocturna'},
        ),
    },
    {
        'id': 'cloud-couriers',
        'label': 'Mensajeros de las nubes',
        'description': 'Lleva pequeños paquetes por un cielo de nubes viajeras.',
        'markers': (
            {'id': 'wind-kite', 'label': 'Cometa de viento'},
            {'id': 'cloud-bell', 'label': 'Campana de nube'},
            {'id': 'sunbeam', 'label': 'Rayo de sol'},
        ),
    },
    {
        'id': 'amber-islands',
        'label': 'Islas de ámbar',
        'description': 'Explora un archipiélago de islas cálidas y lejanas.',
        'markers': (
            {'id': 'amber-shell', 'label': 'Concha de ámbar'},
            {'id': 'coral-star', 'label': 'Estrella de coral'},
            {'id': 'tide-glass', 'label': 'Cristal de marea'},
        ),
    },
)

GAMES_BY_ID = {game['id']: game for game in GAMES}


def contains_game(game_id):
    return game_id in GAMES_BY_ID


def contains_marker(game_id, marker_id):
    game = GAMES_BY_ID.get(game_id)
    return game is not None and marker_id in {
        marker['id'] for marker in game['markers']
    }

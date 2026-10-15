"""Fidelity tests for the static ``monopoly`` card decks (S2).

The 32 cards are spelled out literally, card by card, so a change to
``cards.CARDS`` alone can never rewrite the expectation. ``SimpleTestCase``
only provides the runner: the data module is pure and needs no database.

The expected rows are ``(id, title, effect, amount, space, per_house,
per_hotel)``. Every field is listed for every card, even the ones its effect
does not use, so a card that quietly starts carrying a stray amount is a
failure instead of a surprise.
"""

from django.test import SimpleTestCase

from modules.games.monopoly import board, cards

CHANCE = (
    ('chance-01', 'Avanzá hasta Boardwalk.', 'advance', 0, 39, 0, 0),
    ('chance-02', 'Avanzá hasta la Salida y cobrá $200.', 'advance', 0, 0, 0, 0),
    (
        'chance-03',
        'Avanzá hasta Avenida Illinois; si pasás por la Salida, cobrá $200.',
        'advance',
        0,
        24,
        0,
        0,
    ),
    (
        'chance-04',
        'Avanzá hasta St. Charles Place; si pasás por la Salida, cobrá $200.',
        'advance',
        0,
        11,
        0,
        0,
    ),
    (
        'chance-05',
        'Avanzá hasta el ferrocarril más cercano; si no tiene dueño podés comprarlo y, '
        'si lo tiene, pagá el doble de la renta.',
        'advance_nearest_railroad',
        0,
        None,
        0,
        0,
    ),
    (
        'chance-06',
        'Avanzá hasta el ferrocarril más cercano; si no tiene dueño podés comprarlo y, '
        'si lo tiene, pagá el doble de la renta.',
        'advance_nearest_railroad',
        0,
        None,
        0,
        0,
    ),
    (
        'chance-07',
        'Avanzá hasta el servicio más cercano; si no tiene dueño podés comprarlo y, '
        'si lo tiene, tirá los dados y pagale diez veces lo que salga.',
        'advance_nearest_utility',
        0,
        None,
        0,
        0,
    ),
    ('chance-08', 'El banco te paga un dividendo de $50.', 'collect_bank', 50, None, 0, 0),
    (
        'chance-09',
        'Salí de la cárcel gratis. Conservala hasta que la uses.',
        'jail_card',
        0,
        None,
        0,
        0,
    ),
    ('chance-10', 'Retrocedé tres casillas.', 'go_back_three', 0, None, 0, 0),
    (
        'chance-11',
        'Andá a la cárcel: no pasás por la Salida ni cobrás $200.',
        'go_to_jail',
        0,
        None,
        0,
        0,
    ),
    (
        'chance-12',
        'Reparaciones generales: pagá $25 por cada casa y $100 por cada hotel.',
        'repairs',
        0,
        None,
        25,
        100,
    ),
    ('chance-13', 'Multa por exceso de velocidad: $15.', 'pay_bank', 15, None, 0, 0),
    (
        'chance-14',
        'Viajá hasta el Ferrocarril Reading; si pasás por la Salida, cobrá $200.',
        'advance',
        0,
        5,
        0,
        0,
    ),
    (
        'chance-15',
        'Te eligieron presidente del directorio: pagale $50 a cada jugador.',
        'pay_each_player',
        50,
        None,
        0,
        0,
    ),
    ('chance-16', 'Tu préstamo para construcción vence: cobrá $150.', 'collect_bank', 150, None, 0, 0),
)

COMMUNITY_CHEST = (
    ('community_chest-01', 'Avanzá hasta la Salida y cobrá $200.', 'advance', 0, 0, 0, 0),
    ('community_chest-02', 'Error bancario a tu favor: cobrá $200.', 'collect_bank', 200, None, 0, 0),
    ('community_chest-03', 'Honorarios médicos: pagá $50.', 'pay_bank', 50, None, 0, 0),
    ('community_chest-04', 'Por la venta de acciones cobrás $50.', 'collect_bank', 50, None, 0, 0),
    (
        'community_chest-05',
        'Salí de la cárcel gratis. Conservala hasta que la uses.',
        'jail_card',
        0,
        None,
        0,
        0,
    ),
    (
        'community_chest-06',
        'Andá a la cárcel: no pasás por la Salida ni cobrás $200.',
        'go_to_jail',
        0,
        None,
        0,
        0,
    ),
    ('community_chest-07', 'Vence tu fondo de vacaciones: recibí $100.', 'collect_bank', 100, None, 0, 0),
    ('community_chest-08', 'Devolución de impuestos: cobrá $20.', 'collect_bank', 20, None, 0, 0),
    (
        'community_chest-09',
        'Es tu cumpleaños: cobrá $10 de cada jugador.',
        'collect_each_player',
        10,
        None,
        0,
        0,
    ),
    ('community_chest-10', 'Vence tu seguro de vida: cobrá $100.', 'collect_bank', 100, None, 0, 0),
    ('community_chest-11', 'Pagá gastos de hospital: $100.', 'pay_bank', 100, None, 0, 0),
    ('community_chest-12', 'Pagá la cuota escolar: $50.', 'pay_bank', 50, None, 0, 0),
    ('community_chest-13', 'Cobrá $25 por servicios de consultoría.', 'collect_bank', 25, None, 0, 0),
    (
        'community_chest-14',
        'Te cobran arreglos de calles: $40 por cada casa y $115 por cada hotel.',
        'repairs',
        0,
        None,
        40,
        115,
    ),
    (
        'community_chest-15',
        'Ganaste el segundo premio del concurso de belleza: cobrá $10.',
        'collect_bank',
        10,
        None,
        0,
        0,
    ),
    ('community_chest-16', 'Recibís una herencia de $100.', 'collect_bank', 100, None, 0, 0),
)


class MonopolyCardTests(SimpleTestCase):
    def test_the_chance_deck_matches_the_normative_table(self):
        self.assertEqual(_rows(cards.deck_cards(cards.CHANCE)), CHANCE)

    def test_the_community_chest_deck_matches_the_normative_table(self):
        self.assertEqual(_rows(cards.deck_cards(cards.COMMUNITY_CHEST)), COMMUNITY_CHEST)

    def test_the_two_decks_hold_sixteen_cards_each_and_thirty_two_together(self):
        self.assertEqual(len(cards.deck_cards(cards.CHANCE)), 16)
        self.assertEqual(len(cards.deck_cards(cards.COMMUNITY_CHEST)), 16)
        self.assertEqual(len(cards.CARDS), 32)
        self.assertEqual(
            {card.deck for card in cards.CARDS},
            {cards.CHANCE, cards.COMMUNITY_CHEST},
        )

    def test_every_id_is_unique_and_names_its_own_deck_and_position(self):
        for deck, rows in ((cards.CHANCE, CHANCE), (cards.COMMUNITY_CHEST, COMMUNITY_CHEST)):
            ids = [row[0] for row in rows]
            with self.subTest(deck=deck):
                self.assertEqual(ids, [f'{deck}-{index:02d}' for index in range(1, 17)])
        self.assertEqual(len({card.id for card in cards.CARDS}), 32)

    def test_a_card_is_found_by_its_id_and_an_unknown_id_is_rejected(self):
        for card in cards.CARDS:
            with self.subTest(card=card.id):
                self.assertIs(cards.card_for(card.id), card)
        with self.assertRaises(ValueError):
            cards.card_for('chance-17')
        with self.assertRaises(ValueError):
            cards.card_for('nope')

    def test_every_deck_id_is_in_the_deck_it_names(self):
        for deck in (cards.CHANCE, cards.COMMUNITY_CHEST):
            for card_id in cards.deck_ids(deck):
                with self.subTest(card=card_id):
                    self.assertEqual(cards.card_for(card_id).deck, deck)
        with self.assertRaises(ValueError):
            cards.deck_ids('nope')

    def test_each_effect_carries_exactly_the_payload_it_needs(self):
        for card in cards.CARDS:
            with self.subTest(card=card.id, effect=card.effect):
                if card.effect == 'advance':
                    self.assertIsNotNone(card.space)
                    self.assertEqual(card.amount, 0)
                elif card.effect in ('collect_bank', 'pay_bank'):
                    self.assertGreater(card.amount, 0)
                    self.assertIsNone(card.space)
                elif card.effect in ('collect_each_player', 'pay_each_player'):
                    self.assertGreater(card.amount, 0)
                elif card.effect == 'repairs':
                    self.assertGreater(card.per_house, 0)
                    self.assertGreater(card.per_hotel, 0)
                else:
                    self.assertEqual((card.amount, card.space, card.per_house, card.per_hotel), (0, None, 0, 0))

    def test_every_advance_card_names_a_space_on_the_board(self):
        for card in cards.CARDS:
            if card.effect != 'advance':
                continue
            with self.subTest(card=card.id):
                self.assertIsNotNone(board_space(card.space))

    def test_only_the_go_back_card_can_reach_another_card_space(self):
        """The chain of draws terminates, and this pins why (S7).

        A card that lands the token on a card space draws again. The only card
        that can do that is the chance retroceso landing on Caja de comunidad
        33, and no community-chest card moves the token at all, so the chain
        can never be longer than two cards.
        """
        destinations = {}
        for card in cards.CARDS:
            for destination in card_destinations(card):
                destinations.setdefault(card.deck, set()).add(destination)

        card_spaces = {2, 7, 17, 22, 33, 36}
        self.assertEqual(destinations[cards.CHANCE] & card_spaces, {33})
        self.assertEqual(destinations[cards.COMMUNITY_CHEST] & card_spaces, set())


def _rows(deck):
    """Project every card of ``deck`` onto the normative row shape."""
    return tuple(
        (
            card.id,
            card.title,
            card.effect,
            card.amount,
            card.space,
            card.per_house,
            card.per_hotel,
        )
        for card in deck
    )


def board_space(index):
    """Return the index when it is inside the circuit, or ``None``."""
    return index if 0 <= index < board.BOARD_SIZE else None


def card_destinations(card):
    """Yield every space a card can leave the token on, for the chain check."""
    if card.effect == 'advance':
        return (card.space,)
    if card.effect == 'advance_nearest_railroad':
        return board.RAILROAD_INDEXES
    if card.effect == 'advance_nearest_utility':
        return board.UTILITY_INDEXES
    if card.effect == 'go_back_three':
        return tuple((index - 3) % board.BOARD_SIZE for index in (7, 22, 36))
    return ()

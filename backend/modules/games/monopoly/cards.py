"""Static data of the classic Monopoly card decks (S2 of ``monopoly-cards.md``).

Pure data plus lookups: no Django, DRF or Channels, no rules and no mutable
state. The 32 cards of the classic United States set -- the one that goes with
the 1999-2007 edition this product plays (S2 of ``monopoly.md``) -- with the
copy a player reads and the effect the rules resolve.

Only the *data* lives here. Which deck is on top, who holds a card and what a
card does to the match are the rules module's business, and the deck order is
hidden information the view must never expose.
"""

from dataclasses import dataclass

CHANCE = 'chance'
COMMUNITY_CHEST = 'community_chest'

DECKS = (CHANCE, COMMUNITY_CHEST)

# The effect kinds a card can carry. Kept as plain strings instead of an enum
# so the card table below reads as data and the rules can switch on them
# without importing anything from this module but the names.
ADVANCE = 'advance'
ADVANCE_NEAREST_RAILROAD = 'advance_nearest_railroad'
ADVANCE_NEAREST_UTILITY = 'advance_nearest_utility'
GO_BACK_THREE = 'go_back_three'
GO_TO_JAIL = 'go_to_jail'
JAIL_CARD = 'jail_card'
COLLECT_BANK = 'collect_bank'
PAY_BANK = 'pay_bank'
COLLECT_EACH_PLAYER = 'collect_each_player'
PAY_EACH_PLAYER = 'pay_each_player'
REPAIRS = 'repairs'


@dataclass(frozen=True)
class Card:
    """One printed card.

    Only the field its ``effect`` needs is set; the card test pins that a card
    cannot quietly carry a payload its effect ignores. ``title`` is the copy a
    player reads, and it is what the view publishes when the card is drawn.
    """

    id: str
    deck: str
    title: str
    effect: str
    amount: int = 0
    space: int | None = None
    per_house: int = 0
    per_hotel: int = 0


# The classic United States set, in deck order. This is the single source of
# the cards, and ``test_monopoly_cards.py`` pins it card by card against S2.
CARDS: tuple[Card, ...] = (
    # --- Suerte -----------------------------------------------------------
    Card('chance-01', CHANCE, 'Avanzá hasta Boardwalk.', ADVANCE, space=39),
    Card('chance-02', CHANCE, 'Avanzá hasta la Salida y cobrá $200.', ADVANCE, space=0),
    Card(
        'chance-03',
        CHANCE,
        'Avanzá hasta Avenida Illinois; si pasás por la Salida, cobrá $200.',
        ADVANCE,
        space=24,
    ),
    Card(
        'chance-04',
        CHANCE,
        'Avanzá hasta St. Charles Place; si pasás por la Salida, cobrá $200.',
        ADVANCE,
        space=11,
    ),
    Card(
        'chance-05',
        CHANCE,
        'Avanzá hasta el ferrocarril más cercano; si no tiene dueño podés comprarlo y, '
        'si lo tiene, pagá el doble de la renta.',
        ADVANCE_NEAREST_RAILROAD,
    ),
    Card(
        'chance-06',
        CHANCE,
        'Avanzá hasta el ferrocarril más cercano; si no tiene dueño podés comprarlo y, '
        'si lo tiene, pagá el doble de la renta.',
        ADVANCE_NEAREST_RAILROAD,
    ),
    Card(
        'chance-07',
        CHANCE,
        'Avanzá hasta el servicio más cercano; si no tiene dueño podés comprarlo y, '
        'si lo tiene, tirá los dados y pagale diez veces lo que salga.',
        ADVANCE_NEAREST_UTILITY,
    ),
    Card('chance-08', CHANCE, 'El banco te paga un dividendo de $50.', COLLECT_BANK, amount=50),
    Card(
        'chance-09',
        CHANCE,
        'Salí de la cárcel gratis. Conservala hasta que la uses.',
        JAIL_CARD,
    ),
    Card('chance-10', CHANCE, 'Retrocedé tres casillas.', GO_BACK_THREE),
    Card(
        'chance-11',
        CHANCE,
        'Andá a la cárcel: no pasás por la Salida ni cobrás $200.',
        GO_TO_JAIL,
    ),
    Card(
        'chance-12',
        CHANCE,
        'Reparaciones generales: pagá $25 por cada casa y $100 por cada hotel.',
        REPAIRS,
        per_house=25,
        per_hotel=100,
    ),
    Card('chance-13', CHANCE, 'Multa por exceso de velocidad: $15.', PAY_BANK, amount=15),
    Card(
        'chance-14',
        CHANCE,
        'Viajá hasta el Ferrocarril Reading; si pasás por la Salida, cobrá $200.',
        ADVANCE,
        space=5,
    ),
    Card(
        'chance-15',
        CHANCE,
        'Te eligieron presidente del directorio: pagale $50 a cada jugador.',
        PAY_EACH_PLAYER,
        amount=50,
    ),
    Card(
        'chance-16',
        CHANCE,
        'Tu préstamo para construcción vence: cobrá $150.',
        COLLECT_BANK,
        amount=150,
    ),
    # --- Caja de comunidad -------------------------------------------------
    Card(
        'community_chest-01',
        COMMUNITY_CHEST,
        'Avanzá hasta la Salida y cobrá $200.',
        ADVANCE,
        space=0,
    ),
    Card(
        'community_chest-02',
        COMMUNITY_CHEST,
        'Error bancario a tu favor: cobrá $200.',
        COLLECT_BANK,
        amount=200,
    ),
    Card(
        'community_chest-03',
        COMMUNITY_CHEST,
        'Honorarios médicos: pagá $50.',
        PAY_BANK,
        amount=50,
    ),
    Card(
        'community_chest-04',
        COMMUNITY_CHEST,
        'Por la venta de acciones cobrás $50.',
        COLLECT_BANK,
        amount=50,
    ),
    Card(
        'community_chest-05',
        COMMUNITY_CHEST,
        'Salí de la cárcel gratis. Conservala hasta que la uses.',
        JAIL_CARD,
    ),
    Card(
        'community_chest-06',
        COMMUNITY_CHEST,
        'Andá a la cárcel: no pasás por la Salida ni cobrás $200.',
        GO_TO_JAIL,
    ),
    Card(
        'community_chest-07',
        COMMUNITY_CHEST,
        'Vence tu fondo de vacaciones: recibí $100.',
        COLLECT_BANK,
        amount=100,
    ),
    Card(
        'community_chest-08',
        COMMUNITY_CHEST,
        'Devolución de impuestos: cobrá $20.',
        COLLECT_BANK,
        amount=20,
    ),
    Card(
        'community_chest-09',
        COMMUNITY_CHEST,
        'Es tu cumpleaños: cobrá $10 de cada jugador.',
        COLLECT_EACH_PLAYER,
        amount=10,
    ),
    Card(
        'community_chest-10',
        COMMUNITY_CHEST,
        'Vence tu seguro de vida: cobrá $100.',
        COLLECT_BANK,
        amount=100,
    ),
    Card(
        'community_chest-11',
        COMMUNITY_CHEST,
        'Pagá gastos de hospital: $100.',
        PAY_BANK,
        amount=100,
    ),
    Card(
        'community_chest-12',
        COMMUNITY_CHEST,
        'Pagá la cuota escolar: $50.',
        PAY_BANK,
        amount=50,
    ),
    Card(
        'community_chest-13',
        COMMUNITY_CHEST,
        'Cobrá $25 por servicios de consultoría.',
        COLLECT_BANK,
        amount=25,
    ),
    Card(
        'community_chest-14',
        COMMUNITY_CHEST,
        'Te cobran arreglos de calles: $40 por cada casa y $115 por cada hotel.',
        REPAIRS,
        per_house=40,
        per_hotel=115,
    ),
    Card(
        'community_chest-15',
        COMMUNITY_CHEST,
        'Ganaste el segundo premio del concurso de belleza: cobrá $10.',
        COLLECT_BANK,
        amount=10,
    ),
    Card(
        'community_chest-16',
        COMMUNITY_CHEST,
        'Recibís una herencia de $100.',
        COLLECT_BANK,
        amount=100,
    ),
)

_BY_ID = {card.id: card for card in CARDS}

_DECK_IDS = {
    deck: tuple(card.id for card in CARDS if card.deck == deck) for deck in DECKS
}

_DECK_CARDS = {
    deck: tuple(card for card in CARDS if card.deck == deck) for deck in DECKS
}


def card_for(card_id: str) -> Card:
    """Return the card with ``card_id``.

    Raises ``ValueError`` for an unknown id: a card the data does not hold
    cannot be resolved, and guessing would corrupt a match silently.
    """
    try:
        return _BY_ID[card_id]
    except KeyError:
        raise ValueError(f'unknown card: {card_id!r}') from None


def deck_ids(deck: str) -> tuple[str, ...]:
    """Return the ids of ``deck`` in printed order.

    This is the order a fresh deck is shuffled from, and the order
    ``test_monopoly_cards.py`` pins the whole table in.
    """
    try:
        return _DECK_IDS[deck]
    except KeyError:
        raise ValueError(f'unknown deck: {deck!r}') from None


def deck_cards(deck: str) -> tuple[Card, ...]:
    """Return the cards of ``deck`` in printed order."""
    try:
        return _DECK_CARDS[deck]
    except KeyError:
        raise ValueError(f'unknown deck: {deck!r}') from None


def deck_for_space(index: int) -> str | None:
    """Return the deck a space draws from, or ``None`` when it draws nothing."""
    from . import board

    space = board.space_at(index)
    if space.kind is board.SpaceKind.CHANCE:
        return CHANCE
    if space.kind is board.SpaceKind.COMMUNITY_CHEST:
        return COMMUNITY_CHEST
    return None

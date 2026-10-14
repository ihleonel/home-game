import type { Game } from '../api/types'

type GameCatalogProps = {
  games: Game[]
  busy: boolean
  hasSession: boolean
  onSelectGame: (game: Game) => void
}

export function GameCatalog({ games, busy, hasSession, onSelectGame }: GameCatalogProps) {
  return (
    <section className="catalog-section" aria-labelledby="catalog-title">
      <div className="section-intro">
        <p className="eyebrow">Catálogo de juegos</p>
        <h2 id="catalog-title">Elige a qué jugar</h2>
        <p>
          {hasSession
            ? 'Sal de la sala actual antes de elegir otro juego.'
            : 'Al elegir un juego, entras en la sala de ese juego.'}
        </p>
      </div>

      {games.length > 0 ? (
        <div className="game-grid">
          {games.map((game) => (
            <article className="game-card" key={game.id}>
              <div className="game-card-symbol" aria-hidden="true">
                {game.label.slice(0, 1)}
              </div>
              <h3>{game.label}</h3>
              <p>{game.description}</p>
              <div className="marker-options" aria-label={`Fichas de ${game.label}`}>
                {game.markers.map((marker) => (
                  <span className="marker-chip" key={marker.id}>{marker.label}</span>
                ))}
              </div>
              <button
                className="button button-primary"
                disabled={busy || hasSession}
                onClick={() => onSelectGame(game)}
                type="button"
              >
                Elegir juego
              </button>
            </article>
          ))}
        </div>
      ) : (
        <p className="quiet-copy">No hay juegos disponibles en este momento.</p>
      )}
    </section>
  )
}

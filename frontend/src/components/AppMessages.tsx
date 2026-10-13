type AppMessagesProps = {
  actionError: string | null
  connectionError: string | null
  voteNotice: string | null
  countdownNotice: string | null
}

/**
 * The four app-level notices, in the order they were always rendered.
 *
 * Presentational only: the app decides what each string says and when it is
 * cleared; this component decides nothing.
 */
export function AppMessages({
  actionError,
  connectionError,
  voteNotice,
  countdownNotice,
}: AppMessagesProps) {
  return (
    <>
      {actionError && <p className="message message-error" role="alert">{actionError}</p>}
      {connectionError && <p className="message message-error" role="status">{connectionError}</p>}
      {voteNotice && <p className="message message-info" role="status">{voteNotice}</p>}
      {countdownNotice && <p className="message message-info" role="status">{countdownNotice}</p>}
    </>
  )
}

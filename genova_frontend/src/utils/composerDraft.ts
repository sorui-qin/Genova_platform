/**
 * Input-box text to keep after a message was sent. `sent` is the text fixed when Send was pressed; anything typed
 * after it while the request was being prepared or sent stays as the next draft. When the sent part itself was
 * changed in the meantime, the whole current text is kept so nothing the user typed is lost.
 */
export function unsentRemainder(current: string, sent: string): string {
  if (!sent || !current.startsWith(sent)) return current
  return current.slice(sent.length).replace(/^\s+/, '')
}

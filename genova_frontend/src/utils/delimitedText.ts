// Keep values as arrays: duplicate/empty headers must not discard columns.
export function parseDelimitedText(content: string, delimiter = ',', skipBlankRecords = false): { headers: string[]; rows: string[][] } {
  const text = content.replace(/^\uFEFF/, '')
  const records: string[][] = []
  let row: string[] = [], cell = '', quoted = false, rowStart = 0
  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++ }
        else quoted = false
      } else cell += char
    } else if (char === '"' && !cell) quoted = true
    else if (char === delimiter) { row.push(cell); cell = '' }
    else if (char === '\r' || char === '\n') {
      row.push(cell)
      const raw = text.slice(rowStart, i)
      // Ignore leading blank lines, but retain explicit empty fields and all table data rows.
      if (raw.trim() || raw.includes(delimiter) || (records.length && !skipBlankRecords)) records.push(row)
      row = []; cell = ''
      if (char === '\r' && text[i + 1] === '\n') i++
      rowStart = i + 1
    } else cell += char
  }
  if (quoted) throw new Error('Unclosed quoted field')
  if (rowStart < text.length) {
    row.push(cell)
    const raw = text.slice(rowStart)
    if (raw.trim() || raw.includes(delimiter) || (records.length && !skipBlankRecords)) records.push(row)
  }
  const headers = records.shift() || []
  const width = records.reduce((max, record) => Math.max(max, record.length), headers.length)
  while (headers.length < width) headers.push('')
  return { headers, rows: records }
}

export type DelimitedTextIssue = {
  kind: 'unclosedQuote' | 'tabDelimiter' | 'commaDelimiter' | 'singleColumn' | 'noDataRows' | 'fullWidth'
  line?: number
  count?: number
}

// Full-width space and full-width forms of ASCII symbols, letters and digits. CJK characters and the
// sentence punctuation normally used in Chinese text (\uFF0C\uFF1A\uFF1B\uFF01\uFF1F = FF0C FF1A FF1B FF01 FF1F) are not flagged.
const FULL_WIDTH = /[\u3000\uFF02-\uFF0B\uFF0D-\uFF19\uFF1C-\uFF1E\uFF20-\uFF5E]/

/**
 * Problems a table preview should point out, with 1-based line numbers. `error` is set when quoting is broken:
 * a stray quote would otherwise pair with a later one and merge the lines in between into one cell.
 * Pass the parsed `table` to also report a file without data rows.
 */
export function inspectDelimitedText(content: string, delimiter = ',', table?: { headers: string[]; rows: string[][] }): { error: DelimitedTextIssue | null; warnings: DelimitedTextIssue[] } {
  const text = content.replace(/^\uFEFF/, '')
  let line = 1, quoteLine = 0, quoted = false, cellEmpty = true
  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    const lineBreak = char === '\n' || (char === '\r' && text[i + 1] !== '\n')
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') { i++; continue }
        quoted = false; cellEmpty = false
        const next = text[i + 1]
        // A closing quote must end the field; anything else means the opening quote was stray.
        if (next !== undefined && next !== delimiter && next !== '\r' && next !== '\n') return { error: { kind: 'unclosedQuote', line: quoteLine }, warnings: [] }
      } else if (lineBreak) line++
    } else if (char === '"' && cellEmpty) { quoted = true; quoteLine = line }
    else if (char === delimiter) cellEmpty = true
    else if (char === '\r' || char === '\n') { cellEmpty = true; if (lineBreak) line++ }
    else cellEmpty = false
  }
  if (quoted) return { error: { kind: 'unclosedQuote', line: quoteLine }, warnings: [] }

  const warnings: DelimitedTextIssue[] = []
  const lines = text.split(/\r\n|\r|\n/)
  const headerIndex = lines.findIndex(item => item.trim())
  if (headerIndex >= 0) {
    const header = lines[headerIndex]
    if (!header.includes(delimiter) && delimiter === ',' && header.includes('\t')) warnings.push({ kind: 'tabDelimiter', line: headerIndex + 1 })
    else if (!header.includes(delimiter) && delimiter === '\t' && header.includes(',')) warnings.push({ kind: 'commaDelimiter', line: headerIndex + 1 })
    else if (!text.includes(delimiter)) warnings.push({ kind: 'singleColumn' })
  }
  const fullWidthLines = lines.flatMap((item, index) => FULL_WIDTH.test(item) ? [index + 1] : [])
  if (fullWidthLines.length) warnings.push({ kind: 'fullWidth', line: fullWidthLines[0], count: fullWidthLines.length })
  if (table && !table.rows.length && table.headers.some(Boolean)) warnings.push({ kind: 'noDataRows' })
  return { error: null, warnings }
}

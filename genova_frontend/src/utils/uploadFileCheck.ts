import { translate } from '@/i18n'

// Shared by every upload entry so all file kinds use the same limit.
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024
export const MAX_FILENAME_BYTES = 255
const filenameEncoder = new TextEncoder()

export function filenameByteLength(name: string) {
  return filenameEncoder.encode(name).length
}
// Only the head of the file is read; this keeps the check well under a second.
export const UPLOAD_PROBE_BYTES = 64 * 1024

export type UploadCheckIssue = 'extension' | 'empty' | 'tooLarge' | 'filenameTooLong' | 'binary' | 'format' | 'unreadable'

// Every format accepted by the upload entries is plain text.
const TEXT_EXTENSIONS = new Set(['pdb', 'ent', 'cif', 'mmcif', 'sdf', 'mol', 'mol2', 'csv', 'tsv', 'txt'])
const PDB_MARKER = /^(ATOM|HETATM|HEADER|CRYST1|MODEL|REMARK|COMPND|TITLE|SEQRES|EXPDTA|SOURCE|KEYWDS|AUTHOR|CONECT)\b/m
const CIF_MARKER = /^\s*data_/m
const MOL_MARKER = /V[23]000|^M {2}END|^\$\$\$\$/m
// Content a file of the given extension must contain within the probed head.
const FORMAT_MARKERS: Record<string, RegExp> = {
  pdb: PDB_MARKER,
  ent: PDB_MARKER,
  cif: CIF_MARKER,
  mmcif: CIF_MARKER,
  sdf: MOL_MARKER,
  mol: MOL_MARKER,
  mol2: /@<TRIPOS>/i,
}
// Common binary signatures (images, PDF, archives, UTF-16 byte order marks).
const BINARY_SIGNATURES = [
  [0x89, 0x50, 0x4e, 0x47], [0xff, 0xd8, 0xff], [0x47, 0x49, 0x46, 0x38], [0x25, 0x50, 0x44, 0x46],
  [0x50, 0x4b, 0x03, 0x04], [0x50, 0x4b, 0x05, 0x06], [0x1f, 0x8b], [0x52, 0x61, 0x72, 0x21],
  [0x37, 0x7a, 0xbc, 0xaf], [0xff, 0xfe], [0xfe, 0xff],
]

export function fileExtension(name: string) {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : ''
}

function looksBinary(bytes: Uint8Array) {
  if (BINARY_SIGNATURES.some(signature => signature.every((byte, index) => bytes[index] === byte))) return true
  let control = 0
  for (const byte of bytes) {
    if (byte === 0) return true
    // Tab, line feed, form feed, carriage return and the DOS end-of-file marker are fine in text.
    if ((byte < 0x20 && ![0x09, 0x0a, 0x0c, 0x0d, 0x1a].includes(byte)) || byte === 0x7f) control++
  }
  return bytes.length > 0 && control / bytes.length > 0.01
}

/**
 * Pure content probe on the head of a file.
 * `complete` is true when `bytes` holds the whole file, so a whitespace-only head means an empty file.
 */
export function probeFileHead(bytes: Uint8Array, extension: string, complete: boolean): UploadCheckIssue | null {
  if (!TEXT_EXTENSIONS.has(extension)) return null
  if (looksBinary(bytes)) return 'binary'
  const text = new TextDecoder('utf-8').decode(bytes).replace(/^\uFEFF/, '')
  if (!text.trim()) return complete ? 'empty' : 'format'
  const marker = FORMAT_MARKERS[extension]
  return marker && !marker.test(text) ? 'format' : null
}

// An uploaded structure file needs main record lines; one holding only auxiliary record lines is another kind of file.
// At least one, not more: a very small real structure has only a few. Upload only: the preview still opens such files uploaded earlier.
function missingMainRecords(bytes: Uint8Array, extension: string, complete: boolean) {
  if (!['pdb', 'ent'].includes(extension)) return false
  const text = new TextDecoder('utf-8').decode(bytes).replace(/^﻿/, '')
  const main = text.match(/^ATOM[ \d].*$/gm) || []
  // ponytail: a file larger than the probed head is only rejected when its records start with no main record;
  // a long header may push every record past the head, and the server sees the whole file.
  if (!main.length) return complete || /^HETATM/m.test(text)
  // Main record lines where no line names a standard unit (columns 18-20) hold another kind of content. Whole files only:
  // a head may end before the first standard unit.
  return complete && !main.some(line => STANDARD_UNITS.has(line.slice(17, 20).trim()))
}

// The 20 standard units plus the nucleic-acid ones, so such files are not rejected.
const STANDARD_UNITS = new Set('ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL A C G U I DA DC DG DT DU DI'.split(' '))

/** Extension, size, emptiness and a light content probe; resolves to null when the file may be uploaded. */
export async function checkUploadFile(file: File, allowedExtensions: readonly string[]): Promise<UploadCheckIssue | null> {
  if (filenameByteLength(file.name) > MAX_FILENAME_BYTES) return 'filenameTooLong'
  const extension = fileExtension(file.name)
  if (!allowedExtensions.includes(extension)) return 'extension'
  if (file.size === 0) return 'empty'
  if (file.size > MAX_UPLOAD_BYTES) return 'tooLarge'
  try {
    const head = new Uint8Array(await file.slice(0, UPLOAD_PROBE_BYTES).arrayBuffer())
    const complete = file.size <= UPLOAD_PROBE_BYTES
    return probeFileHead(head, extension, complete) || (missingMainRecords(head, extension, complete) ? 'format' : null)
  } catch {
    return 'unreadable'
  }
}

export function uploadCheckMessage(issue: UploadCheckIssue, fileName = '') {
  if (issue === 'filenameTooLong') return translate('platform.structureErrors.FILENAME_TOO_LONG')
  return translate(`platform.uploadCheck.${issue}`, { ext: fileExtension(fileName), limit: MAX_UPLOAD_BYTES / 1024 / 1024 })
}

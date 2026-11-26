import { parseDelimitedText } from './delimitedText'

type RDKitMol = {
  get_smiles: () => string
  get_json: () => string
  get_svg: () => string
  get_svg_with_highlights?: (detailsJson: string) => string
  get_substruct_match?: (qmol: RDKitMol) => string
  delete: () => void
}

type RDKitModule = {
  get_mol: (input: string, detailsJson?: string) => RDKitMol
  get_qmol?: (smarts: string) => RDKitMol
}

declare global {
  interface Window {
    initRDKitModule?: (options?: { locateFile?: (fileName: string) => string }) => Promise<RDKitModule>
  }
}

const RDKIT_SCRIPT_ID = 'rdkit-minimal-lib-script'
const APP_BASE = import.meta.env.BASE_URL || '/'

function joinBase(base: string, path: string): string {
  const normalizedBase = base.endsWith('/') ? base : `${base}/`
  const normalizedPath = path.startsWith('/') ? path.slice(1) : path
  return `${normalizedBase}${normalizedPath}`
}

const RDKIT_SCRIPT_URL = joinBase(APP_BASE, 'vendor/rdkit/RDKit_minimal.js')
const RDKIT_WASM_URL = joinBase(APP_BASE, 'vendor/rdkit/RDKit_minimal.wasm')

let scriptPromise: Promise<void> | null = null
let modulePromise: Promise<RDKitModule> | null = null

export function getFirstMoleculeInput(content: string, filename: string): string {
  const ext = filename.toLowerCase().split('.').pop()
  if (ext === 'sdf') return content.split('$$$$')[0]
  if (ext === 'mol') return content

  const lines = content.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (!lines.length) return ''
  if (ext === 'smi') {
    const first = lines[0].split(/\s+/)[0]
    return first.toLowerCase() === 'smiles' ? (lines[1]?.split(/\s+/)[0] || '') : first
  }

  if (['csv', 'tsv', 'txt'].includes(ext || '')) {
    try {
      const delimiter = ext === 'tsv' || (ext === 'txt' && lines[0].includes('\t')) ? '\t' : ','
      const { headers, rows } = parseDelimitedText(content, delimiter, true)
      const smilesIndex = headers.findIndex(value => ['smiles', 'smiles_canonical', 'gen_smiles'].includes(value.trim().toLowerCase()))
      return (rows[0]?.[smilesIndex] || '').trim()
    } catch { return '' }
  }

  return ''
}

function loadScriptOnce(): Promise<void> {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('RDKit.js only works in browser context'))
  }
  if (window.initRDKitModule) {
    return Promise.resolve()
  }
  if (scriptPromise) {
    return scriptPromise
  }

  scriptPromise = new Promise((resolve, reject) => {
    const existing = document.getElementById(RDKIT_SCRIPT_ID) as HTMLScriptElement | null
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true })
      existing.addEventListener('error', () => reject(new Error('Failed to load RDKit.js script')), { once: true })
      return
    }

    const script = document.createElement('script')
    script.id = RDKIT_SCRIPT_ID
    script.src = RDKIT_SCRIPT_URL
    script.async = true
    script.onload = () => {
      if (window.initRDKitModule) {
        resolve()
      } else {
        reject(new Error('RDKit.js script loaded but init function not found'))
      }
    }
    script.onerror = () => reject(new Error('Failed to load RDKit.js script'))
    document.head.appendChild(script)
  })

  return scriptPromise
}

export async function getRDKitModule(): Promise<RDKitModule> {
  if (modulePromise) {
    return modulePromise
  }

  await loadScriptOnce()
  if (!window.initRDKitModule) {
    throw new Error('RDKit.js init function is unavailable')
  }

  modulePromise = window.initRDKitModule({
    locateFile: (fileName: string) => {
      if (fileName.endsWith('.wasm')) {
        return RDKIT_WASM_URL
      }
      return fileName
    },
  })
  return modulePromise
}

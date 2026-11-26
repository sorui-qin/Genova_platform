// navigator.clipboard exists only in secure contexts (HTTPS or localhost). On plain-HTTP deployments the
// legacy copy command is used instead, so copying still works there.
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return } catch { /* fall back to the legacy command below */ }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  try {
    if (!document.execCommand('copy')) throw new Error('copy command was rejected')
  } finally {
    area.remove()
  }
}

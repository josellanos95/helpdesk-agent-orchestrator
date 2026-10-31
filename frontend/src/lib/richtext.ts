export type Block = { type: 'p'; text: string } | { type: 'ul' | 'ol'; items: string[] }

export function parseBlocks(source: string): Block[] {
  const blocks: Block[] = []
  for (const chunk of source.trim().split(/\n{2,}/)) {
    const lines = chunk.split('\n').map((l) => l.trimEnd())
    const bullet = lines.every((l) => /^\s*[-*•]\s+/.test(l))
    const numbered = lines.every((l) => /^\s*\d+[.)]\s+/.test(l))
    if (bullet) blocks.push({ type: 'ul', items: lines.map((l) => l.replace(/^\s*[-*•]\s+/, '')) })
    else if (numbered) blocks.push({ type: 'ol', items: lines.map((l) => l.replace(/^\s*\d+[.)]\s+/, '')) })
    else blocks.push({ type: 'p', text: lines.join('\n') })
  }
  return blocks
}

/** The agent's markdown flattened to one plain line, for previews. */
export function plainText(source: string): string {
  return source
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*(?:[-*•]|\d+[.)])\s+/gm, '')
    .replace(/:\s*-\s+/g, ': ')
    .replace(/\s+/g, ' ')
    .trim()
}

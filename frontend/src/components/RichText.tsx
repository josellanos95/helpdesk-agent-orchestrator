import { Fragment, type ReactNode } from 'react'
import { parseBlocks } from '../lib/richtext'

// The agent writes light markdown (paragraphs, lists, **bold**, `code`). Rendered as React nodes, never as
// HTML, so nothing the model or a knowledge-base article says can inject markup.

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) return <code key={i}>{part.slice(1, -1)}</code>
    return <Fragment key={i}>{part}</Fragment>
  })
}

export function RichText({ text }: { text: string }) {
  return (
    <div className="prose lc-text">
      {parseBlocks(text).map((block, i) => {
        if (block.type === 'p') {
          return (
            <p key={i} style={{ whiteSpace: 'pre-line' }}>
              {inline(block.text)}
            </p>
          )
        }
        const List = block.type
        return (
          <List key={i}>
            {block.items.map((item, j) => (
              <li key={j}>{inline(item)}</li>
            ))}
          </List>
        )
      })}
    </div>
  )
}

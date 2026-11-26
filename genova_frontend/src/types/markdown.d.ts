declare module 'markdown-it' {
  interface Token {
    attrs: [string, string][] | null
    attrIndex(name: string): number
    attrPush(attr: [string, string]): void
  }

  type RenderRule = (tokens: Token[], index: number, options: MarkdownItOptions, env: unknown, self: Renderer) => string

  interface Renderer {
    rules: Record<string, RenderRule | undefined>
    renderToken(tokens: Token[], index: number, options: MarkdownItOptions): string
  }

  interface MarkdownIt {
    render(src: string): string
    renderer: Renderer
  }
  
  interface MarkdownItOptions {
    html?: boolean
    linkify?: boolean
    typographer?: boolean
    breaks?: boolean
    langPrefix?: string
    highlight?: (str: string, lang: string) => string
  }
  
  const markdownit: {
    (options?: MarkdownItOptions): MarkdownIt
    new (options?: MarkdownItOptions): MarkdownIt
  }
  
  export = markdownit
}

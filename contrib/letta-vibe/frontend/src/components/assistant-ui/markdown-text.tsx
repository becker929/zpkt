'use client'

import { type FC } from 'react'
import { MarkdownTextPrimitive, type MarkdownTextPrimitiveProps } from '@assistant-ui/react-markdown'
import { SyntaxHighlighter } from './syntax-highlighter'
import remarkGfm from 'remark-gfm'

const REMARK_PLUGINS = [remarkGfm]

export const MarkdownText: FC<Omit<MarkdownTextPrimitiveProps, 'components'>> = (props) => (
  <MarkdownTextPrimitive
    components={{ SyntaxHighlighter }}
    remarkPlugins={REMARK_PLUGINS}
    {...props}
  />
)

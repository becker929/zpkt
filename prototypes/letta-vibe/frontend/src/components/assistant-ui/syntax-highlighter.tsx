'use client'

import { makePrismAsyncLightSyntaxHighlighter } from '@assistant-ui/react-syntax-highlighter'
import { coldarkDark } from 'react-syntax-highlighter/dist/cjs/styles/prism'

export const SyntaxHighlighter = makePrismAsyncLightSyntaxHighlighter({
  style: coldarkDark,
  customStyle: {
    margin: 0,
    borderRadius: '0.375rem',
    fontSize: '0.8125rem',
    background: 'hsl(240 8% 5%)',
  },
})

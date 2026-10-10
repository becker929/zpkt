import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'
import Providers from './providers'
import { AgentDetailsProvider } from '@/components/ui/agent-details'
import { SidebarProvider } from '@/components/ui/sidebar'
import ContentLayout from './content-layout'
import { DialogContextProvider } from '@/components/ui/agent-dialog'

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin']
})

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin']
})

export const metadata: Metadata = {
  title: 'Vibe — AI Music Feedback',
  description:
    'Bounce audio from Ableton, listen, and give natural-language feedback. Powered by Letta.'
}

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang='en' className='dark' suppressHydrationWarning>
      <body suppressHydrationWarning
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <Providers>
          <DialogContextProvider>
            <SidebarProvider>
              <AgentDetailsProvider>
                <ContentLayout>{children}</ContentLayout>
              </AgentDetailsProvider>
            </SidebarProvider>
          </DialogContextProvider>
        </Providers>
      </body>
    </html>
  )
}

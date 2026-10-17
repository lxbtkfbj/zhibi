import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { SiteLayout } from './components/Layout'
import './index.css'
import { BookLayout } from './pages/book/BookLayout'
import { ForeshadowingPage, RelationsPage } from './pages/book/sections/BiblePages'
import { ChapterPage, ContentsPage } from './pages/book/sections/ChapterPages'
import { Overview } from './pages/book/sections/Overview'
import { NextSegmentPage } from './pages/book/sections/NextSegmentPage'
import { SecretsPage } from './pages/book/sections/SecretsPage'
import { StoryPage } from './pages/book/sections/StoryPage'
import { LibraryPage } from './pages/book/sections/LibraryPage'
import { OutlinePage } from './pages/book/sections/OutlinePage'
import { LegacyBookRoute } from './pages/book/LegacyBookRoute'
import { Home } from './pages/Home'
import { BookSettingsPage } from './pages/BookSettingsPage'
import { AppearanceProvider } from './lib/appearance'
import { SettingsHost } from './lib/settingsModal'

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 5_000, retry: 1 } },
})

const router = createBrowserRouter([
 { element: <SettingsHost />, children: [
  {
    element: <SiteLayout />,
    children: [
      { path: '/', element: <Home /> },
      { path: '/settings', element: <Navigate to="/" replace state={{ openSettings: true }} /> },
      { path: '/prompts', lazy: async () => ({ Component: (await import('./pages/PromptsPage')).PromptsPage }) },
    ],
  },
  {
    path: '/books/:bookId',
    element: <BookLayout />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'concept', element: <StoryPage /> },
      { path: 'library', element: <LibraryPage /> },
      { path: 'outline', element: <OutlinePage /> },
      { path: 'protagonist', element: <LegacyBookRoute /> },
      { path: 'spine', element: <LegacyBookRoute /> },
      { path: 'next-segment', element: <NextSegmentPage /> },
      { path: 'threads', element: <LegacyBookRoute /> },
      { path: 'chapters', element: <ContentsPage /> },
      { path: 'chapter/:index', element: <ChapterPage /> },
      { path: 'volume/:index', element: <LegacyBookRoute /> },
      { path: 'characters', element: <LegacyBookRoute /> },
      { path: 'world', element: <LegacyBookRoute /> },
      { path: 'relations', element: <RelationsPage /> },
      { path: 'foreshadowing', element: <ForeshadowingPage /> },
      { path: 'secrets', element: <SecretsPage /> },
      { path: 'settings', element: <BookSettingsPage /> },
      { path: 'meeting', element: <Navigate to=".." relative="path" replace /> },
    ],
  },
 ] },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppearanceProvider>
        <RouterProvider router={router} />
      </AppearanceProvider>
    </QueryClientProvider>
  </StrictMode>,
)

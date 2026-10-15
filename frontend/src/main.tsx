import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { SiteLayout } from './components/Layout'
import './index.css'
import { BookLayout } from './pages/book/BookLayout'
import { CharactersPage, ForeshadowingPage, RelationsPage, WorldPage } from './pages/book/sections/BiblePages'
import { ChapterPage, ContentsPage } from './pages/book/sections/ChapterPages'
import { ConceptPage } from './pages/book/sections/ConceptPage'
import { Overview } from './pages/book/sections/Overview'
import { SpinePage } from './pages/book/sections/SpinePage'
import { ThreadsPage } from './pages/book/sections/ThreadsPage'
import { VolumePage } from './pages/book/sections/VolumePage'
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
      { path: 'concept', element: <ConceptPage /> },
      { path: 'spine', element: <SpinePage /> },
      { path: 'threads', element: <ThreadsPage /> },
      { path: 'chapters', element: <ContentsPage /> },
      { path: 'chapter/:index', element: <ChapterPage /> },
      { path: 'volume/:index', element: <VolumePage /> },
      { path: 'characters', element: <CharactersPage /> },
      { path: 'world', element: <WorldPage /> },
      { path: 'relations', element: <RelationsPage /> },
      { path: 'foreshadowing', element: <ForeshadowingPage /> },
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

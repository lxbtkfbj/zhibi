import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'motion/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { SiteLayout } from './components/Layout'
import './index.css'
import { BookLayout } from './pages/book/BookLayout'
import { CharactersPage, ForeshadowingPage, RelationsPage, WorldPage } from './pages/book/sections/BiblePages'
import { ChapterPage, ContentsPage } from './pages/book/sections/ChapterPages'
import { ConceptPage } from './pages/book/sections/ConceptPage'
import { MeetingLogPage } from './pages/book/sections/MeetingLogPage'
import { Overview } from './pages/book/sections/Overview'
import { SpinePage } from './pages/book/sections/SpinePage'
import { ThreadsPage } from './pages/book/sections/ThreadsPage'
import { VolumePage } from './pages/book/sections/VolumePage'
import { Home } from './pages/Home'
import { SettingsPage } from './pages/SettingsPage'

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, staleTime: 5_000, retry: 1 } },
})

const router = createBrowserRouter([
  {
    element: <SiteLayout />,
    children: [
      { path: '/', element: <Home /> },
      { path: '/settings', element: <SettingsPage /> },
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
      { path: 'meeting', element: <MeetingLogPage /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">
        <RouterProvider router={router} />
      </MotionConfig>
    </QueryClientProvider>
  </StrictMode>,
)

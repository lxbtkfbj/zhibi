import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { SiteLayout } from './components/Layout'
// 自带思源宋体：Windows 上没装的话会退回又细又飘的老宋体。只下载页面上用到的字
import '@fontsource/noto-serif-sc/400.css'
import '@fontsource/noto-serif-sc/700.css'
import './index.css'
import { BookLayout } from './pages/book/BookLayout'
import { ChapterPage, ContentsPage } from './pages/book/sections/ChapterPages'
import { StoryPage } from './pages/book/sections/StoryPage'
import { LibraryPage } from './pages/book/sections/LibraryPage'
import { OutlinePage } from './pages/book/sections/OutlinePage'
import { LegacyBookRoute } from './pages/book/LegacyBookRoute'
import { Home } from './pages/Home'
import { NewBookPage } from './pages/NewBook'
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
      { path: '/new', element: <NewBookPage /> },
      { path: '/settings', element: <Navigate to="/" replace state={{ openSettings: true }} /> },
      { path: '/prompts', lazy: async () => ({ Component: (await import('./pages/PromptsPage')).PromptsPage }) },
    ],
  },
  // 新书页：简介、设定、大纲；没搬过来的功能还在旧版 /books/:bookId 里
  { path: '/desk/:bookId', lazy: async () => ({ Component: (await import('./pages/workspace/BookDesk')).BookDesk }) },
  // 工作台原型：同一套界面，示例书和快照，改了不存
  { path: '/prototype/workspace', lazy: async () => ({ Component: (await import('./pages/workspace/WorkspacePrototype')).WorkspacePrototype }) },
  {
    path: '/books/:bookId',
    element: <BookLayout />,
    children: [
      { index: true, element: <StoryPage /> },
      { path: 'concept', element: <StoryPage /> },
      { path: 'library', element: <LibraryPage /> },
      { path: 'outline', element: <OutlinePage /> },
      { path: 'protagonist', element: <LegacyBookRoute /> },
      { path: 'spine', element: <LegacyBookRoute /> },
      { path: 'next-segment', element: <LegacyBookRoute /> },
      { path: 'threads', element: <LegacyBookRoute /> },
      { path: 'chapters', element: <ContentsPage /> },
      { path: 'chapter/:index', element: <ChapterPage /> },
      { path: 'volume/:index', element: <LegacyBookRoute /> },
      { path: 'characters', element: <LegacyBookRoute /> },
      { path: 'world', element: <LegacyBookRoute /> },
      { path: 'relations', element: <Navigate to="../library?cat=%E8%A7%92%E8%89%B2%E5%8D%A1%E7%89%87" relative="path" replace /> },
      { path: 'foreshadowing', element: <Navigate to="../outline?view=threads" relative="path" replace /> },
      { path: 'secrets', element: <Navigate to="../library?cat=%E5%BE%80%E4%BA%8B%E4%B8%8E%E7%A7%98%E5%AF%86" relative="path" replace /> },
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

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom'
import { SiteLayout } from './components/Layout'
// 自带思源宋体：Windows 上没装的话会退回又细又飘的老宋体。只下载页面上用到的字
import '@fontsource/noto-serif-sc/400.css'
import '@fontsource/noto-serif-sc/600.css'
import '@fontsource/noto-serif-sc/700.css'
import './index.css'
import './styles/desk-v2-host.css'
import './styles/desk-v2.css'
import './styles/desk-v2-dark.css'
import { Home } from './pages/Home'
import { NewBookPage } from './pages/NewBook'
import { TeardownAppendPage, TeardownConfirmPage, TeardownUploadPage } from './pages/Teardown'
import { OldBookRedirect } from './pages/OldBookRedirect'
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
      { path: '/teardown/new', element: <TeardownUploadPage /> },
      { path: '/teardown/:bookId', element: <TeardownConfirmPage /> },
      { path: '/teardown/:bookId/append', element: <TeardownAppendPage /> },
      { path: '/settings', element: <Navigate to="/" replace state={{ openSettings: true }} /> },
    ],
  },
  // 提示词与调用记录使用独立书页外壳；URL 中保留原书的返回上下文。
  { path: '/prompts', lazy: async () => ({ Component: (await import('./pages/PromptsPage')).PromptsPage }) },
  { path: '/presets', lazy: async () => ({ Component: (await import('./pages/PresetsPage')).PresetsPage }) },
  { path: '/handbooks', lazy: async () => ({ Component: (await import('./pages/HandbooksPage')).HandbooksPage }) },
  // 书页：简介、设定、大纲、正文；编辑部、存档、待处理、本书设置都在这一页上
  { path: '/desk/:bookId', lazy: async () => ({ Component: (await import('./pages/workspace/BookDesk')).BookDesk }) },
  // 工作台原型：同一套界面，示例书和快照，改了不存
  { path: '/prototype/workspace', lazy: async () => ({ Component: (await import('./pages/workspace/WorkspacePrototype')).WorkspacePrototype }) },
  // 旧版书页退役：以前的地址都到书页
  { path: '/books/:bookId/*', element: <OldBookRedirect /> },
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

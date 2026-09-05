import { createBrowserRouter } from 'react-router'
import { RootLayout } from '@/pages/RootLayout'
import { RouteError } from '@/pages/RouteError'
import { SectionPage } from '@/pages/SectionPage'

export const router = createBrowserRouter([
  {
    path: '/',
    Component: RootLayout,
    ErrorBoundary: RouteError,
    children: [
      { index: true, Component: SectionPage },
      { path: 's/:sectionId', Component: SectionPage },
      { path: '*', Component: SectionPage },
    ],
  },
])

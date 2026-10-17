import { Navigate, useLocation, useParams } from 'react-router-dom'
import { legacyBookRoute } from '../../lib/bookRoutes'

export function LegacyBookRoute() {
  const { bookId } = useParams()
  const location = useLocation()
  const base = `/books/${bookId}/`
  return <Navigate replace to={`${base}${legacyBookRoute(location.pathname.slice(base.length)) ?? ''}${location.hash}`} />
}

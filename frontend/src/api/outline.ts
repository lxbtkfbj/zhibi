import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { del, get, patch, post } from './client'
import type { OutlineTree } from '../lib/outlineTree'

export const outlineTreeKey = (bookId: string) => ['outline-tree', bookId] as const

export function useOutlineTree(bookId: string) {
  return useQuery({ queryKey: outlineTreeKey(bookId), queryFn: () => get<OutlineTree>(`/books/${bookId}/outline-tree`) })
}

type OutlineChange =
  | { action: 'patch'; kind: 'segment' | 'volume' | 'unit' | 'ending'; id: string; body: Record<string, unknown> }
  | { action: 'add-unit'; volumeId: string; title: string; summary: string; chapter_count: number; after_unit_id: string | null }
  | { action: 'remove-unit'; id: string }
  | { action: 'order-units'; volumeId: string; ids: string[] }
  | { action: 'add-volume'; title: string; summary: string; chapter_count: number; target_node_id: string | null; after_volume_id: string | null }
  | { action: 'remove-volume'; id: string }

export function useOutlineChanges(bookId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (change: OutlineChange): Promise<unknown> => {
      switch (change.action) {
        case 'patch': {
          const { kind, id, body } = change
          return patch(`/${kind === 'segment' || kind === 'ending' ? 'nodes' : kind === 'volume' ? 'volumes' : 'units'}/${id}`, kind === 'segment' ? { segment: body } : body)
        }
        case 'add-unit': {
          const { volumeId, action: _, ...body } = change
          return post(`/volumes/${volumeId}/units`, body)
        }
        case 'remove-unit': return del(`/units/${change.id}`)
        case 'order-units': return post(`/volumes/${change.volumeId}/units/order`, { ids: change.ids })
        case 'add-volume': {
          const { action: _, ...body } = change
          return post(`/books/${bookId}/volumes`, body)
        }
        case 'remove-volume': return del(`/volumes/${change.id}`)
      }
    },
    onSuccess: async () => {
      await Promise.all(['outline-tree', 'outline', 'nodes', 'chapters', 'book', 'library-versions'].map(key => qc.invalidateQueries({ queryKey: [key, bookId] })))
    },
  })
}

import React, { useEffect, useRef, useState } from 'react'
import { DialogButton, Focusable, ModalRoot, Spinner, TextField } from '@decky/ui'
import { call } from '@decky/api'
import { EqState, HeadphoneSearchResult } from '../interfaces'

interface HeadphoneSearchModalProps {
  closeModal?: () => void
  onAdded: (state: EqState) => void
}

const SEARCH_DELAY_MS = 400

/**
 * Searches the AutoEq database and adds the chosen headphones (downloaded once, then kept offline).
 */
const HeadphoneSearchModal: React.FC<HeadphoneSearchModalProps> = ({ closeModal, onAdded }) => {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<HeadphoneSearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [adding, setAdding] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const searchId = useRef(0)

  useEffect(() => {
    const id = ++searchId.current
    if (query.trim().length < 2) {
      setResults([])
      setSearching(false)
      return
    }
    setSearching(true)
    const timer = setTimeout(async () => {
      try {
        const response = await call<[string], { ok: boolean; results: HeadphoneSearchResult[]; error?: string }>(
          'search_headphones',
          query,
        )
        if (id !== searchId.current) return
        setResults(response.results ?? [])
        setError(response.ok ? null : response.error ?? 'Search failed')
      } catch (e) {
        if (id === searchId.current) setError('Search failed')
      } finally {
        if (id === searchId.current) setSearching(false)
      }
    }, SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [query])

  const add = async (result: HeadphoneSearchResult) => {
    setAdding(result.id)
    setError(null)
    try {
      const response = await call<[string], { ok: boolean; state?: EqState; error?: string }>(
        'add_headphone_profile',
        result.id,
      )
      if (response.ok && response.state) {
        onAdded(response.state)
        closeModal?.()
        return
      }
      setError(response.error ?? 'Download failed')
    } catch (e) {
      setError('Download failed')
    } finally {
      setAdding(null)
    }
  }

  return (
    <ModalRoot closeModal={closeModal}>
      <div style={{ fontSize: '20px', fontWeight: 600, marginBottom: '8px' }}>Add headphones</div>
      <TextField
        label="Search AutoEq"
        value={query}
        focusOnMount
        bShowClearAction
        onChange={(e) => setQuery(e.target.value)}
      />
      <div style={{ minHeight: '24px', margin: '8px 0', fontSize: '13px', opacity: 0.7 }}>
        {searching ? <Spinner style={{ width: '18px', height: '18px' }} /> : error ?? (query.trim().length >= 2 && results.length === 0 ? 'No headphones found' : '')}
      </div>
      <Focusable style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '50vh', overflowY: 'auto' }}>
        {results.map((result) => (
          <DialogButton
            key={result.id}
            disabled={adding !== null}
            onClick={() => add(result)}
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', textAlign: 'left', padding: '8px 12px' }}
          >
            <span>
              <div>{result.name}</div>
              <div style={{ fontSize: '12px', opacity: 0.6 }}>
                {result.recommended ? '★ Recommended · ' : ''}{result.form} · {result.source}
              </div>
            </span>
            {adding === result.id && <Spinner style={{ width: '18px', height: '18px' }} />}
          </DialogButton>
        ))}
      </Focusable>
    </ModalRoot>
  )
}

export default HeadphoneSearchModal

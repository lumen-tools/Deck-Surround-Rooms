import React, { useEffect, useState } from 'react'
import { ButtonItem, Dropdown, Field, PanelSection, PanelSectionRow, showModal, ToggleField } from '@decky/ui'
import { call, openFilePicker, toaster } from '@decky/api'
import { EqState } from '../interfaces'
import HeadphoneSearchModal from './HeadphoneSearchModal'
import EqCurve from './EqCurve'

const ADD_OPTION = '__add_headphones__'
const IMPORT_OPTION = '__import_file__'

/** Headphone EQ section of the main page: on/off switch and the saved headphones. */
const HeadphoneEq: React.FC = () => {
  const [state, setState] = useState<EqState | null>(null)
  const [busy, setBusy] = useState(false)
  // Bumped after the 'Add headphones…' / 'Import file…' entries, so the dropdown shows the active
  // headphones again instead of the action entry (also when the action is cancelled).
  const [dropdownKey, setDropdownKey] = useState(0)

  useEffect(() => {
    // Polled: the EQ pauses by itself when no headphones are connected, or when another output is chosen in Steam.
    const load = () => call<[], EqState>('get_eq_state').then(setState).catch((error) => {
      console.error('[decky-virtual-surround-rooms:HeadphoneEq] Error loading EQ state:', error)
    })
    load()
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [])

  const openSearch = () => {
    showModal(<HeadphoneSearchModal onAdded={setState} />)
  }

  // Offline alternative to the search: import an AutoEq "<headphones> ParametricEQ.txt" file.
  const importFile = async () => {
    try {
      const startPath = await call<[], string>('get_eq_import_start_path')
      // 0 = FileSelectionType.FILE
      const picked = await openFilePicker(0, startPath, true, true)
      if (!picked?.realpath) return
      setBusy(true)
      const result = await call<[string], { ok: boolean; state?: EqState; error?: string; warning?: string }>(
        'import_headphone_profile',
        picked.realpath,
      )
      if (result.ok && result.state) {
        setState(result.state)
        if (result.warning) toaster.toast({ title: 'Headphone EQ', body: result.warning })
      } else {
        toaster.toast({ title: 'Import failed', body: result.error ?? 'Not an AutoEq ParametricEQ file' })
      }
    } catch (error) {
      // The picker throws when it is closed without choosing a file.
      console.log('[decky-virtual-surround-rooms:HeadphoneEq] Import cancelled or failed:', error)
    } finally {
      setBusy(false)
    }
  }

  const run = async (fn: () => Promise<EqState>) => {
    setBusy(true)
    try {
      setState(await fn())
    } catch (error) {
      console.error('[decky-virtual-surround-rooms:HeadphoneEq] Error:', error)
    } finally {
      setBusy(false)
    }
  }

  if (!state) return null
  const hasProfiles = state.profiles.length > 0

  return (
    <PanelSection title="Headphone EQ">
      {hasProfiles ? (
        <>
          <PanelSectionRow>
            <ToggleField
              label="AutoEq"
              checked={state.enabled}
              disabled={busy}
              onChange={(enabled) => run(() => call<[boolean], EqState>('set_eq_enabled', enabled))}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <Field label="Headphones" childrenLayout="below" childrenContainerWidth="max" bottomSeparator="none">
              <Dropdown
                key={dropdownKey}
                rgOptions={[
                  ...state.profiles.map((profile) => ({ label: profile.label, data: profile.id })),
                  { label: 'Add headphones…', data: ADD_OPTION },
                  { label: 'Import file…', data: IMPORT_OPTION },
                ]}
                selectedOption={state.active}
                disabled={busy}
                onChange={(option) => {
                  if (option.data === ADD_OPTION) {
                    setDropdownKey((k) => k + 1)
                    openSearch()
                    return
                  }
                  if (option.data === IMPORT_OPTION) {
                    setDropdownKey((k) => k + 1)
                    importFile()
                    return
                  }
                  run(() => call<[string], EqState>('set_eq_profile', option.data))
                }}
              />
            </Field>
          </PanelSectionRow>
          {state.curve && (
            <PanelSectionRow>
              <EqCurve curve={state.curve} enabled={state.enabled} />
            </PanelSectionRow>
          )}
        </>
      ) : (
        <>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={openSearch}>
              Add headphones
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={busy} onClick={importFile}>
              Import file
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
    </PanelSection>
  )
}

export default HeadphoneEq

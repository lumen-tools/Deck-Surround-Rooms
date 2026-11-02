import React, { useEffect, useState } from 'react'
import { ButtonItem, Dropdown, Field, PanelSection, PanelSectionRow, showModal, ToggleField } from '@decky/ui'
import { call } from '@decky/api'
import { EqState } from '../interfaces'
import HeadphoneSearchModal from './HeadphoneSearchModal'

const ADD_OPTION = '__add_headphones__'

/** Headphone EQ section of the main page: on/off switch and the saved headphones. */
const HeadphoneEq: React.FC = () => {
  const [state, setState] = useState<EqState | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    call<[], EqState>('get_eq_state').then(setState).catch((error) => {
      console.error('[decky-virtual-surround-rooms:HeadphoneEq] Error loading EQ state:', error)
    })
  }, [])

  const openSearch = () => {
    showModal(<HeadphoneSearchModal onAdded={setState} />)
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
                rgOptions={[
                  ...state.profiles.map((profile) => ({ label: profile.label, data: profile.id })),
                  { label: 'Add headphones…', data: ADD_OPTION },
                ]}
                selectedOption={state.active}
                disabled={busy}
                onChange={(option) => {
                  if (option.data === ADD_OPTION) {
                    openSearch()
                    return
                  }
                  run(() => call<[string], EqState>('set_eq_profile', option.data))
                }}
              />
            </Field>
          </PanelSectionRow>
        </>
      ) : (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={openSearch}>
            Add headphones
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  )
}

export default HeadphoneEq

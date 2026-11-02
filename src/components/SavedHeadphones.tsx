import React, { useEffect, useState } from 'react'
import { DialogButton, Field, PanelSection, PanelSectionRow } from '@decky/ui'
import { call } from '@decky/api'
import { EqState } from '../interfaces'

/** Settings page: list of the downloaded headphone EQ profiles with a remove button each. */
const SavedHeadphones: React.FC = () => {
  const [state, setState] = useState<EqState | null>(null)

  useEffect(() => {
    call<[], EqState>('get_eq_state').then(setState).catch(() => undefined)
  }, [])

  if (!state || state.profiles.length === 0) return null

  return (
    <PanelSection title="Saved Headphones">
      {state.profiles.map((profile) => (
        <PanelSectionRow key={profile.id}>
          <Field label={profile.label} childrenLayout="below" bottomSeparator="none">
            <DialogButton
              style={{ minWidth: 0, padding: '4px 12px' }}
              onClick={async () => setState(await call<[string], EqState>('remove_headphone_profile', profile.id))}
            >
              Remove
            </DialogButton>
          </Field>
        </PanelSectionRow>
      ))}
    </PanelSection>
  )
}

export default SavedHeadphones

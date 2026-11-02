import React, { useEffect, useState } from 'react'
import { Dropdown, Field, PanelSectionRow } from '@decky/ui'
import { call } from '@decky/api'

interface Outputs {
  selected: string | null
  outputs: { name: string; label: string }[]
}

/** Output device for surround/EQ. Only external outputs; the internal speakers are never offered. */
const OutputSelect: React.FC = () => {
  const [outputs, setOutputs] = useState<Outputs | null>(null)

  useEffect(() => {
    const load = () => call<[], Outputs>('get_outputs').then(setOutputs).catch(() => undefined)
    load()
    const timer = setInterval(load, 3000)
    return () => clearInterval(timer)
  }, [])

  if (!outputs) return null
  return (
    <PanelSectionRow>
      <Field label="Output" childrenLayout="below" childrenContainerWidth="max" bottomSeparator="none">
        <Dropdown
          rgOptions={outputs.outputs.map((o) => ({ label: o.label, data: o.name }))}
          selectedOption={outputs.selected}
          strDefaultLabel="No headphones connected"
          disabled={outputs.outputs.length === 0}
          onChange={async (option) => setOutputs(await call<[string], Outputs>('set_output', option.data))}
        />
      </Field>
    </PanelSectionRow>
  )
}

export default OutputSelect

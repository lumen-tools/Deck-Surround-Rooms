import React, { useEffect, useRef, useState } from 'react'
import { call } from '@decky/api'

// Order of the levels returned by the backend (get_channel_levels).
const METER_CHANNELS = ['FL', 'FR', 'FC', 'LFE', 'RL', 'RR', 'SL', 'SR']
// Speaker layout as seen from above, listener in the middle.
const LAYOUT: (string | null)[] = ['FL', 'FC', 'FR', 'SL', null, 'SR', 'RL', 'LFE', 'RR']
const POLL_INTERVAL_MS = 100
// Levels below -60 dBFS count as silence.
const FLOOR_DB = -60

const levelToIntensity = (level: number): number => {
  if (!level || level <= 0) return 0
  const db = 20 * Math.log10(level)
  return Math.min(1, Math.max(0, (db - FLOOR_DB) / -FLOOR_DB))
}

/**
 * Shows which of the 8 input channels of the virtual surround device currently carry audio.
 * Polls the backend only while it is mounted (plugin panel open). The backend stops measuring on
 * its own a few seconds after the last poll.
 */
const ChannelMeter: React.FC = () => {
  const [levels, setLevels] = useState<number[]>(() => METER_CHANNELS.map(() => 0))
  const busyRef = useRef(false)

  useEffect(() => {
    let active = true
    const poll = async () => {
      if (busyRef.current) return
      busyRef.current = true
      try {
        const result = await call<[], number[]>('get_channel_levels')
        if (active && Array.isArray(result)) setLevels(result)
      } catch (error) {
        console.error('[decky-virtual-surround-rooms:ChannelMeter] Error reading levels:', error)
      } finally {
        busyRef.current = false
      }
    }
    poll()
    const timer = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      active = false
      clearInterval(timer)
      call<[], boolean>('stop_channel_meter').catch(() => undefined)
    }
  }, [])

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px', padding: '4px 0' }}>
      {LAYOUT.map((code, index) => {
        if (!code) return <div key={`gap-${index}`} />
        const intensity = levelToIntensity(levels[METER_CHANNELS.indexOf(code)])
        const lit = intensity > 0
        return (
          <div
            key={code}
            style={{
              height: '22px',
              borderRadius: '3px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '11px',
              fontWeight: 600,
              letterSpacing: '0.5px',
              color: lit ? '#ffffff' : 'rgba(255, 255, 255, 0.35)',
              backgroundColor: lit
                ? `rgba(26, 159, 255, ${(0.25 + 0.75 * intensity).toFixed(2)})`
                : 'rgba(255, 255, 255, 0.06)',
              transition: 'background-color 80ms linear, color 80ms linear',
            }}
          >
            {code}
          </div>
        )
      })}
    </div>
  )
}

export default ChannelMeter

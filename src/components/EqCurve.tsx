import React, { useMemo } from 'react'
import { EqCurveData, EqFilter } from '../interfaces'

const SAMPLE_RATE = 48000
const WIDTH = 260
const HEIGHT = 90
const F_MIN = 20
const F_MAX = 20000
const POINTS = 120

// Magnitude (dB) of one RBJ biquad, the same formulas PipeWire's bq_* filters use.
const biquadDb = (f: EqFilter, freq: number): number => {
  const A = Math.pow(10, f.gain / 40)
  const w0 = (2 * Math.PI * f.fc) / SAMPLE_RATE
  const alpha = Math.sin(w0) / (2 * Math.max(f.q, 0.05))
  const cos = Math.cos(w0)
  let b0, b1, b2, a0, a1, a2
  if (f.type === 'PK') {
    b0 = 1 + alpha * A; b1 = -2 * cos; b2 = 1 - alpha * A
    a0 = 1 + alpha / A; a1 = -2 * cos; a2 = 1 - alpha / A
  } else {
    const s = f.type === 'LSC' ? 1 : -1
    const sq = 2 * Math.sqrt(A) * alpha
    b0 = A * ((A + 1) - s * (A - 1) * cos + sq)
    b1 = s * 2 * A * ((A - 1) - s * (A + 1) * cos)
    b2 = A * ((A + 1) - s * (A - 1) * cos - sq)
    a0 = (A + 1) + s * (A - 1) * cos + sq
    a1 = -s * 2 * ((A - 1) + s * (A + 1) * cos)
    a2 = (A + 1) + s * (A - 1) * cos - sq
  }
  const w = (2 * Math.PI * freq) / SAMPLE_RATE
  const c1 = Math.cos(w), s1 = Math.sin(w), c2 = Math.cos(2 * w), s2 = Math.sin(2 * w)
  const numRe = b0 + b1 * c1 + b2 * c2, numIm = -(b1 * s1 + b2 * s2)
  const denRe = a0 + a1 * c1 + a2 * c2, denIm = -(a1 * s1 + a2 * s2)
  return 10 * Math.log10((numRe * numRe + numIm * numIm) / (denRe * denRe + denIm * denIm))
}

const xOf = (freq: number) => (Math.log10(freq / F_MIN) / Math.log10(F_MAX / F_MIN)) * WIDTH

/** Frequency response of the headphone correction (without preamp: 0 dB = unchanged). */
const EqCurve: React.FC<{ curve: EqCurveData; enabled: boolean }> = ({ curve, enabled }) => {
  const { path, range } = useMemo(() => {
    const values: [number, number][] = []
    for (let i = 0; i < POINTS; i++) {
      const freq = F_MIN * Math.pow(F_MAX / F_MIN, i / (POINTS - 1))
      values.push([freq, curve.filters.reduce((sum, f) => sum + biquadDb(f, freq), 0)])
    }
    const peak = Math.max(6, ...values.map(([, db]) => Math.ceil(Math.abs(db))))
    const yOf = (db: number) => HEIGHT / 2 - (db / peak) * (HEIGHT / 2 - 4)
    const d = values.map(([freq, db], i) => `${i ? 'L' : 'M'}${xOf(freq).toFixed(1)},${yOf(db).toFixed(1)}`).join(' ')
    return { path: d, range: peak }
  }, [curve])

  const grid = 'rgba(255, 255, 255, 0.12)'
  return (
    <div style={{ opacity: enabled ? 1 : 0.4, padding: '4px 0' }}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" style={{ display: 'block', background: 'rgba(255, 255, 255, 0.04)', borderRadius: '4px' }}>
        {[100, 1000, 10000].map((f) => (
          <line key={f} x1={xOf(f)} x2={xOf(f)} y1={0} y2={HEIGHT} stroke={grid} strokeWidth={1} />
        ))}
        <line x1={0} x2={WIDTH} y1={HEIGHT / 2} y2={HEIGHT / 2} stroke="rgba(255, 255, 255, 0.25)" strokeWidth={1} />
        <path d={path} fill="none" stroke="#1a9fff" strokeWidth={2} strokeLinejoin="round" />
        {[['100', 100], ['1k', 1000], ['10k', 10000]].map(([label, f]) => (
          <text key={label} x={xOf(f as number) + 2} y={HEIGHT - 3} fontSize={8} fill="rgba(255, 255, 255, 0.45)">{label}</text>
        ))}
        <text x={2} y={9} fontSize={8} fill="rgba(255, 255, 255, 0.45)">+{range} dB</text>
        <text x={2} y={HEIGHT - 3} fontSize={8} fill="rgba(255, 255, 255, 0.45)">−{range}</text>
      </svg>
    </div>
  )
}

export default EqCurve

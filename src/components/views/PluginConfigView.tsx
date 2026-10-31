import {
  ButtonItem,
  ConfirmModal,
  DialogButton,
  Focusable,
  Navigation,
  PanelSection,
  PanelSectionRow,
  showModal,
} from '@decky/ui'
import { CSSProperties, useState } from 'react'
import { MdArrowBack } from 'react-icons/md'
import { SiGithub } from 'react-icons/si'
import { call } from '@decky/api'
import {
  clearPluginConfig,
  defaultMixerProfile,
  FORK_REPO_URL,
  ORIGINAL_REPO_URL,
  setMixerProfileInBackend,
  CHANNEL_NAMES,
} from '../../constants'

interface PluginConfigViewProps {
  onGoBack: () => void
}

// Speaker layout as seen from above (listener in the middle).
const speakerGrid: (string | null)[] = [
  'FL', 'FC', 'FR',
  'SL', null, 'SR',
  'RL', 'LFE', 'RR',
]

const channelButtonStyle = (active: boolean): CSSProperties => ({
  minWidth: 0,
  width: '100%',
  minHeight: '30px',
  padding: '4px 0',
  fontSize: '12px',
  fontWeight: active ? 700 : 400,
  outline: active ? '2px solid #1a9fff' : undefined,
})

const mutedTextStyle: CSSProperties = { fontSize: '12px', color: '#8b929a' }

const openUrl = (url: string) => {
  Navigation.CloseSideMenus()
  Navigation.NavigateToExternalWeb(url)
}

const PluginConfigView: React.FC<PluginConfigViewProps> = ({ onGoBack }) => {
  const [runningTest, setRunningTest] = useState<string | null>(null)
  const [isResetting, setIsResetting] = useState<boolean>(false)
  const [message, setMessage] = useState<string | null>(null)

  // sink: 'virtual-surround' (through the filter) or 'default' (real output device, no filter)
  // channel: optional single channel code; plays the whole sequence when omitted.
  const runSoundTest = async (sink: string, channel?: string) => {
    const testId = `${sink}:${channel ?? 'all'}`
    setMessage(null)
    setRunningTest(testId)
    try {
      const ok = await call<[sink: string, channel: string | null], boolean>('run_sound_test', sink, channel ?? null)
      setRunningTest((current) => {
        // false is also returned when the test was replaced by another one; only report our own failure.
        if (current === testId && ok === false) setMessage('Sound test failed.')
        return current === testId ? null : current
      })
    } catch (error) {
      console.error('[decky-virtual-surround-rooms:PluginConfigView] Sound test failed:', error)
      setRunningTest(null)
      setMessage('Sound test failed.')
    }
  }

  const stopSoundTest = async () => {
    setRunningTest(null)
    await call<[], boolean>('stop_sound_test')
  }

  const resetPlugin = async () => {
    setIsResetting(true)
    setMessage(null)
    setRunningTest(null)
    try {
      clearPluginConfig()
      const ok = await call<[], boolean>('reset_plugin')
      await setMixerProfileInBackend(defaultMixerProfile)
      setMessage(ok ? 'Plugin reset.' : 'Reset finished with errors.')
    } catch (error) {
      console.error('[decky-virtual-surround-rooms:PluginConfigView] Reset failed:', error)
      setMessage('Reset failed.')
    } finally {
      setIsResetting(false)
    }
  }

  const confirmResetPlugin = () => {
    showModal(
      <ConfirmModal
        strTitle="Reset Virtual Surround + Rooms?"
        strDescription="All settings, mixer and per-game profiles go back to their defaults. Audio drops out for a moment."
        strOKButtonText="Reset"
        bDestructiveWarning={true}
        onOK={() => {
          resetPlugin()
        }}
      />,
      window,
    )
  }

  return (
    <>
      <div style={{ padding: '3px 16px', margin: 0 }}>
        <Focusable style={{ display: 'flex', height: '26px' }} flow-children="horizontal">
          <DialogButton
            // @ts-ignore
            autoFocus={true}
            retainFocus={true}
            style={{ width: '40px', minWidth: '40px', padding: '3px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={onGoBack}
          >
            <MdArrowBack />
          </DialogButton>
        </Focusable>
      </div>

      <PanelSection title="Sound Test">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => runSoundTest('virtual-surround')}>
            {runningTest === 'virtual-surround:all' ? 'Playing…' : 'With surround'}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => runSoundTest('default')}>
            {runningTest === 'default:all' ? 'Playing…' : 'Without surround'}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <Focusable
            style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px', padding: '8px 0' }}
          >
            {speakerGrid.map((code, index) => code ? (
              <DialogButton
                key={code}
                style={channelButtonStyle(runningTest === `virtual-surround:${code}`)}
                onClick={() => runSoundTest('virtual-surround', code)}
              >
                {CHANNEL_NAMES[code]}
              </DialogButton>
            ) : (
              <div key={`listener-${index}`} style={{ textAlign: 'center', alignSelf: 'center', fontSize: '18px', opacity: 0.6 }}>🎧</div>
            ))}
          </Focusable>
        </PanelSectionRow>
        {runningTest !== null && (
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => stopSoundTest()}>
              Stop
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Reset">
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={isResetting} onClick={() => confirmResetPlugin()}>
            {isResetting ? 'Resetting…' : 'Reset plugin'}
          </ButtonItem>
        </PanelSectionRow>
        {message && (
          <PanelSectionRow>
            <div style={{ ...mutedTextStyle, padding: '4px 0' }}>{message}</div>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="About">
        <PanelSectionRow>
          <div style={{ ...mutedTextStyle, padding: '0 0 6px' }}>
            Fork of Virtual Surround Sound by Josh.5
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => openUrl(FORK_REPO_URL)}>
            <SiGithub style={{ marginRight: '8px', verticalAlign: 'middle' }} />GitHub
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => openUrl(ORIGINAL_REPO_URL)}>
            <SiGithub style={{ marginRight: '8px', verticalAlign: 'middle' }} />Original on GitHub
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  )
}

export default PluginConfigView

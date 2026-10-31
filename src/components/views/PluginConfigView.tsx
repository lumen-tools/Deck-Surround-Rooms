import {
  PanelSection,
  PanelSectionRow,
  DialogButton,
  Focusable,
  Dropdown,
  ToggleField,
  ConfirmModal,
  showModal,
} from '@decky/ui'
import { useState, useEffect, CSSProperties } from 'react'
import { MdArrowBack, MdRestartAlt, MdStop, MdSurroundSound } from 'react-icons/md'
import { SiDiscord, SiGithub, SiKofi, SiPatreon } from 'react-icons/si'
import { HrirFile, PluginConfig } from '../../interfaces'
import {
  clearPluginConfig,
  defaultMixerProfile,
  getPluginConfig,
  setMixerProfileInBackend,
  setPluginConfig,
} from '../../constants'
import { call } from '@decky/api'
import { PanelSocialButton } from '../elements/SocialButton'
import { VscSurroundWith } from 'react-icons/vsc'
import { popupVssHelpDialog } from '../elements/VssHelpDialog'
import { popupHrirInfoDialog } from '../elements/HrirInfoDialog'
import { TiInfo } from 'react-icons/ti'

interface PluginConfigViewProps {
  onGoBack: () => void
}

const fieldBlockStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '6px',
  width: '100%',
  padding: '8px 16px 8px 0',
}
const fieldHeadingStyle: CSSProperties = { fontSize: '12px', fontWeight: 600, letterSpacing: '0.01em' }
const helperTextStyle: CSSProperties = { fontSize: '11px', opacity: 0.75, lineHeight: '1.35' }

const actionButtonStyle: CSSProperties = {
  alignSelf: 'flex-start',
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  minHeight: '28px',
  padding: '6px 10px',
  fontSize: '12px',
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
  minHeight: '28px',
  padding: '4px 0',
  fontSize: '12px',
  fontWeight: active ? 700 : 400,
  outline: active ? '2px solid #1a9fff' : undefined,
})

const PluginConfigView: React.FC<PluginConfigViewProps> = ({ onGoBack }) => {
  const [isLoading, setIsLoading] = useState(false)
  const [currentConfig, setCurrentConfig] = useState(() => getPluginConfig())
  const [hrirFileList, setHrirFileList] = useState<HrirFile[]>([])
  const [surroundSinkDefaultConfig, setSurroundSinkDefaultConfig] = useState<boolean>(false)
  const [isResetting, setIsResetting] = useState<boolean>(false)
  const [resetMessage, setResetMessage] = useState<string | null>(null)
  const [isApplyingHrir, setIsApplyingHrir] = useState<boolean>(false)
  const [runningTest, setRunningTest] = useState<string | null>(null)
  const [testError, setTestError] = useState<string | null>(null)

  const readBackendConfig = async () => {
    const surroundSinkDefault = await call<[], boolean[]>('get_surround_sink_default')
    if (surroundSinkDefault) {
      setSurroundSinkDefaultConfig(true)
    } else {
      setSurroundSinkDefaultConfig(false)
    }
  }

  const resetPlugin = async () => {
    setIsResetting(true)
    setResetMessage(null)
    setRunningTest(null)
    setTestError(null)
    try {
      // Frontend settings: mixer, per-game profiles, selected HRIR name, acknowledged notes.
      clearPluginConfig()
      const freshConfig = getPluginConfig()
      setCurrentConfig(freshConfig)
      // Backend: settings, default HRIR, service restart, app routing.
      const ok = await call<[], boolean>('reset_plugin')
      await setMixerProfileInBackend(defaultMixerProfile)
      await readBackendConfig()
      setResetMessage(ok ? 'Plugin has been reset to defaults.' : 'Reset finished with errors. Check the plugin log.')
    } catch (error) {
      console.error('[decky-virtual-surround-sound:PluginConfigView] Reset failed:', error)
      setResetMessage('Reset failed. Check the plugin log.')
    } finally {
      setIsResetting(false)
    }
  }

  const confirmResetPlugin = () => {
    showModal(
      <ConfirmModal
        strTitle="Reset Virtual Surround Sound?"
        strDescription={
          'This restores the plugin to a fresh install: default HRIR, all mixer and per-game profiles ' +
          'set back to 100%, all per-app "Enable" switches turned off and the virtual surround sink ' +
          'used as default output again. The surround service restarts, so audio drops out for a moment.'
        }
        strOKButtonText="Reset everything"
        bDestructiveWarning={true}
        onOK={() => {
          resetPlugin()
        }}
      />,
      window,
    )
  }

  const updateHrirFileListList = async () => {
    setIsLoading(true)
    try {
      const hrirFiles = await call<[], HrirFile[]>('get_hrir_file_list')
      setHrirFileList(hrirFiles || [])
    } catch (error) {
      console.error('[decky-virtual-surround-sound:PluginConfigView] Error fetching game details:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const updateConfig = (updates: Partial<PluginConfig>) => {
    // Update the localStorage config
    setPluginConfig(updates)
    // Update the local state of component
    setCurrentConfig((prevConfig: PluginConfig) => ({
      ...prevConfig,
      ...updates,
    }))
  }

  const handleHrirSelection = async (hrirName: string) => {
    const selectedHrir = hrirFileList.find((file) => file.label === hrirName)
    if (!selectedHrir) {
      console.error(`[decky-virtual-surround-sound:PluginConfigView] HRIR file not found for name: ${hrirName}`)
      return
    }
    const hrirPath = selectedHrir.path
    setIsApplyingHrir(true)
    const result = await call<[hrirPath: string], boolean>('set_hrir_file', hrirPath)
    setIsApplyingHrir(false)
    if (!result) {
      console.error('[decky-virtual-surround-sound:PluginConfigView] Error saving new HRIR file:', result)
    } else {
      updateConfig({ hrirName: hrirName })
    }
  }

  const handleEnableSurroundDefaultSink = async (enabled: boolean) => {
    console.log(`[decky-virtual-surround-sound:PluginConfigView] Configure Virtual Surround Sink as default: ${enabled}`)
    if (!currentConfig?.notesAcknowledgedV2) {
      console.log(`[decky-virtual-surround-sound:PluginConfigView] Divert to first display warnings dialog.`)
      popupVssHelpDialog(() => {
        console.log(`[decky-virtual-surround-sound:PluginConfigView] Reloading settings.`)
        setCurrentConfig(getPluginConfig())
      })
      return
    }
    try {
      if (enabled) {
        await call<[], boolean>('enable_surround_sink_default')
      } else {
        await call<[], boolean>('disable_surround_sink_default')
      }
      await readBackendConfig()
    } catch (error) {
      console.error(`[decky-virtual-surround-sound:PluginConfigView] Error setting default sink as ${enabled}:`, error)
    }
  }

  // sink: 'virtual-surround' (through the filter) or 'default' (real output device, no filter)
  // channel: optional single channel code; plays the whole sequence when omitted.
  const runSoundTest = async (sink: string, channel?: string) => {
    const testId = `${sink}:${channel ?? 'all'}`
    console.info(`[decky-virtual-surround-sound:PluginConfigView] Exec sound test ${testId}`)
    setTestError(null)
    setRunningTest(testId)
    try {
      const ok = await call<[sink: string, channel: string | null], boolean>('run_sound_test', sink, channel ?? null)
      if (ok === false) {
        // false is also returned when a test was stopped/replaced by another one.
        setRunningTest((current) => {
          if (current === testId) {
            setTestError('Sound test did not complete. Check the plugin log if this keeps happening.')
            return null
          }
          return current
        })
        return
      }
    } catch (error) {
      console.error('[decky-virtual-surround-sound:PluginConfigView] Sound test failed:', error)
      setTestError('Sound test failed.')
    }
    setRunningTest((current) => (current === testId ? null : current))
  }

  const stopSoundTest = async () => {
    setRunningTest(null)
    await call<[], boolean>('stop_sound_test')
  }

  useEffect(() => {
    console.log(`[decky-virtual-surround-sound:PluginConfigView] Mounted`)
    readBackendConfig()
    updateHrirFileListList()
  }, [])

  return (
    <>
      <div style={{ padding: '3px 16px 3px 16px', margin: 0 }}>
        <Focusable
          style={{ display: 'flex', alignItems: 'stretch', gap: '1rem', height: '26px' }}
          flow-children='horizontal'
        >
          <DialogButton
            // @ts-ignore
            autoFocus={true}
            retainFocus={true}
            style={{
              width: '73px',
              minWidth: '73px',
              padding: '3px',
              fontSize: '14px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '1rem',
            }}
            onClick={onGoBack}
          >
            <MdArrowBack />
          </DialogButton>
        </Focusable>
      </div>
      <hr />

      <>
        {isLoading ? (
          <PanelSection spinner title="Fetching settings..." />
        ) : (
          <>
            <PanelSection title="Default Audio Sink">
              <PanelSectionRow>
                <div style={fieldBlockStyle}>
                  <ToggleField
                    label="Use Virtual Surround Sound as Default Output"
                    checked={surroundSinkDefaultConfig}
                    onChange={(e) => {
                      handleEnableSurroundDefaultSink(e)
                    }}
                    disabled={(surroundSinkDefaultConfig === null)}
                  />
                  <div style={helperTextStyle}>
                    Setting this sink as the system default helps surround-aware apps stay multichannel, though it can make some stereo-only apps behave differently.
                  </div>
                  <DialogButton
                    style={actionButtonStyle}
                    onClick={() => popupVssHelpDialog(undefined, { hideAcknowledge: true })}
                  >
                    <TiInfo size="1em" /> More Info
                  </DialogButton>
                </div>
              </PanelSectionRow>
            </PanelSection>


            <PanelSection title='Select a HRIR file for filter'>
              <PanelSectionRow>
                <div style={fieldBlockStyle}>
                  <div style={fieldHeadingStyle}>Select from one of the HRIR WAV files to apply to your audio downsampling.</div>
                  <Dropdown
                    rgOptions={hrirFileList.map((hrirFile) => ({
                      label: `${(currentConfig.hrirName === hrirFile.label) ? '✔' : '—'} ${hrirFile.label}`,
                      data: hrirFile.label,
                    }))}
                    selectedOption={currentConfig.hrirName}
                    onChange={(option) => handleHrirSelection(option.data)}
                    strDefaultLabel="Select HRIR Profile"
                  />
                  <div style={helperTextStyle}>
                    Choose from the list of Head-Related Impulse Response (HRIR) .wav files, which captures how
                    sound is modified by the shape of a human head and ears. These HRIRs are applied to your audio
                    so the plugin can simulate a realistic binaural surround effect on headphones.
                    <br />
                    Tap <strong>More HRIR Info</strong> below to learn in simple terms how HRTF/HRIR works and how
                    to add your own custom HRIR files.
                  </div>
                  <DialogButton
                    style={actionButtonStyle}
                    onClick={() => popupHrirInfoDialog()}
                  >
                    <TiInfo size="1em" /> More HRIR Info
                  </DialogButton>
                </div>
              </PanelSectionRow>

              <PanelSectionRow>
                <div style={{
                  margin: '20px 5px 0',
                  padding: '0px 0px 8px',
                  fontSize: '16px',
                  fontWeight: '600',
                  fontStyle: 'normal',
                  textAlign: 'left',
                  textDecoration: 'none',
                  textIndent: '0',
                  textTransform: 'uppercase',
                  lineHeight: '20px',
                  letterSpacing: '.5px',
                }}>Test your selected profile
                </div>

                <Focusable style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <DialogButton
                    style={actionButtonStyle}
                    disabled={isApplyingHrir}
                    onClick={() => runSoundTest('virtual-surround')}
                  >
                    <MdSurroundSound /> {runningTest === 'virtual-surround:all' ? 'Playing…' : 'Surround Enabled'}
                  </DialogButton>
                  <DialogButton
                    style={actionButtonStyle}
                    onClick={() => runSoundTest('default')}
                  >
                    <VscSurroundWith /> {runningTest === 'default:all' ? 'Playing…' : 'Surround Disabled'}
                  </DialogButton>
                </Focusable>

                <div style={{ ...fieldHeadingStyle, marginTop: '12px' }}>Test a single channel (surround enabled)</div>
                <Focusable
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: '4px',
                    marginTop: '4px',
                  }}
                >
                  {speakerGrid.map((code, index) => code ? (
                    <DialogButton
                      key={code}
                      style={channelButtonStyle(runningTest === `virtual-surround:${code}`)}
                      disabled={isApplyingHrir}
                      onClick={() => runSoundTest('virtual-surround', code)}
                    >
                      {code}
                    </DialogButton>
                  ) : (
                    <div key={`empty-${index}`} style={{ textAlign: 'center', fontSize: '18px', opacity: 0.6 }}>🎧</div>
                  ))}
                </Focusable>

                {runningTest !== null && (
                  <DialogButton style={{ ...actionButtonStyle, marginTop: '6px' }} onClick={() => stopSoundTest()}>
                    <MdStop /> Stop test
                  </DialogButton>
                )}
                {testError && (
                  <div style={{ ...helperTextStyle, color: 'orange', marginTop: '4px' }}>{testError}</div>
                )}

                <br />
                <div style={helperTextStyle}>
                  Compare how audio sounds with and without the virtual surround filter applied.
                  <br />
                  The top button plays the test sequence through the surround filter, while the
                  bottom button plays it through the real SteamOS output device (no filter).
                  Starting a new test stops the previous one.
                  <br />
                  The sequence starts front left and goes clockwise around you, ending with the
                  subwoofer. A voice announces each channel:
                  <ul style={{ paddingLeft: 20, margin: 0 }}>
                    <li>Front Left (FL)</li>
                    <li>Front Center (FC)</li>
                    <li>Front Right (FR)</li>
                    <li>Side Right (SR)</li>
                    <li>Rear Right (RR)</li>
                    <li>Rear Left (RL)</li>
                    <li>Side Left (SL)</li>
                    <li>50Hz Low-Frequency Effects (LFE) tone (subwoofer)</li>
                  </ul>
                </div>
              </PanelSectionRow>
            </PanelSection>
            <hr />
            <PanelSection title="Reset">
              <PanelSectionRow>
                <div style={fieldBlockStyle}>
                  <DialogButton
                    style={actionButtonStyle}
                    disabled={isResetting}
                    onClick={() => confirmResetPlugin()}
                  >
                    <MdRestartAlt /> {isResetting ? 'Resetting…' : 'Reset plugin to defaults'}
                  </DialogButton>
                  {resetMessage && <div style={helperTextStyle}>{resetMessage}</div>}
                  <div style={helperTextStyle}>
                    Restores everything to a fresh install. Use this if the audio sounds wrong and you
                    are not sure which setting causes it.
                  </div>
                </div>
              </PanelSectionRow>
            </PanelSection>
            <hr />
            <PanelSection>
              <PanelSocialButton icon={<SiPatreon fill='#438AB9' />} url='https://www.patreon.com/c/Josh5'>
                Patreon
              </PanelSocialButton>
              <PanelSocialButton icon={<SiKofi fill='#FF5E5B' />} url='https://ko-fi.com/josh5coffee'>
                Ko-fi
              </PanelSocialButton>
              <PanelSocialButton icon={<SiDiscord fill='#5865F2' />} url='https://streamingtech.co.nz/discord'>
                Discord
              </PanelSocialButton>
              <PanelSocialButton
                icon={<SiGithub fill='#f5f5f5' />}
                url='https://github.com/DeckSettings/decky-game-settings'
              >
                Plugin Source
              </PanelSocialButton>
            </PanelSection>
          </>
        )}
      </>
    </>
  )
}

export default PluginConfigView

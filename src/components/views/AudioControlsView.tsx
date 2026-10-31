import {
  ButtonItem,
  DialogButton,
  Dropdown,
  Field,
  Focusable,
  PanelSection,
  PanelSectionRow,
  Router,
  SliderField,
  ToggleField,
} from '@decky/ui'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MdSettings } from 'react-icons/md'
import { call } from '@decky/api'
import { HrirFile, MixerProfile, PluginConfig, PluginPage, RunningApp, Source } from '../../interfaces'
import {
  defaultMixerProfile,
  defaultMixerVolumes,
  getCurrentMixerProfile,
  getMixerChannels,
  getPluginConfig,
  setMixerProfileInBackend,
  setPluginConfig,
} from '../../constants'

interface AudioControlsViewProps {
  onChangePage: (page: PluginPage) => void
}

const statusLabel: Record<Source['status'], string> = {
  surround: 'Surround',
  direct: 'Stereo',
  pinned: 'Own output',
}

const AudioControlsView: React.FC<AudioControlsViewProps> = ({ onChangePage }) => {
  const [currentConfig, setCurrentConfig] = useState<PluginConfig | null>(null)
  const [runningApp, setRunningApp] = useState<RunningApp | null>(null)
  const [profile, setProfile] = useState<string>('default')
  const [usePerAppProfiles, setUsePerAppProfiles] = useState<boolean>(false)
  const channels = useMemo(() => getMixerChannels(currentConfig?.channelCount), [currentConfig?.channelCount])
  const [mixerVolumes, setMixerVolumes] = useState<{ [code: string]: number }>(
    defaultMixerProfile.volumes,
  )
  const [surroundEnabled, setSurroundEnabled] = useState<boolean | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [hrirFiles, setHrirFiles] = useState<HrirFile[]>([])
  const [isApplyingHrir, setIsApplyingHrir] = useState<boolean>(false)

  const refreshState = async () => {
    const currentRunningApp = Router.MainRunningApp
    setRunningApp(currentRunningApp ? { display_name: currentRunningApp.display_name } : null)
    try {
      setSurroundEnabled(!!(await call<[], boolean>('get_surround_enabled')))
      setSources((await call<[], Source[]>('get_sources')) ?? [])
    } catch (error) {
      console.error('[decky-virtual-surround-sound:AudioControlsView] Error refreshing state:', error)
    }
  }

  const loadHrirFiles = async () => {
    try {
      setHrirFiles((await call<[], HrirFile[]>('get_hrir_file_list')) ?? [])
    } catch (error) {
      console.error('[decky-virtual-surround-sound:AudioControlsView] Error loading HRIR list:', error)
    }
  }

  const toggleSurround = async (enabled: boolean) => {
    setSurroundEnabled(enabled)
    await call<[enabled: boolean], boolean>('set_surround_enabled', enabled)
    await refreshState()
  }

  const selectHrir = async (path: string) => {
    setIsApplyingHrir(true)
    setHrirFiles((files) => files.map((file) => ({ ...file, active: file.path === path })))
    try {
      await call<[path: string], boolean>('set_hrir_file', path)
    } finally {
      setIsApplyingHrir(false)
      await loadHrirFiles()
    }
  }

  // Update mixer profile from backend and update state accordingly.
  const updateMixerProfile = async () => {
    const mixerProfile = await getCurrentMixerProfile()
    setProfile(mixerProfile.name)
    if (mixerProfile.name === 'default') {
      setUsePerAppProfiles(false)
    } else {
      setUsePerAppProfiles(!!(mixerProfile?.usePerAppProfile))
    }
    if (mixerProfile.volumes) {
      setMixerVolumes(mixerProfile.volumes)
    }
    setCurrentConfig(getPluginConfig())
  }

  // Toggle per-app profiles and update the mixer profile afterward.
  const togglePerAppProfiles = async (enabled: boolean) => {
    console.log(`[decky-virtual-surround-sound:AudioControlsView] Toggle per-app profile: ${enabled}`)
    setUsePerAppProfiles(enabled)
    if (runningApp?.display_name) {
      const existingProfile = getPluginConfig().perAppProfiles?.[runningApp.display_name]
      setPluginConfig({
        perAppProfiles: {
          [runningApp.display_name]: {
            name: runningApp.display_name,
            usePerAppProfile: enabled,
            // A new per-game profile starts with the volumes that are currently active.
            volumes: existingProfile?.volumes ?? { ...mixerVolumes },
          },
        },
      })
    } else {
      // Always set to false if no app is running
      setUsePerAppProfiles(false)
    }
    await updateMixerProfile()
    // Apply the (possibly different) profile right away instead of waiting for the background poll.
    await setMixerProfileInBackend(await getCurrentMixerProfile())
  }

  const updateChannelVolume = useCallback(
    async (channel: string, value: number) => {
      console.log(`[decky-virtual-surround-sound] Setting ${channel} volume to ${value}`)
      const updatedVolumes = { ...mixerVolumes, [channel]: value }
      const mixerProfile: MixerProfile = {
        name: profile,
        volumes: updatedVolumes,
      }
      // Save plugin config
      setPluginConfig({
        perAppProfiles: {
          ...currentConfig?.perAppProfiles,
          [profile]: mixerProfile,
        },
      })
      // Save send updated mixer profile to backend
      await setMixerProfileInBackend(mixerProfile)
      //await call<[MixerProfile], boolean>('set_mixer_profile', mixerProfile);
    },
    [mixerVolumes, currentConfig, profile],
  )
  const channelDebounceRef = useRef(
    new Map<string, { timer: ReturnType<typeof setTimeout>; value: number }>(),
  )
  const resetMixerVolumes = async () => {
    channelDebounceRef.current.forEach((entry) => clearTimeout(entry.timer))
    channelDebounceRef.current.clear()
    const volumes = { ...defaultMixerVolumes }
    setMixerVolumes(volumes)
    const mixerProfile: MixerProfile = { name: profile, volumes }
    setPluginConfig({
      perAppProfiles: {
        ...currentConfig?.perAppProfiles,
        [profile]: { ...(currentConfig?.perAppProfiles?.[profile] ?? {}), ...mixerProfile },
      },
    })
    await setMixerProfileInBackend(mixerProfile)
  }

  const handleVolumeChange = (channel: string, value: number) => {
    const updatedVolumes = { ...mixerVolumes, [channel]: value }
    setMixerVolumes(updatedVolumes)

    // Flush pending debounce timers for any channels that are not the current one.
    channelDebounceRef.current.forEach((entry, ch) => {
      if (ch !== channel) {
        clearTimeout(entry.timer)
        // Commit the pending update immediately for that channel.
        updateChannelVolume(ch, entry.value)
        channelDebounceRef.current.delete(ch)
      }
    })

    // For the current channel, if there's an existing timer, clear it.
    if (channelDebounceRef.current.has(channel)) {
      clearTimeout(channelDebounceRef.current.get(channel)!.timer)
    }

    // Set a new timer for the current channel.
    const timer = setTimeout(() => {
      updateChannelVolume(channel, value)
      channelDebounceRef.current.delete(channel)
    }, 250)

    // Store (or update) the pending timer and value for this channel.
    channelDebounceRef.current.set(channel, { timer, value })
  }


  useEffect(() => {
    setCurrentConfig(getPluginConfig())
    refreshState()
    loadHrirFiles()
    updateMixerProfile()
    const interval = setInterval(refreshState, 5000)
    return () => clearInterval(interval)
  }, [])

  const activeHrir = hrirFiles.find((file) => file.active)

  return (
    <>
      <div style={{ padding: '3px 16px', margin: 0 }}>
        <Focusable style={{ display: 'flex', justifyContent: 'flex-end', height: '26px' }} flow-children="horizontal">
          <DialogButton
            style={{ width: '40px', minWidth: '40px', padding: '3px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            onClick={() => onChangePage('plugin_config')}
          >
            <MdSettings />
          </DialogButton>
        </Focusable>
      </div>

      <PanelSection>
        <PanelSectionRow>
          <ToggleField
            label="Virtual Surround"
            checked={!!surroundEnabled}
            disabled={surroundEnabled === null}
            onChange={(enabled) => toggleSurround(enabled)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="HRTF" childrenLayout="below" childrenContainerWidth="max" bottomSeparator="none">
            <Dropdown
              rgOptions={hrirFiles.map((file) => ({ label: file.label, data: file.path }))}
              selectedOption={activeHrir?.path}
              strDefaultLabel="Select HRTF"
              disabled={isApplyingHrir || hrirFiles.length === 0}
              onChange={(option) => selectHrir(option.data)}
            />
          </Field>
        </PanelSectionRow>
      </PanelSection>

      {sources.length > 0 && (
        <PanelSection title="Sources">
          {sources.map((source) => (
            <PanelSectionRow key={source.name}>
              <Field label={source.name} bottomSeparator="none" padding="compact">
                <span style={{ fontSize: '12px', color: source.status === 'surround' ? '#1a9fff' : '#8b929a' }}>
                  {statusLabel[source.status]}
                </span>
              </Field>
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}

      <PanelSection title="Mixer">
        {runningApp && (
          <PanelSectionRow>
            <ToggleField
              label="Per-game profile"
              checked={usePerAppProfiles}
              onChange={(enabled) => togglePerAppProfiles(enabled)}
            />
          </PanelSectionRow>
        )}
        {channels.map(({ code, label }) => (
          <PanelSectionRow key={code}>
            <SliderField
              min={0}
              max={150}
              step={5}
              notchCount={4}
              notchTicksVisible={false}
              label={label}
              showValue
              valueSuffix="%"
              resetValue={100}
              bottomSeparator="none"
              value={mixerVolumes[code] ?? 100}
              onChange={(value: number) => handleVolumeChange(code, value)}
            />
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => resetMixerVolumes()}>
            Reset mixer
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  )
}

export default AudioControlsView

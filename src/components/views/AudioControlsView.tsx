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
  Spinner,
  ToggleField,
} from '@decky/ui'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MdSettings } from 'react-icons/md'
import { call } from '@decky/api'
import { HrirFile, MixerProfile, PluginConfig, PluginPage, RunningApp } from '../../interfaces'
import {
  defaultMixerProfile,
  defaultMixerVolumes,
  getCurrentMixerProfile,
  getMixerChannels,
  getPluginConfig,
  setMixerProfileInBackend,
  setPluginConfig,
} from '../../constants'
import ChannelMeter from '../ChannelMeter'
import HeadphoneEq from '../HeadphoneEq'
import OutputSelect from '../OutputSelect'

interface AudioControlsViewProps {
  onChangePage: (page: PluginPage) => void
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
  const [hrirFiles, setHrirFiles] = useState<HrirFile[]>([])
  const [isApplyingHrir, setIsApplyingHrir] = useState<boolean>(false)
  const [isSwitching, setIsSwitching] = useState<boolean>(false)
  // False while only the internal speakers are available (no headphones etc. connected).
  const [outputAvailable, setOutputAvailable] = useState<boolean>(true)
  const isSwitchingRef = useRef<boolean>(false)

  const refreshState = async () => {
    const currentRunningApp = Router.MainRunningApp
    setRunningApp(currentRunningApp ? { display_name: currentRunningApp.display_name } : null)
    try {
      setOutputAvailable(!!(await call<[], boolean>('get_output_available')))
      const enabled = !!(await call<[], boolean>('get_surround_enabled'))
      // Don't let the background refresh flip the switch back while a switch is in progress.
      if (!isSwitchingRef.current) setSurroundEnabled(enabled)
    } catch (error) {
      console.error('[decky-virtual-surround-rooms:AudioControlsView] Error refreshing state:', error)
    }
  }

  const loadHrirFiles = async () => {
    try {
      setHrirFiles((await call<[], HrirFile[]>('get_hrir_file_list')) ?? [])
    } catch (error) {
      console.error('[decky-virtual-surround-rooms:AudioControlsView] Error loading HRIR list:', error)
    }
  }

  // The switch shows the new position right away, but stays locked with a spinner until the backend
  // has changed the default output and moved the running apps (that takes a few seconds).
  const toggleSurround = async (enabled: boolean) => {
    isSwitchingRef.current = true
    setIsSwitching(true)
    setSurroundEnabled(enabled)
    try {
      await call<[enabled: boolean], boolean>('set_surround_enabled', enabled)
    } catch (error) {
      console.error('[decky-virtual-surround-rooms:AudioControlsView] Error switching surround:', error)
    } finally {
      isSwitchingRef.current = false
      setIsSwitching(false)
      await refreshState()
    }
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
    console.log(`[decky-virtual-surround-rooms:AudioControlsView] Toggle per-app profile: ${enabled}`)
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
      console.log(`[decky-virtual-surround-rooms] Setting ${channel} volume to ${value}`)
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
    const interval = setInterval(refreshState, 2000)
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
            label={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                Virtual Surround
                {isSwitching && <Spinner style={{ width: '16px', height: '16px' }} />}
              </span>
            }
            description={
              <>
                No sound? Change the volume briefly.
                <br />
                Switching mid-game can mute all audio until restart.
              </>
            }
            checked={!!surroundEnabled}
            disabled={surroundEnabled === null || isSwitching || !outputAvailable}
            onChange={(enabled) => toggleSurround(enabled)}
          />
        </PanelSectionRow>
        <OutputSelect />
        <PanelSectionRow>
          <Field label="Room" childrenLayout="below" childrenContainerWidth="max" bottomSeparator="none">
            <Dropdown
              rgOptions={hrirFiles.map((file) => ({ label: file.label, data: file.path }))}
              selectedOption={activeHrir?.path}
              strDefaultLabel="Select room"
              disabled={isApplyingHrir || hrirFiles.length === 0}
              onChange={(option) => selectHrir(option.data)}
            />
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Channels" childrenLayout="below" childrenContainerWidth="max" bottomSeparator="none">
            <ChannelMeter />
          </Field>
        </PanelSectionRow>
      </PanelSection>

      <HeadphoneEq />

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

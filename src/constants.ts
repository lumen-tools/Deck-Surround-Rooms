import { Channel, MixerProfile, PluginConfig } from './interfaces'
import { Router } from '@decky/ui'
import { call } from '@decky/api'

// Links shown in the settings page
export const FORK_REPO_URL = 'https://github.com/lumen-tools/Virtual-Surround-Rooms'
export const ORIGINAL_REPO_URL = 'https://github.com/DeckSettings/decky-virtual-surround-sound'

export const restartSteamClient = (): void => {
  SteamClient.User.StartRestart(false)
}

export const mergeDeep = (defaultObj: any, sourceObj: any): any => {
  // If sourceObj isn't an object, just return defaultObj (or you could return sourceObj)
  if (typeof sourceObj !== 'object' || sourceObj === null) {
    return defaultObj
  }

  // Start with a shallow copy of the default object.
  const result: any = { ...defaultObj }

  // Iterate over each key in the source object.
  Object.keys(sourceObj).forEach((key) => {
    const sourceVal = sourceObj[key]

    if (result.hasOwnProperty(key)) {
      // If the key exists in both, and both values are plain objects (not arrays), merge them recursively.
      const defaultVal = result[key]
      if (
        typeof defaultVal === 'object' &&
        defaultVal !== null &&
        !Array.isArray(defaultVal) &&
        typeof sourceVal === 'object' &&
        sourceVal !== null &&
        !Array.isArray(sourceVal)
      ) {
        result[key] = mergeDeep(defaultVal, sourceVal)
      } else {
        // Otherwise, override the default with the source value.
        result[key] = sourceVal
      }
    } else {
      // If the key doesn't exist in the default object, add it.
      result[key] = sourceVal
    }
  })

  return result
}

// All channels at 100%. The backend normalises the HRIR so that every virtual speaker has the same
// loudness; any further adjustment is up to the user.
export const defaultMixerVolumes: { [code: string]: number } = {
  FL: 100,
  FR: 100,
  FC: 100,
  LFE: 100,
  RL: 100,
  RR: 100,
  SL: 100,
  SR: 100,
}

export const defaultMixerProfile = {
  name: 'default',
  usePerAppProfile: false,
  volumes: { ...defaultMixerVolumes },
}

// Mixer defaults shipped by plugin versions <= 0.1.6. Note that pactl volumes are cubic, so these
// made the rear channels ~6dB quieter and the centre ~5dB louder than the front channels.
const legacyDefaultMixerVolumes: { [code: string]: number } = {
  FL: 100, FR: 100, FC: 120, LFE: 100, RL: 80, RR: 80, SL: 90, SR: 90,
}
const currentConfigVersion = 2

const volumesEqual = (a?: { [code: string]: number }, b?: { [code: string]: number }): boolean => {
  if (!a || !b) return false
  return Object.keys(b).every((key) => a[key] === b[key]) && Object.keys(a).length === Object.keys(b).length
}

export const generateUniqueId = (): string => {
  // Use the built-in randomUUID if available
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  } else if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    // Create a template string by forcing the first value to a string.
    const template = String(1e7) + -1e3 + -4e3 + -8e3 + -1e11
    return template.replace(/[018]/g, (c) =>
      (Number(c) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(c) / 4).toString(16),
    )
  }
  // Fallback if crypto is not available
  return Math.random().toString(36).substring(2) + Date.now().toString(36)
}

const pluginSettingsKey = __PLUGIN_NAME__

export const getPluginConfig = (): PluginConfig => {
  const defaultConfig: PluginConfig = {
    configVersion: currentConfigVersion,
    channelCount: 8,
    usePerAppProfiles: false,
    perAppProfiles: {
      default: defaultMixerProfile,
    },
  }
  const dataJson = window.localStorage.getItem(pluginSettingsKey)
  let config: PluginConfig = defaultConfig
  if (dataJson) {
    try {
      const parsedConfig = JSON.parse(dataJson)
      // Deep merge the stored config over the defaults:
      config = mergeDeep(defaultConfig, parsedConfig)
      if (!parsedConfig.configVersion || parsedConfig.configVersion < currentConfigVersion) {
        // Migration: replace untouched legacy mixer defaults with the new flat defaults.
        Object.values(config.perAppProfiles ?? {}).forEach((mixerProfile) => {
          if (volumesEqual(mixerProfile.volumes, legacyDefaultMixerVolumes)) {
            mixerProfile.volumes = { ...defaultMixerVolumes }
          }
        })
        config.configVersion = currentConfigVersion
        window.localStorage.setItem(pluginSettingsKey, JSON.stringify(config))
      }
    } catch (error) {
      console.error('[decky-virtual-surround-rooms:constants] Failed to parse plugin config:', error)
    }
  }
  // If the installation ID is not present, generate one and save it.
  if (!('installationId' in config) || !config.installationId) {
    config.installationId = generateUniqueId()
    window.localStorage.setItem(pluginSettingsKey, JSON.stringify(config))
  }
  return config
}

// Removes all locally stored frontend settings (mixer, per-game profiles, selected HRIR, notes).
export const clearPluginConfig = (): void => {
  try {
    window.localStorage.removeItem(pluginSettingsKey)
  } catch (error) {
    console.error('[decky-virtual-surround-rooms:constants] Failed to clear plugin config:', error)
  }
}

export const setPluginConfig = (updates: Partial<PluginConfig>): void => {
  const currentConfig = getPluginConfig()
  // Deep merge the updates into the current config:
  const newConfig = mergeDeep(currentConfig, updates)
  try {
    window.localStorage.setItem(pluginSettingsKey, JSON.stringify(newConfig))
  } catch (error) {
    console.error('[decky-virtual-surround-rooms:constants] Failed to save plugin config:', error)
  }
}

export const getCurrentProfileFromRunningApp = async (currentConfig: PluginConfig): Promise<string> => {
  let profileName = 'default'
  const currentRunningGame = Router.MainRunningApp
  if (currentRunningGame?.display_name) {
    // If per-app profiles are enabled, and we have a mapping, use the running app's profile.
    if (currentConfig.perAppProfiles) {
      if (currentRunningGame.display_name in currentConfig.perAppProfiles) {
        // Check if per-app profile is enabled from this running app
        const existingProfile = currentConfig.perAppProfiles[currentRunningGame.display_name]
        if (existingProfile.usePerAppProfile) {
          profileName = currentConfig.perAppProfiles[currentRunningGame.display_name].name || currentRunningGame.display_name
        }
      }
    }
  }
  return profileName
}

// Studio channel names (ITU-R BS.775 / SMPTE) for the PipeWire channel codes.
export const CHANNEL_NAMES: { [code: string]: string } = {
  FL: 'L',
  FR: 'R',
  FC: 'C',
  LFE: 'LFE',
  SL: 'Lss',
  SR: 'Rss',
  RL: 'Lrs',
  RR: 'Rrs',
}

// Channel order used in the UI (ITU-R BS.775 / SMPTE 7.1 order).
export const CHANNEL_ORDER = ['FL', 'FR', 'FC', 'LFE', 'SL', 'SR', 'RL', 'RR']

export const getMixerChannels = (channelCount: number = 8): Channel[] => {
  const channels: Channel[] = CHANNEL_ORDER.map((code) => ({ code, label: CHANNEL_NAMES[code] }))
  if (channelCount === 6) {
    // For a 5.1 setup (6 channels), only return these channels:
    return channels.filter((channel) =>
      ['FL', 'FR', 'FC', 'LFE', 'SL', 'SR'].includes(channel.code),
    )
  }
  return channels
}

// This function updates the mixer profile based on the backend settings and running app.
export const getCurrentMixerProfile = async (): Promise<MixerProfile> => {
  const currentConfig = getPluginConfig()
  // Get selected profile. If per-app profiles are enabled, check for a profile based on the running app.
  const selectedProfileName = await getCurrentProfileFromRunningApp(currentConfig)
  // Lookup the mixer profile settings.
  const baseVolumes = {
    ...defaultMixerVolumes,
    ...(currentConfig.perAppProfiles?.default?.volumes ?? {}),
  }
  let mixerProfile: MixerProfile
  if (currentConfig.perAppProfiles &&
    currentConfig.perAppProfiles[selectedProfileName]) {
    mixerProfile = currentConfig.perAppProfiles[selectedProfileName]
  } else {
    mixerProfile = defaultMixerProfile
  }
  // Always return a complete set of volumes. A freshly enabled per-game profile has no volumes yet;
  // previously that made the backend reset every channel to 100% while the UI still showed the old
  // values, so the audible levels depended on whether a game was running.
  return {
    ...mixerProfile,
    name: mixerProfile.name || selectedProfileName,
    volumes: { ...baseVolumes, ...(mixerProfile.volumes ?? {}) },
  }
}

export const setMixerProfileInBackend = async (mixerProfile: MixerProfile): Promise<void> => {
  // Set this 'mixerProfile' in the backend by sending the whole profile volume list
  await call<[MixerProfile], boolean>('set_mixer_profile', mixerProfile)
}

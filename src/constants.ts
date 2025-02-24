// Site URLs
import {Channel, MixerProfile, PluginConfig} from "./interfaces";
import {Router} from "@decky/ui";
import {call} from "@decky/api";

export const deckyPluginAvatarUrl = "https://deckverified.games/deck-verified/api/v1/images/plugin/decky-virtual-surround-sound/avatar.jpg";

export const restartSteamClient = (): void => {
    SteamClient.User.StartRestart(false);
}

export const mergeDeep = (defaultObj: any, sourceObj: any): any => {
    // If sourceObj isn't an object, just return defaultObj (or you could return sourceObj)
    if (typeof sourceObj !== 'object' || sourceObj === null) {
        return defaultObj;
    }

    // Start with a shallow copy of the default object.
    const result: any = {...defaultObj};

    // Iterate over each key in the source object.
    Object.keys(sourceObj).forEach((key) => {
        const sourceVal = sourceObj[key];

        if (result.hasOwnProperty(key)) {
            // If the key exists in both, and both values are plain objects (not arrays), merge them recursively.
            const defaultVal = result[key];
            if (
                typeof defaultVal === 'object' &&
                defaultVal !== null &&
                !Array.isArray(defaultVal) &&
                typeof sourceVal === 'object' &&
                sourceVal !== null &&
                !Array.isArray(sourceVal)
            ) {
                result[key] = mergeDeep(defaultVal, sourceVal);
            } else {
                // Otherwise, override the default with the source value.
                result[key] = sourceVal;
            }
        } else {
            // If the key doesn't exist in the default object, add it.
            result[key] = sourceVal;
        }
    });

    return result;
};

export const defaultMixerProfile = {
    name: "default",
    usePerAppProfile: false,
    volumes: {
        FL: 100,
        FR: 100,
        FC: 100,
        LFE: 100,
        RL: 100,
        RR: 100,
        SL: 100,
        SR: 100
    }
}

export const getPluginConfig = (): PluginConfig => {
    const defaultConfig: PluginConfig = {
        notesAcknowledgedV1: false,
        hrirName: "Steam Audio",
        channelCount: 8,
        usePerAppProfiles: false,
        perAppProfiles: {
            default: defaultMixerProfile
        }
    };
    const dataJson = window.localStorage.getItem("decky-virtual-surround-sound");
    if (dataJson) {
        try {
            const parsedConfig = JSON.parse(dataJson);
            // Deep merge the stored config over the defaults:
            const mergedConfig = mergeDeep(defaultConfig, parsedConfig);
            return mergedConfig
        } catch (error) {
            console.error("[decky-virtual-surround-sound:constants] Failed to parse plugin config:", error);
        }
    }
    return defaultConfig;
}

export const setPluginConfig = (updates: Partial<PluginConfig>): void => {
    const currentConfig = getPluginConfig();
    // Deep merge the updates into the current config:
    const newConfig = mergeDeep(currentConfig, updates);
    try {
        window.localStorage.setItem("decky-virtual-surround-sound", JSON.stringify(newConfig));
    } catch (error) {
        console.error("[decky-virtual-surround-sound:constants] Failed to save plugin config:", error);
    }
};

export const getCurrentProfileFromRunningApp = async (currentConfig: PluginConfig): Promise<string> => {
    let profileName = 'default';
    const currentRunningGame = Router.MainRunningApp;
    if (currentRunningGame?.display_name) {
        // If per-app profiles are enabled, and we have a mapping, use the running app's profile.
        if (currentConfig.perAppProfiles) {
            if (currentRunningGame.display_name in currentConfig.perAppProfiles) {
                // Check if per-app profile is enabled from this running app
                const existingProfile = currentConfig.perAppProfiles[currentRunningGame.display_name]
                if (existingProfile.usePerAppProfile) {
                    profileName = currentConfig.perAppProfiles[currentRunningGame.display_name].name || currentRunningGame.display_name;
                }
            }
        }
    }
    return profileName;
};

export const getMixerChannels = (channelCount: number = 8): Channel[] => {
    const channels: Channel[] = [
        {code: 'FL', label: 'Front Left'},
        {code: 'FC', label: 'Front Center'},
        {code: 'FR', label: 'Front Right'},
        {code: 'SL', label: 'Side Left'},
        {code: 'SR', label: 'Side Right'},
        {code: 'LFE', label: 'Subwoofer (LFE)'},
        {code: 'RL', label: 'Rear Left'},
        {code: 'RR', label: 'Rear Right'},
    ];
    if (channelCount === 6) {
        // For a 5.1 setup (6 channels), only return these channels:
        return channels.filter((channel) =>
            ['FL', 'FR', 'FC', 'LFE', 'SL', 'SR'].includes(channel.code)
        );
    }
    return channels;
};

// This function updates the mixer profile based on the backend settings and running app.
export const getCurrentMixerProfile = async (): Promise<MixerProfile> => {
    const currentConfig = getPluginConfig();
    // Get selected profile. If per-app profiles are enabled, check for a profile based on the running app.
    const selectedProfileName = await getCurrentProfileFromRunningApp(currentConfig);
    // Lookup the mixer profile settings.
    let mixerProfile: MixerProfile;
    if (currentConfig.perAppProfiles &&
        currentConfig.perAppProfiles[selectedProfileName]) {
        mixerProfile = currentConfig.perAppProfiles[selectedProfileName];
    } else {
        mixerProfile = defaultMixerProfile;
    }
    // Return mixer profile
    return mixerProfile
};

export const setMixerProfileInBackend = async (mixerProfile: MixerProfile): Promise<void> => {
    // Set this 'mixerProfile' in the backend by sending the whole profile volume list
    await call<[MixerProfile], boolean>('set_mixer_profile', mixerProfile);
};

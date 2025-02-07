// Site URLs
import type {PluginConfig} from "./interfaces";

export const restartSteamClient = (): void => {
    SteamClient.User.StartRestart(false);
}

export const getPluginConfig = (): PluginConfig => {
    const defaultConfig: PluginConfig = {
        hrirName: "Steam Audio",
    };
    const dataJson = window.localStorage.getItem("decky-virtual-surround-sound");
    console.log(dataJson)
    if (dataJson) {
        try {
            const parsedConfig = JSON.parse(dataJson);
            console.log(parsedConfig)
            return {
                ...defaultConfig,
                ...parsedConfig,
            };
        } catch (error) {
            console.error("Failed to parse plugin config:", error);
        }
    }
    return defaultConfig;
}

export const setPluginConfig = (updates: Partial<PluginConfig>): void => {
    const currentConfig = getPluginConfig();
    const newConfig = {
        ...currentConfig,
        ...updates,
    };
    try {
        window.localStorage.setItem("decky-virtual-surround-sound", JSON.stringify(newConfig));
        console.log("Plugin configuration updated:", newConfig);
    } catch (error) {
        console.error("Failed to save plugin config:", error);
    }
};

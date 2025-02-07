export interface PluginConfig {
    hrirName: string;
}

export type PluginPage = "audio_controls" | "plugin_config";

export interface HrirFile {
    label: string;
    path: string;
    channel_count?: string;
}

export interface SinkInput {
    name: string;
    index: number;
    sink: number;
    format: SinkInputFormat;
    volume: string;
    target_object: string;
    enabled: boolean;
}

export interface SinkInputFormat {
    format: string;
    sample_format: string;
    rate: string;
    channels: string;
}

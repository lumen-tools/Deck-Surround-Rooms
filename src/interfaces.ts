export interface PluginConfig {
  configVersion?: number;
  installationId?: string;
  channelCount: number;
  usePerAppProfiles?: boolean;
  // Map an app's display name to its mixer profile
  perAppProfiles?: {
    [appDisplayName: string]: MixerProfile;
  };
}

export interface MixerProfile {
  name: string;
  usePerAppProfile?: boolean;
  volumes?: {
    [code: string]: number
  };
}

export interface MixerVolumes {
  FL: number;
  FR: number;
  FC: number;
  LFE: number;
  RL: number;
  RR: number;
  SL: number;
  SR: number;
}

export interface Channel {
  code: string;
  label: string;
}

export interface RunningApp {
  display_name?: string;
}

export type PluginPage = 'audio_controls' | 'plugin_config';

export interface HrirFile {
  label: string;
  path: string;
  channel_count?: number | null;
  active?: boolean;
}

export interface SinkInputFormat {
  format: string;
  sample_format: string;
  rate: string;
  channels: string;
  channel_map: string[];
}

export interface SinkInput {
  name?: string;
  index: number;
  sink?: number;
  format: SinkInputFormat;
  volume: string;
  target_object?: string;
  properties?: Record<string, string>;
}

export interface SinkInputConsolidated {
  name: string;
  index: number;
  formats: SinkInputFormat[];
  volume: string;
  target_object: string;
  sink?: number;
  connectedToVirtualSurroundSink?: boolean;
  enabled: boolean;
}

export interface Sink {
  index?: number;
  name?: string;
  description?: string;
  properties?: Record<string, string>;
}

export interface EqProfileEntry {
  id: string;
  label: string;
}

export interface EqFilter {
  type: 'LSC' | 'PK' | 'HSC';
  fc: number;
  gain: number;
  q: number;
}

export interface EqCurveData {
  preamp: number;
  filters: EqFilter[];
}

export interface EqState {
  enabled: boolean;
  active: string | null;
  profiles: EqProfileEntry[];
  curve?: EqCurveData | null;
  available?: boolean;
}

export interface HeadphoneSearchResult {
  id: string;
  name: string;
  source: string;
  form: string;
  recommended?: boolean;
}

# Decky Virtual Surround Sound

[![Chat](https://img.shields.io/badge/chat-on%20discord-7289da.svg)](https://streamingtech.co.nz/discord)

Decky Virtual Surround Sound is a Decky plugin that provides a virtual audio output device—**Virtual Surround Sound**—for games and applications. By using a custom Pipewire filter-chain module, this plugin converts 7.1 surround sound into immersive binaural audio tailored for headphone use.

> **Note:** This solution is optimized for headphone listeners. While it may work for games targeting surround sound outputs (such as theatre systems), if the game natively supports surround-to-headphone processing, that option is recommended.

Users of this plugin are able to place a custom .wav from the HRTF Database (https://airtable.com/appayGNkn3nSuXkaz/shruimhjdSakUPg2m/tbloLjoZKWJDnLtTc) at `~/.config/pipewire/hrir.wav`. Note that changing presets in the plugin config will overwrite this file. Set the file to read-only to prevent this from happening.

## Features

- **Custom Pipewire Filter-Chain:** Loads/unloads a custom filter-chain module via a script to process audio.
- **Binaural Audio Processing:** Uses HRIR-based filtering to convert 7.1 surround audio into binaural output.
- **Multiple HRIR Presets:** Choose from a list of presets including Atmos, DTS, Steam, Razer, Windows Sonic, OpenAL, Realtek, etc.
- **Per-App/Game Enablement:** Activate the virtual surround sound output on a per-game or per-application basis through the plugin UI.
- **User-Friendly Interface:** Easily enable/disable the effect without complex configuration.

## Prerequisites

- A Decky environment with support for custom plugins.
- A system running Pipewire with the ability to load/unload custom modules.
- Headphones are strongly recommended for the best experience.

## Developers

### Dependencies

This relies on the user having Node.js v16.14+ and `pnpm` (v9) installed on their system.  
Please make sure to install pnpm v9 to prevent issues with CI during plugin submission.  
`pnpm` can be downloaded from `npm` itself which is recommended.

#### Linux

```bash
npm i -g pnpm@9
```

### Building Virtual Surround Sound

1. Clone the repository.
2. In your local fork/own plugin-repository run these commands:
   1. ``pnpm i``
   2. ``ln -sf ./defaults/service.sh ./service.sh``
   3. ``pnpm run build``
      - These setup pnpm and build the frontend code for testing.
3. Use the [decky-frontend-lib](https://github.com/SteamDeckHomebrew/decky-frontend-lib) documentation to integrate additional functionality as needed.
4. If using VSCodium/VSCode, run the `setup` and `build` and `deploy` tasks. If not using VSCodium etc. you can derive your own makefile or just manually utilize the scripts for these commands as you see fit.

If you use VSCode or it's derivatives (we suggest [VSCodium](https://vscodium.com/)!) just run the `setup` and `build` tasks. It's really that simple.

#### Rebuilding After Code Changes

Everytime you change the frontend code (`index.tsx` etc) you will need to rebuild using the commands from step 2 above or the build task if you're using vscode or a derivative.

Note: If you are receiving build errors due to an out of date library, you should run this command inside of your repository:

```bash
pnpm update @decky/ui --latest
```

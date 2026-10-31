> **Fork notice:** This is a fork of [Virtual Surround Sound](https://github.com/DeckSettings/decky-virtual-surround-sound) by Josh.5, maintained by [lumen-tools](https://github.com/lumen-tools/decky-virtual-surround-rooms).

# Virtual Surround + Rooms

> **No sound after switching?** Change the volume briefly (up or down). The sound comes back immediately.

Virtual Surround + Rooms is a Decky plugin that provides a virtual audio output device—**Virtual Surround + Rooms**—for games and applications. By using a custom Pipewire filter-chain module, this plugin converts 7.1 surround sound into immersive binaural audio tailored for headphone use.

> **Note:** This solution is optimized for headphone listeners. While it may work for games targeting surround sound outputs (such as theatre systems), if the game natively supports surround-to-headphone processing, that option is recommended.

Users of this plugin are able to place a custom .wav from the HRTF Database (<https://airtable.com/appayGNkn3nSuXkaz/shruimhjdSakUPg2m/tbloLjoZKWJDnLtTc>) at `~/.config/pipewire/hrir.wav`. Note that changing presets in the plugin config will overwrite this file. Set the file to read-only to prevent this from happening.

## Features

- **Custom Pipewire Filter-Chain:** Loads/unloads a custom filter-chain module via a script to process audio.
- **Binaural Audio Processing:** Convolves 7.1 surround audio with binaural room impulse responses (BRIRs) for headphone output.
- **Room Presets:** Eight real rooms, from broadcast studios to a lecture hall, measured with dummy heads.
- **One Switch:** Turns virtual surround on or off for all apps and games.
- **User-Friendly Interface:** Easily enable/disable the effect without complex configuration.

## Prerequisites

- A Decky environment with support for custom plugins.
- A system running Pipewire with the ability to load/unload custom modules.
- Headphones are strongly recommended for the best experience.

## Developers

### Dependencies

This relies on the user having Node.js v18+ and `pnpm` (v9) installed on their system.  
Please make sure to install pnpm v9 to prevent issues with CI during plugin submission.  
`pnpm` can be downloaded from `npm` itself which is recommended.

#### Linux

```bash
npm i -g pnpm@9
```

### Building Virtual Surround + Rooms

1. Clone the repository.
2. In your local fork/own plugin-repository run these commands:
   1. `pnpm i`
   2. `ln -sf ./defaults/service.sh ./service.sh`
   3. `ln -sf ./defaults/hrir-audio ./hrir-audio`
   4. `ln -sf ./defaults/hrtf-sofa ./hrtf-sofa`
   5. `pnpm run build`
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

### Development environment

Install some useful tools

```bash
python3 -m venv venv --clear
source venv/bin/activate

python3 -m pip install pulsemixer

```

Create a symlink to the stuff in `defaults` so that the plugin can use them

```bash
ln -sf ./defaults/hrir-audio hrir-audio
ln -sf ./defaults/service.sh service.sh
```

Install virtual surround sound service

```bash
./service.sh install
```

Run the CLI

```bash
python ./main.py 
```

## Notes on how this works on SteamOS

SteamOS ships with PipeWire for low-latency audio handling and WirePlumber as its default session manager. WirePlumber negotiates which nodes become available to the desktop and what devices Steam exposes in Settings, while PipeWire handles the actual DSP graph. Virtual Surround + Rooms slots into that graph by loading a custom `module-filter-chain` definition that mixes 7.1 input down to binaural headphone output.

Instead of dropping a static filter-chain file into `~/.config/pipewire`, the plugin installs a user-level systemd unit that calls `service.sh`. The script dynamically loads and unloads the filter through PipeWire's CLI so the module is registered immediately, without needing to restart PipeWire or WirePlumber (those restarts tend to upset Steam until you reboot the client). This approach also keeps Steam's Audio Output list clean: the filter is advertised directly to PipeWire so it just appears as another routable node rather than an extra, confusing device entry inside Steam Settings.

The filter itself relies on Head Related Impulse Response (HRIR) data. HRIR files capture how sound at different angles reaches real human ears, combining the effects of head, torso, and outer ear reflections into short impulse responses. When convolving speaker channels with HRIRs, we approximate how a surround speaker layout would sound through headphones, delivering the virtual surround effect. The plugin ships with eight room presets (see below), and you can experiment with others. A good catalog of measured HRIRs lives at [HRTF Database](https://airtable.com/appayGNkn3nSuXkaz/shruimhjdSakUPg2m/tbloLjoZKWJDnLtTc).

During startup, the systemd unit runs `service.sh` which writes the selected HRIR into `~/.config/pipewire/hrir.wav`, ensures the filter parameters match your preset, and issues the PipeWire commands required to (re)load the module. Because everything happens in-process, switching presets or enabling/disabling the plugin is instantaneous and doesn’t interfere with the rest of the audio stack.

## Presets and licences

The bundled presets are binaural room impulse responses (BRIRs) of real rooms, taken from the [ASH IR Dataset](https://github.com/ShanonPearce/ASH-IR-Dataset) by Shanon Pearce (licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)). The 7.1 layout uses front ±30°, sides ±90° and rear ±150°. The files were converted to the 14 channel HeSuVi layout and resampled to 48 kHz for this plugin.

| Preset | Room | Size (m) | RT60 | Head | Original measurements | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| Small Studio | Control Room 1, WDR Broadcast Studios | 6.85 x 5.48 x 2.47 | 0.23 s | Neumann KU100 | [1] | CC BY-SA 3.0 |
| Medium Studio | Control Room 7, WDR Broadcast Studios | 7.26 x 8.26 x 2.90 | 0.27 s | Neumann KU100 | [1] | CC BY-SA 3.0 |
| Large Studio | Small Broadcast Studio, WDR Broadcast Studios (reverberation reduced in the dataset) | 17.33 x 11.07 x 6.20 | reduced (originally 0.97 s) | Neumann KU100 | [1] | CC BY-SA 3.0 |
| TV Studio | TV Studio, TU Ilmenau | 19.50 x 11.50 x 5.50 | 0.70 s | KEMAR | [2] | CC BY-NC 4.0 |
| Listening Room | Listening Room, University of Salford | 5.80 x 6.60 x 2.70 | 0.26 s | B&K HATS 4100 | [3] | CC BY-NC-SA 4.0 |
| Audio Lab | Audio Lab, University of Rostock (with absorbers) | 5.00 x 5.75 x 3.00 | 0.37 s | KEMAR 45BA | [4] | CC BY 4.0 |
| Conference Room | Conference Room, TU Ilmenau | 10.31 x 5.76 x 3.10 | 0.41 s | KEMAR 45BA | [5] | CC BY 4.0 |
| Lecture Hall | Auditorium 3, TU Berlin | 10.00 x 9.00 | 0.46 s | KEMAR 45BA | [6] | CC BY 4.0 |

1. P. Stade, B. Bernschütz and M. Rühl, "A Spatial Audio Impulse Response Compilation Captured at the WDR Broadcast Studios", 27th Tonmeistertagung – VDT International Convention, Cologne, 2012. <http://audiogroup.web.th-koeln.de/wdr_irc.html>
2. S. Werner, M. Voigt and F. Klein, "Dataset of measured binaural room impulse responses for use in an position-dynamic auditory augmented reality application", Zenodo, 2018. <https://zenodo.org/record/1321996>
3. F. Melchior, D. Marston, C. Pike, D. Satongar and Y. Lam, "The Salford BBC Spatially-sampled Binaural Room Impulse Response dataset", University of Salford, 2014. <http://usir.salford.ac.uk/id/eprint/30868>
4. V. Erbes, M. Geier, S. Weinzierl and S. Spors, "Single-channel and binaural room impulse responses of a 64-channel loudspeaker array for different room configurations", depositonce, 2015. <http://dx.doi.org/10.14279/depositonce-87.6>
5. A. Neidhardt, "Binaural room impulse responses: Same listener-source-setup at different positions in the room", Zenodo, 2016. <https://doi.org/10.5281/zenodo.163617>
6. H. Wierstorf and M. Geier, "Binaural room impulse responses recorded with KEMAR in a mid-size lecture hall", Zenodo, 2016. <https://doi.org/10.5281/zenodo.160749>

The converted files in `defaults/hrir-audio` are distributed under CC BY-NC-SA 4.0 (see `defaults/hrir-audio/LICENSE.txt`) and must not be used commercially. The licence of the plugin code (BSD-3-Clause) does not apply to these files.

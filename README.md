# DeckSurroundRooms

**Virtual 7.1 surround for headphones on the Steam Deck, with real room simulation and headphone correction.**

DeckSurroundRooms is a [Decky](https://github.com/SteamDeckHomebrew/decky-loader) plugin. It adds a virtual 7.1 audio device that games and apps play into, and renders it binaurally for your headphones, as if you were sitting in front of a real speaker setup in a studio or listening room.

DeckSurroundRooms is a fork of [Virtual Surround Sound](https://github.com/DeckSettings/decky-virtual-surround-sound) by Josh.5 (see [Credits](#credits)).

> **No sound after switching?** Change the volume briefly (up or down). The sound comes back immediately.

## Features

- **Real rooms instead of a dry virtualiser:** Eight binaural room impulse responses (BRIRs) measured with dummy heads in real rooms, from broadcast studios to a lecture hall. The room's reflections and reverb put the sound outside your head and give it a natural distance. Two dry presets without room are included as well.
- **One switch:** Turns surround on or off for all games and apps at once.
- **Headphone EQ:** Corrects your headphones to a neutral (Harman) response with a profile from [AutoEq](https://github.com/jaakkopasanen/AutoEq). It also works with surround switched off.
- **Output selection:** Choose which headphones or output device the processed sound goes to.
- **Channel activity:** Shows live which of the 8 channels carry audio, so you can see whether a game really outputs surround.
- **Mixer:** Adjust each speaker's level, optionally with a separate profile per game.
- **Sound test:** Plays each speaker in turn, with and without surround, or a single speaker on its own.

## Installation

DeckSurroundRooms is not in the Decky Plugin Store. Install it from the [latest release](https://github.com/lumen-tools/Deck-Surround-Rooms/releases/latest):

1. **Uninstall older versions first.** This applies to *Virtual Surround + Rooms* (the previous name of this plugin) and to the original *Virtual Surround Sound* plugin. They all use the same audio service and would get in each other's way. Settings from *Virtual Surround + Rooms* are taken over automatically.
2. In Decky, open **Settings → General** and turn on **Developer mode**.
3. Open **Settings → Developer**, choose **Install Plugin from URL** and enter:
   ```
   https://github.com/lumen-tools/Deck-Surround-Rooms/releases/latest/download/deck-surround-rooms.zip
   ```
   Alternatively, download the ZIP from the latest release and use **Install Plugin from ZIP File**.

**Updating:** Repeat step 3. Your settings are kept.

## Usage

Open the Quick Access Menu (**…** button) and select DeckSurroundRooms.

| Control | What it does |
| --- | --- |
| **Virtual Surround** | Turns surround on or off for everything. It is only available while headphones or another external output are connected. Switching in the middle of a game can mute its audio until the game is restarted. |
| **Output** | The device the processed sound is played on. |
| **Room** | The room preset, or a dry preset without room (see [Room presets](#room-presets)). |
| **Channels** | Live activity of the 8 input channels. |
| **Headphone EQ** | Search AutoEq for your headphones, or import a profile file. Saved headphones can be switched with one tap. |
| **Mixer** | Level of each speaker (0–150 %). With **Per-game profile** on, the running game gets its own settings. |
| **Settings** (gear icon) | Sound test, full reset and links. |

Most games only output 7.1 when they detect a surround device. If **Channels** only shows activity on the front left and right channels, choose 7.1 or surround in the game's audio settings.

## Room presets

Each preset is a binaural room impulse response of a real room, taken from the [ASH IR Dataset](https://github.com/ShanonPearce/ASH-IR-Dataset) by Shanon Pearce. The 7.1 layout uses front ±30°, sides ±90° and rear ±150°. The files were converted to the 14-channel HeSuVi layout and resampled to 48 kHz.

| Preset | Room | Size (m) | RT60 | Head | Source | Licence |
| --- | --- | --- | --- | --- | --- | --- |
| Small Studio | Control Room 1, WDR Broadcast Studios | 6.85 × 5.48 × 2.47 | 0.23 s | Neumann KU100 | [1] | CC BY-SA 3.0 |
| Medium Studio | Control Room 7, WDR Broadcast Studios | 7.26 × 8.26 × 2.90 | 0.27 s | Neumann KU100 | [1] | CC BY-SA 3.0 |
| Large Studio | Small Broadcast Studio, WDR Broadcast Studios (reverberation reduced in the dataset) | 17.33 × 11.07 × 6.20 | reduced (originally 0.97 s) | Neumann KU100 | [1] | CC BY-SA 3.0 |
| TV Studio | TV Studio, TU Ilmenau | 19.50 × 11.50 × 5.50 | 0.70 s | KEMAR | [2] | CC BY-NC 4.0 |
| Listening Room | Listening Room, University of Salford | 5.80 × 6.60 × 2.70 | 0.26 s | B&K HATS 4100 | [3] | CC BY-NC-SA 4.0 |
| Audio Lab | Audio Lab, University of Rostock (with absorbers) | 5.00 × 5.75 × 3.00 | 0.37 s | KEMAR 45BA | [4] | CC BY 4.0 |
| Conference Room | Conference Room, TU Ilmenau | 10.31 × 5.76 × 3.10 | 0.41 s | KEMAR 45BA | [5] | CC BY 4.0 |
| Lecture Hall | Auditorium 3, TU Berlin | 10.00 × 9.00 | 0.46 s | KEMAR 45BA | [6] | CC BY 4.0 |

Small Studio is the default. Smaller, drier rooms sound more precise; larger rooms sound more spacious but less direct.

### Dry presets

For a direct sound without any room, two anechoic HRIRs (head-related impulse responses measured without room reflections) are included. Both are from the [SADIE II database](https://www.york.ac.uk/sadie-project/database.html) of the University of York and use the same dummy heads as most of the rooms:

| Preset | Dummy head | Source | Licence |
| --- | --- | --- | --- |
| Dry · Neumann KU100 (Dummy Head) | Neumann KU100 | SADIE II, D01 | Apache 2.0 |
| Dry · KEMAR (Dummy Head) | KEMAR | SADIE II, D02 | Apache 2.0 |

C. Armstrong, L. Thresh, D. Murphy and G. Kearney, "A Perceptual Evaluation of Individual and Non-Individual HRTFs: A Case Study of the SADIE II Database", Applied Sciences, 2018. The licence text is in [`defaults/hrir-audio/LICENSE-SADIE.txt`](defaults/hrir-audio/LICENSE-SADIE.txt).

1. P. Stade, B. Bernschütz and M. Rühl, "A Spatial Audio Impulse Response Compilation Captured at the WDR Broadcast Studios", 27th Tonmeistertagung – VDT International Convention, Cologne, 2012. <http://audiogroup.web.th-koeln.de/wdr_irc.html>
2. S. Werner, M. Voigt and F. Klein, "Dataset of measured binaural room impulse responses for use in an position-dynamic auditory augmented reality application", Zenodo, 2018. <https://zenodo.org/record/1321996>
3. F. Melchior, D. Marston, C. Pike, D. Satongar and Y. Lam, "The Salford BBC Spatially-sampled Binaural Room Impulse Response dataset", University of Salford, 2014. <http://usir.salford.ac.uk/id/eprint/30868>
4. V. Erbes, M. Geier, S. Weinzierl and S. Spors, "Single-channel and binaural room impulse responses of a 64-channel loudspeaker array for different room configurations", depositonce, 2015. <http://dx.doi.org/10.14279/depositonce-87.6>
5. A. Neidhardt, "Binaural room impulse responses: Same listener-source-setup at different positions in the room", Zenodo, 2016. <https://doi.org/10.5281/zenodo.163617>
6. H. Wierstorf and M. Geier, "Binaural room impulse responses recorded with KEMAR in a mid-size lecture hall", Zenodo, 2016. <https://doi.org/10.5281/zenodo.160749>

The converted room files in `defaults/hrir-audio` are distributed under CC BY-NC-SA 4.0 (see [`defaults/hrir-audio/LICENSE.txt`](defaults/hrir-audio/LICENSE.txt)) and must not be used commercially. The BSD-3-Clause licence of the plugin code does not apply to these files.

## Headphone EQ

The headphone EQ uses parametric profiles from [AutoEq](https://github.com/jaakkopasanen/AutoEq) by Jaakko Pasanen (MIT licence), computed from measurements by oratory1990, crinacle, Rtings and others. Over-ear and on-ear headphones are corrected to the Harman over-ear target, in-ears to the Harman in-ear target.

No profiles are bundled. Searching needs an internet connection once; the chosen profile is then stored and works offline.

**Importing a profile without internet:** Download the `<headphones> ParametricEQ.txt` file of your headphones from the [AutoEq results](https://github.com/jaakkopasanen/AutoEq/tree/master/results), or select the equalizer app **EqualizerAPO ParametricEq** on [autoeq.app](https://autoeq.app) and download the result. Copy the file to the Steam Deck (e.g. to `Downloads`) and choose **Headphone EQ → Import file…** in the plugin. GraphicEQ and FixedBandEQ files are not supported.

## How it works

SteamOS uses PipeWire for audio and WirePlumber as its session manager. DeckSurroundRooms installs a user-level systemd service that runs `service.sh`. The script loads three PipeWire nodes at runtime, without restarting PipeWire or WirePlumber (which tends to upset Steam):

1. **DeckSurroundRooms** – a 7.1 device that games and apps play into. When surround is on, it becomes the default output and running apps are moved onto it.
2. **Room filter** – a `module-filter-chain` that convolves each of the 7 speaker channels with the room's impulse responses for both ears, feeds the low-pass-filtered LFE channel directly to both ears and then applies the headphone EQ and a limiter (see [Clipping protection](#clipping-protection)).
3. **Headphone EQ** – a stereo sink with only the headphone EQ, used when surround is off and the EQ is on.

The selected room is normalised (equal loudness for every speaker, symmetric left and right) and written to `~/.config/pipewire/hrir.wav`, so switching rooms does not change the volume. The volume of the DeckSurroundRooms device is mirrored onto the real output device, so the Steam volume slider keeps working and the volume is not applied twice.

## Clipping protection

In surround mode, up to eight channels are added up for each ear. Loud surround mixes (explosions, gunfire, bass on all channels) can add up to more than 0 dBFS, which the output would clip hard. The surround chain therefore leaves 6 dB of headroom and ends with the *Fast Lookahead Limiter* from Steve Harris' [swh LADSPA plugins](https://github.com/swh/ladspa) (GPL-2.0). It holds the output at -1 dBFS and adds 5 ms of latency. Normal game audio stays below the limit and is not changed.

The limiter is bundled in `defaults/ladspa` together with its source and licence. If PipeWire can't load it, the surround chain runs without limiter. The headphone EQ without surround has no limiter, since nothing is added up there and the AutoEq profiles already lower the level by their preamp.

## Credits

DeckSurroundRooms is a fork of [Virtual Surround Sound](https://github.com/DeckSettings/decky-virtual-surround-sound) by Josh.5 and was previously called *Virtual Surround + Rooms*. Compared to the original, it:

- uses freely licensed measurements of real rooms instead of presets derived from commercial products with unclear licensing,
- normalises every speaker to the same loudness, keeps left and right symmetric and keeps the volume constant when switching presets,
- applies the output volume only once,
- switches all apps with one switch and fixes delayed switching, silence after turning surround back on and dropouts when changing the room,
- adds the headphone EQ, output selection, channel activity and an extended sound test,
- has a cleaner interface with a one-click reset.

## Development

Requirements: Node.js 18–24 and pnpm 9 (`npm i -g pnpm@9`).

```bash
pnpm i
pnpm run build
```

The frontend is built to `dist/`. To run the backend outside Decky, link the files from `defaults/` and start the CLI:

```bash
ln -sf ./defaults/service.sh service.sh
ln -sf ./defaults/hrir-audio hrir-audio
./service.sh install
python3 main.py --menu
```

With VS Code or VSCodium, the `setup`, `build` and `deploy` tasks in `.vscode/tasks.json` build the plugin with the Decky CLI and copy it to a Steam Deck (the `setup` task creates `.vscode/settings.json`; enter the address and login of your Steam Deck there).

Pushing to `master` builds the plugin and, if the version in `package.json` has no release yet, publishes a new release.

## Licence

The plugin code is licensed under [BSD-3-Clause](LICENSE). The room and dry presets have their own licences, see [Room presets](#room-presets). The bundled limiter is licensed under GPL-2.0, see [`defaults/ladspa/README.txt`](defaults/ladspa/README.txt).

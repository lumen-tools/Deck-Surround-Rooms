#!/bin/bash
set -e

# Get script path
script_path="$(readlink -f "${BASH_SOURCE[0]}")"
script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
real_script_directory="$(cd "$(dirname "${script_path}")" && pwd)"

# Catch term signal
_term() {
    stop_audio_event_subscription
    cleanup_headphone_eq_module
    cleanup_virtual_surround_module
    cleanup_virtual_surround_default_sink
}

service_shutdown_requested="false"
_handle_signal() {
    if [[ "${service_shutdown_requested}" == "true" ]]; then
        return
    fi
    service_shutdown_requested="true"
    _term
    exit 1
}

# Per-input gain of the final L/R mixers (linear). 0.5 == -6dB.
# NOTE: PipeWire filter-chain links do NOT support a "gain" key (it is ignored with an
# "unexpected link key" error), so the gain has to be set as a control on the mixer nodes.
mix_gain="0.5"
# Low-pass cut-off for the LFE channel. LFE is non-directional, so it is low-passed and fed
# to both ears directly instead of being convolved with the centre HRIR.
lfe_cutoff_hz="120"

# Configure pipewire modules names/descriptions
virtual_surround_filter_sink_node_name="vss-filter"
virtual_surround_filter_sink_description="Virtual Surround + Rooms Filter"
virtual_surround_filter_sink_capture_node_name="input.vss-filter"
virtual_surround_filter_sink_playback_node_name="output.vss-filter"
if [[ -n "${VIRTUAL_SURROUND_SINK_SUFFIX:-}" ]]; then
    virtual_surround_filter_sink_node_name="vss-filter"
    virtual_surround_filter_sink_description="Virtual Surround + Rooms (${VIRTUAL_SURROUND_SINK_SUFFIX:-})"
    virtual_surround_filter_sink_capture_node_name="input.vss-filter-${VIRTUAL_SURROUND_SINK_SUFFIX:-}"
    virtual_surround_filter_sink_playback_node_name="output.vss-filter-${VIRTUAL_SURROUND_SINK_SUFFIX:-}"
fi
virtual_surround_device_sink_node_name="virtual-surround-sound"
virtual_surround_device_sink_description="Virtual Surround + Rooms"
virtual_surround_device_sink_capture_node_name="Virtual Surround Sound"
virtual_surround_device_sink_playback_node_name="output.virtual-surround-sound"
# Stereo sink with only the headphone EQ (no room simulation), used when surround is off but the
# headphone EQ is on.
virtual_surround_eq_sink_node_name="vss-headphone-eq"
virtual_surround_eq_sink_description="Headphone EQ"
virtual_surround_eq_sink_capture_node_name="input.vss-headphone-eq"
virtual_surround_eq_sink_playback_node_name="output.vss-headphone-eq"

# 7.1
device_module_args_8=$(
    cat <<EOF
{
    "audio.channels": 8,
    "audio.position": [ FL FR FC LFE RL RR SL SR ],
    "node.name": "${virtual_surround_device_sink_node_name:?}",
    "node.description": "${virtual_surround_device_sink_description:?}",
    filter.graph = {
        "nodes": [
            { "type": "builtin", "label": "copy", "name": "copyFL" },
            { "type": "builtin", "label": "copy", "name": "copyFR" },
            { "type": "builtin", "label": "copy", "name": "copyFC" },
            { "type": "builtin", "label": "copy", "name": "copyLFE" },
            { "type": "builtin", "label": "copy", "name": "copyRL" },
            { "type": "builtin", "label": "copy", "name": "copyRR" },
            { "type": "builtin", "label": "copy", "name": "copySL" },
            { "type": "builtin", "label": "copy", "name": "copySR" }
        ],
        "inputs":  [ "copyFL:In", "copyFR:In", "copyFC:In", "copyLFE:In", "copyRL:In", "copyRR:In", "copySL:In", "copySR:In" ],
        "outputs": [ "copyFL:Out", "copyFR:Out", "copyFC:Out", "copyLFE:Out", "copyRL:Out", "copyRR:Out", "copySL:Out", "copySR:Out" ]
    },
    capture.props = {
        "media.class": "Audio/Sink",
        "node.name": "${virtual_surround_device_sink_capture_node_name:?}",
        "node.description": "${virtual_surround_device_sink_description:?}",
        "node.dont-fallback": true,
        "node.passive": true,
        "node.linger": true,
        "node.autoconnect": false,
        "stream.dont-remix": true,
        "channelmix.normalize": false,
        "audio.channels": 8,
        "audio.position": [ FL FR FC LFE RL RR SL SR ]
    },
    playback.props = {
        "node.name": "${virtual_surround_device_sink_playback_node_name:?}",
        "node.passive": true,
        "node.autoconnect": false,
        "stream.dont-remix": true,
        "channelmix.normalize": false,
        "audio.channels": 8,
        "audio.position": [ FL FR FC LFE RL RR SL SR ]
    }
}
EOF
)
# ---- Headphone EQ ------------------------------------------------------------------------------
# A fixed chain of filters per ear behind the binaural mix: preamp, 2 low shelves, 10 peaks and 2 high
# shelves. Biquads in series commute, so any AutoEq parametric profile fits into these slots; unused
# slots have 0 dB gain and do nothing. The plugin writes the values to ${eq_settings_file} (read when
# the filter is loaded) and changes them at runtime without reloading.
eq_settings_file="${HOME:?}/.config/pipewire/vss-eq.txt"
eq_slots=(ls1 ls2 pk1 pk2 pk3 pk4 pk5 pk6 pk7 pk8 pk9 pk10 hs1 hs2)

eq_slot_label() {
    case "$1" in
    ls*) echo "bq_lowshelf" ;;
    hs*) echo "bq_highshelf" ;;
    *) echo "bq_peaking" ;;
    esac
}

# Prints "freq q gain" for a slot (or the linear preamp for "pre") from the settings file.
eq_slot_values() {
    local slot="$1" values=""
    if [[ -f "${eq_settings_file}" ]]; then
        values=$(awk -v s="${slot}" '$1 == s { $1 = ""; sub(/^ /, ""); print; exit }' "${eq_settings_file}" 2>/dev/null || true)
    fi
    if [[ -z "${values}" ]]; then
        if [[ "${slot}" == "pre" ]]; then values="1.0"; else values="1000 0.707 0"; fi
    fi
    echo "${values}"
}

eq_graph_nodes() {
    local side slot label freq q gain pre
    pre=$(eq_slot_values pre)
    for side in L R; do
        printf ',\n            { "type": "builtin", "label": "mixer", "name": "eq%s_pre", "control": { "Gain 1": %s } }' "${side}" "${pre}"
        for slot in "${eq_slots[@]}"; do
            label=$(eq_slot_label "${slot}")
            read -r freq q gain <<<"$(eq_slot_values "${slot}")"
            printf ',\n            { "type": "builtin", "label": "%s", "name": "eq%s_%s", "control": { "Freq": %s, "Q": %s, "Gain": %s } }' \
                "${label}" "${side}" "${slot}" "${freq}" "${q}" "${gain}"
        done
    done
}

eq_graph_links() {
    local side slot prev
    for side in L R; do
        printf ',\n            { "output": "mix%s:Out", "input": "eq%s_pre:In 1" }' "${side}" "${side}"
        prev="eq${side}_pre"
        for slot in "${eq_slots[@]}"; do
            printf ',\n            { "output": "%s:Out", "input": "eq%s_%s:In" }' "${prev}" "${side}" "${slot}"
            prev="eq${side}_${slot}"
        done
    done
}

# EQ-only filter chain: 2 channels in, the same EQ chain as behind the binaural mix, 2 channels out.
build_eq_module_args() {
    local nodes links
    nodes=$(eq_graph_nodes)
    links=$(eq_graph_links | grep -v '"output": "mix[LR]:Out"')
    eq_module_args=$(
        cat <<EOF
{
    "node.name": "${virtual_surround_eq_sink_node_name:?}",
    "node.description": "${virtual_surround_eq_sink_description:?}",
    filter.graph = {
        "nodes": [
            ${nodes#*,}
        ],
        "links": [
            ${links#*,}
        ],
        "inputs":  [ "eqL_pre:In 1", "eqR_pre:In 1" ],
        "outputs": [ "eqL_hs2:Out", "eqR_hs2:Out" ]
    },
    capture.props = {
        "node.name": "${virtual_surround_eq_sink_capture_node_name:?}",
        "node.description": "${virtual_surround_eq_sink_description:?}",
        "node.nick": "${virtual_surround_eq_sink_description:?}",
        "media.class": "Audio/Sink",
        "audio.channels": 2,
        "audio.position": [ FL FR ],
        "node.dont-fallback": true
    },
    playback.props = {
        "node.name": "${virtual_surround_eq_sink_playback_node_name:?}",
        "node.passive": true,
        "node.autoconnect": false,
        "audio.channels": 2,
        "audio.position": [ FL FR ],
        "stream.dont-remix": true
    }
}
EOF
    )
}

build_filter_module_convolver_args_8() {
filter_module_convolver_args_8=$(
    cat <<EOF
{
    "audio.channels": 8,
    "audio.position": ["FL","FR","FC","LFE","RL","RR","SL","SR"],
    "node.name": "${virtual_surround_filter_sink_node_name:?}",
    "node.description": "${virtual_surround_filter_sink_description:?}",
    filter.graph = {
        "nodes": [
            { "type": "builtin", "label": "copy", "name": "copyFL" },
            { "type": "builtin", "label": "copy", "name": "copyFR" },
            { "type": "builtin", "label": "copy", "name": "copyFC" },
            { "type": "builtin", "label": "copy", "name": "copyRL" },
            { "type": "builtin", "label": "copy", "name": "copyRR" },
            { "type": "builtin", "label": "copy", "name": "copySL" },
            { "type": "builtin", "label": "copy", "name": "copySR" },
            { "type": "builtin", "label": "copy", "name": "copyLFE" },
            { "type": "builtin", "label": "convolver", "name": "convFL_L", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 0 } },
            { "type": "builtin", "label": "convolver", "name": "convFL_R", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 1 } },
            { "type": "builtin", "label": "convolver", "name": "convSL_L", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 2 } },
            { "type": "builtin", "label": "convolver", "name": "convSL_R", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 3 } },
            { "type": "builtin", "label": "convolver", "name": "convRL_L", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 4 } },
            { "type": "builtin", "label": "convolver", "name": "convRL_R", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 5 } },
            { "type": "builtin", "label": "convolver", "name": "convFC_L", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 6 } },
            { "type": "builtin", "label": "convolver", "name": "convFR_R", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 7 } },
            { "type": "builtin", "label": "convolver", "name": "convFR_L", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 8 } },
            { "type": "builtin", "label": "convolver", "name": "convSR_R", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 9 } },
            { "type": "builtin", "label": "convolver", "name": "convSR_L", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 10 } },
            { "type": "builtin", "label": "convolver", "name": "convRR_R", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 11 } },
            { "type": "builtin", "label": "convolver", "name": "convRR_L", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 12 } },
            { "type": "builtin", "label": "convolver", "name": "convFC_R", "config": { "filename": "${HOME:?}/.config/pipewire/hrir.wav", "channel": 13 } },
            { "type": "builtin", "label": "bq_lowpass", "name": "lpLFE", "control": { "Freq": ${lfe_cutoff_hz:?}, "Q": 0.707 } },
            { "type": "builtin", "label": "mixer", "name": "mixL", "control": { "Gain 1": ${mix_gain:?}, "Gain 2": ${mix_gain:?}, "Gain 3": ${mix_gain:?}, "Gain 4": ${mix_gain:?}, "Gain 5": ${mix_gain:?}, "Gain 6": ${mix_gain:?}, "Gain 7": ${mix_gain:?}, "Gain 8": ${mix_gain:?} } },
            { "type": "builtin", "label": "mixer", "name": "mixR", "control": { "Gain 1": ${mix_gain:?}, "Gain 2": ${mix_gain:?}, "Gain 3": ${mix_gain:?}, "Gain 4": ${mix_gain:?}, "Gain 5": ${mix_gain:?}, "Gain 6": ${mix_gain:?}, "Gain 7": ${mix_gain:?}, "Gain 8": ${mix_gain:?} } }$(eq_graph_nodes)
        ],
        "links": [
            { "output": "copyFL:Out", "input": "convFL_L:In" },
            { "output": "copyFL:Out", "input": "convFL_R:In" },
            { "output": "copySL:Out", "input": "convSL_L:In" },
            { "output": "copySL:Out", "input": "convSL_R:In" },
            { "output": "copyRL:Out", "input": "convRL_L:In" },
            { "output": "copyRL:Out", "input": "convRL_R:In" },
            { "output": "copyFC:Out", "input": "convFC_L:In" },
            { "output": "copyFR:Out", "input": "convFR_R:In" },
            { "output": "copyFR:Out", "input": "convFR_L:In" },
            { "output": "copySR:Out", "input": "convSR_R:In" },
            { "output": "copySR:Out", "input": "convSR_L:In" },
            { "output": "copyRR:Out", "input": "convRR_R:In" },
            { "output": "copyRR:Out", "input": "convRR_L:In" },
            { "output": "copyFC:Out", "input": "convFC_R:In" },
            { "output": "copyLFE:Out", "input": "lpLFE:In" },
            { "output": "convFL_L:Out", "input": "mixL:In 1" },
            { "output": "convFL_R:Out", "input": "mixR:In 1" },
            { "output": "convSL_L:Out", "input": "mixL:In 2" },
            { "output": "convSL_R:Out", "input": "mixR:In 2" },
            { "output": "convRL_L:Out", "input": "mixL:In 3" },
            { "output": "convRL_R:Out", "input": "mixR:In 3" },
            { "output": "convFC_L:Out", "input": "mixL:In 4" },
            { "output": "convFC_R:Out", "input": "mixR:In 4" },
            { "output": "convFR_R:Out", "input": "mixR:In 5" },
            { "output": "convFR_L:Out", "input": "mixL:In 5" },
            { "output": "convSR_R:Out", "input": "mixR:In 6" },
            { "output": "convSR_L:Out", "input": "mixL:In 6" },
            { "output": "convRR_R:Out", "input": "mixR:In 7" },
            { "output": "convRR_L:Out", "input": "mixL:In 7" },
            { "output": "lpLFE:Out", "input": "mixR:In 8" },
            { "output": "lpLFE:Out", "input": "mixL:In 8" }$(eq_graph_links)
        ],
        "inputs":  [ "copyFL:In", "copyFR:In", "copyFC:In", "copyLFE:In", "copyRL:In", "copyRR:In", "copySL:In", "copySR:In" ],
        "outputs": [ "eqL_hs2:Out", "eqR_hs2:Out" ]
    },
    capture.props = {
        "node.name": "${virtual_surround_filter_sink_capture_node_name:?}",
        "node.description": "${virtual_surround_filter_sink_description:?}",
        "node.nick": "${virtual_surround_filter_sink_description:?}",
        "media.class": "Audio/Sink",
        "audio.channels": 8,
        "audio.position": [ FL FR FC LFE RL RR SL SR ],
        "node.dont-fallback": true,
        "node.linger": true,
        "node.autoconnect": false,
        "stream.dont-remix": true,
        "channelmix.normalize": false
    },
    playback.props = {
        "node.name": "${virtual_surround_filter_sink_playback_node_name:?}",
        "node.passive": true,
        "node.autoconnect": false,
        "audio.channels": 2,
        "audio.position": [ FL FR ],
        "stream.dont-remix": true,
        "channelmix.normalize": false
    }
}
EOF
)
}
build_filter_module_convolver_args_8
filter_module_sofa_args_8=$(
    cat <<EOF
{
    "audio.channels": 8,
    "audio.position": ["FL","FR","FC","LFE","RL","RR","SL","SR"],
    "node.name": "${virtual_surround_filter_sink_node_name:?}",
    "node.description": "${virtual_surround_filter_sink_description:?}",
    filter.graph = {
        "nodes": [
            {
                "type": "sofa",
                "label": "spatializer",
                "name": "spFL",
                "config": {
                    "filename": "${HOME:?}/.config/pipewire/hrir.sofa"
                },
                "control": {
                    "Azimuth": 30.0,
                    "Elevation": -10.0,
                    "Radius": 10.0
                }
            },
            {
                "type": "sofa",
                "label": "spatializer",
                "name": "spFR",
                "config": {
                    "filename": "${HOME:?}/.config/pipewire/hrir.sofa"
                },
                "control": {
                    "Azimuth": 330.0,
                    "Elevation": -10.0,
                    "Radius": 10.0
                }
            },
            {
                "type": "sofa",
                "label": "spatializer",
                "name": "spFC",
                "config": {
                    "filename": "${HOME:?}/.config/pipewire/hrir.sofa"
                },
                "control": {
                    "Azimuth": 0.0,
                    "Elevation": -10.0,
                    "Radius": 10.0
                }
            },
            {
                "type": "sofa",
                "label": "spatializer",
                "name": "spRL",
                "config": {
                    "filename": "${HOME:?}/.config/pipewire/hrir.sofa"
                },
                "control": {
                    "Azimuth": 150.0,
                    "Elevation": -10.0,
                    "Radius": 10.0
                }
            },
            {
                "type": "sofa",
                "label": "spatializer",
                "name": "spRR",
                "config": {
                    "filename": "${HOME:?}/.config/pipewire/hrir.sofa"
                },
                "control": {
                    "Azimuth": 210.0,
                    "Elevation": -10.0,
                    "Radius": 10.0
                }
            },
            {
                "type": "sofa",
                "label": "spatializer",
                "name": "spSL",
                "config": {
                    "filename": "${HOME:?}/.config/pipewire/hrir.sofa"
                },
                "control": {
                    "Azimuth": 90.0,
                    "Elevation": -10.0,
                    "Radius": 10.0
                }
            },
            {
                "type": "sofa",
                "label": "spatializer",
                "name": "spSR",
                "config": {
                    "filename": "${HOME:?}/.config/pipewire/hrir.sofa"
                },
                "control": {
                    "Azimuth": 270.0,
                    "Elevation": -10.0,
                    "Radius": 10.0
                }
            },
            { "type": "builtin", "label": "copy", "name": "copyLFE" },
            { "type": "builtin", "label": "bq_lowpass", "name": "lpLFE", "control": { "Freq": ${lfe_cutoff_hz:?}, "Q": 0.707 } },
            { "type": "builtin", "label": "mixer", "name": "mixL", "control": { "Gain 1": ${mix_gain:?}, "Gain 2": ${mix_gain:?}, "Gain 3": ${mix_gain:?}, "Gain 4": ${mix_gain:?}, "Gain 5": ${mix_gain:?}, "Gain 6": ${mix_gain:?}, "Gain 7": ${mix_gain:?}, "Gain 8": ${mix_gain:?} } },
            { "type": "builtin", "label": "mixer", "name": "mixR", "control": { "Gain 1": ${mix_gain:?}, "Gain 2": ${mix_gain:?}, "Gain 3": ${mix_gain:?}, "Gain 4": ${mix_gain:?}, "Gain 5": ${mix_gain:?}, "Gain 6": ${mix_gain:?}, "Gain 7": ${mix_gain:?}, "Gain 8": ${mix_gain:?} } }
        ],
        "links": [
            { "output": "spFL:Out L", "input": "mixL:In 1" },
            { "output": "spFL:Out R", "input": "mixR:In 1" },
            { "output": "spFR:Out L", "input": "mixL:In 2" },
            { "output": "spFR:Out R", "input": "mixR:In 2" },
            { "output": "spFC:Out L", "input": "mixL:In 3" },
            { "output": "spFC:Out R", "input": "mixR:In 3" },
            { "output": "spRL:Out L", "input": "mixL:In 4" },
            { "output": "spRL:Out R", "input": "mixR:In 4" },
            { "output": "spRR:Out L", "input": "mixL:In 5" },
            { "output": "spRR:Out R", "input": "mixR:In 5" },
            { "output": "spSL:Out L", "input": "mixL:In 6" },
            { "output": "spSL:Out R", "input": "mixR:In 6" },
            { "output": "spSR:Out L", "input": "mixL:In 7" },
            { "output": "spSR:Out R", "input": "mixR:In 7" },
            { "output": "copyLFE:Out", "input": "lpLFE:In" },
            { "output": "lpLFE:Out", "input": "mixL:In 8" },
            { "output": "lpLFE:Out", "input": "mixR:In 8" }
        ],
        "inputs":  [ "spFL:In", "spFR:In", "spFC:In", "copyLFE:In", "spRL:In", "spRR:In", "spSL:In", "spSR:In" ],
        "outputs": [ "mixL:Out", "mixR:Out" ]
    },
    capture.props = {
        "node.name": "${virtual_surround_filter_sink_capture_node_name:?}",
        "node.description": "${virtual_surround_filter_sink_description:?}",
        "node.nick": "${virtual_surround_filter_sink_description:?}",
        "media.class": "Audio/Sink",
        "audio.channels": 8,
        "audio.position": [ FL FR FC LFE RL RR SL SR ],
        "node.dont-fallback": true,
        "node.linger": true,
        "node.autoconnect": false,
        "stream.dont-remix": true,
        "channelmix.normalize": false
    },
    playback.props = {
        "node.name": "${virtual_surround_filter_sink_playback_node_name:?}",
        "node.passive": true,
        "node.autoconnect": false,
        "audio.channels": 2,
        "audio.position": [ FL FR ],
        "stream.dont-remix": true,
        "channelmix.normalize": false
    }
}
EOF
)
# Check channel counthrir.wav files with command:
#   > ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=noprint_wrappers=1:nokey=1 /home/deck/.config/pipewire/hrir.wav
# Or get all info
#   ffprobe -v error -print_format json -show_format -show_streams /home/deck/.config/pipewire/hrir.wav

# Add the DBUS_SESSION_BUS_ADDRESS environment variable
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    eval $(dbus-launch --sh-syntax)
    export DBUS_SESSION_BUS_ADDRESS
fi

# Configure systemd service
if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
filter_module_pid_file="${XDG_RUNTIME_DIR:?}/${virtual_surround_filter_sink_node_name:?}.pid"
device_module_pid_file="${XDG_RUNTIME_DIR:?}/${virtual_surround_device_sink_node_name:?}.pid"
eq_module_pid_file="${XDG_RUNTIME_DIR:?}/${virtual_surround_eq_sink_node_name:?}.pid"
service_name="virtual-surround-sound.service"
service_file="${HOME:?}/.config/systemd/user/${service_name:?}"
run_script="${HOME:?}/.config/pipewire/run.sh"
service_config=$(
    cat <<EOF
[Unit]
Description=${virtual_surround_filter_sink_description:?}
Requires=pipewire.service
After=pipewire.service
PartOf=pipewire.service wireplumber.service

[Service]
Type=simple
Restart=always
RestartSec=1
StartLimitInterval=5
StartLimitBurst=5
ExecStart=${run_script:?}

[Install]
WantedBy=default.target
EOF
)

get_run_script_contents() {
    local filter_type="${1:-convolver}"
    cat <<EOF
#!/bin/bash
set -euo pipefail

cleanup() {
    echo "Missing service script at '${script_directory:?}/service.sh'. Cleaning up systemd unit: ${service_name}"
    systemctl --user disable "${service_name}" >/dev/null 2>&1 || true
    rm -f "${service_file}" >/dev/null 2>&1 || true
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    rm -f "${run_script:?}" >/dev/null 2>&1 || true
}

echo "Checking for service script..."
if [[ ! -f "${script_directory:?}/service.sh" ]]; then
    cleanup
    exit 0
fi

exec "${script_directory:?}/service.sh" run --filter=${filter_type:?}
EOF
}

virtual_surround_filter_sink_pw_cli_pid=""
virtual_surround_device_sink_pw_cli_pid=""

cleanup_headphone_eq_module() {
    local running_pid="${virtual_surround_eq_sink_pw_cli_pid:-}"
    if [[ -z "${running_pid}" && -f "${eq_module_pid_file:?}" ]]; then
        running_pid=$(cat "${eq_module_pid_file:?}" 2>/dev/null || true)
    fi
    if [[ -n "${running_pid}" ]]; then
        kill -TERM "${running_pid}" >/dev/null 2>&1 || true
        sleep 0.2
    fi
    rm -f "${eq_module_pid_file:?}" >/dev/null 2>&1 || true
    virtual_surround_eq_sink_pw_cli_pid=""
}

create_headphone_eq_module() {
    cleanup_headphone_eq_module
    build_eq_module_args
    echo "Creating and loading module libpipewire-module-filter-chain (headphone EQ) - ${virtual_surround_eq_sink_capture_node_name:?}"
    pw-cli -m load-module libpipewire-module-filter-chain "${eq_module_args:?}" &
    virtual_surround_eq_sink_pw_cli_pid=$!
    echo "${virtual_surround_eq_sink_pw_cli_pid:?}" >"${eq_module_pid_file:?}"
    sleep 1
    if ! wait_for_sink_registration "${virtual_surround_eq_sink_capture_node_name:?}" 40 0.25; then
        echo "ERROR! Unable to detect sink '${virtual_surround_eq_sink_capture_node_name:?}' after loading module."
        cleanup_headphone_eq_module
        return 1
    fi
    echo "Created filter-chain sink '${virtual_surround_eq_sink_capture_node_name:?}' (pid ${virtual_surround_eq_sink_pw_cli_pid:?})"
    return 0
}

reset_default_sink() {
    local default_id=""
    default_id=$(wpctl status | awk '/\*/ && /Audio\/Sink/ {if (match($0,/[0-9]+\./,m)) {print substr(m[0], 1, length(m[0])-1); exit}}')
    if [[ -n "${default_id}" ]]; then
        wpctl set-default "${default_id}" >/dev/null 2>&1 || true
        wpctl clear-default
    fi
}

cleanup_virtual_surround_module() {
    local running_pid=""
    local terminated=""
    if [[ -n "${virtual_surround_filter_sink_pw_cli_pid:-}" ]]; then
        running_pid="${virtual_surround_filter_sink_pw_cli_pid}"
    elif [[ -f "${filter_module_pid_file:?}" ]]; then
        running_pid=$(cat "${filter_module_pid_file:?}" 2>/dev/null || true)
    fi

    if [[ -n "${running_pid}" ]]; then
        kill -TERM "${running_pid}" >/dev/null 2>&1 || true
        terminated="true"
    fi
    if [[ -f "${filter_module_pid_file:?}" ]]; then
        rm -f "${filter_module_pid_file:?}" >/dev/null 2>&1 || true
    fi
    if [[ "${terminated}" == "true" ]]; then
        sleep 0.2
    fi
    virtual_surround_filter_sink_pw_cli_pid=""
}

create_virtual_surround_module() {
    local filter_type="${1:-convolver}"
    local channel_count="8"
    build_filter_module_convolver_args_8
    local module_args="${filter_module_convolver_args_8}"
    if [[ "${filter_type}" == "sofa" ]]; then
        module_args="${filter_module_sofa_args_8}"
    fi

    cleanup_virtual_surround_module

    echo "Creating and loading module libpipewire-module-filter-chain (${filter_type:?}) with ${channel_count:?} channels - ${virtual_surround_filter_sink_capture_node_name:?}"
    pw-cli -m load-module libpipewire-module-filter-chain "${module_args:?}" &
    virtual_surround_filter_sink_pw_cli_pid=$!
    echo "${virtual_surround_filter_sink_pw_cli_pid:?}" >"${filter_module_pid_file:?}"
    sleep 1 # <- sleep for a second to ensure everything is loaded before linking

    if ! wait_for_sink_registration "${virtual_surround_filter_sink_capture_node_name:?}" 40 0.25; then
        echo "ERROR! Unable to detect sink '${virtual_surround_filter_sink_capture_node_name:?}' after loading module."
        cleanup_virtual_surround_module
        return 1
    fi

    echo "Created filter-chain sink '${virtual_surround_filter_sink_capture_node_name:?}' (pid ${virtual_surround_filter_sink_pw_cli_pid:?})"
    return 0
}

cleanup_virtual_surround_default_sink() {
    local running_pid=""
    local terminated=""
    if [[ -n "${virtual_surround_device_sink_pw_cli_pid:-}" ]]; then
        running_pid="${virtual_surround_device_sink_pw_cli_pid}"
    elif [[ -f "${device_module_pid_file:?}" ]]; then
        running_pid=$(cat "${device_module_pid_file:?}" 2>/dev/null || true)
    fi

    if [[ -n "${running_pid}" ]]; then
        kill -TERM "${running_pid}" >/dev/null 2>&1 || true
        terminated="true"
    fi
    if [[ -f "${device_module_pid_file:?}" ]]; then
        rm -f "${device_module_pid_file:?}" >/dev/null 2>&1 || true
    fi
    if [[ "${terminated}" == "true" ]]; then
        sleep 0.2
    fi
    virtual_surround_device_sink_pw_cli_pid=""
}

create_virtual_surround_default_sink() {
    local channel_count="${1:-8}"
    local module_args="${device_module_args_8}"

    cleanup_virtual_surround_default_sink

    echo "Creating and loading module libpipewire-module-filter-chain with ${channel_count:?} channels - ${virtual_surround_device_sink_capture_node_name:?}"
    pw-cli -m load-module libpipewire-module-filter-chain "${module_args:?}" &
    virtual_surround_device_sink_pw_cli_pid=$!
    echo "${virtual_surround_device_sink_pw_cli_pid:?}" >"${device_module_pid_file:?}"
    sleep 1 # <- sleep for a second to ensure everything is loaded before linking

    if ! wait_for_sink_registration "${virtual_surround_device_sink_capture_node_name:?}" 40 0.25; then
        echo "ERROR! Unable to detect sink '${virtual_surround_device_sink_capture_node_name:?}' after loading module."
        cleanup_virtual_surround_default_sink
        return 1
    fi

    echo "Created filter-chain sink '${virtual_surround_device_sink_capture_node_name:?}' (pid ${virtual_surround_device_sink_pw_cli_pid:?})"
    return 0
}

link_ports() {
    local output_port="$1"
    local input_port="$2"
    local result
    local existing_inputs
    existing_inputs=$(pw-link -l 2>/dev/null | awk -v target="${output_port}" '
        BEGIN {record = 0}
        {
            line = $0
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            if (line == target) {
                record = 1
                next
            }
            if (record) {
                if (line ~ /^\|[-<]>/) {
                    sub(/^\|[-<]>[[:space:]]*/, "", line)
                    print line
                    next
                }
                if (line !~ /^\|/) {
                    record = 0
                }
            }
        }
    ')
    for existing in ${existing_inputs}; do
        if [[ -n "${existing}" && "${existing}" != "${input_port}" ]]; then
            pw-link -d "${output_port}" "${existing}" >/dev/null 2>&1 || true
        fi
    done
    if result=$(pw-link -w "${output_port}" "${input_port}" 2>&1); then
        echo "Linking ${output_port} -> ${input_port}"
        return 0
    fi
    if printf '%s\n' "${result}" | grep -qi 'file exists'; then
        return 0
    fi
    echo "Failed to link ${output_port} -> ${input_port}: ${result}"
    return 1
}

link_virtual_surround_chain() {
    local channel_count="${1:-8}"
    local -a channels=(FL FR FC LFE RL RR SL SR)

    local device_playback_node="${virtual_surround_device_sink_playback_node_name:?}"
    local filter_capture_node="${virtual_surround_filter_sink_capture_node_name:?}"
    local filter_playback_node="${virtual_surround_filter_sink_playback_node_name:?}"
    local default_output_prefix="${device_playback_node}:output_"
    local surround_input_prefix="${filter_capture_node}:playback_"
    local surround_output_prefix="${filter_playback_node}:output_"

    local default_sink_name
    # The effective default sink (node name). Parsing the text output of "wpctl status" was unreliable:
    # depending on the WirePlumber version and on whether a default is "configured" (the service clears
    # it on start) it found nothing, the service exited and was restarted over and over, and the filter
    # stayed unlinked (no sound) until a default happened to be set.
    default_sink_name=$(pactl get-default-sink 2>/dev/null | head -n 1 | sed 's/[[:space:]]*$//')
    local virtual_filter="${virtual_surround_filter_sink_capture_node_name:?}"
    local virtual_device="${virtual_surround_device_sink_capture_node_name:?}"

    local virtual_eq="${virtual_surround_eq_sink_capture_node_name:?}"

    if [[ -n "${default_sink_name}" && ("${default_sink_name}" == "${virtual_filter}" || "${default_sink_name}" == "${virtual_device}" || "${default_sink_name}" == "${virtual_eq}") ]]; then
        if ! command -v python3 >/dev/null 2>&1; then
            echo "Unable to find python to determine the highest priority sink."
            return 1
        fi
        local fallback_output=""
        pushd "${script_directory:?}" >/dev/null
        fallback_output=$(python3 ./main.py --print-highest-priority-sink 2>/dev/null || true)
        popd >/dev/null
        local fallback_object_name
        fallback_object_name=$(printf "%s\n" "${fallback_output}" | awk -F': ' '/^Name:/ {print $2; exit}')
        if [[ -z "${fallback_object_name:-}" ]]; then
            echo "Unable to determine fallback sink name."
            return 1
        fi
        default_sink_name="${fallback_object_name:?}"
        #local fallback_object_id
        #fallback_object_id=$(printf "%s\n" "${fallback_output}" | awk -F': ' '/^Object ID:/ {print $2; exit}')
        #if [[ -z "${fallback_object_id}" ]]; then
        #    echo "Unable to determine fallback sink object ID."
        #    return 1
        #fi
        #echo "Default sink is virtual; switching to highest priority sink object ${fallback_object_id}"
        #wpctl set-default "${fallback_object_id}" >/dev/null 2>&1 || true
        #default_sink_name=$(wpctl status | awk '/\*/ && /Audio\/Sink/ { sub(/.*\*\s*[0-9]+\.\s*/, ""); sub(/\s*\[.*/, ""); print; exit }' | sed 's/[[:space:]]*$//')
    fi

    if [[ -z "${default_sink_name}" || "${default_sink_name}" == "${virtual_filter}" || "${default_sink_name}" == "${virtual_device}" || "${default_sink_name}" == "${virtual_eq}" ]]; then
        echo "Unable to detect a valid target output sink"
        return 1
    fi

    local output_ports
    local input_ports
    output_ports=$(pw-link -o 2>/dev/null | sed 's/[[:space:]]*$//')
    input_ports=$(pw-link -i 2>/dev/null | sed 's/[[:space:]]*$//')

    for ch in "${channels[@]}"; do
        local device_output_port="${default_output_prefix}${ch}"
        local surround_input_port="${surround_input_prefix}${ch}"

        if ! grep -Fxq -- "${device_output_port}" <<<"${output_ports}"; then
            echo "Skipping ${device_output_port} -> ${surround_input_port}: device output port missing"
            continue
        fi
        if ! grep -Fxq -- "${surround_input_port}" <<<"${input_ports}"; then
            echo "Skipping ${device_output_port} -> ${surround_input_port}: filter input port missing"
            continue
        fi

        if ! link_ports "${device_output_port}" "${surround_input_port}"; then
            return 1
        fi
    done

    local target_input_prefix="${default_sink_name}:playback_"
    local target_channels=(FL FR)
    for ch in "${target_channels[@]}"; do
        local surround_output_port="${surround_output_prefix}${ch}"
        local target_input_port="${target_input_prefix}${ch}"

        if ! grep -Fxq -- "${surround_output_port}" <<<"${output_ports}"; then
            echo "Skipping ${surround_output_port} -> ${target_input_port}: filter output port missing"
            continue
        fi
        if ! grep -Fxq -- "${target_input_port}" <<<"${input_ports}"; then
            echo "Skipping ${surround_output_port} -> ${target_input_port}: target sink input port missing"
            continue
        fi
        if ! link_ports "${surround_output_port}" "${target_input_port}"; then
            echo "Failed"
            return 1
        fi
    done

    # The headphone EQ sink plays to the same output device.
    local eq_output_prefix="${virtual_surround_eq_sink_playback_node_name:?}:output_"
    for ch in "${target_channels[@]}"; do
        local eq_output_port="${eq_output_prefix}${ch}"
        local eq_target_port="${target_input_prefix}${ch}"
        if ! grep -Fxq -- "${eq_output_port}" <<<"${output_ports}" || ! grep -Fxq -- "${eq_target_port}" <<<"${input_ports}"; then
            continue
        fi
        if ! link_ports "${eq_output_port}" "${eq_target_port}"; then
            echo "Failed"
            return 1
        fi
    done
    return 0
}

wait_for_sink_registration() {
    local sink_name="$1"
    local retries="${2:-30}"
    local delay_seconds="${3:-0.25}"
    local i
    for ((i = 0; i < retries; i++)); do
        if pactl list short sinks | cut -f2 | grep -Fxq -- "${sink_name:?}"; then
            return 0
        fi
        sleep "${delay_seconds}"
    done
    return 1
}

virtual_surround_sinks_exist() {
    local sink_list
    if ! sink_list=$(pactl list short sinks 2>/dev/null | cut -f2); then
        return 1
    fi

    if ! grep -Fxq -- "${virtual_surround_filter_sink_capture_node_name:?}" <<<"${sink_list}"; then
        return 1
    fi

    if ! grep -Fxq -- "${virtual_surround_device_sink_capture_node_name:?}" <<<"${sink_list}"; then
        return 1
    fi

    if ! grep -Fxq -- "${virtual_surround_eq_sink_capture_node_name:?}" <<<"${sink_list}"; then
        return 1
    fi

    return 0
}

kill_all_running_instances() {
    cleanup_virtual_surround_module
    cleanup_virtual_surround_default_sink
    running_pids=$(ps aux | grep -i "pw-cli -m load-module" | grep -v grep | grep "${virtual_surround_filter_sink_node_name:?}" | awk '{print $2}')
    if [ -n "${running_pids}" ]; then
        kill -TERM ${running_pids}
    fi
}

is_pid_running() {
    local pid="$1"
    [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

filter_reload_requested="false"

# ---- Audio event subscription -------------------------------------------------------------------
# The service used to check (and re-link) the whole chain every second. Each check starts several
# PipeWire clients (pactl, pw-link, ...), which also keeps PipeWire and WirePlumber busy: a constant
# few percent of a CPU core and battery, even while nothing changes. Now the chain is only checked
# when PipeWire reports a change of a sink, card or the default output (pactl subscribe), plus a
# slow safety check every few seconds.
audio_event_check_interval=10

start_audio_event_subscription() {
    if [[ -n "${VSS_EVENTS_PID:-}" ]] && is_pid_running "${VSS_EVENTS_PID}"; then
        return 0
    fi
    coproc VSS_EVENTS { exec pactl subscribe 2>/dev/null; }
}

stop_audio_event_subscription() {
    if [[ -n "${VSS_EVENTS_PID:-}" ]]; then
        kill "${VSS_EVENTS_PID}" >/dev/null 2>&1 || true
    fi
}

# Waits up to $1 seconds for a relevant audio event. Returns success if one arrived.
wait_for_audio_event() {
    local timeout="$1"
    local fd="${VSS_EVENTS[0]:-}"
    local line relevant=1 start="${SECONDS}"
    if [[ -z "${fd}" ]]; then
        sleep "${timeout}"
        return 1
    fi
    if IFS= read -r -t "${timeout}" -u "${fd}" line; then
        if [[ "${line}" == *" on sink #"* || "${line}" == *" on server"* || "${line}" == *" on card #"* ]]; then
            relevant=0
        fi
        # Events come in bursts; collect the rest of the burst.
        while IFS= read -r -t 0.2 -u "${fd}" line; do
            if [[ "${line}" == *" on sink #"* || "${line}" == *" on server"* || "${line}" == *" on card #"* ]]; then
                relevant=0
            fi
        done
    elif [[ $((SECONDS - start)) -lt 1 ]] && ! is_pid_running "${VSS_EVENTS_PID:-}"; then
        # The subscription ended (e.g. pipewire-pulse restarted). Don't spin; it is restarted.
        sleep "${timeout}"
    fi
    return "${relevant}"
}

run() {
    trap '_handle_signal' INT QUIT HUP TERM ERR
    # SIGUSR1 reloads only the filter module (e.g. after the HRIR file changed). The
    # "Virtual Surround Sound" device sink that the apps are connected to stays in place, so
    # apps are not moved to another output and keep playing once the new filter is linked.
    trap 'filter_reload_requested="true"' USR1
    echo "Running service"
    local filter_type="convolver"
    while [[ $# -gt 0 ]]; do
        case "$1" in
        --filter=*)
            filter_type="${1#*=}"
            ;;
        --filter)
            shift
            filter_type="$1"
            ;;
        *)
            echo "Invalid arg: $1"
            print_usage_and_exit 1
            ;;
        esac
        shift
    done

    if [[ "${filter_type}" != "convolver" && "${filter_type}" != "sofa" ]]; then
        echo "Invalid filter value: ${filter_type}. Must be convolver or sofa."
        exit 1
    fi

    local channels="8"

    reset_default_sink

    if ! create_virtual_surround_module "${filter_type:?}"; then
        _term
        exit 1
    fi

    if ! create_virtual_surround_default_sink "${channels:?}"; then
        _term
        exit 1
    fi

    if ! create_headphone_eq_module; then
        _term
        exit 1
    fi

    local linking_failed=0
    # Check every second for a while after start and after a filter reload (things are still
    # settling), then only on audio events or every ${audio_event_check_interval} seconds.
    local fast_checks_until=$((SECONDS + 15))
    local last_check=-1000
    local retry_next="false"
    while true; do
        start_audio_event_subscription || true
        local event="false"
        if wait_for_audio_event 1; then
            event="true"
        fi
        if ! is_pid_running "${virtual_surround_filter_sink_pw_cli_pid}" || ! is_pid_running "${virtual_surround_device_sink_pw_cli_pid}" || ! is_pid_running "${virtual_surround_eq_sink_pw_cli_pid}"; then
            break
        fi
        if [[ "${filter_reload_requested}" == "true" ]]; then
            filter_reload_requested="false"
            echo "Reloading filter module"
            if ! create_virtual_surround_module "${filter_type:?}"; then
                linking_failed=1
                break
            fi
            fast_checks_until=$((SECONDS + 15))
            event="true"
        fi
        if [[ "${event}" != "true" && "${retry_next}" != "true" && "${SECONDS}" -ge "${fast_checks_until}" && $((SECONDS - last_check)) -lt "${audio_event_check_interval}" ]]; then
            continue
        fi
        last_check="${SECONDS}"
        retry_next="false"
        if ! virtual_surround_sinks_exist; then
            echo "Virtual surround sinks are no longer available"
            linking_failed=1
            break
        fi
        if ! link_virtual_surround_chain "${channels:?}"; then
            # Don't tear everything down (that also removes the sinks the apps are connected to);
            # just try again on the next iteration.
            echo "Linking failed, retrying"
            retry_next="true"
        fi
    done

    stop_audio_event_subscription
    cleanup_headphone_eq_module

    cleanup_virtual_surround_default_sink
    cleanup_virtual_surround_module

    if [[ "${linking_failed}" -ne 0 ]]; then
        echo "Failed to rewire virtual surround nodes"
        exit 1
    fi

    echo "DONE"
}

# Returns success if the filter output is linked to the real output device.
filter_output_is_linked() {
    pw-link -l 2>/dev/null | awk -v port="${virtual_surround_filter_sink_playback_node_name:?}:output_FL" '
        { line = $0; gsub(/^[[:space:]]+|[[:space:]]+$/, "", line) }
        line == port { found = 1; next }
        found && line ~ /^\|->/ { linked = 1; exit }
        found && line !~ /^\|/ { found = 0 }
        END { exit linked ? 0 : 1 }
    '
}

wait_for_filter_linked() {
    local retries="${1:-40}"
    local i
    for ((i = 0; i < retries; i++)); do
        if filter_output_is_linked; then
            return 0
        fi
        sleep 0.25
    done
    return 1
}

reload_filter() {
    echo "Reloading filter module of ${service_name:?}"
    local main_pid=""
    main_pid=$(systemctl --user show -p MainPID --value "${service_name:?}" 2>/dev/null || true)
    if [[ -z "${main_pid}" || "${main_pid}" == "0" ]]; then
        echo "  - Service is not running. Restarting it instead."
        restart_service
        return 0
    fi
    local old_module_pid=""
    old_module_pid=$(cat "${filter_module_pid_file:?}" 2>/dev/null || true)
    kill -USR1 "${main_pid}"
    # Wait until the service has replaced the filter module and linked it again.
    local i
    for ((i = 0; i < 60; i++)); do
        local current_module_pid=""
        current_module_pid=$(cat "${filter_module_pid_file:?}" 2>/dev/null || true)
        if [[ -n "${current_module_pid}" && "${current_module_pid}" != "${old_module_pid}" ]] && filter_output_is_linked; then
            echo "  - Filter reloaded"
            return 0
        fi
        sleep 0.25
    done
    echo "  - Timed out waiting for the filter to reload"
    return 1
}

# speaker-test addresses single speakers (-s N) in its own "circular clockwise" order, NOT in the
# PipeWire/ALSA channel order:
#   1=FL 2=FC 3=FR 4=SR 5=RR 6=RL 7=SL 8=LFE
speaker_test_index() {
    case "$1" in
    FL) echo 1 ;;
    FC) echo 2 ;;
    FR) echo 3 ;;
    SR) echo 4 ;;
    RR) echo 5 ;;
    RL) echo 6 ;;
    SL) echo 7 ;;
    LFE) echo 8 ;;
    *) return 1 ;;
    esac
}

speaker_test() {
    echo "Running sound test"
    local pulse_sink_name="${virtual_surround_filter_sink_capture_node_name:?}"
    # Default sequence: start front left, go clockwise around the listener, end with the subwoofer.
    local -a test_channels=(FL FC FR SR RR RL SL LFE)
    while [[ $# -gt 0 ]]; do
        case "$1" in
        --sink=*)
            pulse_sink_name="${1#*=}"
            ;;
        --sink)
            shift
            pulse_sink_name="$1"
            ;;
        --channel=*)
            test_channels=("${1#*=}")
            ;;
        --channel)
            shift
            test_channels=("$1")
            ;;
        *)
            echo "Invalid arg: $1"
            print_usage_and_exit 1
            ;;
        esac
        shift
    done

    # Never let the test silently fall back to some other output. If the sink does not exist,
    # PipeWire would route the stream to whatever the current default is, which makes the
    # result different from one run to the next. Allow a few seconds in case the filter is
    # just being (re)loaded.
    if ! wait_for_sink_registration "${pulse_sink_name:?}" 20 0.25; then
        echo "ERROR! Sink '${pulse_sink_name}' does not exist. Aborting sound test." >&2
        exit 1
    fi
    if [[ "${pulse_sink_name}" == "${virtual_surround_filter_sink_capture_node_name:?}" || "${pulse_sink_name}" == "${virtual_surround_device_sink_capture_node_name:?}" ]]; then
        if ! wait_for_filter_linked 40; then
            echo "WARNING! Filter output is not linked to an output device yet." >&2
        fi
    fi
    # Lead-in: half a second of silence wakes up the (possibly suspended) output device, so the
    # first announcement is not cut off.
    head -c $((48000 * 8 * 2 / 2)) /dev/zero |
        paplay --raw --format=s16le --rate=48000 --channels=8 \
            --channel-map=front-left,front-right,front-center,lfe,rear-left,rear-right,side-left,side-right \
            --device="${pulse_sink_name:?}" >/dev/null 2>&1 || true

    local ch idx
    for ch in "${test_channels[@]}"; do
        if ! idx=$(speaker_test_index "${ch}"); then
            echo "ERROR! Unknown channel '${ch}'" >&2
            exit 1
        fi
        echo "  - ${ch} (speaker-test -s ${idx})"
        if [[ "${ch}" == "LFE" ]]; then
            speaker-test -D "pulse:${pulse_sink_name:?}" -c 8 -t sine -f 50 -s "${idx}"
        else
            speaker-test -D "pulse:${pulse_sink_name:?}" -c 8 -t wav -s "${idx}"
        fi
    done
}

install_service() {
    echo "Installing service: ${service_name:?}"
    local install_filter_type="convolver"
    local restart_after_install="false"
    while [[ $# -gt 0 ]]; do
        case "$1" in
        --restart-after-install)
            restart_after_install="true"
            ;;
        --filter=*)
            install_filter_type="${1#*=}"
            ;;
        --filter)
            shift
            install_filter_type="$1"
            ;;
        *)
            echo "Invalid arg: $1"
            print_usage_and_exit 1
            ;;
        esac
        shift
    done
    if [[ "${install_filter_type}" != "convolver" && "${install_filter_type}" != "sofa" ]]; then
        echo "Invalid filter value: ${install_filter_type}. Must be convolver or sofa."
        exit 1
    fi
    local run_script_contents
    run_script_contents=$(get_run_script_contents "${install_filter_type:?}")
    echo "  - Creating directory: '${HOME:?}/.config/pipewire'"
    mkdir -p "${HOME:?}/.config/pipewire"
    echo "  - Ensure directory and all contents is RW by the user"
    chmod 755 "${HOME:?}/.config/pipewire"
    chmod u+rw -R "${HOME:?}/.config/pipewire"
    echo "  - Installing run wrapper script: ${run_script:?}"
    echo "${run_script_contents:?}" >"${run_script:?}"
    chmod +x "${run_script:?}"
    echo "  - Installing systemd unit: ${service_file:?}"
    echo "${service_config:?}" >"${service_file:?}"
    echo "  - Exec daemon-reload"
    systemctl --user daemon-reload
    echo "  - Enabling systemd unit"
    # Only enable here; the service is (re)started exactly once below. "enable --now" followed by
    # "restart" started it twice, and the first instance was torn down again a few seconds later.
    systemctl --user enable "${service_name:?}"
    local start_cmd="start"
    if [[ "${restart_after_install:-}" == "true" ]]; then
        start_cmd="restart"
    fi
    echo "  - Now ${start_cmd:?}ing systemd service"
    systemctl --user ${start_cmd:?} "${service_name:?}"
    echo "Systemd service installed and ${start_cmd:?}ed."
}

uninstall_service() {
    echo "Uninstalling systemd unit: ${service_name:?}"
    if [ -f "${service_file:?}" ]; then
        # Stop and disable the service
        echo "  - Stopping systemd service"
        systemctl --user stop "${service_name}"
        echo "  - Disabling systemd unit"
        systemctl --user disable "${service_name}"
        # Remove the service file
        echo "  - Removing systemd unit: ${service_file:?}"
        rm -f "${service_file}"
        echo "  - Exec daemon-reload"
        systemctl --user daemon-reload
        echo "  - Removing run wrapper script: ${run_script:?}"
        rm -f "${run_script:?}"
        echo "Systemd service stopped and uninstalled."
    else
        echo "Systemd service has not been installed. Run this script with the 'install' command to install it."
    fi
}

restart_service() {
    echo "Restarting systemd unit: ${service_name:?}"
    if [ -f "${service_file:?}" ]; then
        echo "  - Restarting systemd service"
        systemctl --user restart "${service_name:?}"
        echo "Systemd service restarted."
    else
        echo "Systemd service has not been installed. Run this script with the 'install' command to install it."
    fi
}

stop_service() {
    echo "Stopping running service: ${service_name:?}"
    if [ -f "${service_file:?}" ]; then
        echo "  - Stopping systemd service"
        systemctl --user stop "${service_name:?}"
        echo "Systemd service stopped."
    else
        echo "Systemd service has not been installed. Run this script with the 'install' command to install it."
    fi
}

print_usage_and_exit() {
    echo "Usage: $0 {run|install|uninstall|restart|reload-filter|stop|kill-all|print-vss-info|speaker-test} [--filter=<convolver|sofa>] [--sink=<name>] [--channel=<FL|FR|FC|LFE|RL|RR|SL|SR>] [additional args...]"
    exit "$1"
}

print_vss_info() {
    printf 'VSS Filter Node Name: %s\n' "${virtual_surround_filter_sink_node_name:?}"
    printf 'VSS Filter Capture Name: %s\n' "${virtual_surround_filter_sink_capture_node_name:?}"
    printf 'VSS Device Node Name: %s\n' "${virtual_surround_device_sink_node_name:?}"
    printf 'VSS Device Capture Name: %s\n' "${virtual_surround_device_sink_capture_node_name:?}"
    printf 'VSS EQ Capture Name: %s\n' "${virtual_surround_eq_sink_capture_node_name:?}"
}

# Check if the effective user ID is 0 (root)
if [ "$EUID" -eq 0 ]; then
    echo "Error: This script must not be run as root. This is bad. You should be running this as a standard user." >&2
    exit 1
fi

# Parse command line arguments
if [[ $# -eq 0 ]]; then
    print_usage_and_exit 1
fi

# The first parameter is the command.
cmd="$1"
shift

case "$cmd" in
"run")
    run "$@"
    ;;
"speaker-test")
    speaker_test "$@"
    ;;
"install")
    install_service "$@"
    ;;
"uninstall")
    uninstall_service "$@"
    ;;
"restart")
    restart_service "$@"
    ;;
"reload-filter")
    reload_filter "$@"
    ;;
"stop")
    stop_service "$@"
    ;;
"kill-all")
    kill_all_running_instances "$@"
    ;;
"print-vss-info")
    print_vss_info
    ;;
*)
    echo "Invalid command: $cmd"
    print_usage_and_exit 1
    ;;
esac

import asyncio
import asyncio.subprocess
import json
import os
import re
import shutil
import signal
import subprocess
from typing import Any, Coroutine

# The decky plugin module is located at decky-loader/plugin
# For easy intellisense checkout the decky-loader code repo
# and add the `decky-loader/plugin/imports` path to `python.analysis.extraPaths` in `.vscode/settings.json`
import decky
from settings import SettingsManager

# Get environment variable
settingsDir = os.environ["DECKY_PLUGIN_SETTINGS_DIR"]
settings = SettingsManager(name="settings", settings_directory=settingsDir)
settings.read()


def subprocess_exec_env():
    uid = os.getuid()
    env = os.environ.copy()
    env['XDG_RUNTIME_DIR'] = f"/run/user/{uid}"
    env['DBUS_SESSION_BUS_ADDRESS'] = f"unix:path=/run/user/{uid}/bus"
    return env


class Plugin:
    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded
    async def _main(self):
        self.loop = asyncio.get_event_loop()
        decky.logger.info("Installing service")
        # Install service
        script_directory = os.path.dirname(os.path.abspath(__file__))
        service_script = os.path.join(script_directory, "service.sh")
        try:
            process = await asyncio.create_subprocess_exec(
                service_script, "install",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error(f"Service installation failed: {stderr.decode()}")
            decky.logger.info("Service installation output:")
            for line in stdout.decode().splitlines():
                decky.logger.info(line)
        except Exception as e:
            decky.logger.error(f"Error installing service: {e}")

        # Monitor running apps to auto-assign the correct audio sink
        self.running = True

        async def check_state_loop():
            decky.logger.info("Starting service to manage app sink association...")
            while self.running:
                try:
                    await self.check_state()
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    # This can happen during shutdown, just ignore
                    pass
                except Exception as e:
                    decky.logger.error(f"Error in check_state_loop: {e}")

        async def handle_interrupt(int_sig):
            decky.logger.info(f"Received signal {int_sig}. Stopping check_state_loop.")
            self.running = False
            # Give the loop a little time to exit gracefully.
            await asyncio.sleep(1)
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            [task.cancel() for task in tasks]
            await asyncio.gather(*tasks, return_exceptions=True)
            self.loop.stop()

        # Set up signal handler for Ctrl+C (SIGINT) and other signals you want to catch
        for signal_to_handle in (signal.SIGINT, signal.SIGTERM):
            self.loop.add_signal_handler(signal_to_handle,
                                         lambda sig=signal_to_handle: asyncio.create_task(handle_interrupt(sig)))

        try:
            await check_state_loop()
        except asyncio.CancelledError:
            decky.logger.info("check_state_loop CancelledError.")
        finally:
            decky.logger.info("check_state_loop finished.")

    # Function called first during the unload process, utilize this to handle your plugin being stopped, but not
    # completely removed
    async def _unload(self):
        decky.logger.info("Goodnight World!")
        pass

    # Function called after `_unload` during uninstall, utilize this to clean up processes and other remnants of your
    # plugin that may remain on the system
    async def _uninstall(self):
        decky.logger.info("Uninstalling service")
        # Uninstall service
        script_directory = os.path.dirname(os.path.abspath(__file__))
        service_script = os.path.join(script_directory, "service.sh")
        try:
            process = await asyncio.create_subprocess_exec(
                service_script, "uninstall",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )

            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error(f"Service uninstallation failed: {stderr.decode()}")
            else:
                decky.logger.info("Service uninstallation output:")
                for line in stdout.decode().splitlines():
                    decky.logger.info(line)
        except Exception as e:
            decky.logger.error(f"Error uninstalling service: {e}")

    async def start_timer(self):
        self.loop.create_task(self.long_running())

    # Migrations that should be performed before entering `_main()`.
    async def _migration(self):
        decky.logger.info("Migrating")
        # Here's a migration example for logs:
        # - `~/.config/decky-template/template.log` will be migrated to `decky.decky_LOG_DIR/template.log`
        decky.migrate_logs(os.path.join(decky.DECKY_USER_HOME,
                                        ".config", "decky-template", "template.log"))
        # Here's a migration example for settings:
        # - `~/homebrew/settings/template.json` is migrated to `decky.decky_SETTINGS_DIR/template.json`
        # - `~/.config/decky-template/` all files and directories under this root are migrated to `decky.decky_SETTINGS_DIR/`
        decky.migrate_settings(
            os.path.join(decky.DECKY_HOME, "settings", "template.json"),
            os.path.join(decky.DECKY_USER_HOME, ".config", "decky-template"))
        # Here's a migration example for runtime data:
        # - `~/homebrew/template/` all files and directories under this root are migrated to `decky.decky_RUNTIME_DIR/`
        # - `~/.local/share/decky-template/` all files and directories under this root are migrated to `decky.decky_RUNTIME_DIR/`
        decky.migrate_runtime(
            os.path.join(decky.DECKY_HOME, "template"),
            os.path.join(decky.DECKY_USER_HOME, ".local", "share", "decky-template"))

    async def get_enabled_apps_list(self):
        """Reads the current list of enabled apps"""
        return settings.getSetting("enabled_apps", [])

    async def enable_for_app(self, app_name: str):
        """Adds a given app name to the list of enabled apps"""
        decky.logger.info("Enabling Virtual Surround Sound for app %s", app_name)
        enabled_apps = settings.getSetting("enabled_apps", [])
        if app_name not in enabled_apps:
            enabled_apps.append(app_name)
            settings.setSetting("enabled_apps", enabled_apps)
            decky.logger.info("App %s enabled.", app_name)
            await self.check_state()
        else:
            decky.logger.info("App %s was already enabled.", app_name)
        return True

    async def disable_for_app(self, app_name: str):
        """Removes a given app name from the list of enabled apps"""
        decky.logger.info("Disabling Virtual Surround Sound for app %s", app_name)
        enabled_apps = settings.getSetting("enabled_apps", [])
        if app_name in enabled_apps:
            updated_list = [a for a in enabled_apps if a != app_name]
            settings.setSetting("enabled_apps", updated_list)
            decky.logger.info("App %s disabled.", app_name)
            await self.check_state()
        else:
            decky.logger.info("App %s was not enabled.", app_name)
        return True

    async def check_state(self):
        settings.read()
        enabled_apps = settings.getSetting("enabled_apps", [])
        sinks = await self.get_sinks()
        sink_inputs = await self.get_sink_inputs()

        # Find the sinks for "Virtual Surround Sound" and "Virtual Sink"
        virtual_surround_sink = next((sink for sink in sinks if sink["name"] == "input.virtual-surround-sound"), None)
        virtual_sink = next((sink for sink in sinks if sink["name"] == "input.virtual-sink"), None)
        if not virtual_surround_sink or not virtual_sink:
            decky.logger.error("Required sinks not found. Virtual Surround Sound or Virtual Sink is missing.")
            return

        # Loop over each sink input and check its assignment.
        for sink_input in sink_inputs:
            # If the sink input has a non-empty target_object, ignore it.
            if sink_input.get('target_object', '').strip() != "":
                continue

            app_name = sink_input.get('name')
            current_sink_index = sink_input.get('sink')
            # If the app is in the enabled_apps list,
            # it should be assigned to the Virtual Surround Sound sink.
            if app_name in enabled_apps:
                decky.logger.info(current_sink_index, virtual_surround_sink['index'])
                if current_sink_index != virtual_surround_sink['index']:
                    decky.logger.info("Moving %s (sink input %s) to Virtual Surround Sound (sink %s)",
                                      app_name, sink_input['index'], virtual_surround_sink['index'])
                    await self.set_sink_for_application(sink_input['index'], virtual_surround_sink['index'])
            else:
                # If the app is not enabled but is currently assigned to the Virtual Surround Sound sink,
                # move it to the Virtual Sink.
                decky.logger.info(current_sink_index, virtual_surround_sink['index'])
                if current_sink_index == virtual_surround_sink['index']:
                    decky.logger.info("Moving %s (sink input %s) to Virtual Sink (sink %s)",
                                      app_name, sink_input['index'], virtual_sink['index'])
                    await self.set_sink_for_application(sink_input['index'], virtual_sink['index'])

    async def get_hrir_file_list(self) -> list[dict[str, str | None | int]] | None:
        """Lists available HRIR files with channel count."""
        script_directory = os.path.dirname(os.path.abspath(__file__))
        hrir_directory = os.path.join(script_directory, "assets", "hrir-audio")
        hrir_files = []
        i = 1
        # Check if ffprobe is installed
        try:
            process = await asyncio.create_subprocess_exec(
                "ffprobe", "-version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            await process.communicate()
            ffprobe = process.returncode == 0
        except FileNotFoundError:
            decky.logger.warning("ffprobe not found. HRIR channel detection will be skipped.")
            ffprobe = False
        except Exception as e:
            decky.logger.error(f"Error checking ffprobe: {e}")
            ffprobe = False
        for filename in os.listdir(hrir_directory):
            if filename.endswith(".wav") and os.path.isfile(os.path.join(hrir_directory, filename)):
                filepath = os.path.join(hrir_directory, filename)
                channel_count = None
                try:
                    if ffprobe:
                        process = await asyncio.create_subprocess_exec(
                            "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                            "-of", "default=noprint_wrappers=1:nokey=1", filepath,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            env=subprocess_exec_env()
                        )
                        stdout, stderr = await process.communicate()
                        if process.returncode != 0:
                            decky.logger.error(f"ffprobe failed for {filename}: {stderr.decode()}")
                        else:
                            channel_count = int(stdout.decode().strip())
                except (ValueError, FileNotFoundError) as e:
                    channel_count = None
                finally:
                    hrir_files.append({
                        "label": os.path.basename(filepath)[:-4],
                        "path": filepath,
                        "channel_count": channel_count
                    })
                    i += 1
        if hrir_files:
            hrir_files.sort(key=lambda x: (x["channel_count"] is not None, x["channel_count"] or 0, x["path"]),
                            reverse=False)
        return hrir_files

    async def set_hrir_file(self, selected_hrir_path: str) -> bool:
        """Installs the specified HRIR file."""
        script_directory = os.path.dirname(os.path.abspath(__file__))
        hrir_directory = os.path.join(script_directory, "hrir-audio")
        pipewire_config_path = os.path.join(os.path.expanduser("~"), ".config", "pipewire")
        decky.logger.info("Installing %s", selected_hrir_path)
        try:
            os.makedirs(os.path.dirname(pipewire_config_path), exist_ok=True)
            hrir_dest_path = os.path.join(pipewire_config_path, "hrir.wav")
            shutil.copy2(selected_hrir_path, hrir_dest_path)
            decky.logger.info("Copied %s to %s", selected_hrir_path, hrir_dest_path)
            return True
        except Exception as e:
            decky.logger.error("Error: Failed to copy HRIR WAV file: %s", e)
        return False

    async def parse_properties(self, lines, start_index):
        """
        Parse the properties block from the given lines starting at start_index.
        Returns a dictionary of properties and the index where the block ends.
        """
        props = {}
        i = start_index
        prop_pattern = re.compile(r'^\s*(\S+)\s*=\s*"(.*)"')
        while i < len(lines):
            line = lines[i].rstrip()
            # Stop if the line is not indented (end of properties block)
            if not line.startswith('\t') and not line.startswith('    '):
                break
            m = prop_pattern.match(line.strip())
            if m:
                key, value = m.groups()
                props[key] = value
            i += 1
        return props, i

    async def get_sinks(self):
        """
        Retrieve a mapping of sink index to its name and description.
        """
        sinks = []
        try:
            process = await asyncio.create_subprocess_exec(
                'pactl', 'list', 'sinks',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error(f"pactl list sinks failed: {stderr.decode()}")
                return []
            output = stdout.decode()
            current_sink = None
            for line in output.splitlines():
                line = line.rstrip()
                # Detect the start of a sink block, e.g., "Sink #1"
                sink_match = re.match(r'^Sink #(\d+)', line)
                if sink_match:
                    if current_sink is not None:
                        sinks.append(current_sink)
                    current_sink = {
                        'index': int(sink_match.group(1)),
                        'name': 'Unknown',
                        'description': 'No description'
                    }
                    continue

                # Capture sink name
                name_match = re.match(r'\s*Name:\s+(.*)', line)
                if name_match and current_sink is not None:
                    current_sink['name'] = name_match.group(1).strip()
                    continue

                # Capture sink description
                desc_match = re.match(r'\s*Description:\s+(.*)', line)
                if desc_match and current_sink is not None:
                    current_sink['description'] = desc_match.group(1).strip()
                    continue

            # Add the last sink block if exists
            if current_sink is not None:
                sinks.append(current_sink)
        except FileNotFoundError:
            decky.logger.error("pactl not found.")
            return []
        except Exception as e:
            decky.logger.error(f"Error getting sinks: {e}")
            return []
        return sinks

    async def get_sink_inputs(self):
        """
        Retrieve sink inputs (running application audio streams) using pactl,
        applying filtering similar to the pulsectl-based implementation.
        """
        sink_inputs = []
        found_bt_devices = []
        try:
            process = await asyncio.create_subprocess_exec(
                'pactl', 'list', 'sink-inputs',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                decky.logger.error(f"pactl list sink-inputs failed: {stderr.decode()}")
                return []
            output = stdout.decode()

            # Split output into blocks per sink input. Each block starts with "Sink Input #"
            blocks = output.split("Sink Input #")
            for block in blocks:
                block = block.strip()
                if not block:
                    continue

                # The first line of the block should be the index number.
                lines = block.splitlines()
                try:
                    index = int(lines[0].split()[0])
                except (ValueError, IndexError):
                    continue

                # Initialize data dictionary for this sink input.
                data = {'index': index, 'volume': None, 'props': {}}

                # Parse the block for Volume and Properties.
                i = 1
                while i < len(lines):
                    line = lines[i].strip()
                    if line.startswith("Sink:"):
                        sink_line = line[len("Sink:"):].strip()
                        data['sink'] = int(sink_line)
                    # Capture the volume line. Example: Volume: front-left: 26214 / 40% / -18.06 dB, front-right: 26214 / 40% / -18.06 dB
                    elif line.startswith("Volume:"):
                        volume_line = line[len("Volume:"):].strip()
                        data['volume'] = volume_line
                    # Capture the format line. Example: Format: pcm, format.sample_format = "\"float32le\""  format.rate = "48000"  format.channels = "2"  format.channel_map = "\"front-left,front-right\""
                    elif line.startswith("Format:"):
                        format_line = line[len("Format:"):].strip()
                        parts = format_line.split(',', 1)
                        sample_format_match = re.search(r'format\.sample_format\s*=\s*"\\?"([^"]+?)\\?"', format_line)
                        rate_match = re.search(r'format\.rate\s*=\s*"([^"]+)"', format_line)
                        channels_match = re.search(r'format\.channels\s*=\s*"([^"]+)"', format_line)
                        data['format'] = {
                            "format": parts[0].strip() if parts else "",
                            "sample_format": sample_format_match.group(1) if sample_format_match else None,
                            "rate": rate_match.group(1) if rate_match else None,
                            "channels": channels_match.group(1) if channels_match else None,
                        }
                    # Look for the start of Properties block.
                    elif line.startswith("Properties:"):
                        # Parse the properties block. The properties lines are indented.
                        props, new_index = await self.parse_properties(lines, i + 1)
                        data['props'] = props
                        i = new_index - 1  # adjust i because it will be incremented below
                    i += 1

                # Apply filtering similar to the pulsectl snippet.
                props = data['props']
                # Case 1: application.process.binary is steamwebhelper -> label as "Steam"
                if props.get('application.process.binary') == 'steamwebhelper':
                    # Let's ignore the Steam UI audio
                    pass
                    # sink_inputs.append({
                    #     'name': 'Steam',
                    #     'index': data['index'],
                    #     'sink': data['sink'],
                    #     'format': data['format'],
                    #     'volume': data['volume'],
                    #     'target_object': props.get('target.object', "")
                    # })
                # Case 2: Use application.name if available.
                elif 'application.name' in props:
                    sink_inputs.append({
                        'name': props['application.name'],
                        'index': data['index'],
                        'sink': data['sink'],
                        'format': data['format'],
                        'volume': data['volume'],
                        'target_object': props.get('target.object', "")
                    })
                # # Case 3: For Bluetooth devices (device.api == bluez5)
                # elif props.get('device.api') == 'bluez5':
                #     bt_address = props.get('api.bluez5.address', 'Unknown')
                #     if bt_address not in found_bt_devices:
                #         found_bt_devices.append(bt_address)
                #     entry = {
                #         'name': props.get('media.name', 'Bluetooth Device'),
                #         'index': data['index'],
                #         'volume': data['volume'],
                #         'device': {'address': bt_address}
                #     }
                #     sink_inputs.append(entry)

        except FileNotFoundError:
            decky.logger.error("pactl not found.")
            return []
        except Exception as e:
            decky.logger.error(f"Error getting sink inputs: {e}")
            return []
        return sink_inputs

    async def set_sink_for_application(self, sink_input_index: str, target_sink_index: str):
        """Moves the sink output for the given app"""
        # Plex - Sink Input #649
        # Plex -         Sink: 50
        # Virtual Sink: 50
        # Virtual Surround Sound Sink: 57
        #  pactl move-sink-input 649 50
        #  pactl list sink-inputs
        #  pactl list sinks
        try:
            process = await asyncio.create_subprocess_exec(
                "pactl", 'move-sink-input', str(sink_input_index), str(target_sink_index),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=subprocess_exec_env()
            )
            await process.communicate()
            return process.returncode == 0
        except FileNotFoundError:
            decky.logger.warning("ffprobe not found. HRIR channel detection will be skipped.")
            return False
        except Exception as e:
            decky.logger.error(f"Error checking ffprobe: {e}")
            return False

    async def test(self):
        # await self._main()
        # await self._uninstall()
        # hrir_file_list = await self.get_hrir_file_list()
        # await self.set_hrir_file(hrir_file_list[0].get("path"))
        sinks = await self.get_sinks()
        print(json.dumps(sinks, indent=2))
        sink_inputs = await self.get_sink_inputs()
        print(json.dumps(sink_inputs, indent=2))


if __name__ == '__main__':
    plugin = Plugin()


    async def main():
        await plugin.test()


    asyncio.run(main())

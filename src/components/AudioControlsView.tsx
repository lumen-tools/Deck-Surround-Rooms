import {
    DialogButton,
    PanelSection,
    PanelSectionRow,
    Focusable, ToggleField,
} from "@decky/ui";
import {useState, useEffect} from 'react';
import {PluginPage, SinkInput} from "../interfaces";
import {MdOutlineWarningAmber, MdSettings} from "react-icons/md";
import {call} from "@decky/api";


interface AudioControlsViewProps {
    onChangePage: (page: PluginPage) => void;
}

const AudioControlsView: React.FC<AudioControlsViewProps> = ({onChangePage,}) => {
    const [sinkInputList, setSinkInputList] = useState<SinkInput[]>([]);

    const updateApplicationList = async () => {
        try {
            const sinkInputs = await call<[], SinkInput[]>('get_sink_inputs');
            if (!sinkInputs) return;
            const enabled_apps = await call<[], string[]>('get_enabled_apps_list');
            const updatedSinkInputs = await Promise.all(
                sinkInputs.map(async (app) => {
                    // Call backend function to get the enabled state for the app.
                    const enabled = enabled_apps.includes(app.name);
                    return {...app, enabled};
                })
            );
            setSinkInputList(updatedSinkInputs);
        } catch (error) {
            console.error("[AudioControlsView] Error fetching game details:", error);
        }
    };

    const handleAppSelect = async (app: SinkInput, state: boolean) => {
        console.log(`[AudioControlsView] Setting app to state ${state} [AppID:${app.index}, Title:${app.name}]`);
        if (state) {
            await call<[app_name: string], boolean>('enable_for_app', app.name);
        } else {
            await call<[app_name: string], boolean>('disable_for_app', app.name);
        }
        // Update list of app states
        await updateApplicationList();
    };

    useEffect(() => {
        console.log(`[AudioControlsView] Mounted`);
        // noinspection JSIgnoredPromiseFromCall
        updateApplicationList();
        // Add loop to update
        const interval = setInterval(() => {
            updateApplicationList()
        }, 5000)
        return () => clearInterval(interval);
    }, []);

    return (
        <>
            <div>
                <PanelSection>
                    <Focusable style={{display: 'flex', alignItems: 'center', gap: '1rem'}}
                               flow-children="horizontal">
                        <DialogButton
                            style={{width: '100%', minWidth: 0}}
                            onClick={() => onChangePage("plugin_config")}>
                            <MdSettings/> Plugin Settings
                        </DialogButton>
                    </Focusable>
                </PanelSection>
                <hr/>
            </div>
            {sinkInputList.map((app) => (
                <PanelSection key={app.index} title={app.name}>
                    <PanelSectionRow>
                        <ul style={{
                            listStyle: 'none',
                            fontSize: '0.7rem',
                            padding: 0,
                            marginLeft: '15px',
                            marginRight: '10px',
                            marginTop: '0',
                            marginBottom: '3px',
                        }}>
                            <li
                                style={{
                                    display: 'table',
                                    textAlign: 'right',
                                    width: '100%',
                                    borderBottom: '1px solid #333',
                                    paddingTop: '2px',
                                    paddingBottom: '2px',
                                }}>
                                <strong style={{
                                    display: 'table-cell',
                                    textAlign: 'left',
                                    paddingRight: '3px',
                                }}>Audio:</strong>
                                {app.format.format}_{app.format.sample_format}, {app.format.rate}Hz, {app.format.channels} channels
                            </li>
                            {app.target_object.trim() !== "" && (
                                <li style={{
                                    display: 'table',
                                    textAlign: 'left',
                                    width: '100%',
                                    borderBottom: '1px solid #333',
                                    paddingTop: '2px',
                                    paddingBottom: '2px',
                                }}>
                                    <MdOutlineWarningAmber style={{color: 'orange', marginRight: '3px'}}/>
                                    <strong> NOTE: </strong>
                                    This app has specifically targeted an output and cannot be edited here.
                                    Try editing audio output from within the app.
                                </li>
                            )}
                        </ul>
                    </PanelSectionRow>
                    <PanelSectionRow>
                        <ToggleField
                            label="Enable"
                            description="Enable Virtual Surround Sound filter for this app"
                            checked={app.enabled}
                            onChange={(e) => {
                                handleAppSelect(app, e)
                            }}
                            disabled={app.target_object.trim() !== ""}
                        />
                    </PanelSectionRow>
                </PanelSection>
            ))}
        </>
    );
};

export default AudioControlsView;
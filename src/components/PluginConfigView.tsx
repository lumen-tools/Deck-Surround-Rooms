import {
    PanelSection,
    PanelSectionRow,
    DialogButton,
    Focusable,
    Dropdown, Navigation, Router,
} from "@decky/ui";
import {useState, useEffect} from "react";
import {MdArrowBack, MdWeb} from "react-icons/md";
import {SiDiscord, SiGithub, SiKofi, SiPatreon} from 'react-icons/si'
import {HrirFile, PluginConfig} from "../interfaces";
import {getPluginConfig, setPluginConfig} from "../constants";
import {call} from "@decky/api";
import {PanelSocialButton} from "./elements/socialButton";

interface PluginConfigViewProps {
    onGoBack: () => void;
}

const PluginConfigView: React.FC<PluginConfigViewProps> = ({onGoBack,}) => {
    const [isLoading, setIsLoading] = useState(false);
    const [currentConfig, setCurrentConfig] = useState(() => getPluginConfig())
    const [hrirFileList, setHrirFileList] = useState<HrirFile[]>([]);

    const updateHrirFileListList = async () => {
        setIsLoading(true);
        try {
            const hrirFiles = await call<[], HrirFile[]>('get_hrir_file_list');
            setHrirFileList(hrirFiles || []);
        } catch (error) {
            console.error("[PluginConfigView] Error fetching game details:", error);
        } finally {
            setIsLoading(false);
        }
    };

    const updateConfig = (updates: Partial<PluginConfig>) => {
        // Update the localStorage config
        setPluginConfig(updates);
        // Update the local state of component
        setCurrentConfig((prevConfig: PluginConfig) => ({
            ...prevConfig,
            ...updates,
        }));
    };

    const handleHrirSelection = async (hrirName: string) => {
        const selectedHrir = hrirFileList.find((file) => file.label === hrirName);
        if (!selectedHrir) {
            console.error(`[PluginConfigView] HRIR file not found for name: ${hrirName}`);
            return;
        }
        const hrirPath = selectedHrir.path;
        const result = await call<[hrirPath: string], boolean>('set_hrir_file', hrirPath);
        if (!result) {
            console.error("[PluginConfigView] Error saving new HRIR file:", result);
        } else {
            updateConfig({hrirName: hrirName});
        }
    };

    useEffect(() => {
        console.log(`[PluginConfigView] Mounted`);
        updateHrirFileListList()
    }, []);

    const openWeb = (url: string) => {
        Navigation.NavigateToExternalWeb(url)
        Router.CloseSideMenus()
    }

    return (
        <div>
            <div>
                <PanelSection>
                    <Focusable style={{display: 'flex', alignItems: 'center', gap: '1rem'}}
                               flow-children="horizontal">
                        <DialogButton
                            style={{width: '30%', minWidth: 0}}
                            onClick={onGoBack}>
                            <MdArrowBack/>
                        </DialogButton>
                    </Focusable>
                </PanelSection>
                <hr/>
            </div>
            <PanelSection title="Plugin Configuration">
            </PanelSection>
            {isLoading ? (
                <PanelSection spinner title="Fetching settings..."/>
            ) : (
                <div>
                    <PanelSection title="Select a HRIR file for filter">
                        <PanelSectionRow>
                            <Dropdown
                                rgOptions={hrirFileList.map((hrirFile) => ({
                                    label: `${(currentConfig.hrirName === hrirFile.label) ? '✔' : '—'} ${hrirFile.label}`,
                                    data: hrirFile.label,
                                }))}
                                selectedOption={currentConfig.hrirName}
                                onChange={(option) => handleHrirSelection(option.data)}
                                strDefaultLabel="Select HRIR Profile"
                            />
                            <p style={{fontSize: '0.7rem', marginBottom: '10px'}}>
                                Choose from the list of Head-Related Impulse Response (HRIR) .wav files, which captures
                                how sound is modified by the shape of your head and ears. This will be applied to your
                                audio signal, to create a realistic binaural effect, simulating surround sound through
                                headphones. Pick a profile (e.g., Atmos, DTS, Steam) that best suits your taste. You can
                                also manually supply your own (see below).
                            </p>
                            <p style={{fontSize: '0.7rem', marginBottom: '10px'}}>
                                If you wish to provide your own HRIR .wav file, you can download it from the HRTF
                                Database and install it to <code>~/.config/pipewire/hrir.wav</code>.
                                (Changing presets in this plugin will overwrite that file. To prevent this, set it to
                                read-only to prevent changes.)
                            </p>

                            <DialogButton
                                style={{width: '100%', minWidth: 0}}
                                onClick={() => {
                                    openWeb(`https://airtable.com/appayGNkn3nSuXkaz/shruimhjdSakUPg2m/tbloLjoZKWJDnLtTc`);
                                }}>
                                <MdWeb/> Go To HRTF Database
                            </DialogButton>
                        </PanelSectionRow>
                    </PanelSection>
                    <PanelSection>
                        <PanelSocialButton icon={<SiPatreon fill="#438AB9"/>} url="https://www.patreon.com/c/Josh5">
                            Patreon
                        </PanelSocialButton>
                        <PanelSocialButton icon={<SiKofi fill="#FF5E5B"/>} url="https://ko-fi.com/josh5coffee">
                            Ko-fi
                        </PanelSocialButton>
                        <PanelSocialButton icon={<SiDiscord fill="#5865F2"/>} url="https://streamingtech.co.nz/discord">
                            Discord
                        </PanelSocialButton>
                        <PanelSocialButton icon={<SiGithub fill="#f5f5f5"/>}
                                           url="https://github.com/Josh5/decky-virtual-surround-sound">
                            Github
                        </PanelSocialButton>
                    </PanelSection>
                </div>
            )}
        </div>
    );
};

export default PluginConfigView;

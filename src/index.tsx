import {
    staticClasses
} from "@decky/ui";
import {
    definePlugin,
    // routerHook
} from "@decky/api"
import {RiSurroundSoundFill} from "react-icons/ri";
import QuickAccessView from "./components/QuickAccessView";


export default definePlugin(() => {
    console.log("Virtual Surround Sound plugin initializing, this is called once on frontend startup")

    return {
        // The name shown in various decky menus
        name: "Virtual Surround Sound",
        // The element displayed at the top of your plugin's menu
        titleView: <div className={staticClasses.Title}>Virtual Surround Sound</div>,
        // Preserve the plugin's state while the QAM is closed
        alwaysRender: true,
        // The content of your plugin's menu
        content: <QuickAccessView/>,
        // The icon displayed in the plugin list
        icon: <RiSurroundSoundFill/>,
        // The function triggered when your plugin unloads
        onDismount() {
            console.log("Unloading")
        },
    };
});

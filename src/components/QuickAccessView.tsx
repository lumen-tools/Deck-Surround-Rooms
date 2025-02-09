import React, {useEffect, useState} from 'react';
import type {PluginPage} from "../interfaces";
import PluginConfigView from "./PluginConfigView";
import AudioControlsView from "./AudioControlsView";
import {Footer} from "./elements/authorFooter";


const QuickAccessView: React.FC = () => {
    const [currentPage, setCurrentPage] = useState<PluginPage>("audio_controls");
    const changePage = (page: PluginPage) => {
        console.log(`[QuickAccessView] Changing page to: ${page}`);
        setCurrentPage(page);
    };

    useEffect(() => {
        console.log(`[QuickAccessView] Current page changed to: ${currentPage}`);
    }, [currentPage]);

    return (
        <div>
            {currentPage === "plugin_config" && (
                <PluginConfigView
                    onGoBack={() => changePage("audio_controls")}
                />
            )}
            {currentPage === "audio_controls" && (
                <AudioControlsView
                    onChangePage={changePage}
                />
            )}

            {/* Footer */}
            <Footer/>
        </div>
    )
        ;
};

export default QuickAccessView;

import React, { useEffect, useState } from 'react'
import type { PluginPage } from '../interfaces'
import PluginConfigView from './views/PluginConfigView'
import AudioControlsView from './views/AudioControlsView'


const QuickAccessMenuRouter: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<PluginPage>('audio_controls')
  const changePage = (page: PluginPage) => {
    console.log(`[deck-surround-rooms:QuickAccessMenuRouter] Changing page to: ${page}`)
    setCurrentPage(page)
  }

  useEffect(() => {
    console.log(`[deck-surround-rooms:QuickAccessMenuRouter] Current page changed to: ${currentPage}`)
  }, [currentPage])

  return (
    <div>
      {currentPage === 'plugin_config' && (
        <PluginConfigView
          onGoBack={() => changePage('audio_controls')}
        />
      )}
      {currentPage === 'audio_controls' && (
        <AudioControlsView
          onChangePage={changePage}
        />
      )}
    </div>
  )

}

export default QuickAccessMenuRouter

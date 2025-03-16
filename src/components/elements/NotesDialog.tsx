import { ConfirmModal, showModal } from '@decky/ui'
import { setPluginConfig } from '../../constants'
import { TiInfo } from 'react-icons/ti'

export const popupNotesDialog = (onCloseCallback = () => {
}) => {
  let closePopup = () => {
  }

  // Wrap the modal closing so we can also call the callback.
  const handleClose = () => {
    closePopup()
    onCloseCallback()
  }

  let Popup = () => {
    const iconStyle = {
      marginRight: '5px',
      marginLeft: '5px',
      verticalAlign: 'middle',
    }
    const titleStyle = {
      width: '100%',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: 'steelblue',
      margin: 0,
    }
    const messageStyle = { marginLeft: '10px' }

    return (
      <ConfirmModal
        strTitle={
          <p style={titleStyle}>
            <TiInfo style={iconStyle} /> NOTES <TiInfo style={iconStyle} />
          </p>
        }
        closeModal={handleClose}
        strOKButtonText={'Acknowledge'}
        bAlertDialog={true}
        onOK={() => {
          console.log(`[decky-virtual-surround-sound:WarningDialog] Setting as acknowledged.`)
          setPluginConfig({ notesAcknowledgedV1: true })
          handleClose()
        }}>
        <p style={messageStyle}>
          1) Binaural virtual surround sound produced by this plugin's filter will only work with headphones.
        </p>
        <p style={messageStyle}>
          2) Not every game or app supports outputting more than 2 channels. Even if Pipewire reports
          8-channel PCM, that may not be the case — you can test this by muting the front-left and front-right
          channels in the plugin mixer.
        </p>
        <p style={messageStyle}>
          3) In some cases, setting the game to use the Virtual Surround Sound sink in the game settings
          produces better results than enabling the sink in the plugin. Please test on a per-app basis.
        </p>
        <p style={{ ...messageStyle, fontStyle: 'italic' }}>
          Compatibility is not guaranteed; test and tweak settings to achieve the best setup for your system.
        </p>
      </ConfirmModal>
    )
  }

  const modal = showModal(<Popup />, window)
  closePopup = modal.Close
}

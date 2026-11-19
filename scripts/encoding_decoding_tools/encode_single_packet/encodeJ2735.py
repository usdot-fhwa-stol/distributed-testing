# SAE J2735 Encoder
import J2735_201603_combined_voices_mr_fix as J2735
import ast
import signal, sys
from binascii import hexlify

def signal_handler(sig, frame):
    print('\nExiting')
    sys.exit(0)


msgIn = input('Enter your JSON J2735 message:\n')
updatedMsg = msgIn.replace("\'", "\"")
updatedMsg = updatedMsg.strip("\n")
msg = ast.literal_eval(updatedMsg)

header_msg = {
    'messageId': 19,
    'value': ('signalPhaseAndTimingMessage', msg)
}
msgFrame = J2735.DSRC.MessageFrame
msgFrame.set_val(header_msg)
msgFrameUper = msgFrame.to_uper()
encodedMsg = hexlify(msgFrameUper)
print("\nEncoded Hex:\n", encodedMsg)


# header_sdsm = {
#     'messageId': 41,
#     'value': ('SPaT', sdsm)
# }

# # encode SDSM to hex
# header_sdsm_msg = SDSM.MessageFrame.MessageFrame
# header_sdsm_msg.set_val(header_sdsm)
# hex_sdsm = hexlify(header_sdsm_msg.to_uper())

# header_sdsm_msg.from_uper_ws(unhexlify(hex_sdsm))

signal.signal(signal.SIGINT, signal_handler)
print('\n<Ctrl+C> to exit')
signal.pause()
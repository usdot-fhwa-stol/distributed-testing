# Send replay raw PCAP using UDP
import socket
from time import sleep
import pyshark

def extract_bsm_payload_from_packet(pkt):
    # Ensure this is a UDP packet with a payload
    if not hasattr(pkt, 'udp') or not hasattr(pkt.udp, 'payload'):
        return None

    # UDP payload is a colon-separated hex string (e.g., '03:80:28:00:14...')
    raw_hex = pkt.udp.payload.replace(':', '')

    # Convert to bytes
    payload_bytes = bytes.fromhex(raw_hex)

    if len(payload_bytes) <= 3:
        return None

    # Skip first 3 bytes and return the rest as hex string
    bsm_payload = payload_bytes[3:]
    return bsm_payload.hex()

def main():
    # send Hex string to IP + port
    ip = '127.0.0.1'
    port = '56700'
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sk.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    packet_data = None
    try:
        cap = pyshark.FileCapture('/home/annika/Downloads/rewrite_pocx_bsms.pcap', display_filter='udp')
        packet_data = [pkt for pkt in cap]
    except:
        packet_data = None

    # f = open('SdsmEncoded_state_and_main.txt', 'r')
    # Lines = f.readlines()
    # f.close()
    # header_file = open('sdsm_AMF_header.txt', 'r')
    # header = header_file.read()
    # header_file.close()

    header_spat = 'Version=0.7\nType=MAP\nPSID=0x8002\nPriority=7\nTxMode=CONT\nTxChannel=180\nTxInterval=0\nDeliveryStart=\nDeliveryStop=\nSignature=False\nEncryption=False\n\nPayload='
    header_bsm = 'Version=0.7\nType=BSM\nPSID=0x20\nPriority=7\nTxMode=CONT\nTxChannel=183\nTxInterval=0\nDeliveryStart=\nDeliveryStop=\nSignature=False\nEncryption=False\n\nPayload='
    header_psm = 'Version=0.7\nType=PSM\nPSID=0x8003\nPriority=7\nTxMode=CONT\nTxChannel=183\nTxInterval=0\nDeliveryStart=\nDeliveryStop=\nSignature=False\nEncryption=False\n\nPayload='
    
    # data = "001283d33807302030141a1d4edb835139666d771ab402dc051178936033d4fa61e995053e9cb2e5e88276fe5d3462dfd776441a7767e5979f33400000200005c72ccde853b6df7e411af71cb337c64edb6367027b1c72cce4853b6d750009f61c85c00027681b21840009da066005969f4c3d32a0a7d17209dbf974d18b7f5dd91042d3af2a0998776541a7767e5979f33400100000038e599c10676dbefc82256e396670779db6e02804fb3603cb4fa61e995053e8b904edfcba68c5bfaeec8834eecfcb2f3e683665cdd1074ebcb71a00000080000e39666dbd9db6fbee08f638e599b79a76db807013ec390f40004ed00e44100013b402d815253e987a65414fa2e41170f3e98b7f5dd91069dd9f965e7cd04ccb9ba20a9d796e4400000100001c72ccd1453b6e0a8811f471cb33301cedb82a2027d8321680009da036c09666e1d3b9053e8b9045c3cfa62dfd776441a7767e5979f34400000200001c72ccd1633b6e059c11fa71cb32fbf4edb814e027d8321900009da086c088e6e1d3b9053e8b9045c3cfa62dfd776441a7767e5979f341332e6e882a75e5b910000002000071cb334514edb8018047e5c72ccbf253b6e003809f60c869000276821b00d99b874ee414fa2e415f2f3e98b7f5dd91049dd9f965e7cc9000000a000071cb3395bcedb84bc04841c72cd09cb3b6e127c0a0a2c85900027681321f00009da04c884000276811b01239b874ee414fa2e415f2f3e98b7f5dd91069dd9f965e7cd06ccb9ba20e9d796e2400000100001c72cce56f3b6e0cf0126171cb33cde4edb833002828321a80009da07500d5a9f4c3d32a0a7bfaf4d18b7f5dd91065cfcb2f3e6e4000000038e599af5276dbef6823b8e39666c109db6e03004fb2807374fa61e995073dfd7a68c5bfaeec8832e7e5979f3418b4ebcae400200000071cb3354ccedb7ded044adc72ccd5b93b6dc04c09f6500c526e1d3b9045c3cfa62dfd776441973f2cbcf9b100000000e396672b19db702ac08fe38e59a12f676dc09981414a016fcdc3a7720f082669c597974f28376fe5d3462dfd776441973f2cbcf9a900000000e39666f0d9db7109e099218e599bb9276dca192807c3370e9dc83be5e7d316febbb220cb9f965e7cd06ccb9ba2dcdbf977c3cb24100000000e396668e59db7097e08f038e5997ff676dc25d013eca020fcdc3a7720af979f4c5bfaeec8832e7e5979f341cb4e7d1d16f4ebcb74100000000e396668de9db70bf808f738e5997ff676dc2fb813ecd804dd3e987a65414fa2e414f7f5e9a316febbb22093bb3f2cbcf98a000001c0000e39666bc69db71094098998e599ae7a76dc9ff1e43100013b40590d80004ed01643c80013b40591020004ed012009b14fa61e995053e8b9073dfd7a68418f96fe7cfbe1d9ac00020000006396669dd9db6fdd063966709f9db6fde28024b4dc3a7720a7d1720cb879f4418f96fe7cfbe1d9ac00020000006396672249db6ff206396672099db70eb48022c53e987a6541cfa2e418f96fe7cfbe1d9ad06edfcba68000080000018e599c71a76dc3f298e599a52676dc3eb200a2d370e9dc829f45c831f2dfcf9f7c3b35a0ef979f4000080000018e599a55e76dc39418e599a59276dbfd70"
    # data = "001425167c0eb5843089a66e8bc29ea6c15488000000000010001b326efa1fa1007fff0000010028"
    data = "00201c000002a5158048d159e14cdd338f3d4da420101effffffff00000000"

    # for line in Lines:
    # line = Lines[1]
    if not packet_data:
        print('Sending repeated single packet.\nPress Ctrl+C to exit')
        sleep(1)
        while True:
            # data = line.strip('\n')     # removes any new line characters
            # if data[0:4] == "2023":
            #     continue
            # print(data)                 # uncomment to view data to be sent
            # send Hex string to port
            hexed = bytes(header_psm + data + '\n', 'utf-8')
            # hexed = bytearray.fromhex(data)
            # print(hexed)
            sk.sendto(hexed,(ip,int(port)))
            sleep(0.1) # 0.1 for BSM or SPAT or a pre-recorded message with multiple message types, 1 for ONLY Map
    else:
        print('Sending converted pcap data.\nPress Ctrl+C to exit')
        sleep(1)
        for packet in packet_data:
            data = extract_bsm_payload_from_packet(packet)
            if data is not None:
                # hexed = bytes(header_bsm + data + '\n', 'utf-8')
                hexed = bytearray.fromhex(data)
                sk.sendto(hexed,(ip,int(port)))
                sleep(0.1) # 0.1 for BSM or SPAT or a pre-recorded message with multiple message types, 1 for ONLY Map


if __name__ == "__main__":
    main()

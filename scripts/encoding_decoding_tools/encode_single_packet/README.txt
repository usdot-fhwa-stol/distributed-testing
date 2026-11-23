This encoder script encodes SAE J2735 messages in JSON format to UPER-encoded Hex.
Developed using linux. Can also be used in Windows.

Example JSON SPAT message:
{"messageId": 19, "value": ("SPAT", {"intersections": [{"id": {"id": 5813}, "revision": 1, "status": (0, 16), "moy": 137825, "states": [{"signalGroup": 7, "state-time-speed": [{"eventState": "permissive-clearance", "timing": {"startTime": 0, "minEndTime": 40, "maxEndTime": 40, "likelyTime": 40, "confidence": 15, "nextTime": 0}}]}]}]})}

Prerequisites:
1. J2735.py     # included in folder
2. pycrate      # pip3 install pycrate (installed after python3)
Additional for Windows:
1. python3      # Follow instructions: https://sites.pitt.edu/~naraehan/python3/getting_started_win_install.html
                # Latest version (as of April 2022): https://www.python.org/downloads/release/python-3104/ 
                # Select appropriate installer to download from "Files" at bottom of page. 
                    # Most likely "Windows installer (64-bit)"

To use:
1. cd to the encodeJ2735 directory
2. python3 encodeJ2735.py
3. Paste the JSON dict in the terminal when prompted
4. Hex string will be printed

The following states must be used in SPAT (case-sensitive):
Reds:
stop-Then-Proceed
stop-And-Remain

Greens:
permissive-Movement-Allowed
protected-Movement-Allowed

Yellows:
permissive-clearance
protected-clearance
caution-Conflicting-Traffic
# Radio HWIL Latency Analysis

## Input Folder Setup

```text
event/
└── run_001/
    ├── pcap/
    │   ├── dut_1/
    │   │   ├── tx.pcap
    │   │   └── rx.pcap
    │   ├── proxy_1/
    │   │   ├── tx.pcap
    │   │   └── rx.pcap
    │   └── v2xhub/
    │       ├── tx.pcap
    │       └── rx.pcap
    └── csv/
        Radio/
          ├── Entities-Radio.csv
        SecureV2XMessage/
          └── TV2XMsg-SecureV2XMsg.csv
```

## Running the analysis

Run both PCAP and CSV analysis:

```bash
# event/run_001/csv/radio.csv
python run_analysis.py --input-dir event/
```

### PCAP filename discovery

PCAP files are assigned to roles by looking for an endpoint and direction in
the filename or folder path.

Supported endpoints are:

```text
dut_1
dut_2
proxy_1
proxy_2
v2xhub_1
v2xhub_2
```

Supported directions are:

```text
tx
rx
```

Endpoint names may use forms such as:

```text
dut_1
dut-1
dut1
proxy_1
proxy-1
proxy1
```

Directions may use:

```text
tx
rx
transmit
receive
```

Examples of discoverable PCAP names include:

```text
dut_1_tx.pcap
dut-1-receive.pcap
proxy1_transmit.pcap
v2xhub_rx.pcap
```

### CSV filename discovery

#### Radio

```text
*Entities-Radio*.csv
*Radio*.csv
```

#### SecureV2XMessage

```text
*TV2XMsg-SecureV2XMsg*.csv
*SecureV2XMsg*.csv
*SecureV2X*.csv
```

If multiple files match, the first sorted match is used.


### Output

Input and output runs must have matching directory names:

```text
input-runs/
├── run_001/
├── run_002/
└── run_003/

output-runs/
├── run_001/
├── run_002/
└── run_003/
```

## Latency Thresholds

### PCAP thresholds

| Direction | Threshold |
|---|---:|
| DUT to DUT | `< 120 ms` |
| DUT to proxy | `< 39.77 ms` |
| Proxy to V2X Hub | `< 10 ms` |
| Proxy to DUT | `< 32 ms` |

### CSV threshold

Both CSV message types use:

```text
< 10 ms
```

## Generated Output

```text

results
|
├── run_001/
    ├── decoded/
        ├──dut_1_tx
            ├── decoded_tx.log
    └── pcap/
      ├── dut_1_to_proxy_1/
      │   ├── latency_results.csv
      │   ├── results_summary.csv
      │   └── plot files
      ├── proxy_1_to_dut_1/
      │   ├── latency_results.csv
      │   ├── results_summary.csv
      │   └── plot files
      ├── full_chain/
      │   ├── latency_results.csv
      │   ├── results_summary.csv
      │   ├── spdu_repeats.csv
      │   └── plot files
      └── dut_2_bsm_gps/
          ├── bsm_positions.csv
          └── bsm_gps_track.png
    └── csv/
      ├── Radio/
      │   ├── latency_results.csv
      │   ├── results_summary.csv
      │   └── plot files
      ├── SecureV2XMessage/
      │   ├── latency_results.csv
      │   ├── results_summary.csv
      │   └── plot files
      └── total_data_summary.csv
```

## Summary Columns

Each individual `results_summary.csv` includes threshold information such as:

```text
latency_threshold_ms
passed_samples
failed_samples
pass_percent
threshold_result
```

The consolidated `total_data_summary.csv`:

```text
run_name
run_result
failure_reason
```

## SPDU Chain Latency

`analysis_spdu_chain.py` runs as part of `run_analysis.py` and writes to
`pcap/full_chain/`. It follows each signed IEEE 1609.2 SPDU sent by `dut_1`
through the captures below, matching copies by signature (rSig concatenating sSig). Stages
whose PCAP is missing are skipped.

| Stage | PCAP | Default frame filter |
|---|---|---|
| reference | `dut_1/tx` | outgoing frames (Linux SLL); all frames otherwise |
| 1 | `proxy_1/rx` | drop frames whose source appears in `proxy_2/tx` in case of echo |
| 2 | `proxy_2/tx` | none |
| 3 | `dut_2/rx` | none |

Override a default filter with IP or MAC addresses (applies to every run):

```bash
python run_analysis.py --input-dir event/ \
  --dut1-dst ff02::1 \
  --proxy1-src 00:00:00:1e:5c:f6 \
  --dut2-src 80f8:f80:f80f:80f8::3e:7eff
```

Each stage is matched to its earliest copy of the signature with no ordering
assumed, so clock offsets appear as anomalies instead of missed matches.

### Output

| File | Content |
|---|---|
| `latency_results.csv` | One row per `dut_1` SPDU: `signature`, `psid`, `spdu_hex`, `t_<stage>` (epoch s), `lat_<stage>_ms` (from the `dut_1` send), `n_<stage>` (copies captured), `anomalies` |
| `results_summary.csv` | One row per stage: statistics, threshold result, and `sent`, `missing`, `negative`, `out_of_order`, `spdu_mismatch` counts |
| `spdu_repeats.csv` | SPDUs captured more than once at any stage, with every timestamp |
| `spdu_e2e_latency.png` | Histogram and boxplot of `dut_1` → last-stage latency |
| `spdu_latency_by_stage.png` | Boxplot per stage |
| `spdu_latency_per_message.png` | One row per SPDU, one dot per stage, sorted by end-to-end latency |

Anomaly tags (`;`-separated):

| Tag | Meaning |
|---|---|
| `missing:<stage>` | signature never captured at the stage |
| `negative:<stage>` | captured before the `dut_1` send |
| `order:<a>><b>` | captured at stage b before stage a |
| `spdu_mismatch:<stage>` | same signature, different SPDU bytes |

Thresholds come from the PCAP table: DUT to proxy for `proxy_1`, DUT to DUT for
`dut_2`. `proxy_2` has none (`NOT_CONFIGURED`).

### Dependencies

`pandas`, `matplotlib`. No ASN.1 module is needed: `../e2e_utils/spdu_utils.py`
parses the WSMP framing and reads the signature from the last 66 bytes of each
signed SPDU. Only ECDSA NIST P-256 signatures with an x-only or compressed `rSig`
are supported; other SPDUs are skipped and counted in a warning.

## DUT 2 BSM GPS Track

`analysis_bsm_gps.py` runs as part of `run_analysis.py` and writes to
`pcap/dut_2_bsm_gps/`. It plots the positions of the BSMs that `dut_1` sent, as
received by `dut_2`. Received BSMs are matched to `dut_1` by signature; BSMs from
other senders are ignored, and each message is kept once even if it was received
several times.

| File | Content |
|---|---|
| `bsm_positions.csv` | One row per BSM: receive `timestamp`, `src`, `signature`, `copies`, `bsm_id`, `msg_cnt`, `sec_mark`, `lat_deg`, `lon_deg`, `elev_m`, `speed_mps`, `heading_deg`, and `east_m` / `north_m` from the first fix |
| `bsm_gps_track.png` | Positions in metres from the first fix, coloured by receive time |

It can also be run on its own:

```bash
python analysis_bsm_gps.py --sender-pcap event/run_001/pcap/dut_1/tx.pcap \
  --receiver-pcap event/run_001/pcap/dut_2/rx.pcap --output-dir gps_out/
```

Requires `j2735_202409` in addition to the SPDU chain dependencies. The J2735
payload is read from signed SPDUs that embed it with a SHA-256 hash, and from
unsecured SPDUs.

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
          └── plot files
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
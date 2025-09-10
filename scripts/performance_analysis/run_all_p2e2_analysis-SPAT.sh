#!/bin/bash


python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R1/metadata-spat.json -n P2E2-RFR2-R1-SPAT 
python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R2/metadata-spat.json -n P2E2-RFR2-R2-SPAT 
python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R3/metadata-spat.json -n P2E2-RFR2-R3-SPAT 
python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R4/metadata-spat.json -n P2E2-RFR2-R4-SPAT 
python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R5/metadata-spat.json -n P2E2-RFR2-R5-SPAT 
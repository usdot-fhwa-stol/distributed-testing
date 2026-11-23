#!/bin/bash


python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R1/metadata.json -n P2E2-RFR2-R1-BSM 
python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R2/metadata.json -n P2E2-RFR2-R2-BSM 
python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R3/metadata.json -n P2E2-RFR2-R3-BSM 
python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R4/metadata.json -n P2E2-RFR2-R4-BSM 
python3 batch_calculate_e2e_perf_pilot2.py -m ~/distributed-testing/logs/P2E2-RFR2/R5/metadata.json -n P2E2-RFR2-R5-BSM
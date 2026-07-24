"""This script is used to plot the minEndTime field of each phase of received SPaT messages. User is able to specify a specific intersection ID and pass in a .csv of decoded SPaTs"""

import pandas as pd
import ast
import matplotlib.pyplot as plt
import argparse

def process_spat_file(file_path, target_id):
    df_raw = pd.read_csv(file_path, header=None)
    data_list = []

    for idx, row in df_raw.iterrows():
        try:
            # Parse Python-formatted JSON string
            record = ast.literal_eval(row[0])
            if record.get('messageId') == 19:
                spat_data = record['value'][1]
                for inter in spat_data.get('intersections', []):
                    if inter.get('id', {}).get('id') == target_id:
                        entry = {
                            'msg_index': idx,
                            'spat_timestamp': spat_data.get('timeStamp'),
                            'intersection_timestamp': inter.get('timeStamp')
                        }
                        # Extract minEndTime for each phase
                        for state in inter.get('states', []):
                            sg = state.get('signalGroup')
                            timing = state.get('state-time-speed', [{}])[0].get('timing', {})
                            entry[f'phase_{sg}_minEndTime'] = timing.get('minEndTime')
                        data_list.append(entry)
        except: continue
    
    df = pd.DataFrame(data_list)
    
    # Plotting
    plt.figure(figsize=(12, 6))
    plt.plot(df['msg_index'], df['spat_timestamp'], label='SPAT Timestamp', marker='o', alpha=0.5)
    plt.plot(df['msg_index'], df['intersection_timestamp'], label='Intersection Timestamp', marker='x', ls='--')
    
    phase_cols = [c for c in df.columns if 'phase_' in c]
    for col in phase_cols:
        plt.plot(df['msg_index'], df[col], label=col)
        
    plt.title(f'Timing Analysis for Intersection {target_id}')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True)
    plt.tight_layout()
    plt.savefig('spat_plot.png')

# ----------------------------
# main
# ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--file", required=True, help="Path to CSV file for processing")
    parser.add_argument("-i", "--id", required=True, help="intersection id to target")
    args = parser.parse_args()

    process_spat_file(args.file, args.id)
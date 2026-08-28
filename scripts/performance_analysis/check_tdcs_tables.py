#!/usr/bin/env python3

import sqlite3
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        description="List tables and columns in a TDCS SQLite database."
    )
    parser.add_argument(
        "database_file",
        help="Path to the TDCS SQLite database"
    )
    args = parser.parse_args()

    database_file = args.database_file

    if not os.path.isfile(database_file):
        print(f"Database not found: {database_file}")
        sys.exit(1)

    try:
        conn = sqlite3.connect(database_file)
        cursor = conn.cursor()

        # Confirm that the file is a readable SQLite database.
        cursor.execute("PRAGMA integrity_check")
        integrity_result = cursor.fetchone()[0]
        print(f"Database integrity: {integrity_result}\n")

        cursor.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
        """)

        tables = [row[0] for row in cursor.fetchall()]

        print(f"Total tables: {len(tables)}\n")

        print("Relevant tables:")
        relevant_keywords = [
            "Vehicle",
            "TrafficLight",
            "J2735",
            "J3224",
            "BSM"
        ]

        relevant_tables = [
            table
            for table in tables
            if any(keyword.lower() in table.lower()
                   for keyword in relevant_keywords)
        ]

        if relevant_tables:
            for table in relevant_tables:
                print(f"  {table}")
        else:
            print("  No relevant Vehicle, TrafficLight, J2735, J3224, or BSM tables found.")

        print("\nAll tables:")
        for table in tables:
            print(f"  {table}")

        conn.close()

    except sqlite3.Error as error:
        print(f"SQLite error: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
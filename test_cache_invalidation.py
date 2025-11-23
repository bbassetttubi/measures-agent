#!/usr/bin/env python3
"""
Test script to demonstrate cache invalidation when user data is updated.

This script simulates updating user biomarker data and shows how the cache
automatically invalidates, ensuring users always get fresh results.
"""

import json
import time
import os

def update_biomarker_data():
    """Simulate updating a biomarker value in the user's data file."""
    biomarker_file = 'servers/user_data/data/biomarkers.json'
    
    # Read current data
    with open(biomarker_file, 'r') as f:
        data = json.load(f)
    
    # Find and update LDL cholesterol (just as an example)
    for biomarker in data:
        if biomarker['name'] == 'LDL (Low-Density Lipoprotein)':
            old_value = biomarker['value']
            # Simulate improvement - lower LDL by 10 points
            new_value = str(int(old_value.split()[0]) - 10) + ' (calc)'
            biomarker['value'] = new_value
            print(f"\n✅ Updated LDL Cholesterol: {old_value} → {new_value}")
            break
    
    # Write updated data
    with open(biomarker_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"📝 Data file updated: {biomarker_file}")
    print(f"🔄 On next query, cache will automatically invalidate due to data version change")
    print(f"\nNext steps:")
    print(f"1. Ask: 'What are my biggest health issues?' (should use cache if asked recently)")
    print(f"2. Then run this script to update data")
    print(f"3. Ask again: 'What are my biggest health issues?' (will get FRESH results with new data!)")

if __name__ == "__main__":
    print("=" * 70)
    print("Cache Invalidation Test - Updating User Biomarker Data")
    print("=" * 70)
    update_biomarker_data()
    print("=" * 70)


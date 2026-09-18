import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from scripts.circuit_data import SUBSYSTEMS

def main():
    out_path = os.path.join(os.path.dirname(__file__), '../../scripts/static/circuit_schematics.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(SUBSYSTEMS, f, indent=2, ensure_ascii=False)
    print("circuit_schematics.json generated.")

if __name__ == '__main__':
    main()

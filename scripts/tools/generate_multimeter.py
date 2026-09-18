import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from scripts.multimeter_service import TEST_POINTS_CATALOG

def main():
    out_path = os.path.join(os.path.dirname(__file__), '../../scripts/static/multimeter_catalog.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(TEST_POINTS_CATALOG, f, indent=2, ensure_ascii=False)
    print("multimeter_catalog.json generated.")

if __name__ == '__main__':
    main()

"""Export the running code's contract without calling the model."""
import json
from pathlib import Path
from app.main import app

if __name__ == '__main__':
    target = Path(__file__).resolve().parents[2] / 'docs' / 'openapi.json'
    target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Exported docs/openapi.json')

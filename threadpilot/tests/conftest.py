"""Make the threadpilot/ folder importable (simulation package) when pytest runs from here."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "api.py"

spec = importlib.util.spec_from_file_location("gg_erp_api", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

app = module.app

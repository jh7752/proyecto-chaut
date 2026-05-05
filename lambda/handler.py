import sys
from pathlib import Path

# SAM packages the repository root; add src so Lambda can import the app package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mangum import Mangum

from chaut_api.app import app

handler = Mangum(app)

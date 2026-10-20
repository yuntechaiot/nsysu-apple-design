from pathlib import Path
import sys
from dotenv import load_dotenv
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
from nsysu.dashboard import main

if __name__ == '__main__':
    main()

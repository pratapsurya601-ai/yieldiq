import sys
from pipeline import run


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'test'
    skip_nse = '--skip-nse' in sys.argv
    run(mode=mode, skip_nse=skip_nse)
    print("\nDone.")

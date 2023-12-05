import sys

from homematic_exporter.exporter import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped")
        sys.exit(0)

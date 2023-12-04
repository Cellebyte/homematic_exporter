from homematic_exporter.exporter import main
import sys

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt as e:
        print("Stopped")
        sys.exit(0)

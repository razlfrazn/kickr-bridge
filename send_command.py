"""Send one command to a running kickr_bridge.py over UDP 127.0.0.1:5007.

    python send_command.py resistance 40
"""
import json, socket, sys

def main(argv):
    if len(argv) != 3 or argv[1] != "resistance":
        print(__doc__); return 2
    msg = json.dumps({"cmd": "resistance", "level": int(argv[2])})
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(msg.encode(), ("127.0.0.1", 5007))
    print("sent", msg)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Legacy ROS executable delegates startup to the single Moss owner."""
import subprocess


def main(args=None):
    result = subprocess.run(['sudo', '-n', 'systemctl', 'start', 'luka-ws-moss.service'])
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()

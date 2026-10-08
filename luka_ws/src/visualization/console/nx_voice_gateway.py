"""Legacy voice launcher delegates to the canonical audio owner."""
import os


class NXVoiceGateway:
    def __new__(cls, *args, **kwargs):
        from luka_audio.gateway import Gateway
        return Gateway(*args, **kwargs)


def main():
    script = '/home/sunrise/luka_ws/src/system/luka_audio/scripts/start_audio.sh'
    os.execv('/bin/bash', ['/bin/bash', script])


if __name__ == '__main__':
    main()

"""Short fixed confirmation tone, not speech synthesis."""
import math
import struct


def wake_pcm():
    count=1280  # 80 ms at 16 kHz
    return b''.join(struct.pack('<h', int(3276 * math.sin(2*math.pi*880*i/16000)
        * math.sin(math.pi*i/(count-1))**2)) for i in range(count))

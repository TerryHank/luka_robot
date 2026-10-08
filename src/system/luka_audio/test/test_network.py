import unittest
from luka_audio.network import Connectivity


class NetworkTests(unittest.TestCase):
    def test_startup_unknown(self):
        self.assertEqual(Connectivity().state(), 'unknown')

    def test_online_requires_one_success_offline_requires_two_failures(self):
        network = Connectivity(); network.update(True)
        self.assertEqual(network.state(), 'online')
        network.update(False)
        self.assertEqual(network.state(), 'online')
        network.update(False)
        self.assertEqual(network.state(), 'offline')
        network.update(True)
        self.assertEqual(network.state(), 'online')

    def test_stale_state_is_unknown_not_offline(self):
        clock = [0]; network = Connectivity(clock=lambda: clock[0])
        network.update(False); network.update(False)
        clock[0] = 11
        self.assertEqual(network.state(), 'unknown')

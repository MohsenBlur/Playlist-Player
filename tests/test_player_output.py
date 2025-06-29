import importlib, sys, types
from unittest import TestCase
from unittest.mock import patch, MagicMock

# --- prepare minimal vlc stub before importing player ---
class DummyInstance:
    def __init__(self, *args, **kwargs):
        pass

vlc_stub = types.ModuleType('vlc')
vlc_stub.Instance = MagicMock(return_value=DummyInstance())
vlc_stub.EventType = types.SimpleNamespace(MediaPlayerEndReached=object())

with patch.dict(sys.modules, {'vlc': vlc_stub}), \
     patch('shutil.which', return_value=None):
    player = importlib.import_module('player')

class OutputModeTests(TestCase):
    def setUp(self):
        vlc_stub.Instance.reset_mock()
        self.p = player.VLCGaplessPlayer(lambda: None)
        vlc_stub.Instance.reset_mock()

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            self.p.set_output('bogus')

    def test_no_restart_on_same_mode(self):
        # default mode is 'default'
        self.p.set_output('default')
        vlc_stub.Instance.assert_not_called()

    def test_restart_with_directsound(self):
        self.p.set_output('directsound')
        vlc_stub.Instance.assert_called_once()
        opts = vlc_stub.Instance.call_args[0][0]
        self.assertIn('--aout=directsound', opts)

    def test_restart_with_wasapi_exclusive(self):
        vlc_stub.Instance.reset_mock()
        self.p.set_output('wasapi_exclusive')
        vlc_stub.Instance.assert_called_once()
        opts = vlc_stub.Instance.call_args[0][0]
        self.assertIn('--aout=wasapi', opts)
        self.assertIn('--wasapi-exclusivemode', opts)


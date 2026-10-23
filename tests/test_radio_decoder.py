import pyModeS as pms
import pytest
from radio_decoder import FrameValidator, extract_message, text_from_bits

ADS_B = '8D40621D58C382D690C8AC2863A7'
ALL_CALL = '5D484FDEA248F5'  # Published Mode S example, interrogator code 22.
COMM_B = 'A0001838CA380031440000F24177'  # AP recovers 3C6DD0.


def with_parity(payload, overlay=0):
    message = payload + '000000'
    return payload + f'{pms.crc(message) ^ overlay:06X}'


@pytest.mark.parametrize('message', [ADS_B, ALL_CALL])
def test_short_and_long_frames_preserve_length(message):
    bits = f'{int(message, 16):0{len(message)*4}b}'
    samples = [s for bit in bits for s in ((2, 0) if bit == '1' else (0, 2))]
    assert extract_message(samples, 0) == message
    assert extract_message(samples[:-1], 0) is None
    assert text_from_bits(bits) == message


def test_df11_nonzero_interrogator_overlay():
    assert FrameValidator().validate(ALL_CALL, pms, 100) == (11, '484FDE')


def test_adsb_crc_and_full_df_field():
    v = FrameValidator()
    assert v.validate(ADS_B, pms, 100) == (17, '40621D')
    assert v.validate(ADS_B[:-1]+'0', pms, 100) is None
    other_capability = with_parity('8840621D58C382D690C8AC')
    assert v.validate(other_capability, pms, 101) == (17, '40621D')


def test_comm_b_needs_recent_independent_address_and_does_not_refresh_it():
    v = FrameValidator()
    assert pms.crc(COMM_B) == int('3C6DD0', 16)
    assert v.validate(COMM_B, pms, 100) is None
    v.validate(with_parity('5D3C6DD0'), pms, 100)
    assert v.validate(COMM_B, pms, 120) == (20, '3C6DD0')
    assert v.validate(COMM_B, pms, 161) is None


def test_df21_is_identity_not_altitude_and_df22_is_unsupported():
    v = FrameValidator()
    v.validate(with_parity('5D3C6DD0'), pms, 100)
    assert v.validate(with_parity('A8001838CA380031440000', int('3C6DD0', 16)), pms, 101)[0] == 21
    assert v.validate(with_parity('B0001838CA380031440000'), pms, 101) is None


def test_df18_non_icao_and_rebroadcast_excluded_from_direct_coverage():
    v = FrameValidator()
    assert v.validate(with_parity('9040621D58C382D690C8AC'), pms, 100)[0] == 18
    for prefix in ('91', '92', '96'):
        assert v.validate(with_parity(prefix+'40621D58C382D690C8AC'), pms, 100) is None


def test_malformed_length_and_invalid_bits():
    assert FrameValidator().validate(ADS_B[:14], pms, 100) is None
    assert text_from_bits('x'*56) == ''
    assert text_from_bits('0'*10) == ''


def test_radio_preserves_frame_crossing_sample_boundary_once(monkeypatch):
    import sys
    import types
    import numpy as np
    import main
    stream = np.zeros(800)
    start = 300
    stream[[start, start+2, start+7, start+9]] = 2
    bits = f'{int(ADS_B, 16):0112b}'
    for i, bit in enumerate(bits):
        stream[start+16+2*i+(0 if bit == '1' else 1)] = 2
    received = []

    class FakeSdr:
        def __init__(self):
            self.offset = 0
            self.closed = False

        def read_samples(self, count):
            result = stream[self.offset:self.offset+400]
            self.offset += 400
            if self.offset == 800:
                main.receiver_stop.set()
            return result

        def close(self):
            self.closed = True

    sdr = FakeSdr()
    monkeypatch.setitem(sys.modules, 'rtlsdr', types.SimpleNamespace(RtlSdr=lambda: sdr))
    monkeypatch.setattr(main, 'decode_details', received.append)
    main.receiver_stop.clear()
    try:
        main.radio_loop()
    finally:
        main.receiver_stop.clear()
    assert received == [ADS_B]
    assert sdr.closed

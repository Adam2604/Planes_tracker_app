"""Mode S framing/validation. pyModeS is injected to allow hardware-free tests."""


def text_from_bits(bits):
    if len(bits) not in (56, 112) or any(c not in "01" for c in bits):
        return ""
    return f"{int(bits, 2):0{len(bits) // 4}X}"


def extract_message(magnitudes, data_start):
    if data_start + 10 > len(magnitudes):
        return None
    df = 0
    for i in range(5):
        df = (df << 1) | int(magnitudes[data_start + 2*i] > magnitudes[data_start + 2*i + 1])
    length = 112 if df >= 16 else 56
    if data_start + length * 2 > len(magnitudes):
        return None
    return text_from_bits("".join("1" if magnitudes[data_start+2*i] > magnitudes[data_start+2*i+1]
                                  else "0" for i in range(length)))


class FrameValidator:
    """Comm-B AP accepted only for an independently seen, recent ICAO.

    Ambiguous Data Parity frames are intentionally not recovered by guessing BDS.
    DF18 rebroadcast/non-ICAO frames are excluded from the direct-reception model.
    """
    def __init__(self):
        self.known = {}

    def validate(self, message, pms, now):
        self.last_check = dict(crc_checked=False, crc_ok=False)
        if len(message) not in (14, 28):
            return None
        df = int(message[:2], 16) >> 3
        if len(message) != (28 if df >= 16 else 14):
            return None
        remainder = pms.crc(message)
        self.last_check = dict(crc_checked=df in (17, 18), crc_ok=remainder == 0)
        if df == 17:
            if remainder != 0:
                return None
        elif df == 18:
            # CF=0: ADS-B ES/NT with ICAO address, direct transmission.
            if remainder != 0 or int(message[:2], 16) & 7 != 0:
                return None
        elif df == 11:
            if not 0 <= remainder < 80:  # II/SI overlay, not plain CRC=0
                return None
        elif df in (20, 21):
            address = f"{remainder:06X}"
            if not 0 <= now - self.known.get(address, float("-inf")) <= 60:
                return None
            return df, address
        else:
            return None
        address = pms.icao(message).upper()
        self.known = {key: ts for key, ts in self.known.items() if now - ts <= 60}
        self.known[address] = now
        return df, address

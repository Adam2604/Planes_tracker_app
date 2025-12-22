from rtlsdr import RtlSdr
import numpy as np
import pyModeS as pms #biblioteka do wyciągania danych samolotu

def text_from_bits(bits):
    try:
        n = int(bits, 2)
        return "{:028X}".format(n) #zamiana na HEX, wymuszenie 28 znaków
    except ValueError:
        return ""
    
def decode_details(hex_msg):
    tc = pms.typecode(hex_msg)

    #1. Nazwa lotu
    if 1 <= tc <= 4:
        callsing = pms.adsb.callsign(hex_msg)
        print(f"Nazwa lotu: {callsing}")
    
    #2. Wysokość
    elif 9 <= tc <= 18:
        altitude = pms.adsb.altitude(hex_msg)
        altitude_meters = round(altitude * 0.3048)
        print(f"Wysokość: {altitude_meters} m")

    #3. Prędkość i kurs
    elif tc == 19:
        velocity = pms.adsb.velocity(hex_msg)
        if velocity:
            speed, heading, rate, v_type = velocity
            speed_kmh = round(speed * 1.852)
            if v_type == "GS":
                print(f"Prędkość względem ziemi: {speed_kmh} km/h, Kurs: {heading:.2f}°")
            elif v_type == "IAS" or v_type == "TAS":
                print(f"Prędkość powietrzna (IAS/TAS): {speed_kmh} km/h")

def main():
    #Konfiguracja
    sdr = RtlSdr()
    sdr.sample_rate = 2000000
    sdr.center_freq = 1090000000
    sdr.freq_correction = 1

    print("Czekam na sygnał")
    try:
        while True:
            samples = sdr.read_samples(256 * 1024)
            mag = np.abs(samples) #amplituda

            #Wykrywanie preambuły
            p0 = mag[: -16] #Sygnał w chwili T
            p2 = mag[2: -14] #Sygnał w chwili T + 2 próbki
            p7 = mag[7 : -9] #Sygnał w chwili T +7 próbek
            p9 = mag[9 : -7] #Sygnał w chwili T + 9 próbek

            noise = np.mean(mag)
            threshold = noise * 3.5
            hits = (p0 > threshold) & (p2 > threshold) & \
                   (p7 > threshold) & (p9 > threshold)
            hit_indices = np.where(hits)[0]
            #Hits = True -> wiadomość od samolotu się zaczyna

            for idx in hit_indices:
                data_start = idx + 16 #dane zaczynają się 16 próbek po preambule
                if data_start + 224 >= len(mag): continue
                #Dekodowanie bitów
                signal_slice = mag[data_start: data_start + 224]
                try:
                    bit_pairs = signal_slice.reshape(112, 2)
                    #Jeżeli pierwsza połówka pary jest wyższa -> bit "1"
                    bits_list = bit_pairs[:, 0] > bit_pairs[:, 1]
                    bits = "".join(["1" if b else "0" for b in bits_list])

                    hex_msg = text_from_bits(bits)
                except ValueError:
                    continue

                #Filtrowanie - sprawdzanie tylko ramek zaczynających się od "8D"
                #Dodatkowo za pomocą biblioteki pyModeS sprawdzamy sumę kontrolną
                #żeby nie brac pod uwagę błędnych ramek
                if hex_msg.startswith("8D"):
                    try:
                        if pms.crc(hex_msg) == 0:
                            icao = pms.icao(hex_msg)
                            tc = pms.typecode(hex_msg)
                            print(f"Odebrano wiadomość od samolotu ICAO: {icao}, \nType Code: {tc}, HEX: {hex_msg}")
                            decode_details(hex_msg)
                            print("-"*40)
                    except:
                        pass
    except KeyboardInterrupt:
        print("Zakończono odbiór sygnału.")
    finally:
        sdr.close()

if __name__ == "__main__":
    main()

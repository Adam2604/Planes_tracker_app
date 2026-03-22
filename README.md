# ✈️ Custom ADS-B Radar & Flight Analyzer

A custom-built, real-time aircraft tracking system capable of intercepting and decoding radio signals directly from the airspace. Unlike standard trackers, this project focuses on deep data analysis, historical archiving, and detecting "invisible" military traffic.

You can check how it works on this page: [Planes Tracker](https://planes-tracker.pl)

---

## 💡 How It Works

This system turns a standard RTL-SDR USB dongle into a powerful radar station. It listens on the **1090 MHz** frequency, intercepts **ADS-B (Automatic Dependent Surveillance–Broadcast)** signals sent by aircraft, and processes them using Python.

### The Core Logic:
1.  **Signal Interception:** The Python backend captures raw radio packets.
2.  **Decoding:** It decodes the hex messages to extract ICAO addresses, flight IDs, altitude, speed, and GPS coordinates.
3.  **Data Enrichment:** The system matches the ICAO code against a local database to identify the specific aircraft model, manufacturer, and operator (e.g., *Ryanair, Boeing 737-800*).
4.  **Visualization:** A Flask web server pushes this data to a responsive Leaflet.js map.

---

## 🌟 Key Features

### 🗺️ Live Tactical Map
The dashboard provides a real-time view of the airspace with features designed for enthusiasts:
* **Smart Visualization:** Icons differentiate between light aircraft and airliners.
* **True Heading:** Aircraft icons rotate to match their actual flight path.
* **Instant Metrics:** A HUD shows the total number of tracked flights and proximity alerts (< 5km) in real-time.
  
#### Main page - Desktop view:
<img width="1600" alt="image" src="https://github.com/user-attachments/assets/ede030d9-c904-4465-9ef0-074662fba272" />




### 👻 "Ghost" Protocol (Military Detection)
A unique algorithm designed to detect aircraft attempting to fly "under the radar."
* **Logic:** The system flags aircraft that broadcast identification signals (like "NATO" or "AIR FORCE") but deliberately suppress their GPS position data.
* **Alerts:** These "Ghosts" are highlighted on the dashboard even if they cannot be placed on the map.

### 📋 Daily Flight List & Route Replay
A full register of every aircraft detected since midnight. 
* **Historical Logging:** Unlike the live map, this list ensures no flight is missed, logging even brief signal interceptions.
* **Route Visualization:** A new feature allows users to **display the recorded flight path** for any aircraft in the list. By clicking on a flight, the system renders the exact route taken by the plane while it was within the station's range.

#### Daily Flight List - Desktop view
<img width="1600" alt="image" src="https://github.com/user-attachments/assets/7e7a8f54-9f1d-49a8-b8c1-e6d53c60df8e" />


### 📊 Advanced Statistics & Radio Range Map
This module analyzes the performance of the station and the quality of the traffic.
* **Radio Coverage Heatmap:** The statistics page now features a **Radio Range Map**. It visualizes the actual maximum signal reach of the SDR antenna in every direction, helping to identify terrain obstacles or optimal antenna placement.
* **The "Rarest" Algorithm:** A custom scoring system assigns points to aircraft. Common airliners get 0 points, while rare catches (Antonovs, Military, LPR) receive high scores.
* **Daily Archives:** The system automatically saves summaries at midnight, creating a permanent history of the local airspace.

#### Statistics page - Desktop view:
<img width="1500" alt="image" src="https://github.com/user-attachments/assets/4bce8661-d8c6-4f09-a33d-433ee0fd8db4" /> 

#### Radio range map - Desktop view:
<img width="1600" alt="image" src="https://github.com/user-attachments/assets/8842c9c6-b040-480b-bfcb-b19daa04c724" />

### 📱 Dedicated Android App
To ensure the best possible user experience, the system is accessed via a **custom native Android application written in Kotlin**.
* **Immersive View:** The app uses a highly optimized **WebView** implementation to render the radar interface in full-screen mode, removing browser distractions (URL bars, navigation buttons).
* **Mobile-First Interface:** The UI is specifically designed for touch interaction, with oversized controls positioned at the bottom of the screen for easy one-handed operation.
* **Pocket Radar:** Combined with a VPN (Tailscale), the app transforms a smartphone into a secure, portable radar station accessible from anywhere.
  
<img width="270" alt="image" src="https://github.com/user-attachments/assets/0570cf29-5e7a-4116-b746-37d92e9a51a7" />    <img width="270" alt="image" src="https://github.com/user-attachments/assets/9c359fd9-adec-4970-ab59-a9f5dca461eb" />    <img width="270" alt="image" src="https://github.com/user-attachments/assets/65e26a4b-256b-4a7d-9cad-54113243e00f" />     





---

## 🏗️ Tech Stack

* **Core Language:** Python
* **Mobile App:** Kotlin (Android Native + WebView)
* **Web Framework:** Flask
* **Radio Interface:** RTL-SDR
* **Decoding:** pyModeS
* **Frontend:** HTML, CSS, JavaScript
* **Database:** SQLite
* **Multithreading:** Handles radio listening, web serving, and data cleaning simultaneously.

---

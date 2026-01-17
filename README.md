# ✈️ Custom ADS-B Radar & Flight Analyzer

A custom-built, real-time aircraft tracking system capable of intercepting and decoding radio signals directly from the airspace. Unlike standard trackers, this project focuses on deep data analysis, historical archiving, and detecting "invisible" military traffic.

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

### 📋 Daily Flight List
A dedicated subpage serving as a **full register of the current day**. Unlike the main map which displays real-time positions, this list logs **every aircraft detected since midnight**. It allows users to review, sort, and analyze all traffic that has passed through the airspace today, ensuring no flight is missed.

#### Daily Flight List - Desktop view
<img width="1600" alt="image" src="https://github.com/user-attachments/assets/237be765-28ad-4196-9ebb-7996022fa3b1" />


### 📊 Advanced Statistics & Scoring System
Instead of just counting planes, this project analyzes the *quality* of the traffic.
* **The "Rarest" Algorithm:** A custom scoring system assigns points to aircraft. Common airliners (A320, B737) get 0 points, while rare catches (Antonovs, Military, Helicopters, LPR) receive high scores.
* **Daily Archives:** The system automatically saves summaries at midnight, creating a permanent history of the local airspace.
* **Records:** Tracks the farthest detected signal (distance record) and the most frequent models.

#### Statistics page - Desktop view:
<img width="1500" alt="image" src="https://github.com/user-attachments/assets/4bce8661-d8c6-4f09-a33d-433ee0fd8db4" /> 

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

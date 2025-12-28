package com.example.planestracker

import android.os.Bundle
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Znajdź element WebView
        val myWebView: WebView = findViewById(R.id.webview)

        // Włącz JavaScript (wymagany przez mapy Leaflet!)
        myWebView.settings.javaScriptEnabled = true

        // Wyłącz zoomowanie systemowe (mapa ma swój własny zoom)
        myWebView.settings.builtInZoomControls = false

        // Spraw, by linki otwierały się w aplikacji, a nie w Chrome
        myWebView.webViewClient = WebViewClient()

        // ZAŁADUJ STRONĘ Z MALINKI
        // Zmień ten adres na IP swojej Malinki!
        myWebView.loadUrl("http://192.168.0.50:5000")
    }
}
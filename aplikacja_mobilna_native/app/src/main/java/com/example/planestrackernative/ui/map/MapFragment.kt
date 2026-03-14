package com.example.planestrackernative.ui.map

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Matrix
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.example.planestrackernative.R
import com.example.planestrackernative.api.RetrofitClient
import kotlinx.coroutines.*
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polygon
import org.osmdroid.views.overlay.Polyline
import org.osmdroid.views.overlay.MapEventsOverlay
import org.osmdroid.events.MapEventsReceiver
import android.graphics.Color
import android.graphics.drawable.BitmapDrawable

class MapFragment : Fragment() {

    private lateinit var mapView: MapView
    private val planeMarkers = mutableMapOf<String, Marker>()
    private var selectedIcao: String? = null
    private var selectedRouteLine: Polyline? = null
    private var planesJob: Job? = null
    private var statsJob: Job? = null

    // Cached plane icons
    private var planeIcon: Bitmap? = null
    private var planeLightIcon: Bitmap? = null

    companion object {
        private const val BASE_LAT = 51.978
        private const val BASE_LON = 17.498
        private const val REFRESH_INTERVAL_MS = 1000L
        private const val STATS_INTERVAL_MS = 5000L
    }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View? {
        return inflater.inflate(R.layout.fragment_map, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Load plane icons
        planeIcon = BitmapFactory.decodeResource(resources, R.drawable.plane)
        planeLightIcon = BitmapFactory.decodeResource(resources, R.drawable.plane_light)

        setupMap(view)
        startDataLoop()
        startStatsLoop()
    }

    private fun setupMap(view: View) {
        mapView = view.findViewById(R.id.mapView)
        mapView.setTileSource(TileSourceFactory.MAPNIK)
        mapView.setMultiTouchControls(true)
        mapView.controller.setZoom(11.0)
        mapView.controller.setCenter(GeoPoint(BASE_LAT, BASE_LON))

        // Base marker
        val baseMarker = Marker(mapView)
        baseMarker.position = GeoPoint(BASE_LAT, BASE_LON)
        baseMarker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
        baseMarker.title = getString(R.string.base_label)
        mapView.overlays.add(baseMarker)

        // 5km radius circle
        val circle = Polygon(mapView)
        val circlePoints = Polygon.pointsAsCircle(GeoPoint(BASE_LAT, BASE_LON), 5000.0)
        circle.points = circlePoints
        circle.fillPaint.color = Color.TRANSPARENT
        circle.outlinePaint.color = Color.parseColor("#4CAF50")
        circle.outlinePaint.strokeWidth = 4f
        mapView.overlays.add(circle)

        // Click on map to deselect route (using MapEventsOverlay, not setOnClickListener
        // which breaks osmdroid's internal touch handling and causes markers to vanish)
        val mapEventsReceiver = object : MapEventsReceiver {
            override fun singleTapConfirmedHelper(p: GeoPoint?): Boolean {
                // Close all open info windows
                for (marker in planeMarkers.values) {
                    marker.closeInfoWindow()
                }
                clearSelectedRoute()
                return false
            }
            override fun longPressHelper(p: GeoPoint?): Boolean = false
        }
        mapView.overlays.add(0, MapEventsOverlay(mapEventsReceiver))
    }

    private fun startDataLoop() {
        planesJob = viewLifecycleOwner.lifecycleScope.launch {
            while (isActive) {
                try {
                    val planes = RetrofitClient.api.getPlanes()
                    updatePlanes(planes)
                } catch (e: Exception) {
                    // Silent fail — retry next cycle
                }
                delay(REFRESH_INTERVAL_MS)
            }
        }
    }

    private fun startStatsLoop() {
        statsJob = viewLifecycleOwner.lifecycleScope.launch {
            while (isActive) {
                try {
                    val stats = RetrofitClient.api.getQuickStats()
                    updateStats(stats)
                } catch (e: Exception) {
                    // Silent fail
                }
                delay(STATS_INTERVAL_MS)
            }
        }
    }

    private fun updatePlanes(planes: List<com.example.planestrackernative.model.Plane>) {
        val currentIcaos = planes.map { it.icao }.toSet()

        // Remove old markers
        val toRemove = planeMarkers.keys.filter { it !in currentIcaos }
        for (icao in toRemove) {
            planeMarkers[icao]?.let { mapView.overlays.remove(it) }
            planeMarkers.remove(icao)
            if (selectedIcao == icao) clearSelectedRoute()
        }

        // Update or add markers
        for (plane in planes) {
            val lat = plane.lat ?: continue
            val lon = plane.lon ?: continue
            val point = GeoPoint(lat, lon)

            val existingMarker = planeMarkers[plane.icao]
            val titleText = plane.callsign ?: plane.icao
            val snippetText = buildSnippetText(plane)

            if (existingMarker != null) {
                existingMarker.position = point
                existingMarker.title = titleText
                existingMarker.snippet = snippetText
                existingMarker.icon = createRotatedIcon(plane.heading, plane.category)
            } else {
                val marker = Marker(mapView)
                marker.position = point
                marker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
                marker.title = titleText
                marker.snippet = snippetText
                marker.icon = createRotatedIcon(plane.heading, plane.category)
                marker.setOnMarkerClickListener { m, _ ->
                    selectedIcao = plane.icao
                    refreshSelectedRoute()
                    m.showInfoWindow()
                    true // consume event — don't propagate to MapEventsOverlay
                }
                mapView.overlays.add(marker)
                planeMarkers[plane.icao] = marker
            }
        }

        mapView.invalidate()

        // Refresh route if selected
        if (selectedIcao != null) {
            refreshSelectedRoute()
        }
    }

    private fun buildSnippetText(plane: com.example.planestrackernative.model.Plane): String {
        val model = plane.model ?: getString(R.string.unknown_model)
        val alt = plane.altitude?.let { "${it}m" } ?: "?"
        val spd = plane.speed?.let { "${it}km/h" } ?: "?"
        val dst = plane.dist?.let { "${it}km" } ?: "?"
        return "$model\nWys: $alt | Pręd: $spd\nOdl: $dst"
    }

    private fun createRotatedIcon(heading: Double?, category: Int?): BitmapDrawable {
        val baseBitmap = if (category == 1) planeLightIcon else planeIcon
        val source = baseBitmap ?: planeIcon!!

        val angle = heading?.toFloat() ?: 0f
        val size = 110 // pixels for marker icon

        val scaled = Bitmap.createScaledBitmap(source, size, size, true)
        val rotated = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(rotated)
        val matrix = Matrix()
        matrix.postRotate(angle, size / 2f, size / 2f)
        canvas.drawBitmap(scaled, matrix, null)

        return BitmapDrawable(resources, rotated)
    }

    private fun clearSelectedRoute() {
        selectedRouteLine?.let { mapView.overlays.remove(it) }
        selectedRouteLine = null
        selectedIcao = null
        mapView.invalidate()
    }

    private fun refreshSelectedRoute() {
        val icao = selectedIcao ?: return
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val response = RetrofitClient.api.getRoute(icao)
                if (selectedIcao != icao) return@launch

                if (!response.active) {
                    clearSelectedRoute()
                    return@launch
                }

                val routePoints = response.route
                    ?.filterNotNull()
                    ?.filter { it.size >= 2 }
                    ?.map { GeoPoint(it[0], it[1]) }
                    ?: emptyList()

                if (routePoints.size < 2) {
                    selectedRouteLine?.let { mapView.overlays.remove(it) }
                    selectedRouteLine = null
                    return@launch
                }

                if (selectedRouteLine != null) {
                    selectedRouteLine!!.setPoints(routePoints)
                } else {
                    selectedRouteLine = Polyline(mapView).apply {
                        setPoints(routePoints)
                        outlinePaint.color = Color.RED
                        outlinePaint.strokeWidth = 6f
                    }
                    mapView.overlays.add(selectedRouteLine)
                }

                mapView.invalidate()
            } catch (e: Exception) {
                // Ignore errors
            }
        }
    }

    private fun updateStats(stats: com.example.planestrackernative.model.StatsQuick) {
        val view = view ?: return
        view.findViewById<TextView>(R.id.statTotal)?.text = stats.total.toString()
        view.findViewById<TextView>(R.id.statClose)?.text = stats.close.toString()

        val ghostView = view.findViewById<TextView>(R.id.statGhost)
        if (stats.militaryGhost) {
            ghostView?.text = getString(R.string.yes_alert)
            ghostView?.setTextColor(Color.RED)
        } else {
            ghostView?.text = getString(R.string.no_alert)
            ghostView?.setTextColor(Color.WHITE)
        }

        val rareText = stats.rarest ?: getString(R.string.analyzing_sky)
        view.findViewById<TextView>(R.id.statRarest)?.text = rareText
    }

    override fun onResume() {
        super.onResume()
        mapView.onResume()
    }

    override fun onPause() {
        super.onPause()
        mapView.onPause()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        planesJob?.cancel()
        statsJob?.cancel()
    }
}

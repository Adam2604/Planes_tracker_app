package com.example.planestrackernative.ui.stats

import android.app.DatePickerDialog
import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.example.planestrackernative.R
import com.example.planestrackernative.api.RetrofitClient
import com.example.planestrackernative.model.RangeMapSector
import com.example.planestrackernative.model.StatsDetailed
import kotlinx.coroutines.launch
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polygon
import java.text.SimpleDateFormat
import java.util.*
import kotlin.math.*

class StatsFragment : Fragment() {

    private lateinit var dateBtn: TextView
    private lateinit var modeSpinner: Spinner
    private lateinit var statsTitle: TextView
    private lateinit var statsContent: LinearLayout
    private lateinit var noDataPanel: LinearLayout
    private lateinit var rangeMapView: MapView
    private lateinit var rangeNoData: TextView
    private lateinit var rangeMapSection: LinearLayout

    private var currentDate: String = ""
    private var currentMode: String = "day"
    private val modes = arrayOf("day", "week", "month")
    private val modeLabels = arrayOf("Dzień", "Tydzień", "Miesiąc")

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View? {
        return inflater.inflate(R.layout.fragment_stats, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        currentDate = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())

        dateBtn = view.findViewById(R.id.dateBtn)
        modeSpinner = view.findViewById(R.id.modeSpinner)
        statsTitle = view.findViewById(R.id.statsTitle)
        statsContent = view.findViewById(R.id.statsContent)
        noDataPanel = view.findViewById(R.id.noDataPanel)
        rangeMapView = view.findViewById(R.id.rangeMapView)
        rangeNoData = view.findViewById(R.id.rangeNoData)
        rangeMapSection = view.findViewById(R.id.rangeMapSection)

        dateBtn.text = currentDate

        // Setup range map
        setupRangeMap()

        // Setup spinner
        val spinnerAdapter = ArrayAdapter(requireContext(), android.R.layout.simple_spinner_item, modeLabels)
        spinnerAdapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        modeSpinner.adapter = spinnerAdapter
        modeSpinner.setSelection(0)

        modeSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                currentMode = modes[pos]
                if (currentMode == "month") {
                    // Trim date to YYYY-MM
                    if (currentDate.length > 7) currentDate = currentDate.substring(0, 7)
                    dateBtn.text = currentDate
                } else {
                    if (currentDate.length <= 7) currentDate += "-01"
                    dateBtn.text = currentDate
                }
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }

        dateBtn.setOnClickListener { showDatePicker() }

        view.findViewById<Button>(R.id.showBtn).setOnClickListener {
            loadStats()
        }

        loadStats()
    }

    private fun setupRangeMap() {
        rangeMapView.setTileSource(TileSourceFactory.MAPNIK)
        rangeMapView.setMultiTouchControls(true)
        rangeMapView.controller.setZoom(8.0)
        rangeMapView.controller.setCenter(GeoPoint(51.978, 17.498))
    }

    private fun showDatePicker() {
        val cal = Calendar.getInstance()
        try {
            val parsed = if (currentDate.length <= 7) "${currentDate}-01" else currentDate
            cal.time = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).parse(parsed) ?: Date()
        } catch (e: Exception) { /* keep today */ }

        DatePickerDialog(
            requireContext(),
            R.style.Theme_PlanesTracker,
            { _, year, month, day ->
                if (currentMode == "month") {
                    currentDate = String.format("%04d-%02d", year, month + 1)
                } else {
                    currentDate = String.format("%04d-%02d-%02d", year, month + 1, day)
                }
                dateBtn.text = currentDate
            },
            cal.get(Calendar.YEAR),
            cal.get(Calendar.MONTH),
            cal.get(Calendar.DAY_OF_MONTH)
        ).show()
    }

    private fun loadStats() {
        val modeLabel = when (currentMode) {
            "week" -> "Statystyki tygodniowe ($currentDate)"
            "month" -> "Statystyki miesięczne ($currentDate)"
            else -> "📊 Statystyki z dnia: $currentDate"
        }
        statsTitle.text = modeLabel

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val stats = RetrofitClient.api.getDetailedStats(currentDate, currentMode)

                if (stats.total == null) {
                    statsContent.visibility = View.GONE
                    noDataPanel.visibility = View.VISIBLE
                    return@launch
                }

                statsContent.visibility = View.VISIBLE
                noDataPanel.visibility = View.GONE
                displayStats(stats)
                loadRangeMap()
            } catch (e: Exception) {
                statsContent.visibility = View.GONE
                noDataPanel.visibility = View.VISIBLE
            }
        }
    }

    private fun loadRangeMap() {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val response = RetrofitClient.api.getRangeMap(currentDate, currentMode)
                val sectors = response.sectors
                val antLat = response.antenna.lat
                val antLon = response.antenna.lon

                val maxDist = sectors.maxOfOrNull { it.dist } ?: 0.0

                if (maxDist == 0.0) {
                    rangeNoData.visibility = View.VISIBLE
                    // Clear overlays but keep the base map
                    rangeMapView.overlays.clear()
                    addBaseOverlays(antLat, antLon)
                    rangeMapView.invalidate()
                    return@launch
                }

                rangeNoData.visibility = View.GONE
                drawRangeMap(sectors, antLat, antLon)
            } catch (e: Exception) {
                rangeNoData.visibility = View.VISIBLE
                rangeMapView.overlays.clear()
                rangeMapView.invalidate()
            }
        }
    }

    private fun addBaseOverlays(antLat: Double, antLon: Double) {
        // Antenna marker
        val antennaMarker = Marker(rangeMapView)
        antennaMarker.position = GeoPoint(antLat, antLon)
        antennaMarker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
        antennaMarker.title = "📡 Antena"
        antennaMarker.icon = createCircleDrawable(Color.parseColor("#4CAF50"), 14)
        rangeMapView.overlays.add(antennaMarker)

        // Distance circles
        val distances = listOf(50, 100, 200, 350, 500)
        for (r in distances) {
            val circle = Polygon(rangeMapView)
            val circlePoints = Polygon.pointsAsCircle(GeoPoint(antLat, antLon), r * 1000.0)
            circle.points = circlePoints
            circle.fillPaint.color = Color.TRANSPARENT
            circle.outlinePaint.color = Color.parseColor("#555555")
            circle.outlinePaint.strokeWidth = 2f
            circle.outlinePaint.pathEffect = android.graphics.DashPathEffect(floatArrayOf(10f, 16f), 0f)
            rangeMapView.overlays.add(circle)
        }
    }

    private fun drawRangeMap(sectors: List<RangeMapSector>, antLat: Double, antLon: Double) {
        rangeMapView.overlays.clear()
        addBaseOverlays(antLat, antLon)

        // Build polygon points
        val polygonPoints = mutableListOf<GeoPoint>()
        for (s in sectors) {
            val dist = if (s.dist > 0) s.dist else 5.0
            val pt = destPoint(antLat, antLon, dist, s.angle)
            polygonPoints.add(pt)
        }
        // Close polygon
        if (polygonPoints.isNotEmpty()) {
            polygonPoints.add(polygonPoints[0])
        }

        // Main polygon outline
        val mainPolygon = Polygon(rangeMapView)
        mainPolygon.points = polygonPoints
        mainPolygon.fillPaint.color = Color.argb(38, 33, 150, 243) // ~0.15 opacity blue
        mainPolygon.outlinePaint.color = Color.parseColor("#2196F3")
        mainPolygon.outlinePaint.strokeWidth = 4f
        rangeMapView.overlays.add(mainPolygon)

        // Colored sector triangles
        for (i in sectors.indices) {
            val s1 = sectors[i]
            val s2 = sectors[(i + 1) % sectors.size]
            val maxDistForColor = maxOf(s1.dist, s2.dist)
            if (maxDistForColor < 1) continue

            val d1 = if (s1.dist > 0) s1.dist else 5.0
            val d2 = if (s2.dist > 0) s2.dist else 5.0

            val pt1 = destPoint(antLat, antLon, d1, s1.angle)
            val pt2 = destPoint(antLat, antLon, d2, s2.angle)

            val triangle = Polygon(rangeMapView)
            triangle.points = listOf(
                GeoPoint(antLat, antLon), pt1, pt2, GeoPoint(antLat, antLon)
            )
            val color = distColor(maxDistForColor)
            triangle.fillPaint.color = Color.argb(64, Color.red(color), Color.green(color), Color.blue(color))
            triangle.outlinePaint.color = Color.TRANSPARENT
            triangle.outlinePaint.strokeWidth = 0f
            rangeMapView.overlays.add(triangle)
        }

        // Top distance markers (top 4)
        val sortedSectors = sectors.sortedByDescending { it.dist }
        val topN = minOf(4, sortedSectors.count { it.dist > 0 })

        for (i in 0 until topN) {
            val ts = sortedSectors[i]
            if (ts.dist < 10) continue
            val tpt = destPoint(antLat, antLon, ts.dist, ts.angle)

            val marker = Marker(rangeMapView)
            marker.position = tpt
            marker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
            marker.title = "${ts.dist.roundToInt()} km"
            marker.icon = createCircleDrawable(distColor(ts.dist), 10)
            marker.snippet = "Kierunek: ${ts.angle.roundToInt()}°"
            rangeMapView.overlays.add(marker)
        }

        // Fit bounds to polygon
        if (polygonPoints.size > 2) {
            val boundingBox = org.osmdroid.util.BoundingBox.fromGeoPoints(polygonPoints)
            rangeMapView.zoomToBoundingBox(boundingBox, true, 60)
        }

        rangeMapView.invalidate()
    }

    /** Calculates destination point given start, distance in km, and bearing in degrees */
    private fun destPoint(lat: Double, lon: Double, distKm: Double, bearingDeg: Double): GeoPoint {
        val r = 6371.0
        val d = distKm / r
        val brng = Math.toRadians(bearingDeg)
        val lat1 = Math.toRadians(lat)
        val lon1 = Math.toRadians(lon)

        val lat2 = asin(
            sin(lat1) * cos(d) + cos(lat1) * sin(d) * cos(brng)
        )
        val lon2 = lon1 + atan2(
            sin(brng) * sin(d) * cos(lat1),
            cos(d) - sin(lat1) * sin(lat2)
        )

        return GeoPoint(Math.toDegrees(lat2), Math.toDegrees(lon2))
    }

    /** Returns color based on distance — matches web version */
    private fun distColor(d: Double): Int {
        return when {
            d < 100 -> Color.parseColor("#1565C0")
            d < 200 -> Color.parseColor("#00E676")
            d < 350 -> Color.parseColor("#FF9100")
            else -> Color.parseColor("#D50000")
        }
    }

    /** Creates a small filled circle drawable for markers */
    private fun createCircleDrawable(color: Int, sizeDp: Int): android.graphics.drawable.Drawable {
        val density = resources.displayMetrics.density
        val sizePx = (sizeDp * density).toInt()
        val bitmap = android.graphics.Bitmap.createBitmap(sizePx, sizePx, android.graphics.Bitmap.Config.ARGB_8888)
        val canvas = android.graphics.Canvas(bitmap)
        val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
        // White border
        paint.color = Color.WHITE
        canvas.drawCircle(sizePx / 2f, sizePx / 2f, sizePx / 2f, paint)
        // Colored fill
        paint.color = color
        canvas.drawCircle(sizePx / 2f, sizePx / 2f, sizePx / 2f - 2 * density, paint)
        return android.graphics.drawable.BitmapDrawable(resources, bitmap)
    }

    private fun displayStats(s: StatsDetailed) {
        val view = this.view ?: return

        // Number cards
        view.findViewById<TextView>(R.id.cardTotal).text = (s.total ?: 0).toString()
        view.findViewById<TextView>(R.id.cardClose).text = (s.close ?: 0).toString()
        view.findViewById<TextView>(R.id.cardLight).text = (s.light ?: 0).toString()

        // Farthest
        val farthestView = view.findViewById<TextView>(R.id.cardFarthest)
        val farthestModelView = view.findViewById<TextView>(R.id.cardFarthestModel)
        if (s.farthest != null && s.farthest.dist != null) {
            farthestView.text = "${String.format("%.1f", s.farthest.dist)} km"
            farthestModelView.text = s.farthest.model ?: "Nieznany"
            farthestModelView.visibility = View.VISIBLE
        } else {
            farthestView.text = "-"
            farthestModelView.visibility = View.GONE
        }

        // Ghost
        val ghostStatus = view.findViewById<TextView>(R.id.ghostStatus)
        val ghostDetail = view.findViewById<TextView>(R.id.ghostDetail)
        if (s.ghostModel != null) {
            ghostStatus.text = "⚠️ WYKRYTO: ${s.ghostModel}"
            ghostStatus.setTextColor(Color.parseColor("#F44336"))
            ghostDetail.text = getString(R.string.no_gps)
            ghostDetail.visibility = View.VISIBLE
        } else {
            ghostStatus.text = getString(R.string.ghost_clear)
            ghostStatus.setTextColor(Color.parseColor("#4CAF50"))
            ghostDetail.visibility = View.GONE
        }

        // Top models
        val topContainer = view.findViewById<LinearLayout>(R.id.topModelsList)
        topContainer.removeAllViews()
        s.topModels?.forEachIndexed { idx, item ->
            if (item.size >= 2) {
                val name = item[0].toString()
                val count = (item[1] as? Double)?.toInt() ?: item[1].toString().toIntOrNull() ?: 0
                addModelRow(topContainer, "${idx + 1}. $name", "${count}x", Color.parseColor("#444444"))
            }
        }

        // Rare models
        val rareContainer = view.findViewById<LinearLayout>(R.id.rareModelsList)
        rareContainer.removeAllViews()
        s.rareModels?.forEachIndexed { idx, item ->
            if (item.size >= 2) {
                val name = item[0].toString()
                val count = (item[1] as? Double)?.toInt() ?: item[1].toString().toIntOrNull() ?: 0
                addModelRow(rareContainer, "${idx + 1}. $name", "${count}x", Color.parseColor("#FFC107"))
            }
        }
    }

    private fun addModelRow(container: LinearLayout, name: String, count: String, badgeColor: Int) {
        val row = LinearLayout(requireContext()).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(0, 16, 0, 16)
            gravity = android.view.Gravity.CENTER_VERTICAL
        }

        val nameView = TextView(requireContext()).apply {
            text = name
            setTextColor(Color.parseColor("#DDDDDD"))
            textSize = 14f
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }

        val countView = TextView(requireContext()).apply {
            text = count
            textSize = 12f
            setTextColor(if (badgeColor == Color.parseColor("#FFC107")) Color.BLACK else Color.WHITE)
            setPadding(16, 4, 16, 4)
            background = android.graphics.drawable.GradientDrawable().apply {
                setColor(badgeColor)
                cornerRadius = 20f
            }
        }

        row.addView(nameView)
        row.addView(countView)
        container.addView(row)

        // Divider
        val divider = View(requireContext()).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 1
            )
            setBackgroundColor(Color.parseColor("#333333"))
        }
        container.addView(divider)
    }

    override fun onResume() {
        super.onResume()
        if (::rangeMapView.isInitialized) rangeMapView.onResume()
    }

    override fun onPause() {
        super.onPause()
        if (::rangeMapView.isInitialized) rangeMapView.onPause()
    }
}

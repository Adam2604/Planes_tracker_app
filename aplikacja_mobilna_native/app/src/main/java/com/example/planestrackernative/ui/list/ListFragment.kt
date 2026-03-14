package com.example.planestrackernative.ui.list

import android.app.DatePickerDialog
import android.app.Dialog
import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.planestrackernative.R
import com.example.planestrackernative.api.RetrofitClient
import com.example.planestrackernative.model.FlightListItem
import kotlinx.coroutines.launch
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Polyline
import java.text.SimpleDateFormat
import java.util.*

class ListFragment : Fragment() {

    private lateinit var recyclerView: RecyclerView
    private lateinit var emptyText: TextView
    private lateinit var adapter: FlightAdapter
    private lateinit var dateFromBtn: TextView
    private lateinit var dateToBtn: TextView
    private lateinit var listTitle: TextView

    private var dateFrom: String = ""
    private var dateTo: String = ""

    private val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View? {
        return inflater.inflate(R.layout.fragment_list, container, false)
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val today = dateFormat.format(Date())
        dateFrom = today
        dateTo = today

        recyclerView = view.findViewById(R.id.flightsList)
        emptyText = view.findViewById(R.id.emptyText)
        dateFromBtn = view.findViewById(R.id.dateFromBtn)
        dateToBtn = view.findViewById(R.id.dateToBtn)
        listTitle = view.findViewById(R.id.listTitle)

        dateFromBtn.text = dateFrom
        dateToBtn.text = dateTo

        adapter = FlightAdapter(emptyList()) { flight ->
            showRouteDialog(flight)
        }
        recyclerView.layoutManager = LinearLayoutManager(requireContext())
        recyclerView.adapter = adapter

        dateFromBtn.setOnClickListener { showDatePicker(dateFrom) { dateFrom = it; dateFromBtn.text = it } }
        dateToBtn.setOnClickListener { showDatePicker(dateTo) { dateTo = it; dateToBtn.text = it } }

        view.findViewById<Button>(R.id.filterBtn).setOnClickListener {
            loadFlights()
        }

        loadFlights()
    }

    private fun showDatePicker(currentDate: String, onPicked: (String) -> Unit) {
        val cal = Calendar.getInstance()
        try {
            cal.time = dateFormat.parse(currentDate) ?: Date()
        } catch (e: Exception) { /* keep today */ }

        DatePickerDialog(
            requireContext(),
            R.style.Theme_PlanesTracker,
            { _, year, month, day ->
                val picked = String.format("%04d-%02d-%02d", year, month + 1, day)
                onPicked(picked)
            },
            cal.get(Calendar.YEAR),
            cal.get(Calendar.MONTH),
            cal.get(Calendar.DAY_OF_MONTH)
        ).show()
    }

    private fun loadFlights() {
        listTitle.text = if (dateFrom == dateTo) {
            "✈️ Przeloty z dnia $dateFrom"
        } else {
            "✈️ Przeloty od $dateFrom do $dateTo"
        }

        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val flights = RetrofitClient.api.getFlightsList(dateFrom, dateTo)
                if (flights.isEmpty()) {
                    recyclerView.visibility = View.GONE
                    emptyText.visibility = View.VISIBLE
                } else {
                    recyclerView.visibility = View.VISIBLE
                    emptyText.visibility = View.GONE
                    adapter.updateData(flights)
                }
            } catch (e: Exception) {
                Toast.makeText(requireContext(), getString(R.string.error_connection), Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun showRouteDialog(flight: FlightListItem) {
        val dialog = Dialog(requireContext(), android.R.style.Theme_Black_NoTitleBar_Fullscreen)
        dialog.setContentView(R.layout.dialog_route_map)

        val title = dialog.findViewById<TextView>(R.id.routeTitle)
        title.text = getString(R.string.route_title, flight.icao, flight.model ?: "")

        val routeMapView = dialog.findViewById<MapView>(R.id.routeMapView)
        routeMapView.setTileSource(TileSourceFactory.MAPNIK)
        routeMapView.setMultiTouchControls(true)
        routeMapView.controller.setZoom(9.0)
        routeMapView.controller.setCenter(GeoPoint(51.978, 17.498))

        dialog.findViewById<Button>(R.id.closeRouteBtn).setOnClickListener {
            routeMapView.onPause()
            dialog.dismiss()
        }

        dialog.show()

        // Load route data
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val response = RetrofitClient.api.getRouteHistory(flight.rowid)
                val routeRaw = response.route ?: return@launch

                // Split into segments at null points
                val segments = mutableListOf<MutableList<GeoPoint>>()
                var current = mutableListOf<GeoPoint>()
                for (point in routeRaw) {
                    if (point == null) {
                        if (current.size >= 2) segments.add(current)
                        current = mutableListOf()
                    } else if (point.size >= 2) {
                        current.add(GeoPoint(point[0], point[1]))
                    }
                }
                if (current.size >= 2) segments.add(current)

                // Draw segments
                val allPoints = mutableListOf<GeoPoint>()
                for (seg in segments) {
                    val line = Polyline(routeMapView)
                    line.setPoints(seg)
                    line.outlinePaint.color = Color.RED
                    line.outlinePaint.strokeWidth = 6f
                    routeMapView.overlays.add(line)
                    allPoints.addAll(seg)
                }

                // Fit bounds
                if (allPoints.isNotEmpty()) {
                    val boundingBox = org.osmdroid.util.BoundingBox.fromGeoPoints(allPoints)
                    routeMapView.zoomToBoundingBox(boundingBox, true, 80)
                }

                routeMapView.invalidate()
            } catch (e: Exception) {
                Toast.makeText(requireContext(), getString(R.string.error_connection), Toast.LENGTH_SHORT).show()
            }
        }
    }
}

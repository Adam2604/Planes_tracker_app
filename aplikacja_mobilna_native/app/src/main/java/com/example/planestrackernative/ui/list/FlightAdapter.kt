package com.example.planestrackernative.ui.list

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.planestrackernative.R
import com.example.planestrackernative.model.FlightListItem

class FlightAdapter(
    private var flights: List<FlightListItem>,
    private val onRouteClick: (FlightListItem) -> Unit
) : RecyclerView.Adapter<FlightAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val time: TextView = view.findViewById(R.id.flightTime)
        val model: TextView = view.findViewById(R.id.flightModel)
        val icao: TextView = view.findViewById(R.id.flightIcao)
        val dist: TextView = view.findViewById(R.id.flightDist)
        val routeBtn: Button = view.findViewById(R.id.routeBtn)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_flight, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val flight = flights[position]
        holder.time.text = flight.time
        holder.model.text = flight.model ?: "Nieznany"
        holder.icao.text = flight.icao
        holder.dist.text = if (flight.dist >= 9999) "—" else "${flight.dist} km"

        if (flight.hasRoute) {
            holder.routeBtn.visibility = View.VISIBLE
            holder.routeBtn.setOnClickListener { onRouteClick(flight) }
        } else {
            holder.routeBtn.visibility = View.GONE
        }
    }

    override fun getItemCount(): Int = flights.size

    fun updateData(newFlights: List<FlightListItem>) {
        flights = newFlights
        notifyDataSetChanged()
    }
}

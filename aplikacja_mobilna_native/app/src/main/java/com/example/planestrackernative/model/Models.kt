package com.example.planestrackernative.model

import com.google.gson.annotations.SerializedName

data class Plane(
    val icao: String = "",
    val callsign: String? = null,
    val model: String? = null,
    val lat: Double? = null,
    val lon: Double? = null,
    val altitude: Int? = null,
    val speed: Int? = null,
    val heading: Double? = null,
    val dist: Double? = null,
    val category: Int? = null,
    @SerializedName("min_dist") val minDist: Double? = null,
    @SerializedName("max_speed") val maxSpeed: Int? = null,
    @SerializedName("first_seen") val firstSeen: Double? = null,
    @SerializedName("last_seen") val lastSeen: Double? = null
)

data class RouteResponse(
    val icao: String,
    val active: Boolean = false,
    val route: List<List<Double>?>? = null
)

data class StatsQuick(
    @SerializedName("stat_total") val total: Int = 0,
    @SerializedName("stat_close") val close: Int = 0,
    @SerializedName("stat_rarest") val rarest: String? = null,
    @SerializedName("stat_military_ghost") val militaryGhost: Boolean = false,
    @SerializedName("stat_light") val light: Int = 0
)

data class StatsDetailed(
    val total: Int? = null,
    val close: Int? = null,
    val light: Int? = null,
    val farthest: FarthestInfo? = null,
    @SerializedName("ghost_model") val ghostModel: String? = null,
    @SerializedName("top_models") val topModels: List<List<Any>>? = null,
    @SerializedName("rare_models") val rareModels: List<List<Any>>? = null
)

data class FarthestInfo(
    val dist: Double? = null,
    val model: String? = null
)

data class FlightListItem(
    val rowid: Int = 0,
    val icao: String = "",
    val model: String? = null,
    val time: String = "",
    val dist: Double = 9999.0,
    val speed: Int = 0,
    @SerializedName("has_route") val hasRoute: Boolean = false
)

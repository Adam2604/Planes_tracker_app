package com.example.planestrackernative.api

import com.example.planestrackernative.model.*
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Query

interface ApiService {
    @GET("/data")
    suspend fun getPlanes(): List<Plane>

    @GET("/route/{icao}")
    suspend fun getRoute(@Path("icao") icao: String): RouteResponse

    @GET("/route/history/{rowid}")
    suspend fun getRouteHistory(@Path("rowid") rowid: Int): RouteResponse

    @GET("/stats")
    suspend fun getQuickStats(): StatsQuick

    @GET("/api/list")
    suspend fun getFlightsList(
        @Query("date_from") dateFrom: String,
        @Query("date_to") dateTo: String
    ): List<FlightListItem>

    @GET("/api/stats")
    suspend fun getDetailedStats(
        @Query("date") date: String,
        @Query("mode") mode: String
    ): StatsDetailed

    @GET("/api/range_map")
    suspend fun getRangeMap(
        @Query("date") date: String,
        @Query("mode") mode: String
    ): RangeMapResponse
}

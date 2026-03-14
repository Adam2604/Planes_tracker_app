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
import com.example.planestrackernative.model.StatsDetailed
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

class StatsFragment : Fragment() {

    private lateinit var dateBtn: TextView
    private lateinit var modeSpinner: Spinner
    private lateinit var statsTitle: TextView
    private lateinit var statsContent: LinearLayout
    private lateinit var noDataPanel: LinearLayout

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

        dateBtn.text = currentDate

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
            } catch (e: Exception) {
                statsContent.visibility = View.GONE
                noDataPanel.visibility = View.VISIBLE
            }
        }
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
}

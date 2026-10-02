package jp.fujimi.newsbunko.next.speech

import org.json.JSONArray
import org.json.JSONObject

data class SpeechBoundary(val text: String, val offset: Long, val duration: Long)

/** Matches the PC Edge sentence boundaries to original paragraphs without estimating positions. */
object EdgeSentenceTimings {
    fun segments(paragraphs: List<String>, boundaries: List<SpeechBoundary>): JSONArray {
        fun normalized(text: String) = text.replace(Regex("[\\s\\p{Z}\\u0085\\u001c-\\u001f]+"), "")
        val text = paragraphs.map(::normalized)
        require(text.isNotEmpty() && text.all { it.isNotEmpty() } && boundaries.isNotEmpty()) { "在线声线未返回完整的段落时间。" }
        val starts = arrayOfNulls<Double>(text.size)
        var paragraph = 0
        var cursor = 0
        for (boundary in boundaries) {
            val sentence = normalized(boundary.text)
            require(sentence.isNotEmpty() && boundary.offset >= 0 && boundary.duration > 0) { "在线声线逐句时间无效。" }
            var match = text[paragraph].indexOf(sentence, cursor)
            if (match < 0) {
                paragraph++
                cursor = 0
                require(paragraph < text.size) { "在线声线逐句时间与正文不一致。" }
                match = text[paragraph].indexOf(sentence)
                require(match >= 0) { "在线声线逐句时间与正文不一致。" }
            }
            if (starts[paragraph] == null) starts[paragraph] = boundary.offset / 10_000_000.0
            cursor = match + sentence.length
        }
        require(starts.all { it != null }) { "在线声线未返回完整的段落时间。" }
        val end = boundaries.maxOf { it.offset + it.duration } / 10_000_000.0
        val edges = listOf(0.0) + starts.drop(1).map { it!! } + end
        return JSONArray().apply {
            for (index in text.indices) {
                val duration = edges[index + 1] - edges[index]
                require(duration > 0) { "在线声线段落时间无效。" }
                put(JSONObject().put("duration", duration).put("speech_start_offset", maxOf(0.0, starts[index]!! - edges[index]))
                    .put("timing_source", "edge_sentence"))
            }
        }
    }
}

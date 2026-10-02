package jp.fujimi.newsbunko.next.news

import java.net.URI
import org.json.JSONArray
import org.json.JSONObject
import org.jsoup.Jsoup
import org.jsoup.nodes.Document
import org.jsoup.nodes.Element
import org.jsoup.safety.Safelist

/** Single operations only: each publisher owns its selectors and execution order. */
internal object NewsPrimitives {
    fun uri(url: String): URI = try { URI(url) } catch (_: Exception) { throw NewsValidationException("新闻地址无效。") }
    fun hostMatches(host: String, domains: List<String>) = domains.any { host == it || host.endsWith(".$it") }
    fun validUrl(url: String, domains: List<String>, path: Regex) {
        val u = uri(url)
        if (u.scheme !in listOf("https", "http") || u.userInfo != null || !hostMatches(u.host.orEmpty().lowercase(), domains) || !path.matches(u.path.orEmpty()))
            throw NewsValidationException("地址不是该来源的新闻正文页。")
    }
    fun canonical(url: String): String { val u=uri(url); return URI(u.scheme,u.authority,u.path,null,null).toString().trimEnd('/') }
    fun cleanUrl(url: String): String { val u=uri(url); return URI(u.scheme,u.authority,u.path,null,null).toString() }
    fun resolve(base: String, raw: String): String? = try {
        val u=uri(base).resolve(raw.trim()); if(u.scheme in listOf("http","https") && u.host != null && u.userInfo == null) u.toString() else null
    } catch (_: Exception) { null }
    fun request(url: String, transport: NewsTransport, checkpoint: () -> Unit): NewsPage {
        checkpoint(); val page=transport.get(url); checkpoint(); return page
    }
    fun sameArticle(requested: String, final: String, domains: List<String>, pattern: Regex) {
        validUrl(requested,domains,pattern); validUrl(final,domains,pattern)
        if(uri(requested).path.trimEnd('/') != uri(final).path.trimEnd('/')) throw NewsValidationException("原站重定向离开当前文章，未收录。")
    }
    fun document(html: String, url: String): Document = Jsoup.parse(html,url)
    fun metadata(doc: Document): List<JSONObject> {
        val out=mutableListOf<JSONObject>()
        fun walk(value: Any?) {
            when(value) {
                is JSONArray -> (0 until value.length()).forEach { walk(value.opt(it)) }
                is JSONObject -> {
                    val type=value.opt("@type"); val types=if(type is JSONArray) (0 until type.length()).map { type.optString(it) } else listOf(type?.toString())
                    if(types.any { it in listOf("Article","NewsArticle","ReportageNewsArticle") }) out.add(value)
                    walk(value.opt("@graph"))
                }
            }
        }
        doc.select("script[type=application/ld+json]").forEach { try { val raw=it.data().trim(); walk(if(raw.startsWith("[")) JSONArray(raw) else JSONObject(raw)) } catch (_: Exception) { } }
        return out
    }
    fun rejectPaid(records: List<JSONObject>) {
        records.forEach { r ->
            val parts=r.opt("hasPart"); val items=when(parts) { is JSONArray -> (0 until parts.length()).mapNotNull { parts.optJSONObject(it) }; is JSONObject -> listOf(parts); else -> emptyList() }
            if(r.opt("isAccessibleForFree")?.toString().equals("false",true) || items.any { it.opt("isAccessibleForFree")?.toString().equals("false",true) }) throw NewsValidationException("本文为付费或会员限定文章，未收录。")
        }
    }
    fun rejectGate(scope: Element, selectors: String) {
        if(selectors.isNotBlank() && scope.selectFirst(selectors)!=null) throw NewsValidationException("本文存在会员阅读门槛，未收录。")
        val gate=Regex("(?:この記事|この(?:続き|記事)|ここから先).{0,25}(?:会員限定|有料会員|有料記事)|(?:続き|全文)を(?:お)?読(?:みいただく|む)には.{0,20}(?:登録|会員)")
        if(scope.select("p,span,h2,h3,[role=alert]").any { it.text().length<250 && gate.containsMatchIn(it.text()) }) throw NewsValidationException("原站提示本文需会员订阅，未收录。")
    }
    fun scope(doc: Element, selectors: String, name: String): Element = doc.selectFirst(selectors) ?: throw NewsValidationException("$name：未识别正文容器，已跳过。")
    fun clean(scope: Element) { scope.select("script,style,nav,footer,aside,form,noscript,[role=dialog]").remove() }
    fun noise(node: Element, scope: Element): Boolean {
        var current: Element?=node
        while(current!=null && current!==scope) {
            if(current.tagName() in listOf("header","footer","nav","aside","form","button","figcaption") || current.attr("role") in listOf("dialog","alert") || current.attr("aria-hidden")=="true") return true
            if(Regex("(?:^|[\\s_-])(?:related|recommend|sns|share|advert|ranking|paywall|author|copyright)(?:[\\s_-]|$)",RegexOption.IGNORE_CASE).containsMatchIn(current.className()+" "+current.id())) return true
            current=current.parent()
        }; return false
    }
    data class Body(val texts: List<String>, val html: List<String>, val origins: List<Element>)
    fun paragraphs(scope: Element, selector: String, exclude: Set<String> = emptySet(), splitBlank: Boolean=false): Body {
        val texts=mutableListOf<String>(); val markup=mutableListOf<String>(); val origins=mutableListOf<Element>()
        val accepted=mutableSetOf<Element>()
        scope.select(selector).forEach { node ->
            if(noise(node,scope) || node.parents().any { it.tagName()=="a" || it in accepted }) return@forEach
            val copy=node.clone(); copy.select("rt,rp,script,style,iframe").remove()
            copy.select("br").forEach { it.after("\n"); it.remove() }
            val raw=copy.wholeText().replace("\r","").trim()
            if(raw.isBlank() || raw in exclude || copy.select("a").joinToString(""){it.text()} == raw) return@forEach
            accepted.add(node)
            val pieces=if(splitBlank) raw.split(Regex("\n\\s*\n")) else listOf(raw)
            pieces.forEach { part ->
                val text=part.replace(Regex("\\s*\n\\s*")," ").trim()
                if(text.isNotEmpty()) { texts.add(text); origins.add(node); markup.add(if(pieces.size==1) safeHtml(node.html()) else org.jsoup.nodes.Entities.escape(text)) }
            }
        }
        if(texts.isEmpty() || texts.sumOf { it.length } > 150000) throw NewsValidationException("未找到有效公开全文，或文章过长，已跳过。")
        return Body(texts,markup,origins)
    }
    fun safeHtml(html: String): String = Jsoup.clean(html,"",Safelist.none().addTags("ruby","rb","rt","rp","b","strong","em","i","br"),Document.OutputSettings().prettyPrint(false))
    fun title(doc: Document, records: List<JSONObject>, selector: String="h1", excluded: Set<String> = emptySet()): String {
        val result=doc.selectFirst(selector)?.text().orEmpty().ifBlank { records.firstOrNull()?.optString("headline").orEmpty() }.ifBlank { doc.title() }
        if(result.isBlank() || result in excluded) throw NewsValidationException("未识别文章标题，已跳过。")
        return result
    }
    fun published(doc: Document, records: List<JSONObject>): String = records.firstOrNull()?.optString("datePublished").orEmpty().ifBlank { doc.selectFirst("meta[property=article:published_time]")?.attr("content").orEmpty() }
    fun images(scope: Element, selector: String, body: Body, url: String): List<NewsMedia> {
        val order=scope.allElements.withIndex().associate { it.value to it.index }
        return scope.select(selector).filterNot { noise(it,scope) }.mapNotNull { img ->
            val raw=listOf("data-src","data-original","src").map { img.attr(it) }.firstOrNull { it.isNotBlank() } ?: img.attr("srcset").split(',').lastOrNull()?.trim()?.split(Regex("\\s+"))?.firstOrNull().orEmpty()
            val target=resolve(url,raw.takeIf { it.isNotBlank() } ?: return@mapNotNull null) ?: return@mapNotNull null
            if(Regex("(?:logo|banner|bnr_|icon|spacer)",RegexOption.IGNORE_CASE).containsMatchIn(uri(target).path.orEmpty())) return@mapNotNull null
            val figure=img.parents().firstOrNull { it.tagName()=="figure" }
            val caption=figure?.selectFirst("figcaption")?.text().orEmpty().ifBlank { img.attr("alt") }
            val before=body.origins.count { (order[it] ?: 0) < (order[img] ?: 0) }
            NewsMedia(target,"image",caption,if(before==0) -1 else before)
        }.distinctBy { it.url }
    }
    fun preview(doc: Document,url:String):List<NewsMedia> = doc.selectFirst("meta[property=og:image]")?.attr("content")?.let { resolve(url,it) }?.let { listOf(NewsMedia(it,"image",paragraphIndex=-1)) } ?: emptyList()
    fun videos(scope: Element, url: String): List<NewsMedia> = scope.select("video[src],video source[src],[data-video-url],[data-video-src],[data-movie-url],iframe[src]").mapNotNull { node ->
        val raw=listOf("src","data-video-url","data-video-src","data-movie-url").map { node.attr(it) }.firstOrNull { it.isNotBlank() } ?: return@mapNotNull null
        val target=resolve(url,raw) ?: return@mapNotNull null
        val kind=if(Regex("\\.(mp4|webm)$",RegexOption.IGNORE_CASE).containsMatchIn(uri(target).path.orEmpty())) "video" else "preview_video"
        NewsMedia(target,kind)
    }.distinctBy { it.url }
    fun listing(doc: Document, base: String, domains: List<String>, pattern: Regex, badges: String="", terms: Set<String> = emptySet()): List<String> {
        val blocked=mutableSetOf<String>(); val candidates=mutableListOf<String>()
        doc.select("a[href]").forEach { anchor ->
            val url=resolve(base,anchor.attr("href")) ?: return@forEach
            try { validUrl(url,domains,pattern) } catch (_:NewsValidationException) { return@forEach }
            val target=cleanUrl(url)
            val parents=listOf(anchor)+anchor.parents()
            val card=parents.firstOrNull { it.tagName() in listOf("article","li","h2","h3") } ?: parents.firstOrNull { it.tagName() in listOf("div","section") && Regex("article|card|item|list|entry|headline|story",RegexOption.IGNORE_CASE).containsMatchIn(it.className()+it.id()) } ?: anchor
            val labelled=card.text()+" "+card.allElements.joinToString(" "){it.attr("alt")+it.attr("aria-label")+it.attr("title")}
            if((badges.isNotBlank() && (parents.any { it.`is`(badges) } || card.selectFirst(badges)!=null)) || terms.any { labelled.contains(it) }) blocked.add(target) else candidates.add(target)
        }
        return candidates.distinct().filterNot { it in blocked }
    }
    fun requireLinks(links: List<String>,name:String):List<String> = links.ifEmpty { throw NewsValidationException("$name：未发现有效新闻候选链接。") }
}

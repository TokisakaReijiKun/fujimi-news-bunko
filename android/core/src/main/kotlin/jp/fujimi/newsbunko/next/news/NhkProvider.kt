package jp.fujimi.newsbunko.next.news

import java.io.IOException
import java.net.URLEncoder
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.Instant
import org.json.JSONObject
import org.jsoup.Jsoup
import org.jsoup.parser.Parser

object NhkProvider : NewsProvider {
    override val name="NHKニュース"
    override val processingSteps=listOf("kana", "media", "translation")
    private val domains=listOf("news.web.nhk","nhk.or.jp")
    private val pattern=Regex("/(?:newsweb/(?:na|articles)/[^/?]+|news/html/\\d+/[^/]+\\.html)")
    fun htmlLinks(html:String,base:String):List<String> {
        val xml=Jsoup.parse(html,base,Parser.xmlParser())
        val feeds=xml.select("item > link,entry > link").mapNotNull { node -> NewsPrimitives.resolve(base,node.attr("href").ifBlank { node.text() }) }.filter { u -> try { NewsPrimitives.validUrl(u,domains,pattern);true } catch (_:NewsValidationException) { false } }.map { NewsPrimitives.cleanUrl(it).replace(Regex("^http:"),"https:") }.distinct()
        return feeds.ifEmpty { NewsPrimitives.listing(NewsPrimitives.document(html,base),base,domains,pattern).map { it.replace(Regex("^http:"),"https:") } }
    }
    override fun collect(homepage:String,transport:NewsTransport,checkpoint:()->Unit):List<String> {
        val page=try { NewsPrimitives.request(homepage,transport,checkpoint) } catch (_:IOException) {
            val rss=NewsPrimitives.request("https://www3.nhk.or.jp/rss/news/cat0.xml",transport,checkpoint)
            val stamps=Jsoup.parse(rss.html,"",Parser.xmlParser()).select("pubDate").mapNotNull { try { ZonedDateTime.parse(it.text(),DateTimeFormatter.RFC_1123_DATE_TIME).toInstant() } catch (_:Exception) { null } }
            if(stamps.isNotEmpty() && stamps.maxOrNull()!! < Instant.now().minusSeconds(7*86400)) throw NewsValidationException("NHK 官方 RSS 已过期，不能用旧新闻补齐日刊。")
            rss
        }
        if(!NewsPrimitives.hostMatches(NewsPrimitives.uri(page.finalUrl).host.orEmpty(),domains)) throw NewsValidationException("NHK 来源列表归属不匹配。")
        return NewsPrimitives.requireLinks(htmlLinks(page.html,page.finalUrl),name)
    }
    fun extractPage(html:String,url:String):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern);val doc=NewsPrimitives.document(html,url);val records=NewsPrimitives.metadata(doc);NewsPrimitives.rejectPaid(records)
        val scope=NewsPrimitives.scope(doc,".content--detail-body,.article-body,[itemprop=articleBody]",name)
        NewsPrimitives.rejectGate(scope,"[data-paywall=true]");NewsPrimitives.clean(scope)
        scope.select("[class*=related],[class*=recommend],[data-testid*=Related]").remove()
        val body=NewsPrimitives.paragraphs(scope,"p,h2,h3,h4")
        val media=NewsPrimitives.images(scope,"figure img,.article-image img,.content--detail-body img",body,url).ifEmpty { NewsPrimitives.preview(doc,url) }+NewsPrimitives.videos(scope,url)
        return NewsArticle(url,NewsPrimitives.title(doc,records,excluded=setOf("NHKニュース")),name,body.texts,NewsPrimitives.published(doc,records),media,listOf(url),paragraphHtml=body.html)
    }
    /** Official anonymous overseas reading flow. The supplied transport owns its cookie session. */
    private fun authorize(url:String,transport:NewsTransport,checkpoint:()->Unit) {
        val geo=NewsPrimitives.request("https://location.tools.nhk/geoip/area.json",transport,checkpoint)
        if(NewsPrimitives.uri(geo.finalUrl).host!="location.tools.nhk") throw NewsValidationException("NHK 匿名阅读地区确认失败。")
        val country=parseJson(geo.html).optString("country_name")
        if(country.isBlank() || country=="Japan") throw NewsValidationException("NHK 需要原站阅读授权，当前仅取得摘要。")
        val params=linkedMapOf("idp" to "a-alaz","profileType" to "abroad","redirect_uri" to url,"entity" to "none","area" to "130","pref" to "13","jisx0402" to "13101","postal" to "1000001")
        val query=params.entries.joinToString("&") { it.key+"="+URLEncoder.encode(it.value,"UTF-8") }
        val auth=NewsPrimitives.request("https://news.web.nhk/tix/build_authorize?$query",transport,checkpoint)
        if(NewsPrimitives.canonical(auth.finalUrl)!=NewsPrimitives.canonical(url)) throw NewsValidationException("NHK 海外匿名阅读确认未完成。")
    }
    private fun parseJson(html:String):JSONObject = try { JSONObject(html) } catch (_:Exception) { throw NewsValidationException("NHK 未返回有效正文 JSON。") }
    private fun plainMarked(text:String):String = text.replace(Regex("(?m)^:::.*$|^(?:\\*{3,}|-{3,})\\s*$"),"").replace(Regex("!\\[([^]]*)]\\([^\n]*?\\)"),"$1").replace(Regex("(?m)^#{1,6}\\s+"),"").replace(Regex("(?<!!)\\[([^]]+)]\\(https?://[^\\s)]+\\)"),"$1").replace("**","").replace("\\\n","\n").replace(Regex("\\s+"),"")
    private fun apiArticle(data:JSONObject,url:String):NewsArticle {
        val id=NewsPrimitives.uri(url).path.substringAfterLast('/')
        if(data.optString("type")!="NewsArticle" || data.optString("id")!=id || data.optString("canonical").trimEnd('/')!=url.trimEnd('/')) throw NewsValidationException("NHK 全文归属不匹配，已停止收录。")
        NewsPrimitives.rejectPaid(listOf(data))
        val raw=data.optString("articleBody")
        if(raw.isBlank() || raw.length>150000) throw NewsValidationException("NHK 只返回摘要或全文过长，未收录。")
        val detail=data.optJSONObject("detailedArticleBody")
        val marked=listOf(detail?.optString("markedLead").orEmpty(),detail?.optString("markedBody").orEmpty()).joinToString("\n\n")
        val media=mutableListOf<NewsMedia>();val texts=mutableListOf<String>()
        val image=data.optJSONObject("image")?.optJSONObject("medium")
        image?.optString("url")?.takeIf { it.isNotBlank() }?.let { src -> NewsPrimitives.resolve(url,src)?.let { media.add(NewsMedia(it,"image",image.optString("caption"),-1)) } }
        if(marked.isNotBlank()) {
            if(plainMarked(marked)!=plainMarked(raw)) throw NewsValidationException("NHK 格式正文与全文不一致，未收录。")
            val pending=mutableListOf<String>();val containers=mutableListOf<Boolean>()
            fun flush() { if(pending.isNotEmpty()) { val text=pending.joinToString("\n").trim();pending.clear();if(text.isNotEmpty()) texts.add(text) } }
            marked.lines().forEach { rawLine ->
                val line=rawLine.trim()
                if(line.startsWith(":::")) {
                    flush()
                    if(line==":::") { if(containers.isEmpty()) throw NewsValidationException("NHK 正文容器不完整。");containers.removeAt(containers.lastIndex) } else containers.add(line.startsWith(":::nw--link-"))
                } else if(containers.any { it }) { /* recommendation blocks intentionally omitted */ }
                else if(line.isBlank() || Regex("\\*{3,}|-{3,}").matches(line)) flush()
                else {
                    val photo=Regex("!\\[([^]]*)]\\((https?://[^\\s)]+)\\)").matchEntire(line)
                    val heading=Regex("#{1,6}\\s+(.+)").matchEntire(line)
                    when {
                        photo!=null -> { flush();val src=photo.groupValues[2];val u=NewsPrimitives.uri(src);if(u.scheme!="https" || !NewsPrimitives.hostMatches(u.host.orEmpty(),listOf("web.nhk","nhk.or.jp"))) throw NewsValidationException("NHK 正文图片归属不匹配。");media.add(NewsMedia(src,"image",photo.groupValues[1],texts.size)) }
                        heading!=null -> { flush();texts.add(heading.groupValues[1]) }
                        else -> pending.add(line.replace(Regex("(?<!!)\\[([^]]+)]\\(https?://[^\\s)]+\\)"),"$1").replace("**","").removeSuffix("\\"))
                    }
                }
            };flush();if(containers.isNotEmpty()) throw NewsValidationException("NHK 正文容器未闭合。")
        } else texts.addAll(raw.split(Regex("\n\\s*\n")).map { it.trim() }.filter { it.isNotBlank() })
        if(texts.isEmpty()) throw NewsValidationException("NHK 全文没有有效新闻段落。")
        val videos=data.optJSONArray("video")
        if(videos!=null) for(i in 0 until videos.length()) {
            val contents=videos.optJSONObject(i)?.optJSONArray("detailedContent") ?: continue
            for(j in 0 until contents.length()) {
                val src=contents.optJSONObject(j)?.optString("contentUrl").orEmpty()
                if(src.isBlank()) continue
                val u=NewsPrimitives.uri(src)
                if(u.scheme=="https" && NewsPrimitives.hostMatches(u.host.orEmpty(),listOf("nhk","nhk.or.jp")) && Regex("\\.(mp4|m3u8)$").containsMatchIn(u.path.orEmpty())) media.add(NewsMedia(src,if(u.host=="media.vd.st.nhk" || u.path.endsWith(".m3u8")) "preview_video" else "video"))
            }
        }
        val headline=data.optString("headline");if(headline.isBlank()) throw NewsValidationException("NHK 未提供文章标题。")
        val warnings=if(media.any { it.kind=="preview_video" }) listOf("NHK 视频需要原站播放授权或 HLS 处理，当前未下载；请在原站观看。") else emptyList()
        return NewsArticle(url,headline,name,texts,data.optString("datePublished"),media.distinctBy { it.url },listOf(url),warnings,texts.map { org.jsoup.nodes.Entities.escape(it) })
    }
    override fun fetchArticle(url:String,transport:NewsTransport,checkpoint:()->Unit):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern);val page=NewsPrimitives.request(url,transport,checkpoint);NewsPrimitives.sameArticle(url,page.finalUrl,domains,pattern)
        val doc=NewsPrimitives.document(page.html,page.finalUrl)
        if(doc.selectFirst("script[id^=json-ld-]")!=null && doc.selectFirst(".content--detail-body,.article-body,[itemprop=articleBody]")==null) {
            NewsPrimitives.rejectPaid(NewsPrimitives.metadata(doc))
            val api="https://api.web.nhk/r8/t/newsarticle/na/"+NewsPrimitives.uri(page.finalUrl).path.substringAfterLast('/')+".json"
            fun read():JSONObject {
                val response=NewsPrimitives.request(api,transport,checkpoint)
                if(NewsPrimitives.canonical(response.finalUrl)!=NewsPrimitives.canonical(api)) throw NewsValidationException("NHK 全文接口重定向归属不匹配。")
                return parseJson(response.html)
            }
            var data=read();if(data.optString("articleBody").isBlank()) { authorize(page.finalUrl,transport,checkpoint);data=read() }
            return apiArticle(data,page.finalUrl)
        }
        return extractPage(page.html,page.finalUrl)
    }
}

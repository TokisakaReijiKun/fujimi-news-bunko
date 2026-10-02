package jp.fujimi.newsbunko.next.news

object YahooProvider : NewsProvider {
    override val name="Yahoo!ニュース"
    override val processingSteps=listOf("kana", "translation", "media")
    private val domains=listOf("news.yahoo.co.jp")
    private val pattern=Regex("/(?:articles/[a-f0-9]{40}|pickup/\\d+)/?")
    private val bodyPattern=Regex("/articles/[a-f0-9]{40}/?")
    fun htmlLinks(html:String,base:String)=NewsPrimitives.listing(NewsPrimitives.document(html,base),base,domains,pattern)
    override fun collect(homepage:String,transport:NewsTransport,checkpoint:()->Unit):List<String> {
        val page=NewsPrimitives.request(homepage,transport,checkpoint)
        if(NewsPrimitives.uri(page.finalUrl).host!="news.yahoo.co.jp") throw NewsValidationException("Yahoo 来源列表归属不匹配。")
        return NewsPrimitives.requireLinks(htmlLinks(page.html,page.finalUrl),name)
    }
    private fun pageNumber(url:String):Int {
        val value=NewsPrimitives.uri(url).rawQuery.orEmpty().split('&').filter { it.substringBefore('=')=="page" }.map { it.substringAfter('=',"") }
        if(value.size>1) throw NewsValidationException("Yahoo 分页页码无效。")
        return if(value.isEmpty()) 1 else value.single().toIntOrNull()?.takeIf { it in 1..20 } ?: throw NewsValidationException("Yahoo 分页页码无效。")
    }
    fun resolvePickup(html:String,url:String):String {
        val doc=NewsPrimitives.document(html,url)
        return doc.select("a[href]").filter { it.text().contains("記事全文を読む") }.mapNotNull { NewsPrimitives.resolve(url,it.attr("href")) }.firstOrNull { candidate ->
            try { NewsPrimitives.validUrl(candidate,domains,bodyPattern);true } catch (_:NewsValidationException) { false }
        }?.let { NewsPrimitives.cleanUrl(it) } ?: throw NewsValidationException("Yahoo の記事全文リンクが見つかりません。")
    }
    fun extractPage(html:String,url:String):NewsArticle {
        NewsPrimitives.validUrl(url,domains,bodyPattern); pageNumber(url)
        val doc=NewsPrimitives.document(html,url);val records=NewsPrimitives.metadata(doc);NewsPrimitives.rejectPaid(records)
        // A canonical URL and article metadata must refer to this entity, even if the server echoes the requested URL for cached HTML.
        val expected=NewsPrimitives.canonical(url)
        val declared=mutableListOf<String>()
        doc.selectFirst("link[rel=canonical]")?.attr("href")?.takeIf { it.isNotBlank() }?.let { declared.add(it) }
        records.forEach { record ->
            record.optString("url").takeIf { it.isNotBlank() }?.let { declared.add(it) }
            val entity=record.opt("mainEntityOfPage")
            val value=if(entity is org.json.JSONObject) entity.optString("@id") else if(entity is String) entity else ""
            if(value.isNotBlank()) declared.add(value)
        }
        if(declared.any { NewsPrimitives.resolve(url,it)?.let { candidate -> NewsPrimitives.canonical(candidate) } != expected }) throw NewsValidationException("Yahoo 正文元数据归属不匹配。")
        NewsPrimitives.rejectGate(doc.selectFirst("article#uamods") ?: doc,"[data-paywall=true],[data-testid=paywall]")
        val scope=NewsPrimitives.scope(doc,"article#uamods .article_body",name);NewsPrimitives.clean(scope)
        scope.select("[class*=related],[class*=recommend],[data-testid*=related]").remove()
        scope.select("a[data-cl-params*=_cl_vmodule:related],a[data-cl-params*=_cl_link:photo]").remove()
        val body=NewsPrimitives.paragraphs(scope,"p.yjSlinkDirectlink,h2,h3,h4",splitBlank=true)
        val photos=scope.select("img").filter { (it.attr("src")+it.attr("data-src")).let { raw -> raw.contains("newsatcl") || raw.contains("amd-img") } }
        photos.forEach { it.addClass("fujimi-body-photo") }
        val media=NewsPrimitives.images(scope,"img.fujimi-body-photo",body,url).ifEmpty { NewsPrimitives.preview(doc,url) }+NewsPrimitives.videos(scope,url)
        val warnings=if(html.contains("yvpub/player") && media.none { it.kind=="video" }) listOf("原站视频需动态播放器，当前仅保留预览；视频请在原站观看。") else emptyList()
        return NewsArticle(NewsPrimitives.cleanUrl(url),NewsPrimitives.title(doc,records,"article#uamods h1",setOf("Yahoo!ニュース")),name,body.texts,NewsPrimitives.published(doc,records),media,listOf(url),warnings,body.html)
    }
    private fun nextPage(html:String,url:String):String? {
        val expectedPage=pageNumber(url)+1;val origin=NewsPrimitives.uri(url)
        val all=NewsPrimitives.document(html,url).select("a[href]").mapNotNull { NewsPrimitives.resolve(url,it.attr("href")) }.filter { u -> NewsPrimitives.uri(u).host==origin.host && NewsPrimitives.uri(u).path.trimEnd('/')==origin.path.trimEnd('/') && NewsPrimitives.uri(u).rawQuery.orEmpty().contains("page=") }.map { pageNumber(it) }
        if(all.any { it>expectedPage } && expectedPage !in all) throw NewsValidationException("Yahoo 分页不连续，未保存不完整正文。")
        return if(expectedPage in all) NewsPrimitives.cleanUrl(url)+"?page=$expectedPage" else null
    }
    override fun fetchArticle(url:String,transport:NewsTransport,checkpoint:()->Unit):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern)
        var requested=NewsPrimitives.cleanUrl(url)
        var page=NewsPrimitives.request(requested,transport,checkpoint);NewsPrimitives.sameArticle(requested,page.finalUrl,domains,pattern)
        if(NewsPrimitives.uri(page.finalUrl).path.startsWith("/pickup/")) {
            requested=resolvePickup(page.html,page.finalUrl);page=NewsPrimitives.request(requested,transport,checkpoint)
            NewsPrimitives.sameArticle(requested,page.finalUrl,domains,bodyPattern)
        }
        if(pageNumber(page.finalUrl)!=1) throw NewsValidationException("Yahoo 首次请求返回了错误页码。")
        var result=extractPage(page.html,page.finalUrl)
        val seen=mutableSetOf(NewsPrimitives.canonical(page.finalUrl)+"?page=1")
        val fingerprints=mutableSetOf(result.paragraphs.joinToString("\n"))
        var next=nextPage(page.html,page.finalUrl)
        while(next!=null) {
            val target=next
            if(seen.size>=20 || !seen.add(NewsPrimitives.canonical(target)+"?page="+pageNumber(target))) throw NewsValidationException("Yahoo 分页循环或超过20页。")
            val more=NewsPrimitives.request(target,transport,checkpoint)
            NewsPrimitives.sameArticle(target,more.finalUrl,domains,bodyPattern)
            if(pageNumber(target)!=pageNumber(more.finalUrl)) throw NewsValidationException("Yahoo 分页返回了错误页码，未保存不完整文章。")
            val part=extractPage(more.html,more.finalUrl)
            if(!fingerprints.add(part.paragraphs.joinToString("\n"))) throw NewsValidationException("Yahoo 分页返回重复缓存正文，未保存不完整文章。")
            val offset=result.paragraphs.size
            result=result.copy(paragraphs=result.paragraphs+part.paragraphs,paragraphHtml=result.paragraphHtml+part.paragraphHtml,
                media=(result.media+part.media.map { it.copy(paragraphIndex=offset+maxOf(0,it.paragraphIndex)) }).distinctBy { it.url },
                pageUrls=result.pageUrls+more.finalUrl,mediaWarnings=(result.mediaWarnings+part.mediaWarnings).distinct())
            if(result.paragraphs.sumOf { it.length }>150000) throw NewsValidationException("Yahoo 全文过长。")
            next=nextPage(more.html,more.finalUrl)
        }
        return result
    }
}

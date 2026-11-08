package jp.fujimi.newsbunko.next.news

object AsahiProvider : NewsProvider {
    override val name="朝日新聞"
    override val processingSteps=listOf("kana", "translation", "media")
    private val domains=listOf("asahi.com")
    private val pattern=Regex("/articles/[A-Z0-9]+\\.html")
    private const val badges=".c-icon--keyGold, img[alt=有料記事], img[alt=有料会員記事], img[src*=icon__keyGold.svg]"
    fun htmlLinks(html:String,base:String):List<String> {
        val doc=NewsPrimitives.document(html,base); doc.select(".p-breaking__List,.p-breaking__listItem").remove()
        val links=NewsPrimitives.listing(doc,base,domains,pattern,"[data-paywall=true],[data-testid*=paywall],[class*=premium],[class*=Premium],[class*=paywall],$badges",setOf("会員限定","有料記事","有料会員","プレミアム"))
        val denied=mutableSetOf<String>()
        doc.select(badges).forEach { badge ->
            for(container in badge.parents().take(6)) {
                if(container.tagName() in listOf("body","html","main","nav")) break
                val urls=container.select("a[href]").mapNotNull { NewsPrimitives.resolve(base,it.attr("href")) }.filter { u -> try { NewsPrimitives.validUrl(u,domains,pattern);true } catch (_:NewsValidationException) { false } }.map { NewsPrimitives.cleanUrl(it) }.distinct()
                if(urls.isNotEmpty()) { if(urls.size==1) denied.add(urls.single()); break }
            }
        }
        return links.filterNot { it in denied }
    }
    override fun collect(homepage:String,transport:NewsTransport,checkpoint:()->Unit):List<String> {
        val page=NewsPrimitives.request(homepage,transport,checkpoint)
        if(!NewsPrimitives.hostMatches(NewsPrimitives.uri(page.finalUrl).host.orEmpty(),domains)) throw NewsValidationException("朝日来源列表归属不匹配。")
        return NewsPrimitives.requireLinks(htmlLinks(page.html,page.finalUrl),name)
    }
    fun extractPage(html:String,url:String):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern)
        val doc=NewsPrimitives.document(html,url);val records=NewsPrimitives.metadata(doc);NewsPrimitives.rejectPaid(records)
        val gate=doc.selectFirst("main,#MainInner,article") ?: doc
        if(gate.selectFirst("[data-paywall=true],[data-testid=paywall],.premium-block,.paywall")!=null) throw NewsValidationException("朝日本文存在会员阅读门槛，未收录。")
        val heading=doc.selectFirst("h1")
        if(heading?.parent()?.selectFirst("$badges,a[href*=/news/gold.html]")!=null) throw NewsValidationException("朝日正文标题标记为有料記事，未收录。")
        val scope=doc.selectFirst(".article-body,.ArticleText,#MainInner .ArticleBody,[itemprop=articleBody]") ?: if(records.isNotEmpty()) NewsPrimitives.scope(doc,"main#main > div.nfyQp",name) else throw NewsValidationException("朝日页面缺少明确正文容器。")
        NewsPrimitives.rejectGate(scope,"[data-paywall=true],[data-testid=paywall]");NewsPrimitives.clean(scope)
        scope.select("p,h2,h3").filter { Regex("有料会員になると|この記事の続きが読める|有料記事が読み放題|無料期間中に解約").containsMatchIn(it.text()) }.forEach { it.remove() }
        val body=NewsPrimitives.paragraphs(scope,"p,h2,h3")
        val images=NewsPrimitives.images(scope,"figure img,.Image img,.article-image img",body,url).ifEmpty { NewsPrimitives.preview(doc,url) }
        return NewsArticle(url,NewsPrimitives.title(doc,records),name,body.texts,NewsPrimitives.published(doc,records),images+NewsPrimitives.videos(scope,url),listOf(url),paragraphHtml=body.html)
    }
    override fun fetchArticle(url:String,transport:NewsTransport,checkpoint:()->Unit):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern);val page=NewsPrimitives.request(url,transport,checkpoint)
        NewsPrimitives.sameArticle(url,page.finalUrl,domains,pattern);return extractPage(page.html,page.finalUrl)
    }
}

package jp.fujimi.newsbunko.next.news

object SankeiProvider : NewsProvider {
    override val name="産経新聞"
    override val processingSteps=listOf("kana", "media", "translation")
    private val domains=listOf("sankei.com")
    private val pattern=Regex("/article/\\d{8}-[A-Z0-9]+/?")
    private const val badges="img[alt=有料会員記事],img[src*=/img_lock-gold.svg]"
    fun htmlLinks(html:String,base:String)=NewsPrimitives.listing(NewsPrimitives.document(html,base),base,domains,pattern,"[data-paywall=true],[data-testid=paywall],[class*=premium],.paid_members,$badges",setOf("会員限定","有料記事","有料会員記事","産経電子版"))
    override fun collect(homepage:String,transport:NewsTransport,checkpoint:()->Unit):List<String> {
        val page=NewsPrimitives.request(homepage,transport,checkpoint)
        if(!NewsPrimitives.hostMatches(NewsPrimitives.uri(page.finalUrl).host.orEmpty(),domains)) throw NewsValidationException("産経来源列表归属不匹配。")
        return NewsPrimitives.requireLinks(htmlLinks(page.html,page.finalUrl),name)
    }
    fun extractPage(html:String,url:String):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern);val doc=NewsPrimitives.document(html,url);val records=NewsPrimitives.metadata(doc);NewsPrimitives.rejectPaid(records)
        val article=NewsPrimitives.scope(doc,"article.article-wrapper",name)
        if(article.hasClass("paid_members") || article.selectFirst(".article-header,header")?.selectFirst(badges)!=null) throw NewsValidationException("産経本文标记为有料会員記事，未收录。")
        NewsPrimitives.rejectGate(doc.selectFirst("main") ?: doc,"article.article-wrapper.premium,[data-paywall=true]")
        val scope=NewsPrimitives.scope(article,".article-body",name);NewsPrimitives.clean(scope)
        val body=NewsPrimitives.paragraphs(scope,"p.article-text,h2.article-text,h3.article-text,h2,h3",setOf("◇","◇ "))
        return NewsArticle(url,NewsPrimitives.title(doc,records,excluded=setOf("産経ニュース")),name,body.texts,NewsPrimitives.published(doc,records),NewsPrimitives.images(scope,"figure.article-image img",body,url).ifEmpty { NewsPrimitives.preview(doc,url) }+NewsPrimitives.videos(scope,url),listOf(url),paragraphHtml=body.html)
    }
    override fun fetchArticle(url:String,transport:NewsTransport,checkpoint:()->Unit):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern);val page=NewsPrimitives.request(url,transport,checkpoint);NewsPrimitives.sameArticle(url,page.finalUrl,domains,pattern)
        return extractPage(page.html,page.finalUrl)
    }
}

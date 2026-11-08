package jp.fujimi.newsbunko.next.news

/** User-added sites only. Known publisher failures never reach this provider. */
class CustomProvider(private val host:String, override val name:String):NewsProvider {
    override val processingSteps=listOf("kana", "translation", "media")
    init { if(host.isBlank()) throw NewsValidationException("自定义来源地址无效。") }
    fun htmlLinks(html:String,base:String)=NewsPrimitives.listing(NewsPrimitives.document(html,base),base,listOf(host),Regex("/(?:articles?|news)/.+"))
    override fun collect(homepage:String,transport:NewsTransport,checkpoint:()->Unit):List<String> {
        val page=NewsPrimitives.request(homepage,transport,checkpoint)
        if(NewsPrimitives.uri(page.finalUrl).host!=host) throw NewsValidationException("自定义来源列表重定向到其他网站。")
        return NewsPrimitives.requireLinks(htmlLinks(page.html,page.finalUrl),name)
    }
    fun extractPage(html:String,url:String):NewsArticle {
        if(NewsPrimitives.uri(url).host!=host) throw NewsValidationException("自定义来源文章归属不匹配。")
        val doc=NewsPrimitives.document(html,url);val records=NewsPrimitives.metadata(doc);NewsPrimitives.rejectPaid(records)
        val scope=NewsPrimitives.scope(doc,"[itemprop=articleBody],article",name)
        NewsPrimitives.rejectGate(scope,"[data-paywall=true],[data-testid=paywall]");NewsPrimitives.clean(scope)
        val body=NewsPrimitives.paragraphs(scope,"p,h2,h3")
        return NewsArticle(url,NewsPrimitives.title(doc,records),name,body.texts,NewsPrimitives.published(doc,records),NewsPrimitives.images(scope,"figure img",body,url)+NewsPrimitives.videos(scope,url),listOf(url),paragraphHtml=body.html)
    }
    override fun fetchArticle(url:String,transport:NewsTransport,checkpoint:()->Unit):NewsArticle {
        if(NewsPrimitives.uri(url).host!=host) throw NewsValidationException("自定义文章归属不匹配。")
        val page=NewsPrimitives.request(url,transport,checkpoint)
        if(NewsPrimitives.uri(page.finalUrl).host!=host) throw NewsValidationException("自定义来源文章重定向到其他网站。")
        return extractPage(page.html,page.finalUrl)
    }
}

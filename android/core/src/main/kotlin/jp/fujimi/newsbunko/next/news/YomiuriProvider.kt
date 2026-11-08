package jp.fujimi.newsbunko.next.news

object YomiuriProvider : NewsProvider {
    override val name="読売新聞"
    override val processingSteps=listOf("kana", "translation", "media")
    private val domains=listOf("yomiuri.co.jp")
    private val pattern=Regex("/(?:[^/]+/)+\\d{8}-[A-Z0-9]+/?")
    fun htmlLinks(html:String,base:String)=NewsPrimitives.listing(NewsPrimitives.document(html,base),base,domains,pattern,"[data-paywall=true],[data-testid=paywall],[class*=premium]",setOf("会員限定","有料記事","読売ID"))
    override fun collect(homepage:String,transport:NewsTransport,checkpoint:()->Unit):List<String> {
        val page=NewsPrimitives.request(homepage,transport,checkpoint)
        if(!NewsPrimitives.hostMatches(NewsPrimitives.uri(page.finalUrl).host.orEmpty(),domains)) throw NewsValidationException("読売来源列表归属不匹配。")
        return NewsPrimitives.requireLinks(htmlLinks(page.html,page.finalUrl),name)
    }
    fun extractPage(html:String,url:String):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern); val doc=NewsPrimitives.document(html,url);val records=NewsPrimitives.metadata(doc);NewsPrimitives.rejectPaid(records)
        NewsPrimitives.rejectGate(doc.selectFirst("article.article-content") ?: doc,"[data-paywall=true],[data-testid=paywall]")
        val scope=NewsPrimitives.scope(doc,"article.article-content .p-main-contents",name);NewsPrimitives.clean(scope)
        val selector=if(scope.selectFirst("p[itemprop=articleBody]")!=null) "p[itemprop=articleBody],h2,h3" else "p[class^=par],h2,h3"
        val body=NewsPrimitives.paragraphs(scope,selector,setOf("記事をシェアする","完了しました"))
        return NewsArticle(url,NewsPrimitives.title(doc,records),name,body.texts,NewsPrimitives.published(doc,records),NewsPrimitives.images(scope,"figure img",body,url).ifEmpty { NewsPrimitives.preview(doc,url) }+NewsPrimitives.videos(scope,url),listOf(url),paragraphHtml=body.html)
    }
    override fun fetchArticle(url:String,transport:NewsTransport,checkpoint:()->Unit):NewsArticle {
        NewsPrimitives.validUrl(url,domains,pattern);val page=NewsPrimitives.request(url,transport,checkpoint);NewsPrimitives.sameArticle(url,page.finalUrl,domains,pattern)
        return extractPage(page.html,page.finalUrl)
    }
}
